from __future__ import annotations

from typing import Any, Literal

ResponseSubtype = Literal[
    "list_categories",
    "category_plp_sample",
    "category_availability",
    "product_search",
    "product_search_mixed",
    "zero_hit",
    "sort_browse",
    "product_detail",
    "variant_facets",
    "product_compare",
    "similar_products",
    "not_in_catalog",
    "support_faq",
    "guided_discovery",
    "general_chat",
]

MatchQuality = Literal["full", "partial", "alternative"]

SortMode = Literal[
    "relevance",
    "price_asc",
    "price_desc",
    "rating_desc",
    "newest",
    "bestseller",
    "trending",
]

MixedMatchPolicy = Literal["mixed_honest", "exact_only"]

LOADER_STAGES: dict[str, str] = {
    "list_categories": "Loading categories…",
    "category_plp_sample": "Browsing catalog…",
    "category_availability": "Checking catalog…",
    "product_search": "Searching products…",
    "product_search_mixed": "Searching products…",
    "sort_browse": "Finding top items…",
    "product_detail": "Loading product details…",
    "variant_facets": "Loading options…",
    "product_compare": "Comparing products…",
    "similar_products": "Finding similar items…",
    "not_in_catalog": "Checking categories…",
    "support_faq": "Looking up policies…",
    "guided_discovery": "Preparing suggestions…",
    "general_chat": "Thinking…",
    "zero_hit": "Searching catalog…",
}


def mixed_match_policy(profile: dict[str, Any] | None) -> MixedMatchPolicy:
    raw = str((profile or {}).get("mixed_match_policy") or "mixed_honest").strip().lower()
    if raw == "exact_only":
        return "exact_only"
    return "mixed_honest"


def rating_boost_weight(profile: dict[str, Any] | None) -> float:
    try:
        return max(0.0, float((profile or {}).get("rating_boost_weight", 0.05)))
    except (TypeError, ValueError):
        return 0.05
