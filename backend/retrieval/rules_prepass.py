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
NEGATION_PATTERN = re.compile(
    r"\b(?:and\s+)?(?:no|not|without|nothing\s+in)\s+(?P<val>[a-z][a-z0-9\-]+(?:\s+[a-z][a-z0-9\-]+)?)",
    re.IGNORECASE,
)
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
    "help me buy",
    "help me find",
    "help me choose",
    "help me pick",
)
COLOUR_FINISH_FACET_KEYS = frozenset({"colour", "color", "finish"})
_AUDIENCE_CATEGORY_STEMS = frozenset({"men", "women"})


def _is_audience_category(cat_id: str) -> bool:
    """Gender/department gazetteer ids (men, women, men_sale, …)."""
    c = str(cat_id).strip().lower()
    if not c:
        return False
    if c in _AUDIENCE_CATEGORY_STEMS:
        return True
    return any(c.startswith(f"{stem}_") or c.endswith(f"_{stem}") for stem in _AUDIENCE_CATEGORY_STEMS)


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


# ASCII and typographic apostrophe (widget/input often sends U+2019).
_POSSESSIVE_PATTERN = re.compile(r"\b(\w+)['\u2019]s\b", re.IGNORECASE)
_SIZE_PHRASE_PATTERN = re.compile(
    r"\b(?:in\s+)?size\s+(?P<value>[a-z][a-z0-9]*)\b",
    re.IGNORECASE,
)


def _tokenize(query: str) -> list[str]:
    """Tokenize for facet matching; fold possessives so men's does not yield a lone ``s`` token."""
    normalized = _POSSESSIVE_PATTERN.sub(r"\1", query or "")
    return [t for t in re.findall(r"[a-z0-9]+", normalized.lower()) if t]


def term_present_as_word(term: str, text: str) -> bool:
    """True when ``term`` appears as a whole word/phrase in ``text`` (avoids men ⊂ women)."""
    term = _normalize_label(term)
    text = _normalize_label(text)
    if not term or not text:
        return False
    if " " in term:
        return term in text
    return bool(re.search(rf"\b{re.escape(term)}\b", text))


def _extract_explicit_size_phrase(message: str) -> str | None:
    match = _SIZE_PHRASE_PATTERN.search(message or "")
    if not match:
        return None
    return _normalize_label(match.group("value"))


_PRODUCT_TYPE_TIE_BREAK = (
    "tees",
    "tops",
    "tanks",
    "pants",
    "jackets",
    "hoodies_sweatshirts",
    "bags",
)


def _product_type_tie_rank(cat_id: str) -> int:
    try:
        return _PRODUCT_TYPE_TIE_BREAK.index(cat_id)
    except ValueError:
        return len(_PRODUCT_TYPE_TIE_BREAK)


_PRODUCT_TYPE_CATEGORY_PATTERNS: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (re.compile(r"\b(?:t-?shirts?|tees)\b", re.IGNORECASE), ("tee", "shirt")),
    (re.compile(r"\btank\s+tops?\b", re.IGNORECASE), ("tank", "tops", "bras")),
    (re.compile(r"\b(?:trousers|pants)\b", re.IGNORECASE), ("pants", "trouser", "pant")),
    (re.compile(r"\bjackets?\b", re.IGNORECASE), ("jacket",)),
    (re.compile(r"\b(?:hoodies|sweatshirts?)\b", re.IGNORECASE), ("hoodie", "sweatshirt")),
    (re.compile(r"\bbags?\b", re.IGNORECASE), ("bag",)),
]


def _category_id_matches_stem(cat_id: str, stem: str) -> bool:
    """Match stems to gazetteer ids by segment, not substring (shirt ≠ hoodies_sweatshirts)."""
    stem = stem.strip().lower()
    if not stem or not cat_id:
        return False
    parts = re.split(r"[_\-\s]+", cat_id.strip().lower())
    if stem in parts:
        return True
    plural = f"{stem}s"
    return plural in parts or any(part.rstrip("s") == stem for part in parts)


