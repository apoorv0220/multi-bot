from types import SimpleNamespace
from unittest.mock import AsyncMock

from retrieval.planner import RetrievalPlan
from retrieval.post_filter import filters_for_bucket
from retrieval.session_query import merge_session_query
from retrieval.rules_prepass import rules_prepass
from retrieval.query_validator import validate_structured_query
from retrieval.structured_query import FacetSpec, StructuredQuery
from retrieval.tiered_search import execute_tiered_search
from tests.test_structured_query import _bath_profile


def test_filters_for_bucket_strips_product_filters_on_cms():
    metadata = {
        "categories": ["basins"],
        "brand": "SONAS",
        "facet_filters": {"colour": {"values": ["black"], "combine": "OR"}},
        "stock_status": "instock",
    }
    cms_filters = filters_for_bucket(metadata, "cms")
    assert cms_filters == {"stock_status": "instock"}
    catalog_filters = filters_for_bucket(metadata, "catalog")
    assert catalog_filters["categories"] == ["basins"]


def test_session_merge_category_refinement_clears_facets():
    profile = _bath_profile()
    first = validate_structured_query(
        rules_prepass("matt black basins", profile=profile),
        profile=profile,
    )
    second = validate_structured_query(
        rules_prepass("basins", profile=profile),
        profile=profile,
    )
    merged = merge_session_query(first, second, user_message="basins")
    assert "colour" not in merged.facets
    assert "finish" not in merged.facets
    assert merged.category.values


async def _run_tiered(plan: RetrievalPlan, responses: list[list]):
    call_count = {"n": 0}

    async def search_fn(filters):
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return responses[idx]

    return await execute_tiered_search(
        search_fn,
        plan=plan,
        profile=_bath_profile(),
        intent="catalog",
    )


def test_tiered_search_relaxes_when_strict_empty():
    import asyncio

    plan = RetrievalPlan(
        metadata_filters={
            "facet_filters": {
                "colour": {"values": ["matt black"], "combine": "OR"},
            }
        },
        content_kind="product",
        category_hint_terms=["basins"],
    )
    hit = SimpleNamespace(score=0.4, payload={"categories": ["countertop basins"], "price": 128.0})
    result = asyncio.run(_run_tiered(plan, [[], [hit]]))
    assert result.hits
    assert result.tier in ("relaxed_facets", "semantic_catalog")
    assert result.match_mode in ("relaxed", "semantic_fallback")


def test_tiered_search_price_relaxed_when_price_filters_empty():
    import asyncio

    plan = RetrievalPlan(
        metadata_filters={},
        content_kind="product",
        category_hint_terms=["basins"],
        price_max=150.0,
    )
    hit = SimpleNamespace(score=0.4, payload={"categories": ["basins"], "price": 128.0})
    result = asyncio.run(_run_tiered(plan, [[], [hit]]))
    assert result.hits
    assert result.price_relaxed is True
    assert result.match_mode == "relaxed"
