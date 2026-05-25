from __future__ import annotations

import os
from typing import Any

from retrieval.planner import _category_confidence_threshold, _has_product_type_category
from retrieval.profile import resolve_facet_value_to_sample, _normalize_label
from retrieval.rules_prepass import term_present_as_word
from retrieval.structured_query import CategorySpec, FacetSpec, StructuredQuery

# Only explicit `category: …` syntax from rules_prepass reaches this confidence.
_EXPLICIT_CATEGORY_CONFIDENCE = 0.95


def _normalize_facet_value(facet_id: str, value: str, facet_meta: dict[str, Any]) -> str:
    return resolve_facet_value_to_sample(facet_id, value, facet_meta)


def _facet_samples_norm(facet_meta: dict[str, Any] | None) -> set[str]:
    return {_normalize_label(str(s)) for s in ((facet_meta or {}).get("sample_values") or []) if s}


def _category_id_matches_token(cat_id: str, token: str) -> bool:
    """Match token to gazetteer id by segment (jacket → jackets), not substring."""
    token = token.strip().lower()
    if not token or not cat_id:
        return False
    parts = cat_id.strip().lower().replace("-", "_").split("_")
    if token in parts:
        return True
    plural = f"{token}s"
    return plural in parts or any(part.rstrip("s") == token for part in parts)


def _score_gazetteer_category_match(val_norm: str, entry: dict[str, Any]) -> int:
    entry_id = str(entry.get("id") or "").strip().lower()
    if not entry_id:
        return 0
    if val_norm == entry_id:
        return 100
    labels = [str(x).strip().lower() for x in (entry.get("labels") or []) + (entry.get("normalized") or [])]
    aliases = entry.get("aliases") or {}
    alias_keys = (
        [str(k).strip().lower() for k in aliases.keys()]
        if isinstance(aliases, dict)
        else []
    )
    if val_norm in labels or val_norm in alias_keys:
        return 90
    if _category_id_matches_token(entry_id, val_norm):
        return 80
    min_fuzzy_len = 4
    for label in labels:
        if label == val_norm:
            return 90
        if len(val_norm) >= min_fuzzy_len and term_present_as_word(val_norm, label):
            return 60
    return 0


def _canonical_gazetteer_category(value: str, profile: dict[str, Any] | None) -> str:
    """Map NL category token to a single gazetteer id when possible."""
    val_norm = value.strip().lower()
    if not val_norm or not profile:
        return val_norm
    best_id = val_norm
    best_score = 0
    for entry in (profile.get("category_strategy") or {}).get("gazetteer") or []:
        entry_id = str(entry.get("id") or "").strip().lower()
        if not entry_id:
            continue
        score = _score_gazetteer_category_match(val_norm, entry)
        if score > best_score:
            best_score = score
            best_id = entry_id
    return best_id if best_score > 0 else val_norm