def _product_type_entry_score(stems: tuple[str, ...], entry: dict[str, Any]) -> int:
    cat_id = str(entry.get("id") or "").strip().lower()
    if not cat_id or cat_id in {"erin_recommends", "default_category", "sale", "new"}:
        return 0
    labels = [str(x).strip().lower() for x in (entry.get("labels") or []) + (entry.get("normalized") or [])]
    score = 0
    for stem in stems:
        if _category_id_matches_stem(cat_id, stem):
            score += 100
        for label in labels:
            if term_present_as_word(stem, label):
                score += 80
    return score


def _match_category_product_type(message: str, profile: dict[str, Any] | None) -> tuple[list[str], float]:
    """Prefer garment-type categories (tees, pants) over collection buckets like erin_recommends."""
    if not profile:
        return [], 0.0
    gazetteer = (profile.get("category_strategy") or {}).get("gazetteer") or []
    best_id = ""
    best_score = 0
    for pattern, stems in _PRODUCT_TYPE_CATEGORY_PATTERNS:
        if not pattern.search(message):
            continue
        for entry in gazetteer:
            cat_id = str(entry.get("id") or "").strip().lower()
            score = _product_type_entry_score(stems, entry)
            if score > best_score or (
                score == best_score
                and score > 0
                and _product_type_tie_rank(cat_id) < _product_type_tie_rank(best_id)
            ):
                best_score = score
                best_id = cat_id
    if best_id:
        return [best_id], 0.89
    return [], 0.0


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
            if term_present_as_word(label_norm, q_norm):
                conf = 0.88 if len(label_norm.split()) > 1 else 0.85
            else:
                label_stem = label_norm.rstrip("s")
                if label_stem != label_norm and term_present_as_word(label_stem, q_norm):
                    conf = 0.82
                elif label_norm in q_tokens or label_stem in q_tokens:
                    conf = 0.80
                else:
                    for token in q_tokens:
                        if len(token) < 3:
                            continue
                        if token == label_norm or token == label_stem:
                            conf = max(conf, 0.78)
            entry_conf = max(entry_conf, conf)
        if cat_id and entry_conf == 0:
            cat_phrase = cat_id.replace("_", " ")
            if term_present_as_word(cat_id, q_norm) or term_present_as_word(cat_phrase, q_norm):
                entry_conf = 0.80
            elif cat_id in q_tokens or cat_phrase in q_tokens:
                entry_conf = 0.78
        if entry_conf > 0:
            best_conf = max(best_conf, entry_conf)
            if cat_id:
                matched_values.append(cat_id)
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
    from retrieval.category_match import hard_filter_category_terms_in_message

    return hard_filter_category_terms_in_message(message, profile)


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


def _apply_negation_phrases(
    message: str,
    facets: dict[str, FacetSpec],
    profile: dict[str, Any] | None,
) -> None:
    if not profile:
        return
    profile_facets = (profile.get("facets") or {})
    for match in NEGATION_PATTERN.finditer(message):
        token = _normalize_label(match.group("val"))
        if not token:
            continue
        for facet_id, meta in profile_facets.items():
            samples = [str(s) for s in (meta.get("sample_values") or []) if s]
            aliases = meta.get("value_aliases") or {}
            alias_hits = (
                [_normalize_label(k) for k in aliases.keys()]
                if isinstance(aliases, dict)
                else []
            )
            matched = token in {_normalize_label(s) for s in samples}
            matched = matched or token in alias_hits
            if not matched and not any(token in _normalize_label(s) for s in samples):
                continue
            spec = facets.setdefault(facet_id, FacetSpec(values=[], combine="OR"))
            spec.values = [v for v in spec.values if _normalize_label(v) != token]
            excludes = list(spec.exclude_values)
            if token not in excludes:
                excludes.append(token)
            spec.exclude_values = excludes


