from __future__ import annotations

import os
import re
from typing import Any, Literal

from retrieval.planner import RetrievalPlan
from retrieval.structured_query import StructuredQuery

RetrievalTier = Literal["strict", "relaxed_facets", "relaxed_category", "semantic_catalog", "relaxed_price"]
_PRODUCT_TYPE_STEM = re.compile(
    r"\b(?:taps?|faucets?|basins?|sinks?|toilets?|showers?|baths?|wcs?)\b",
    re.IGNORECASE,
)
MatchMode = Literal["exact", "relaxed", "semantic_fallback"]


def _payload_price(payload: dict[str, Any]) -> float | None:
    raw = payload.get("price")
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def filter_results_by_price(
    results: list[Any],
    *,
    min_price: float | None = None,
    max_price: float | None = None,
) -> list[Any]:
    """Apply price bounds in-app (Qdrant Range on price is unreliable without a float index)."""
    if min_price is None and max_price is None:
        return results
    kept: list[Any] = []
    for result in results:
        price = _payload_price(getattr(result, "payload", None) or {})
        if price is None:
            continue
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        kept.append(result)
    return kept


_EXACT_CATEGORY_BOOST = 0.15
_SUBSTRING_CATEGORY_BOOST = 0.08


def _category_boost(payload: dict[str, Any], hint_terms: list[str]) -> float:
    if not hint_terms:
        return 0.0
    categories = [str(c).strip().lower() for c in (payload.get("categories") or []) if str(c).strip()]
    if not categories:
        return 0.0
    best = 0.0
    for term in hint_terms:
        t = term.strip().lower()
        if not t:
            continue
        t_stem = t.rstrip("s")
        for cat in categories:
            if cat == t:
                best = max(best, _EXACT_CATEGORY_BOOST)
                continue
            cat_stem = cat.rstrip("s")
            if t in cat or cat in t or t_stem in cat or cat_stem in t:
                best = max(best, _SUBSTRING_CATEGORY_BOOST)
    return best


def filter_results_by_category_hints(
    results: list[Any],
    hint_terms: list[str],
    *,
    require_match: bool = False,
) -> list[Any]:
    """Keep hits whose payload categories match hint terms; optional hard filter for product-type hints."""
    if not hint_terms or not results:
        return results
    matched: list[Any] = []
    for result in results:
        payload = getattr(result, "payload", None) or {}
        if require_match:
            if category_match_tier(payload, hint_terms) > 0:
                matched.append(result)
        elif _category_boost(payload, hint_terms) > 0:
            matched.append(result)
    if require_match and matched:
        return matched
    return matched if matched else results


def boost_results_by_category(results: list[Any], hint_terms: list[str]) -> list[Any]:
    """Deprecated: prefer sort_results_by_category_tier."""
    return sort_results_by_category_tier(results, hint_terms)


def _payload_categories(payload: dict[str, Any]) -> list[str]:
    return [str(c).strip().lower() for c in (payload.get("categories") or []) if str(c).strip()]


def _fixture_stems_in_hints(hint_terms: list[str]) -> set[str]:
    stems: set[str] = set()
    for term in hint_terms:
        t = term.strip().lower()
        if not t:
            continue
        if _PRODUCT_TYPE_STEM.search(t):
            stems.add(t.rstrip("s"))
    return stems


def _category_has_exact_fixture_label(categories: list[str], fixture_stem: str) -> bool:
    """True when a category path names the fixture type (e.g. 'Basins'), not an accessory branch."""
    stem = fixture_stem.strip().lower()
    plural = f"{stem}s"
    for cat in categories:
        if cat == stem or cat == plural:
            return True
        parts = [p for p in re.split(r"[\s&,]+", cat) if p]
        if parts and parts[-1].rstrip("s") == stem:
            return True
    return False


def _should_demote_accessory_categories(categories: list[str], hint_terms: list[str]) -> bool:
    """Demote substring-only matches like 'Basin Taps & Mixers' when user asked for basins fixtures."""
    fixture_stems = _fixture_stems_in_hints(hint_terms)
    if "basin" not in fixture_stems:
        return False
    if _category_has_exact_fixture_label(categories, "basin"):
        return False
    return any("tap" in cat or "mixer" in cat for cat in categories)


