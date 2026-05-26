from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from retrieval.planner import RetrievalPlan, _has_product_type_category
from retrieval.post_filter import (
    MatchMode,
    RetrievalTier,
    boost_results_by_facets,
    filter_results_by_category_hints,
    filter_results_by_category_tier,
    filter_results_by_audience,
    filter_results_by_facet_excludes,
    filter_results_by_min_rating,
    filter_results_on_sale,
    filter_results_by_price,
    match_mode_for_tier,
    prefer_category_tier_hits,
    sort_results_by_category_tier,
)

SearchFn = Callable[[dict[str, Any]], Awaitable[list[Any]]]


@dataclass
class TieredSearchResult:
    hits: list[Any] = field(default_factory=list)
    tier: RetrievalTier = "strict"
    match_mode: MatchMode = "exact"
    dropped_filters: list[str] = field(default_factory=list)
    price_relaxed: bool = False


def _tier_enabled() -> bool:
    return os.getenv("RETRIEVAL_TIER_RELAXATION_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def _min_results() -> int:
    try:
        return max(1, int(os.getenv("RETRIEVAL_TIER_MIN_RESULTS", "1")))
    except ValueError:
        return 1


def _facet_drop_order(metadata_filters: dict[str, Any], profile: dict[str, Any] | None) -> list[str]:
    facet_filters = dict(metadata_filters.get("facet_filters") or {})
    if not facet_filters:
        return []
    coverage: dict[str, float] = {}
    facets_meta = (profile or {}).get("facets") or {}
    for facet_id in facet_filters:
        meta = facets_meta.get(facet_id) or {}
        try:
            coverage[facet_id] = float(meta.get("coverage_pct") or 0.0)
        except (TypeError, ValueError):
            coverage[facet_id] = 0.0
    return sorted(facet_filters.keys(), key=lambda item: coverage.get(item, 0.0))


def _filter_fingerprint(filters: dict[str, Any]) -> str:
    return json.dumps(filters or {}, sort_keys=True, default=str)


def _has_category_filter(metadata_filters: dict[str, Any]) -> bool:
    cats = metadata_filters.get("categories")
    return bool(cats)


def _filter_variants(
    base_filters: dict[str, Any],
    profile: dict[str, Any] | None,
    *,
    retain_category: bool,
) -> list[tuple[dict[str, Any], RetrievalTier, list[str]]]:
    variants: list[tuple[dict[str, Any], RetrievalTier, list[str]]] = []
    base = dict(base_filters or {})
    variants.append((base, "strict", []))

    current = dict(base)
    dropped: list[str] = []
    for facet_id in _facet_drop_order(base, profile):
        facet_filters = dict(current.get("facet_filters") or {})
        if facet_id not in facet_filters:
            continue
        facet_filters.pop(facet_id, None)
        dropped.append(f"facet:{facet_id}")
        current = dict(current)
        if facet_filters:
            current["facet_filters"] = facet_filters
        else:
            current.pop("facet_filters", None)
        variants.append((dict(current), "relaxed_facets", list(dropped)))

    if base.get("brand"):
        no_brand = dict(current)
        no_brand.pop("brand", None)
        dropped_brand = dropped + ["brand"]
        variants.append((no_brand, "relaxed_facets", dropped_brand))
        current = no_brand

    if retain_category and _has_category_filter(base):
        category_only = {"categories": list(base["categories"])}
        for i, (filters, tier, dropped_list) in enumerate(variants):
            if filters == category_only and tier == "relaxed_facets":
                variants[i] = (filters, "relaxed_category", dropped_list)
                break
        else:
            if not any(filters == category_only for filters, _, _ in variants):
                variants.append(
                    (
                        category_only,
                        "relaxed_category",
                        dropped + ["facets", "brand"],
                    )
                )

    variants.append(({}, "semantic_catalog", dropped + ["all_payload_filters"]))
    return variants


async def _run_variant(
    search_fn: SearchFn,
    filters: dict[str, Any],
    *,
    price_min: float | None,
    price_max: float | None,
    min_rating: float | None = None,
    on_sale_only: bool = False,
    category_hint_terms: list[str],
    category_values: list[str] | None = None,
    profile: dict[str, Any] | None = None,
    tier: RetrievalTier = "strict",
    soft_facet_boosts: dict[str, list[str]] | None = None,
    facet_excludes: dict[str, list[str]] | None = None,
) -> list[Any]:
    hits = await search_fn(filters)
    if category_hint_terms:
        has_qdrant_category = bool((filters or {}).get("categories"))
        require_category = bool(
            category_values
            and (
                _has_product_type_category(category_values, profile)
                or tier == "semantic_catalog"
            )
            and not has_qdrant_category
        )
        if tier == "semantic_catalog" and category_values:
            require_category = True
        hits = filter_results_by_category_hints(
            hits,
            category_hint_terms,
            require_match=require_category,
            profile=profile,
        )
        hits = sort_results_by_category_tier(hits, category_hint_terms, profile)
        if _has_product_type_category(category_values or [], profile):
            hits = filter_results_by_category_tier(hits, category_hint_terms, profile=profile)
        hits = filter_results_by_audience(hits, category_values)
    if price_min is not None or price_max is not None:
        hits = filter_results_by_price(hits, min_price=price_min, max_price=price_max)
    if min_rating is not None:
        hits = filter_results_by_min_rating(hits, min_rating=min_rating)
    if on_sale_only:
        hits = filter_results_on_sale(hits, on_sale_only=True)
    hits = boost_results_by_facets(hits, soft_facet_boosts)
    hits = filter_results_by_facet_excludes(hits, facet_excludes)
    if category_hint_terms and not (filters or {}).get("categories"):
        hits = prefer_category_tier_hits(hits, category_hint_terms, profile)
    return hits


async def execute_tiered_search(
    search_fn: SearchFn,
    *,
    plan: RetrievalPlan,
    profile: dict[str, Any] | None,
    intent: str,
) -> TieredSearchResult:
    """Catalog tiered retrieval; support/general should call search_fn once from the caller."""
    if intent != "catalog" or not _tier_enabled():
        hits = await _run_variant(
            search_fn,
            dict(plan.metadata_filters or {}),
            price_min=plan.price_min,
            price_max=plan.price_max,
            min_rating=plan.min_rating,
            on_sale_only=plan.on_sale_only,
            category_hint_terms=plan.category_hint_terms,
            category_values=plan.category_values,
            profile=profile,
            soft_facet_boosts=plan.soft_facet_boosts,
            facet_excludes=plan.facet_excludes,
        )
        return TieredSearchResult(hits=hits, tier="strict", match_mode="exact")

    min_hits = _min_results()
    seen_fingerprints: set[str] = set()
    retain_category = bool(
        _has_category_filter(plan.metadata_filters or {})
        or (
            plan.category_values
            and _has_product_type_category(plan.category_values, profile)
        )
    )

    async def try_variants(
        price_min: float | None,
        price_max: float | None,
        *,
        price_relaxed: bool,
    ) -> TieredSearchResult | None:
        for filters, tier, dropped in _filter_variants(
            dict(plan.metadata_filters or {}),
            profile,
            retain_category=retain_category,
        ):
            fingerprint = f"{price_relaxed}:{_filter_fingerprint(filters)}"
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            hits = await _run_variant(
                search_fn,
                filters,
                price_min=price_min,
                price_max=price_max,
                min_rating=plan.min_rating,
                on_sale_only=plan.on_sale_only,
                category_hint_terms=plan.category_hint_terms,
                category_values=plan.category_values,
                profile=profile,
                tier=tier,
                soft_facet_boosts=plan.soft_facet_boosts,
                facet_excludes=plan.facet_excludes,
            )
            if len(hits) >= min_hits:
                return TieredSearchResult(
                    hits=hits,
                    tier="relaxed_price" if price_relaxed else tier,
                    match_mode=match_mode_for_tier("relaxed_price" if price_relaxed else tier),
                    dropped_filters=dropped,
                    price_relaxed=price_relaxed,
                )
        return None

    with_price = await try_variants(plan.price_min, plan.price_max, price_relaxed=False)
    if with_price is not None:
        return with_price

    if (plan.price_min is not None or plan.price_max is not None) and plan.min_rating is None:
        without_price = await try_variants(None, None, price_relaxed=True)
        if without_price is not None:
            return without_price

    return TieredSearchResult(hits=[], tier="semantic_catalog", match_mode="semantic_fallback")
