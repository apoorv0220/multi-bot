from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from indexing.payloads import default_bucket_priority
from retrieval.category_match import has_hard_filter_category, should_apply_hard_category_filter
from retrieval.facet_match import facet_match_mode
from retrieval.rules_prepass import term_present_as_word
from retrieval.structured_query import StructuredQuery

_PRICE_ONLY_FREE_TEXT = re.compile(
    r"^\s*(?:under|below|over|above|max|min)?\s*(?:£|\$|€)?\s*\d+(?:\.\d+)?\s*$",
    re.IGNORECASE,
)
_DENSE_FILLER_PHRASE = re.compile(
    r"\b(?:can you|could you|please|show me|find me|i need|i want|looking for|"
    r"make those|make them|keep it|keep them|what about|how about)\b",
    re.IGNORECASE,
)
_DENSE_FILLER_TOKENS = frozenset({
    "some", "any", "the", "a", "an", "me", "those", "these", "them", "it",
    "can", "you", "make", "keep", "under", "please", "show", "find", "want",
    "need", "looking", "for", "about", "what", "how",
})
_COLLECTION_CATEGORY_IDS = frozenset({"erin_recommends", "default_category", "sale", "new"})
_PRODUCT_TYPE_PREPASSES_CONFIDENCE = 0.89


def _structured_has_dense_context(query: StructuredQuery) -> bool:
    if query.category.values:
        return True
    if query.facets:
        return True
    if query.price.min is not None or query.price.max is not None:
        return True
    return False