def category_match_tier(payload: dict[str, Any], hint_terms: list[str]) -> int:
    """Return 2=exact category, 1=substring, 0=no match (or accessory-only false positive)."""
    categories = _payload_categories(payload)
    if not hint_terms or not categories:
        return 0
    best = 0
    for term in hint_terms:
        t = term.strip().lower()
        if not t:
            continue
        t_stem = t.rstrip("s")
        for cat in categories:
            if cat == t or cat == t_stem or cat == f"{t_stem}s":
                best = max(best, 2)
                continue
            cat_stem = cat.rstrip("s")
            if t in cat or cat in t or t_stem in cat or cat_stem in t:
                best = max(best, 1)
    if best == 1 and _should_demote_accessory_categories(categories, hint_terms):
        return 0
    return best


def sort_results_by_category_tier(results: list[Any], hint_terms: list[str]) -> list[Any]:
    """Sort by category match tier (desc), then vector score (desc)."""
    if not hint_terms or not results:
        return results
    scored: list[tuple[int, float, Any]] = []
    for result in results:
        payload = getattr(result, "payload", None) or {}
        tier = category_match_tier(payload, hint_terms)
        base = float(getattr(result, "score", 0.0) or 0.0)
        scored.append((tier, base, result))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored]


def filter_results_by_category_tier(
    results: list[Any],
    hint_terms: list[str],
    *,
    min_tier: int = 1,
) -> list[Any]:
    """Drop accessory false-positives when at least one hit has a real category match."""
    if not hint_terms or not results:
        return results
    tiers = [category_match_tier(getattr(r, "payload", None) or {}, hint_terms) for r in results]
    if not any(t >= min_tier for t in tiers):
        return results
    return [r for r, tier in zip(results, tiers) if tier >= min_tier]


def filters_for_bucket(metadata_filters: dict[str, Any] | None, bucket: str) -> dict[str, Any]:
    """Product facets apply only on catalog bucket; other buckets keep stock_status only."""
    filters = dict(metadata_filters or {})
    if bucket == "catalog":
        return filters
    return {key: value for key, value in filters.items() if key == "stock_status" and value not in (None, "", [], {})}


def match_mode_for_tier(tier: RetrievalTier) -> MatchMode:
    if tier == "strict":
        return "exact"
    if tier == "semantic_catalog":
        return "semantic_fallback"
    return "relaxed"


def catalog_match_mode_instruction(match_mode: str | MatchMode | None) -> str:
    if match_mode == "relaxed":
        return (
            "Note: We could not match every filter exactly; the products below are close matches. "
            "Say so briefly in one short sentence, then list the products."
        )
    if match_mode == "semantic_fallback":
        return (
            "Note: No products matched all filters; showing similar catalog items. "
            "Say so briefly in one short sentence, then list the products."
        )
    return ""


def effective_score_threshold(
    *,
    plan: RetrievalPlan,
    structured_query: StructuredQuery,
    tier: RetrievalTier,
) -> float:
    default_threshold = float(os.getenv("RETRIEVAL_SCORE_THRESHOLD_DEFAULT", "0.3"))
    filtered_threshold = float(os.getenv("RETRIEVAL_SCORE_THRESHOLD_FILTERED", "0.25"))
    has_product_filters = bool(plan.metadata_filters) or plan.price_min is not None or plan.price_max is not None
    has_category_filter = structured_query.category.apply == "filter"
    threshold = filtered_threshold if (has_product_filters or has_category_filter) else default_threshold
    if tier in ("relaxed_facets", "relaxed_category", "semantic_catalog", "relaxed_price"):
        threshold = max(0.2, threshold - float(os.getenv("RETRIEVAL_SCORE_THRESHOLD_RELAXED_DELTA", "0.05")))
    return threshold


def apply_score_threshold(
    results: list[Any],
    *,
    threshold: float,
    max_hits: int,
) -> list[Any]:
    kept = [result for result in results if float(getattr(result, "score", 0.0) or 0.0) >= threshold]
    return kept[:max_hits]


def split_price_filters(metadata_filters: dict[str, Any] | None) -> tuple[dict[str, Any], float | None, float | None]:
    """Remove price keys from Qdrant filters; return them for post-filtering."""
    filters = dict(metadata_filters or {})
    max_price = filters.pop("max_price", None)
    min_price = filters.pop("min_price", None)
    max_val = float(max_price) if max_price is not None else None
    min_val = float(min_price) if min_price is not None else None
    return filters, min_val, max_val
