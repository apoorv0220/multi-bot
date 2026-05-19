from __future__ import annotations

import os
from typing import Any

from retrieval.planner import _category_confidence_threshold, _has_product_type_category
from retrieval.structured_query import CategorySpec, FacetSpec, StructuredQuery


# Only explicit `category: …` syntax from rules_prepass reaches this confidence.
_EXPLICIT_CATEGORY_CONFIDENCE = 0.95


def _normalize_facet_value(facet_id: str, value: str, facet_meta: dict[str, Any]) -> str:
    norm = value.strip().lower()
    aliases = facet_meta.get("value_aliases") or {}
    if isinstance(aliases, dict):
        for alias, canonical in aliases.items():
            if norm == str(alias).strip().lower():
                return str(canonical).strip().lower()
    return norm


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
            v_norm = val.strip().lower()
            if not gazetteer_ids or v_norm in gazetteer_ids or any(v_norm in g for g in gazetteer_ids):
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
        if norm_values:
            validated_facets[facet_id] = FacetSpec(values=list(dict.fromkeys(norm_values)), combine=spec.combine)
    validated.facets = validated_facets

    if stripped_terms:
        extra = " ".join(stripped_terms)
        validated.free_text = f"{validated.free_text} {extra}".strip()

    if validated.intent not in ("catalog", "support", "general"):
        validated.intent = "general"

    return validated