def _strip_dense_filler_text(text: str) -> str:
    remaining = _DENSE_FILLER_PHRASE.sub(" ", text or "")
    tokens = [t for t in remaining.split() if t.lower() not in _DENSE_FILLER_TOKENS]
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def _strip_facet_exclude_phrases(text: str, query: StructuredQuery) -> str:
    """Remove negation clauses so dense/lexical search is not biased toward excluded values."""
    remaining = text or ""
    for spec in query.facets.values():
        for raw in spec.exclude_values:
            val = re.escape(str(raw).strip().lower())
            if not val:
                continue
            patterns = (
                rf"(?:,?\s*)?\bbut\s+nothing\s+in\s+{val}\b",
                rf"(?:,?\s*)?\bnothing\s+in\s+{val}\b",
                rf"\b(?:no|not|without|excluding)\s+(?:the\s+)?(?:color\s+|colour\s+)?{val}\b",
                rf"\band\s+no\s+{val}\b",
            )
            for pattern in patterns:
                remaining = re.sub(pattern, " ", remaining, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", remaining).strip()

def _expand_category_hint_terms(values: list[str], profile: dict[str, Any] | None) -> list[str]:
    """All gazetteer labels/ids that match user tokens (substring-friendly)."""
    terms: list[str] = []
    for val in values:
        v = str(val).strip().lower()
        if v:
            terms.append(v)
    if not profile:
        return list(dict.fromkeys(terms))
    tokens = set()
    for val in values:
        tokens.update(t for t in val.lower().split() if len(t) >= 3)
        stem = val.lower().rstrip("s")
        if len(stem) >= 3:
            tokens.add(stem)
    for entry in (profile.get("category_strategy") or {}).get("gazetteer") or []:
        entry_id = str(entry.get("id") or "").lower()
        labels = [str(x).strip().lower() for x in (entry.get("labels") or []) + (entry.get("normalized") or [])]
        matched = entry_id in terms or any(t in entry_id for t in tokens)
        if not matched:
            cat_phrase = entry_id.replace("_", " ")
            for label in labels:
                if any(term_present_as_word(t, label) or term_present_as_word(t, cat_phrase) for t in tokens):
                    matched = True
                    break
                if entry_id in terms or any(label == t for t in tokens):
                    matched = True
                    break
        if matched:
            if entry_id:
                terms.append(entry_id)
            terms.extend(labels)
    return [t for t in dict.fromkeys(terms) if t]


def _expand_category_filter_values(values: list[str], profile: dict[str, Any] | None) -> list[str]:
    expanded: list[str] = []
    for val in values:
        v = str(val).strip().lower()
        if v:
            expanded.append(v)
    if not profile:
        return list(dict.fromkeys(expanded))
    for entry in (profile.get("category_strategy") or {}).get("gazetteer") or []:
        entry_id = str(entry.get("id") or "").lower()
        labels = [str(x).strip().lower() for x in (entry.get("labels") or []) + (entry.get("normalized") or [])]
        if entry_id in expanded or any(label in expanded for label in labels):
            expanded.append(entry_id)
            expanded.extend(labels)
    return [v for v in dict.fromkeys(expanded) if v]


@dataclass
class RetrievalPlan:
    metadata_filters: dict[str, Any] = field(default_factory=dict)
    dense_query_text: str = ""
    lexical_query_text: str = ""
    preferred_buckets: list[str] = field(default_factory=list)
    content_kind: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    category_hint_terms: list[str] = field(default_factory=list)
    category_values: list[str] = field(default_factory=list)
    soft_facet_boosts: dict[str, list[str]] = field(default_factory=dict)
    facet_excludes: dict[str, list[str]] = field(default_factory=dict)
    use_retrieval_hybrid: bool = False


def _lexical_query_text(query: StructuredQuery) -> str:
    parts: list[str] = []
    free_text = _strip_facet_exclude_phrases(query.free_text.strip(), query)
    if free_text:
        parts.append(free_text)
    if query.category.values:
        parts.extend(str(v) for v in query.category.values)
    for facet_id, spec in query.facets.items():
        parts.extend(str(v) for v in spec.values)
        if facet_id == "brand" and spec.values:
            parts.append(str(spec.values[0]))
    sku_tokens = re.findall(r"\b[A-Z0-9][A-Z0-9\-]{3,}\b", query.free_text or "")
    parts.extend(sku_tokens)
    return " ".join(dict.fromkeys(p for p in parts if p)).strip()


def _is_price_only_free_text(text: str) -> bool:
    return bool(_PRICE_ONLY_FREE_TEXT.match((text or "").strip()))


def _catalog_dense_query_text(query: StructuredQuery) -> str:
    """Rebuild dense text from category, facets, and price so stripped free_text stays searchable."""
    parts: list[str] = []
    for val in query.category.values[:4]:
        v = str(val).strip()
        if v:
            parts.append(v)
    for facet_id in sorted(query.facets.keys()):
        spec = query.facets[facet_id]
        for val in spec.values[:3]:
            v = str(val).strip()
            if v:
                parts.append(v)
    residual = _strip_facet_exclude_phrases((query.free_text or "").strip(), query)
    if residual and re.fullmatch(r"[\s'\"]+", residual):
        residual = ""
    if _structured_has_dense_context(query):
        residual = _strip_dense_filler_text(residual)
    filler_only = not residual or all(t in _DENSE_FILLER_TOKENS for t in residual.lower().split())
    if residual and not filler_only and not _is_price_only_free_text(residual):
        parts.append(residual)
    elif query.price.max is not None:
        parts.append(f"under {query.price.max:g}")
    elif query.price.min is not None:
        parts.append(f"over {query.price.min:g}")
    return " ".join(dict.fromkeys(p for p in parts if p)).strip()


def _hybrid_enabled_for_query(query: StructuredQuery, profile: dict[str, Any] | None) -> bool:
    if query.intent != "catalog":
        return False
    if os.getenv("RETRIEVAL_HYBRID_ENABLED", "true").strip().lower() not in ("1", "true", "yes"):
        return False
    try:
        min_products = int(os.getenv("RETRIEVAL_HYBRID_MIN_PRODUCTS", "10"))
    except ValueError:
        min_products = 10
    product_count = int((profile or {}).get("stats", {}).get("product_count") or 0)
    return product_count >= min_products


def apply_retrieval_rewrite(query: StructuredQuery) -> StructuredQuery:
    """Fill retrieval_rewrite when the LLM omitted it (catalog dense phrase)."""
    updated = query.copy()
    if updated.retrieval_rewrite.strip():
        return updated
    if updated.intent == "catalog":
        updated.retrieval_rewrite = _catalog_dense_query_text(updated)
    elif updated.free_text.strip():
        updated.retrieval_rewrite = updated.free_text.strip()
    return updated


def build_retrieval_plan(
    query: StructuredQuery,
    *,
    profile: dict[str, Any] | None = None,
    tenant_profile: dict[str, Any] | None = None,
) -> RetrievalPlan:
    profile = tenant_profile if tenant_profile is not None else profile
    filters: dict[str, Any] = {}
    facet_filters: dict[str, dict[str, Any]] = {}

    category_hint_terms: list[str] = []
    use_category_filter = query.category.apply == "filter"
    if not use_category_filter and should_apply_hard_category_filter(query, profile):
        use_category_filter = True
    if use_category_filter and query.category.values:
        filters["categories"] = _expand_category_filter_values(query.category.values, profile)
        category_hint_terms = _expand_category_hint_terms(query.category.values, profile)
    elif query.category.values:
        category_hint_terms = _expand_category_hint_terms(query.category.values, profile)

    if query.stock_status:
        filters["stock_status"] = query.stock_status

    # Price bounds are applied in-app after vector search (see retrieval/post_filter.py).

    soft_facet_boosts: dict[str, list[str]] = {}
    facet_excludes: dict[str, list[str]] = {}
    for facet_id, spec in query.facets.items():
        if spec.exclude_values:
            facet_excludes[facet_id] = [v.lower() for v in spec.exclude_values]
        if facet_id == "brand" and spec.values:
            filters["brand"] = spec.values[0]
            continue
        if not spec.values:
            continue
        values = [v.lower() for v in spec.values]
        if facet_match_mode(facet_id, profile) == "strict":
            facet_filters[facet_id] = {
                "values": values,
                "combine": spec.combine,
            }
        else:
            soft_facet_boosts[facet_id] = values

    if facet_filters:
        filters["facet_filters"] = facet_filters

    content_kind = "product" if query.intent == "catalog" and (query.category.apply == "filter" or query.facets) else None
    if query.intent == "catalog":
        content_kind = "product"

    catalog_slots = query.intent == "catalog" and (
        query.category.values
        or query.facets
        or query.price.min is not None
        or query.price.max is not None
    )
    if catalog_slots:
        dense_text = _catalog_dense_query_text(query)
    elif query.retrieval_rewrite.strip():
        dense_text = query.retrieval_rewrite.strip()
    else:
        dense_text = query.free_text.strip()
        if category_hint_terms:
            dense_text = f"{dense_text} {' '.join(category_hint_terms)}".strip()
        elif query.category.apply == "hint" and query.category.values:
            dense_text = f"{dense_text} {' '.join(query.category.values)}".strip()

    lexical_text = _lexical_query_text(query) or dense_text or query.free_text

    return RetrievalPlan(
        metadata_filters=filters,
        dense_query_text=dense_text or query.free_text,
        lexical_query_text=lexical_text,
        preferred_buckets=default_bucket_priority(query.intent),
        content_kind=content_kind,
        price_min=query.price.min,
        price_max=query.price.max,
        category_hint_terms=category_hint_terms,
        category_values=list(query.category.values),
        soft_facet_boosts=soft_facet_boosts,
        facet_excludes=facet_excludes,
        use_retrieval_hybrid=_hybrid_enabled_for_query(query, profile),
    )


def _category_confidence_threshold(profile: dict[str, Any] | None) -> float:
    from retrieval.category_match import _category_confidence_threshold as _threshold

    return _threshold(profile)


def _has_product_type_category(values: list[str], profile: dict[str, Any] | None) -> bool:
    if has_hard_filter_category(values, profile):
        return True
    if not values:
        return False
    return any(str(v).strip().lower() not in _COLLECTION_CATEGORY_IDS for v in values)


_should_apply_product_type_category_filter = should_apply_hard_category_filter
