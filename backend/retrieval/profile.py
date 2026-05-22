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


# Natural-language apparel size words → letter codes (only applied when sample exists).
_SIZE_LETTER_ALIASES: dict[str, str] = {
    "extra small": "xs",
    "x-small": "xs",
    "xsmall": "xs",
    "small": "s",
    "sm": "s",
    "medium": "m",
    "med": "m",
    "large": "l",
    "lg": "l",
    "extra large": "xl",
    "x-large": "xl",
    "xlarge": "xl",
    "xx-large": "xxl",
    "xxlarge": "xxl",
    "2xl": "xxl",
    "3xl": "xxxl",
}

_STATIC_FACET_ALIASES: dict[str, dict[str, str]] = {
    "colour": {
        "gray": "grey",
        "matte": "matt",
        "chrome plated": "chrome",
        "violet": "purple",
        "lilac": "purple",
        "lavender": "lavender",
        "charcoal": "charcoal",
        "sand": "beige",
        "navy": "navy",
        "burgundy": "red",
    },
    "color": {
        "gray": "grey",
        "matte": "matt",
        "violet": "purple",
        "lilac": "purple",
        "lavender": "lavender",
        "charcoal": "charcoal",
        "sand": "beige",
        "navy": "navy",
        "burgundy": "red",
    },
    "material": {
        "denim": "denim",
        "polyester": "polyester",
        "cotton": "cotton",
        "leather": "leather",
        "wool": "wool",
        "linen": "linen",
        "nylon": "nylon",
        "silk": "silk",
    },
    "finish": {
        "matte": "matt",
        "chrome plated": "chrome",
    },
    "size": dict(_SIZE_LETTER_ALIASES),
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


def resolve_facet_value_to_sample(
    facet_id: str,
    value: str,
    facet_meta: dict[str, Any] | None,
) -> str:
    """Map user/LLM facet token to a normalized value present in profile samples."""
    norm = _normalize_label(value)
    if not norm:
        return norm
    meta = facet_meta or {}
    samples_norm = {_normalize_label(s) for s in (meta.get("sample_values") or []) if s}
    if norm in samples_norm:
        return norm
    aliases = meta.get("value_aliases") or {}
    if isinstance(aliases, dict):
        for alias, canonical in aliases.items():
            if norm == _normalize_label(alias):
                return _normalize_label(str(canonical))
    static_target = (_STATIC_FACET_ALIASES.get(facet_id) or {}).get(norm)
    if static_target:
        static_norm = _normalize_label(static_target)
        if static_norm in samples_norm:
            return static_norm
    if facet_id == "size":
        static_target = _SIZE_LETTER_ALIASES.get(norm)
        if static_target and static_target in samples_norm:
            return static_target
    return norm


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
        canon_norm = _normalize_label(canonical)
        if not alias_norm or canon_norm not in canonical_by_norm:
            continue
        aliases[alias_norm] = canonical_by_norm[canon_norm]
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
            "match_mode": "soft",
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
            "default_category_match": "soft",
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


_GAZETTEER_MATCH_FLAG_KEYS = (
    "hard_filter",
    "demote_accessory_substrings",
    "fixture_stem",
    "accessory_keywords",
)


def merge_gazetteer_match_flags(
    old_profile: dict[str, Any] | None,
    new_profile: dict[str, Any],
) -> dict[str, Any]:
    """Preserve per-category match flags from a previous profile after reindex rebuild."""
    if not old_profile:
        return new_profile
    old_gazetteer = (old_profile.get("category_strategy") or {}).get("gazetteer") or []
    new_strategy = new_profile.get("category_strategy") or {}
    new_gazetteer = list(new_strategy.get("gazetteer") or [])
    if not new_gazetteer:
        return new_profile
    old_by_id = {str(entry.get("id") or ""): entry for entry in old_gazetteer if entry.get("id")}
    merged_gazetteer: list[dict[str, Any]] = []
    for entry in new_gazetteer:
        updated = dict(entry)
        entry_id = str(updated.get("id") or "")
        prior = old_by_id.get(entry_id)
        if prior:
            for key in _GAZETTEER_MATCH_FLAG_KEYS:
                if key in prior:
                    updated[key] = prior[key]
        merged_gazetteer.append(updated)
    merged = dict(new_profile)
    merged["category_strategy"] = {**new_strategy, "gazetteer": merged_gazetteer}
    return merged


def apply_retrieval_profile_to_tenant(
    tenant: "Tenant",
    profile: dict[str, Any],
    *,
    merge_match_flags: bool = True,
) -> None:
    stored = profile
    if merge_match_flags and tenant.retrieval_profile_json:
        stored = merge_gazetteer_match_flags(tenant.retrieval_profile_json, profile)
    tenant.retrieval_profile_json = stored
    tenant.retrieval_profile_version = int(stored.get("profile_version") or 0)


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
