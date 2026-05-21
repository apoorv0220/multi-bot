from __future__ import annotations

import os
import re
from typing import Any

from indexing.payloads import SUPPORT_PATH_KEYWORDS, infer_intent_from_query
from retrieval.structured_query import (
    CategorySpec,
    FacetSpec,
    PriceSpec,
    StructuredQuery,
    empty_structured_query,
)

ATTRIBUTE_PATTERN = re.compile(
    r"\b(?P<key>color|colour|material|size|brand|category|finish)\s*[:=]\s*(?P<value>.+?)"
    r"(?=\s+\b(?:color|colour|material|size|brand|category|finish)\s*[:=]"
    r"|\s+\b(?:under|below|max|over|above|min)\s+\$?\d+(?:\.\d+)?"
    r"|\s+\b(?:in stock|out of stock)\b|$)",
    re.IGNORECASE,
)
UNDER_PRICE_PATTERN = re.compile(r"\b(?:under|below|max)\s+\$?(\d+(?:\.\d+)?)", re.IGNORECASE)
OVER_PRICE_PATTERN = re.compile(r"\b(?:over|above|min)\s+\$?(\d+(?:\.\d+)?)", re.IGNORECASE)
CLEAR_PRICE_PATTERN = re.compile(r"\b(?:no price|clear price|remove price)\b", re.IGNORECASE)
CLEAR_CATEGORY_PATTERN = re.compile(r"\b(?:clear category|any category)\b", re.IGNORECASE)
CLEAR_ALL_PATTERN = re.compile(r"\b(?:start over|reset filters|clear all)\b", re.IGNORECASE)
SHOPPING_VERBS = (
    "want",
    "need",
    "looking for",
    "show me",
    "find me",
    "browse",
    "shop for",
    "buy",
    "get me",
    "search for",
)
COLOUR_FINISH_FACET_KEYS = frozenset({"colour", "color", "finish"})
PRODUCT_TYPE_PATTERN = re.compile(
    r"\b(?:taps?|faucets?|basins?|sinks?|toilets?|showers?|baths?|wcs?)\b",
    re.IGNORECASE,
)


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _tokenize(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if t]


def _match_gazetteer(query: str, profile: dict[str, Any] | None) -> tuple[list[str], float]:
    if not profile:
        return [], 0.0
    gazetteer = (profile.get("category_strategy") or {}).get("gazetteer") or []
    q_norm = _normalize_label(query)
    q_tokens = set(_tokenize(query))
    matched_values: list[str] = []
    best_conf = 0.0
    for entry in gazetteer:
        labels = list(entry.get("labels") or []) + list(entry.get("normalized") or [])
        aliases = entry.get("aliases") or {}
        if isinstance(aliases, dict):
            labels.extend(str(alias) for alias in aliases.keys())
        cat_id = str(entry.get("id") or "").strip().lower()
        entry_conf = 0.0
        for label in labels:
            label_norm = _normalize_label(label)
            if not label_norm:
                continue
            conf = 0.0
            if label_norm in q_norm:
                conf = 0.88 if len(label_norm.split()) > 1 else 0.85
            elif label_norm.rstrip("s") in q_norm or f"{label_norm}s" in q_norm:
                conf = 0.82
            elif label_norm in q_tokens or label_norm.rstrip("s") in q_tokens:
                conf = 0.80
            else:
                for token in q_tokens:
                    if len(token) < 3:
                        continue
                    stem = token.rstrip("s")
                    label_stem = label_norm.rstrip("s")
                    if stem in label_norm or label_stem in token or token in label_norm:
                        conf = max(conf, 0.78)
            entry_conf = max(entry_conf, conf)
        if entry_conf > 0:
            best_conf = max(best_conf, entry_conf)
            if cat_id:
                matched_values.append(cat_id)
            for label in labels:
                label_norm = _normalize_label(label)
                if label_norm:
                    matched_values.append(label_norm)
    return list(dict.fromkeys(v for v in matched_values if v)), best_conf


def _match_facet_values(query: str, profile: dict[str, Any] | None) -> dict[str, FacetSpec]:
    if not profile:
        return {}
    q_norm = _normalize_label(query)
    q_tokens = set(_tokenize(query))
    matched: dict[str, FacetSpec] = {}
    facets = profile.get("facets") or {}
    for facet_id, facet_meta in facets.items():
        if not isinstance(facet_meta, dict):
            continue
        samples = list(facet_meta.get("sample_values") or [])
        aliases = facet_meta.get("value_aliases") or {}
        if isinstance(aliases, dict):
            for alias, canonical in aliases.items():
                if _normalize_label(alias) in q_norm or _normalize_label(alias) in q_tokens:
                    samples.append(str(canonical))
        hits: list[str] = []
        for sample in samples:
            sample_norm = _normalize_label(str(sample))
            if not sample_norm:
                continue
            if len(sample_norm) <= 2:
                if sample_norm in q_tokens:
                    if sample_norm not in hits:
                        hits.append(sample_norm)
                continue
            if sample_norm in q_tokens or re.search(
                rf"\b{re.escape(sample_norm)}\b",
                q_norm,
            ):
                if sample_norm not in hits:
                    hits.append(sample_norm)
            elif sample_norm == "matt" and "matt" in q_norm:
                if "matt" not in hits:
                    hits.append("matt")
        if hits:
            matched[str(facet_id)] = FacetSpec(values=hits, combine="OR")
    return matched