def _strip_matched_tokens(free_text: str, category_values: list[str], facets: dict[str, FacetSpec]) -> str:
    remaining = _POSSESSIVE_PATTERN.sub(r"\1", free_text or "")
    remaining = re.sub(r"\b's\b", " ", remaining, flags=re.IGNORECASE)
    for cat in category_values:
        cat = str(cat).strip()
        if not cat:
            continue
        remaining = re.sub(re.escape(cat), " ", remaining, flags=re.IGNORECASE)
    for spec in facets.values():
        for val in spec.values:
            val = str(val).strip()
            if not val:
                continue
            remaining = re.sub(re.escape(val), " ", remaining, flags=re.IGNORECASE)
    for verb in SHOPPING_VERBS:
        remaining = re.sub(rf"\b{re.escape(verb)}\b", " ", remaining, flags=re.IGNORECASE)
    remaining = re.sub(r",\s*,+", " ", remaining)
    remaining = re.sub(r"\s*,\s*", " ", remaining)
    remaining = re.sub(r",+", " ", remaining)
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

    from retrieval.tools.product_refs import extract_product_title_from_message, is_product_detail_message

    if is_product_detail_message(message):
        result.intent = "catalog"
        title = extract_product_title_from_message(message)
        if title:
            result.free_text = title
            result.retrieval_rewrite = title
        return result

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
    product_type_values, product_type_conf = _match_category_product_type(message, profile)
    audience_values = [v for v in cat_values if _is_audience_category(v)]
    if product_type_values and product_type_conf >= cat_conf:
        cat_values = list(dict.fromkeys(product_type_values + audience_values))
        cat_conf = product_type_conf
    elif product_type_values:
        cat_values = list(
            dict.fromkeys(
                product_type_values
                + audience_values
                + [v for v in cat_values if v != "erin_recommends"]
            )
        )
        cat_conf = max(cat_conf, product_type_conf)
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

    explicit_size = _extract_explicit_size_phrase(message)
    if explicit_size:
        result.facets["size"] = FacetSpec(values=[explicit_size], combine="OR")

    for facet_id, spec in _detect_colour_phrases(message).items():
        if facet_id not in result.facets:
            result.facets[facet_id] = spec

    _apply_within_facet_or(message, result.facets, profile)
    _apply_negation_phrases(message, result.facets, profile)

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
    has_shopping = any(verb in q_lower for verb in SHOPPING_VERBS)
    if has_shopping:
        intent = "catalog"
    if any(word in q_lower for word in ("price", "stock", "product", "category", "brand:")):
        intent = "catalog"
    if cat_values or facet_hits or result.category.values:
        intent = "catalog"
    if any(word in q_lower for word in SUPPORT_PATH_KEYWORDS):
        if not has_shopping:
            intent = "support"
    if re.search(r"\b(?:cheapest|lowest\s+price|budget[\-\s]?friendly)\b", q_lower):
        result.sort = "price_asc"
    if re.search(r"\b(?:premium|luxury|high[\-\s]?end)\b", q_lower) and re.search(r"\babove\b|\bover\b", q_lower):
        result.sort = "price_desc"
    if re.search(r"\b(?:best[\-\s]?rated|top[\-\s]?rated)\b", q_lower):
        result.sort = "rating_desc"
    if re.search(r"\b(?:newest|latest|new\s+arrivals?)\b", q_lower):
        result.sort = "newest"
    if re.search(r"\b(?:best[\-\s]?selling|bestsellers?)\b", q_lower):
        result.sort = "bestseller"
    if re.search(r"\b(?:trending|popular\s+right\s+now|what(?:'s|\s+is)\s+popular)\b", q_lower):
        result.sort = "trending"
    if result.sort or re.search(
        r"\b(?:show\s+(?:me\s+)?(?:all|every)\s+products?|newest|latest|cheapest|trending|popular)\b",
        q_lower,
    ):
        intent = "catalog"
    result.intent = intent  # type: ignore[assignment]

    result.free_text = _strip_matched_tokens(
        message,
        result.category.values,
        result.facets,
    ) or message

    return result