def validate_structured_query(
    query: StructuredQuery,
    *,
    profile: dict[str, Any] | None,
) -> StructuredQuery:
    validated = query.copy()
    validation_meta: dict[str, Any] = dict(validated.validation_meta or {})

    if validated.category.values:
        gazetteer_ids = set()
        if profile:
            for entry in (profile.get("category_strategy") or {}).get("gazetteer") or []:
                gazetteer_ids.add(str(entry.get("id") or "").lower())
                for label in (entry.get("labels") or []) + (entry.get("normalized") or []):
                    gazetteer_ids.add(str(label).strip().lower())
        filtered_cats: list[str] = []
        soft_categories: list[str] = []
        is_explicit = validated.category.confidence >= _EXPLICIT_CATEGORY_CONFIDENCE
        for val in validated.category.values:
            raw = str(val).strip()
            if not raw:
                continue
            v_norm = _canonical_gazetteer_category(raw, profile)
            if gazetteer_ids and v_norm not in gazetteer_ids:
                if is_explicit:
                    filtered_cats.append(v_norm or raw.lower())
                else:
                    soft_categories.append(raw)
                continue
            filtered_cats.append(v_norm)
        if is_explicit and not filtered_cats and not soft_categories:
            filtered_cats = [str(v).strip().lower() for v in validated.category.values if str(v).strip()]
        if soft_categories:
            validation_meta["soft_categories"] = list(dict.fromkeys(soft_categories))
            hint_blob = " ".join(soft_categories)
            validated.free_text = f"{validated.free_text} {hint_blob}".strip()
            validated.retrieval_rewrite = f"{validated.retrieval_rewrite} {hint_blob}".strip()
        validated.category.values = filtered_cats
        threshold = _EXPLICIT_CATEGORY_CONFIDENCE
        if profile:
            try:
                threshold = float(
                    (profile.get("category_strategy") or {}).get("confidence_threshold")
                    or os.getenv("RETRIEVAL_CATEGORY_CONFIDENCE_THRESHOLD", "0.75")
                )
            except (TypeError, ValueError):
                threshold = 0.75
        gazetteer_filter = os.getenv("RETRIEVAL_CATEGORY_FILTER_ON_GAZETTEER", "false").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        product_type_filter = (
            _has_product_type_category(filtered_cats, profile)
            and validated.category.confidence >= _category_confidence_threshold(profile)
        )
        if filtered_cats and (
            is_explicit
            or (gazetteer_filter and validated.category.confidence >= threshold)
            or validated.category.apply == "filter"
            or product_type_filter
        ):
            validated.category.apply = "filter"
        else:
            validated.category.apply = "hint"
    else:
        validated.category.apply = "hint"

    profile_facets = (profile or {}).get("facets") or {}
    validated_facets: dict[str, FacetSpec] = {}
    stripped_terms: list[str] = []
    soft_facets: dict[str, list[str]] = dict(validation_meta.get("soft_facets") or {})
    dropped_brands: list[str] = list(validation_meta.get("dropped_brands") or [])

    for facet_id, spec in validated.facets.items():
        if facet_id == "brand":
            brand_meta = (profile or {}).get("core_fields", {}).get("brand") or {}
            if profile and not brand_meta.get("indexed", True):
                stripped_terms.extend(spec.values)
                continue
            brand_facet_meta = {
                "sample_values": brand_meta.get("sample_values") or [],
                "value_aliases": brand_meta.get("value_aliases") or {},
            }
            kept: list[str] = []
            samples_norm = _facet_samples_norm(brand_facet_meta)
            for val in spec.values:
                if not val.strip():
                    continue
                norm = _normalize_facet_value("brand", val, brand_facet_meta)
                if samples_norm and norm not in samples_norm:
                    dropped_brands.append(val.strip())
                    stripped_terms.append(val.strip())
                    continue
                kept.append(norm)
            if kept:
                validated_facets["brand"] = FacetSpec(
                    values=list(dict.fromkeys(kept)),
                    combine=spec.combine,
                    exclude_values=[v.strip().lower() for v in spec.exclude_values if v.strip()],
                )
            continue

        facet_meta = profile_facets.get(facet_id)
        if profile and not facet_meta:
            stripped_terms.extend(spec.values)
            continue
        if profile and facet_meta and not facet_meta.get("indexed", True):
            stripped_terms.extend(spec.values)
            continue

        samples_norm = _facet_samples_norm(facet_meta)
        norm_values: list[str] = []
        for val in spec.values:
            raw = val.strip()
            if not raw:
                continue
            if facet_meta:
                norm = _normalize_facet_value(facet_id, raw, facet_meta)
            else:
                norm = raw.lower()
            norm_values.append(norm)
            if samples_norm and norm not in samples_norm:
                bucket = soft_facets.setdefault(facet_id, [])
                if raw not in bucket:
                    bucket.append(raw)

        exclude_norm = []
        for ex in spec.exclude_values:
            if facet_meta:
                exclude_norm.append(_normalize_facet_value(facet_id, ex, facet_meta))
            else:
                exclude_norm.append(ex.strip().lower())
        if norm_values or exclude_norm:
            validated_facets[facet_id] = FacetSpec(
                values=list(dict.fromkeys(norm_values)),
                combine=spec.combine,
                exclude_values=list(dict.fromkeys(exclude_norm)),
            )

    validated.facets = validated_facets
    for facet_id, spec in validated.facets.items():
        if spec.exclude_values:
            excluded = {
                _normalize_facet_value(facet_id, v, profile_facets.get(facet_id) or {})
                for v in spec.exclude_values
            }
            spec.values = [
                v
                for v in spec.values
                if _normalize_facet_value(facet_id, v, profile_facets.get(facet_id) or {}) not in excluded
            ]

    if stripped_terms:
        extra = " ".join(stripped_terms)
        validated.free_text = f"{validated.free_text} {extra}".strip()

    if soft_facets:
        validation_meta["soft_facets"] = soft_facets
    if dropped_brands:
        validation_meta["dropped_brands"] = list(dict.fromkeys(dropped_brands))
    if validation_meta:
        validated.validation_meta = validation_meta

    if validated.intent not in ("catalog", "support", "general"):
        validated.intent = "general"

    return validated
