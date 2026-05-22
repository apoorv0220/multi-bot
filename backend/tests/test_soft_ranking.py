from types import SimpleNamespace

from retrieval.planner import build_retrieval_plan
from retrieval.post_filter import boost_results_by_facets, prefer_category_tier_hits
from retrieval.profile import build_retrieval_profile
from retrieval.query_validator import validate_structured_query
from retrieval.rules_prepass import rules_prepass
from retrieval.structured_query import FacetSpec, StructuredQuery, empty_structured_query
from sources.base import SourceRecord
from tests.test_apparel_refinement import _apparel_profile
from tests.test_facet_profile import _product


def test_soft_color_not_in_qdrant_facet_filters():
    profile = _apparel_profile()
    profile["category_strategy"]["gazetteer"].append(
        {"id": "bags", "labels": ["Bags"], "aliases": {"bag": "bags"}},
    )
    query = empty_structured_query(intent="catalog")
    query.category.values = ["bags"]
    query.category.confidence = 0.86
    query.category.apply = "hint"
    query.facets["color"] = FacetSpec(values=["red"], combine="OR")
    query.price.max = 40.0
    validated = validate_structured_query(query, profile=profile)
    plan = build_retrieval_plan(validated, profile=profile)
    assert "color" not in (plan.metadata_filters.get("facet_filters") or {})
    assert plan.soft_facet_boosts.get("color") == ["red"]
    assert any("bag" in t for t in plan.category_hint_terms)


def test_strict_facet_stays_in_filters():
    profile = _apparel_profile()
    profile["facets"]["color"]["match_mode"] = "strict"
    query = empty_structured_query(intent="catalog")
    query.facets["color"] = FacetSpec(values=["red"], combine="OR")
    validated = validate_structured_query(query, profile=profile)
    plan = build_retrieval_plan(validated, profile=profile)
    assert plan.metadata_filters.get("facet_filters", {}).get("color")


def test_boost_results_by_facets_orders_matches_first():
    hits = [
        SimpleNamespace(score=0.9, payload={"attributes": {"color": ["blue"]}}),
        SimpleNamespace(score=0.5, payload={"attributes": {"color": ["red"]}}),
    ]
    boosted = boost_results_by_facets(hits, {"color": ["red"]})
    assert boosted[0].payload["attributes"]["color"] == ["red"]


def test_prefer_category_tier_hits():
    hits = [
        SimpleNamespace(score=0.9, payload={"categories": ["shorts"]}),
        SimpleNamespace(score=0.5, payload={"categories": ["bags", "gear"]}),
    ]
    ordered = prefer_category_tier_hits(hits, ["bags"], profile=None)
    assert "bags" in ordered[0].payload["categories"][0]
