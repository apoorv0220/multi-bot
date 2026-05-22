import asyncio
from types import SimpleNamespace
from retrieval.planner import RetrievalPlan
from retrieval.post_filter import filter_results_by_category_hints, sort_results_by_category_tier
from retrieval.tiered_search import _filter_variants, execute_tiered_search
from tests.test_structured_query import _bath_profile


def test_filter_variants_keeps_category_before_semantic_empty():
    base = {
        "categories": ["basins"],
        "facet_filters": {"colour": {"values": ["chrome"], "combine": "OR"}},
        "brand": "SONAS",
    }
    variants = _filter_variants(base, _bath_profile(), retain_category=True)
    tiers = [tier for _, tier, _ in variants]
    semantic_idx = tiers.index("semantic_catalog")
    relaxed_cat_idx = tiers.index("relaxed_category")
    assert relaxed_cat_idx < semantic_idx
    relaxed_filters = variants[relaxed_cat_idx][0]
    assert relaxed_filters.get("categories") == ["basins"]
    assert "facet_filters" not in relaxed_filters


def test_semantic_catalog_requires_category_match_when_hints_active():
    hits = [
        SimpleNamespace(
            score=0.9,
            payload={"categories": ["Basin Taps & Mixers"], "price": 50.0},
        ),
        SimpleNamespace(
            score=0.4,
            payload={"categories": ["Basins", "Countertop Basins"], "price": 80.0},
        ),
    ]
    filtered = filter_results_by_category_hints(
        hits,
        ["basins"],
        require_match=True,
        profile=_bath_profile(),
    )
    assert len(filtered) == 1
    assert "Countertop" in filtered[0].payload["categories"][1]


def test_execute_tiered_search_uses_relaxed_category_before_semantic():
    plan = RetrievalPlan(
        metadata_filters={
            "categories": ["basins"],
            "facet_filters": {"colour": {"values": ["chrome"], "combine": "OR"}},
        },
        category_values=["basins"],
        category_hint_terms=["basins"],
        content_kind="product",
    )
    basin_hit = SimpleNamespace(
        score=0.5,
        payload={"categories": ["Basins"], "price": 99.0},
    )
    calls: list[dict] = []

    async def search_fn(filters):
        calls.append(dict(filters or {}))
        if filters.get("categories") == ["basins"] and "facet_filters" not in filters:
            return [basin_hit]
        return []

    result = asyncio.run(
        execute_tiered_search(
            search_fn,
            plan=plan,
            profile=_bath_profile(),
            intent="catalog",
        )
    )
    assert result.hits
    assert result.tier == "relaxed_category"
    assert {} not in calls