def _detect_colour_phrases(query: str) -> dict[str, FacetSpec]:
    """Match common colour phrases when profile samples may not list compounds."""
    q = _normalize_label(query)
    extra: dict[str, FacetSpec] = {}
    colour_hits: list[str] = []
    if "matt black" in q or "matte black" in q:
        colour_hits.append("matt black")
    elif "black" in q:
        colour_hits.append("black")
    if colour_hits:
        extra["colour"] = FacetSpec(values=colour_hits, combine="OR")
        if "matt" in q and "finish" not in extra:
            extra.setdefault("finish", FacetSpec(values=["matt"], combine="OR"))
    return extra


def _has_or_alternation(message: str) -> bool:
    q = (message or "").lower()
    if re.search(r"\b(?:or|either)\b", q):
        return True
    if "/" in q and len(q.split()) <= 10:
        return True
    return False


def _apply_within_facet_or(message: str, facets: dict[str, FacetSpec], profile: dict[str, Any] | None) -> None:
    if not _has_or_alternation(message):
        return
    q_norm = _normalize_label(message)
    profile_facets = (profile or {}).get("facets") or {}
    for facet_id, spec in list(facets.items()):
        if len(spec.values) >= 2:
            spec.combine = "OR"
            continue
        meta = profile_facets.get(facet_id) or {}
        samples = [str(s) for s in (meta.get("sample_values") or [])]
        hits: list[str] = []
        for sample in samples:
            sample_norm = _normalize_label(sample)
            if not sample_norm:
                continue
            if sample_norm in q_norm:
                hits.append(sample_norm)
        if len(hits) >= 2:
            facets[facet_id] = FacetSpec(values=list(dict.fromkeys(hits)), combine="OR")
        elif len(hits) == 1 and re.search(rf"\b{re.escape(hits[0])}\s+or\s+", q_norm):
            for sample in samples:
                sample_norm = _normalize_label(sample)
                if sample_norm and sample_norm in q_norm and sample_norm not in hits:
                    hits.append(sample_norm)
            if len(hits) >= 2:
                facets[facet_id] = FacetSpec(values=list(dict.fromkeys(hits)), combine="OR")


