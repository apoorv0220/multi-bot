from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from models import Tenant
    from sources.base import SourceRecord


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _slug_id(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _normalize_label(label)).strip("_")
    return slug or "unknown"


def _facet_min_coverage_pct() -> float:
    raw = os.getenv("RETRIEVAL_FACET_MIN_COVERAGE_PCT", "5")
    try:
        return max(0.0, min(float(raw), 100.0))
    except ValueError:
        return 5.0


def _category_confidence_threshold() -> float:
    raw = os.getenv("RETRIEVAL_CATEGORY_CONFIDENCE_THRESHOLD", "0.75")
    try:
        return max(0.0, min(float(raw), 1.0))
    except ValueError:
        return 0.75


def _max_sample_values() -> int:
    raw = os.getenv("RETRIEVAL_FACET_MAX_SAMPLE_VALUES", "20")
    try:
        return max(1, int(raw))
    except ValueError:
        return 20


_STATIC_FACET_ALIASES: dict[str, dict[str, str]] = {
    "colour": {
        "gray": "grey",
        "matte": "matt",
        "chrome plated": "chrome",
    },
    "color": {
        "gray": "grey",
        "matte": "matt",
    },
    "finish": {
        "matte": "matt",
        "chrome plated": "chrome",
    },
}

_STATIC_CATEGORY_ALIASES: dict[str, list[str]] = {
    "tap": ["taps", "faucet", "faucets"],
    "basin": ["basins", "sink", "sinks"],
    "toilet": ["toilets", "wc", "wcs"],
    "shower": ["showers"],
    "bath": ["baths"],
}


def _singularize_token(token: str) -> str:
    t = _normalize_label(token)
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _pluralize_token(token: str) -> str:
    t = _normalize_label(token)
    if t.endswith("s"):
        return t
    if t.endswith(("ch", "sh", "x", "z")):
        return f"{t}es"
    if t.endswith("y") and len(t) > 2 and t[-2] not in "aeiou":
        return f"{t[:-1]}ies"
    return f"{t}s"


def _aliases_for_category_label(label: str) -> dict[str, str]:
    norm = _normalize_label(label)
    if not norm:
        return {}
    aliases: dict[str, str] = {}
    singular = _singularize_token(norm)
    plural = _pluralize_token(singular)
    for variant in {norm, singular, plural}:
        if variant and variant != norm:
            aliases[variant] = norm
    stem = _singularize_token(norm)
    for key, extras in _STATIC_CATEGORY_ALIASES.items():
        if stem == key or norm == key or norm in extras:
            for extra in extras + [key, _pluralize_token(key)]:
                extra_norm = _normalize_label(extra)
                if extra_norm and extra_norm != norm:
                    aliases[extra_norm] = norm
    return aliases


