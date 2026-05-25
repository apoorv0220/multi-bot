from __future__ import annotations

import os
from typing import Any

from retrieval.planner import _category_confidence_threshold, _has_product_type_category
from retrieval.profile import resolve_facet_value_to_sample
from retrieval.rules_prepass import term_present_as_word
from retrieval.structured_query import CategorySpec, FacetSpec, StructuredQuery


# Only explicit `category: …` syntax from rules_prepass reaches this confidence.
_EXPLICIT_CATEGORY_CONFIDENCE = 0.95


def _normalize_facet_value(facet_id: str, value: str, facet_meta: dict[str, Any]) -> str:
    return resolve_facet_value_to_sample(facet_id, value, facet_meta)


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
    # Short tokens (men, tops) must exact-match id/label — avoids men ⊂ recommends/women.
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

    if validated.category.values:
        gazetteer_ids = set()
        if profile:
            for entry in (profile.get("category_strategy") or {}).get("gazetteer") or []:
                gazetteer_ids.add(str(entry.get("id") or "").lower())
                for label in (entry.get("labels") or []) + (entry.get("normalized") or []):
                    gazetteer_ids.add(str(label).strip().lower())
        filtered_cats = []
        for val in validated.category.values:
            v_norm = _canonical_gazetteer_category(val, profile)
            if not gazetteer_ids or v_norm in gazetteer_ids:
                filtered_cats.append(v_norm)
        is_explicit = validated.category.confidence >= _EXPLICIT_CATEGORY_CONFIDENCE
        if is_explicit and not filtered_cats:
            filtered_cats = [str(v).strip().lower() for v in validated.category.values if str(v).strip()]
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
        # Natural-language categories default to hint + boost (phase 2b).
        # Hard filter for explicit `category:` or when gazetteer threshold flag is enabled.
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
    for facet_id, spec in validated.facets.items():
        if facet_id == "brand":
            brand_meta = (profile or {}).get("core_fields", {}).get("brand") or {}
            if profile and not brand_meta.get("indexed", True):
                stripped_terms.extend(spec.values)
                continue
            validated_facets["brand"] = FacetSpec(
                values=[v.strip() for v in spec.values if v.strip()],
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
        norm_values = []
        for val in spec.values:
            if facet_meta:
                norm_values.append(_normalize_facet_value(facet_id, val, facet_meta))
            else:
                norm_values.append(val.strip().lower())
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
            excluded = {_normalize_facet_value(facet_id, v, profile_facets.get(facet_id) or {}) for v in spec.exclude_values}
            spec.values = [
                v for v in spec.values
                if _normalize_facet_value(facet_id, v, profile_facets.get(facet_id) or {}) not in excluded
            ]

    if stripped_terms:
        extra = " ".join(stripped_terms)
        validated.free_text = f"{validated.free_text} {extra}".strip()

    if validated.intent not in ("catalog", "support", "general"):
        validated.intent = "general"

    return validated