def _category_filter_on_gazetteer_enabled() -> bool:
    return os.getenv("RETRIEVAL_CATEGORY_FILTER_ON_GAZETTEER", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _category_confidence_threshold(profile: dict[str, Any] | None) -> float:
    if profile:
        try:
            return float(
                (profile.get("category_strategy") or {}).get("confidence_threshold")
                or os.getenv("RETRIEVAL_CATEGORY_CONFIDENCE_THRESHOLD", "0.75")
            )
        except (TypeError, ValueError):
            pass
    try:
        return float(os.getenv("RETRIEVAL_CATEGORY_CONFIDENCE_THRESHOLD", "0.75"))
    except ValueError:
        return 0.75


def _is_colour_only_facets(facets: dict[str, FacetSpec]) -> bool:
    if not facets:
        return False
    return all(key in COLOUR_FINISH_FACET_KEYS for key in facets)


def _product_type_terms_in_query(message: str, profile: dict[str, Any] | None) -> list[str]:
    if not profile:
        return []
    q_tokens = set(_tokenize(message))
    q_norm = _normalize_label(message)
    hits: list[str] = []
    gazetteer = (profile.get("category_strategy") or {}).get("gazetteer") or []
    for entry in gazetteer:
        labels = list(entry.get("labels") or []) + list(entry.get("normalized") or [])
        cat_id = str(entry.get("id") or "").strip().lower()
        aliases = entry.get("aliases") or {}
        if isinstance(aliases, dict):
            labels.extend(str(alias) for alias in aliases.keys())
            labels.extend(str(canonical) for canonical in aliases.values())
        for label in labels:
            label_norm = _normalize_label(label)
            if not label_norm:
                continue
            if label_norm in q_tokens or label_norm in q_norm:
                if cat_id and cat_id not in hits:
                    hits.append(cat_id)
                if label_norm not in hits:
                    hits.append(label_norm)
    for match in PRODUCT_TYPE_PATTERN.finditer(message):
        token = _normalize_label(match.group(0))
        if token and token not in hits:
            hits.append(token)
    return list(dict.fromkeys(hits))


def _boost_category_over_colour_only_facets(
    message: str,
    *,
    profile: dict[str, Any] | None,
    category_values: list[str],
    category_conf: float,
    facets: dict[str, FacetSpec],
) -> tuple[list[str], float]:
    product_types = _product_type_terms_in_query(message, profile)
    if not product_types:
        return category_values, category_conf
    if not _is_colour_only_facets(facets) and category_values:
        return category_values, category_conf
    merged = list(dict.fromkeys(product_types + list(category_values)))
    boosted_conf = max(category_conf, 0.86)
    return merged, boosted_conf


def _strip_matched_tokens(free_text: str, category_values: list[str], facets: dict[str, FacetSpec]) -> str:
    remaining = free_text
    for cat in category_values:
        remaining = re.sub(re.escape(cat), " ", remaining, flags=re.IGNORECASE)
    for spec in facets.values():
        for val in spec.values:
            remaining = re.sub(re.escape(val), " ", remaining, flags=re.IGNORECASE)
    for verb in SHOPPING_VERBS:
        remaining = re.sub(rf"\b{re.escape(verb)}\b", " ", remaining, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", remaining).strip()


def rules_prepass(
    query: str,
    *,
    profile: dict[str, Any] | None,
    session_query: StructuredQuery | None = None,
) -> StructuredQuery:
    message = (query or "").strip()
    result = empty_structured_query()
    result.free_text = message

    if CLEAR_ALL_PATTERN.search(message):
        result.session.clear = {
            "facets": list((session_query.facets if session_query else {}).keys()),
            "category": True,
            "price": True,
            "stock_status": True,
        }
        result.intent = "general"
        return result

    if "in stock" in message.lower():
        result.stock_status = "instock"
    if "out of stock" in message.lower():
        result.stock_status = "outofstock"
    if CLEAR_PRICE_PATTERN.search(message):
        result.session.clear["price"] = True
    if CLEAR_CATEGORY_PATTERN.search(message):
        result.session.clear["category"] = True

    under = UNDER_PRICE_PATTERN.search(message)
    if under:
        result.price.max = float(under.group(1))
    over = OVER_PRICE_PATTERN.search(message)
    if over:
        result.price.min = float(over.group(1))

    explicit_category = False
    for match in ATTRIBUTE_PATTERN.finditer(message):
        key = match.group("key").lower().strip()
        value = match.group("value").strip()
        if key == "category":
            explicit_category = True
            result.category.values = [value]
            result.category.confidence = 0.95
        elif key == "brand":
            result.facets["brand"] = FacetSpec(values=[value], combine="OR")
        else:
            facet_key = "colour" if key == "color" else key
            result.facets[facet_key] = FacetSpec(values=[value], combine="OR")

    cat_values, cat_conf = _match_gazetteer(message, profile)
    if cat_values and not explicit_category and cat_conf >= (result.category.confidence or 0.0):
        result.category.values = cat_values
        result.category.confidence = cat_conf

    facet_hits = _match_facet_values(message, profile)
    for facet_id, spec in facet_hits.items():
        if facet_id not in result.facets:
            result.facets[facet_id] = spec
        else:
            merged = list(dict.fromkeys(result.facets[facet_id].values + spec.values))
            result.facets[facet_id] = FacetSpec(values=merged, combine=result.facets[facet_id].combine)

    for facet_id, spec in _detect_colour_phrases(message).items():
        if facet_id not in result.facets:
            result.facets[facet_id] = spec

    _apply_within_facet_or(message, result.facets, profile)

    boosted_values, boosted_conf = _boost_category_over_colour_only_facets(
        message,
        profile=profile,
        category_values=result.category.values,
        category_conf=result.category.confidence,
        facets=result.facets,
    )
    if boosted_values and not explicit_category:
        result.category.values = boosted_values
        result.category.confidence = boosted_conf

    if (
        _category_filter_on_gazetteer_enabled()
        and cat_values
        and not explicit_category
        and cat_conf >= _category_confidence_threshold(profile)
    ):
        result.category.apply = "filter"

    intent = infer_intent_from_query(message)
    q_lower = message.lower()
    if any(verb in q_lower for verb in SHOPPING_VERBS):
        intent = "catalog"
    if any(word in q_lower for word in ("price", "stock", "product", "category", "brand:")):
        intent = "catalog"
    if cat_values or facet_hits or result.category.values:
        intent = "catalog"
    if any(word in q_lower for word in SUPPORT_PATH_KEYWORDS):
        intent = "support"
    result.intent = intent  # type: ignore[assignment]

    result.free_text = _strip_matched_tokens(
        message,
        result.category.values,
        result.facets,
    ) or message

    return result