def _aliases_for_facet_samples(facet_id: str, samples: list[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    canonical_by_norm = {_normalize_label(sample): sample for sample in samples if sample}
    for sample in samples:
        norm = _normalize_label(sample)
        if not norm:
            continue
        singular = _singularize_token(norm)
        plural = _pluralize_token(singular)
        canonical = canonical_by_norm.get(norm, sample)
        for variant in {singular, plural}:
            if variant and variant != norm:
                aliases[variant] = canonical
    for alias, canonical in (_STATIC_FACET_ALIASES.get(facet_id) or {}).items():
        alias_norm = _normalize_label(alias)
        target = canonical_by_norm.get(_normalize_label(canonical), canonical)
        if alias_norm:
            aliases[alias_norm] = target
    return aliases


def build_retrieval_profile(
    records: Iterable["SourceRecord"],
    *,
    tenant_id: str,
    source_job_id: str | None = None,
    previous_version: int | None = None,
) -> dict[str, Any]:
    """Build TenantFacetProfile JSON from catalog SourceRecords (products + categories)."""
    product_records: list[Any] = []
    category_records: list[Any] = []
    for record in records:
        if getattr(record, "deleted", False):
            continue
        kind = getattr(record, "content_kind", None)
        if kind == "product":
            product_records.append(record)
        elif kind == "category":
            category_records.append(record)

    total_products = len(product_records)
    facet_value_counts: dict[str, Counter] = defaultdict(Counter)
    facet_product_hits: dict[str, int] = defaultdict(int)
    brand_values: Counter = Counter()
    category_labels: Counter = Counter()
    price_present = 0
    stock_present = 0
    brand_present = 0

    for record in product_records:
        metadata = dict(getattr(record, "metadata", None) or {})
        if metadata.get("price") not in (None, ""):
            price_present += 1
        if (metadata.get("stock_status") or "").strip():
            stock_present += 1
        brand = (metadata.get("brand") or "").strip()
        if brand:
            brand_present += 1
            brand_values[brand] += 1
        for cat in metadata.get("categories") or []:
            label = str(cat).strip()
            if label:
                category_labels[label] += 1
        attributes = metadata.get("attributes") or {}
        seen_keys: set[str] = set()
        if isinstance(attributes, dict):
            for key, raw_value in attributes.items():
                facet_id = str(key).strip().lower()
                if not facet_id:
                    continue
                values: list[str] = []
                if isinstance(raw_value, list):
                    values = [str(v).strip() for v in raw_value if str(v).strip()]
                elif raw_value not in (None, "", []):
                    values = [str(raw_value).strip()]
                if not values:
                    continue
                seen_keys.add(facet_id)
                for val in values:
                    facet_value_counts[facet_id][val] += 1
            for facet_id in seen_keys:
                facet_product_hits[facet_id] += 1

    min_coverage = _facet_min_coverage_pct()
    facets: dict[str, Any] = {}
    for facet_id, counter in sorted(facet_value_counts.items()):
        hits = facet_product_hits.get(facet_id, 0)
        coverage_pct = (hits / total_products * 100.0) if total_products else 0.0
        if total_products and coverage_pct < min_coverage:
            continue
        samples = [v for v, _ in counter.most_common(_max_sample_values())]
        value_aliases = _aliases_for_facet_samples(facet_id, samples)
        facet_entry: dict[str, Any] = {
            "qdrant_path": f"attributes.{facet_id}",
            "indexed": True,
            "within_facet_combine_default": "OR",
            "coverage_pct": round(coverage_pct, 2),
            "product_count": hits,
            "sample_values": samples,
        }
        if value_aliases:
            facet_entry["value_aliases"] = value_aliases
        facets[facet_id] = facet_entry

    gazetteer_by_id: dict[str, dict[str, Any]] = {}
    for record in category_records:
        title = (getattr(record, "title", None) or "").strip()
        if not title:
            continue
        cat_id = _slug_id(title)
        normalized = _normalize_label(title)
        entry = gazetteer_by_id.setdefault(
            cat_id,
            {
                "id": cat_id,
                "labels": [],
                "normalized": [],
            },
        )
        if title not in entry["labels"]:
            entry["labels"].append(title)
        if normalized and normalized not in entry["normalized"]:
            entry["normalized"].append(normalized)

    for label, _count in category_labels.most_common(500):
        cat_id = _slug_id(label)
        normalized = _normalize_label(label)
        entry = gazetteer_by_id.setdefault(
            cat_id,
            {"id": cat_id, "labels": [], "normalized": []},
        )
        if label not in entry["labels"]:
            entry["labels"].append(label)
        if normalized and normalized not in entry["normalized"]:
            entry["normalized"].append(normalized)

    for entry in gazetteer_by_id.values():
        merged_aliases: dict[str, str] = {}
        for label in list(entry.get("labels") or []):
            merged_aliases.update(_aliases_for_category_label(str(label)))
        if merged_aliases:
            entry["aliases"] = merged_aliases

    gazetteer = sorted(gazetteer_by_id.values(), key=lambda item: item["id"])

    core_fields: dict[str, Any] = {
        "price": {
            "qdrant_key": "price",
            "indexed": total_products > 0 and price_present > 0,
            "coverage_pct": round((price_present / total_products * 100.0) if total_products else 0.0, 2),
        },
        "stock_status": {
            "qdrant_key": "stock_status",
            "indexed": total_products > 0 and stock_present > 0,
            "coverage_pct": round((stock_present / total_products * 100.0) if total_products else 0.0, 2),
        },
        "brand": {
            "qdrant_key": "brand",
            "indexed": total_products > 0 and brand_present > 0,
            "coverage_pct": round((brand_present / total_products * 100.0) if total_products else 0.0, 2),
            "sample_values": [v for v, _ in brand_values.most_common(_max_sample_values())],
        },
        "categories": {
            "qdrant_key": "categories",
            "indexed": bool(gazetteer),
            "coverage_pct": round(
                (len([1 for r in product_records if (dict(getattr(r, "metadata", None) or {}).get("categories"))]) / total_products * 100.0)
                if total_products
                else 0.0,
                2,
            ),
        },
    }

    profile_body = {
        "tenant_id": tenant_id,
        "category_strategy": {
            "field": "categories",
            "confidence_threshold": _category_confidence_threshold(),
            "gazetteer": gazetteer,
        },
        "core_fields": core_fields,
        "facets": facets,
        "stats": {
            "product_count": total_products,
            "category_entity_count": len(category_records),
            "facet_count": len(facets),
        },
    }
    facet_catalog_hash = hashlib.sha256(
        json.dumps(profile_body, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:32]

    version = (previous_version or 0) + 1
    return {
        "profile_version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_job_id": source_job_id,
        "facet_catalog_hash": facet_catalog_hash,
        "facet_min_coverage_pct": min_coverage,
        **profile_body,
    }


def apply_retrieval_profile_to_tenant(tenant: "Tenant", profile: dict[str, Any]) -> None:
    tenant.retrieval_profile_json = profile
    tenant.retrieval_profile_version = int(profile.get("profile_version") or 0)


def retrieval_profile_summary(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not profile:
        return None
    return {
        "profile_version": profile.get("profile_version"),
        "generated_at": profile.get("generated_at"),
        "source_job_id": profile.get("source_job_id"),
        "facet_catalog_hash": profile.get("facet_catalog_hash"),
        "facet_ids": sorted((profile.get("facets") or {}).keys()),
        "category_count": len((profile.get("category_strategy") or {}).get("gazetteer") or []),
        "product_count": (profile.get("stats") or {}).get("product_count"),
    }
