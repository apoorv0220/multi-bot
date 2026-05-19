from retrieval.planner import build_retrieval_plan
from retrieval.profile import build_retrieval_profile
from retrieval.query_validator import validate_structured_query
from retrieval.rules_prepass import rules_prepass
from retrieval.session_query import merge_session_query
from sources.base import SourceRecord
from tests.test_facet_profile import _product


def _bath_profile():
    records = [
        _product(
            entity_id="1",
            title="Basin One",
            categories=["basins"],
            attributes={"colour": ["matt black"], "finish": ["matt"]},
        ),
        _product(
            entity_id="2",
            title="Waste",
            categories=["tap accessories"],
            attributes={"colour": ["matt black"]},
        ),
        SourceRecord(
            source_provider="woocommerce",
            content_kind="category",
            entity_id="10",
            title="Basins",
            metadata={"categories": ["Basins"]},
        ),
    ]
    return build_retrieval_profile(records, tenant_id="tenant-bath")


def test_rules_prepass_matt_black_basins():
    profile = _bath_profile()
    query = rules_prepass("I want matt black basins", profile=profile)
    validated = validate_structured_query(query, profile=profile)
    assert validated.intent == "catalog"
    assert validated.category.values
    assert validated.category.apply == "filter"
    assert validated.category.confidence >= 0.75
    colour = validated.facets.get("colour")
    assert colour is not None
    assert any("black" in v or "matt" in v for v in colour.values)


def test_planner_applies_category_and_product_kind():
    profile = _bath_profile()
    query = rules_prepass("I want matt black basins", profile=profile)
    validated = validate_structured_query(query, profile=profile)
    plan = build_retrieval_plan(validated, profile=profile)
    assert plan.content_kind == "product"
    assert plan.preferred_buckets[0] == "catalog"
    assert plan.metadata_filters.get("categories")
    assert plan.category_hint_terms
    assert plan.price_max is None


def test_explicit_category_syntax_uses_hard_filter():
    profile = _bath_profile()
    validated = validate_structured_query(
        rules_prepass("category: basins matt black", profile=profile),
        profile=profile,
    )
    plan = build_retrieval_plan(validated, profile=profile)
    assert validated.category.apply == "filter"
    assert plan.metadata_filters.get("categories")


def test_category_boost_prefers_substring_match():
    from types import SimpleNamespace
    from retrieval.post_filter import boost_results_by_category

    results = [
        SimpleNamespace(score=0.5, payload={"categories": ["tap accessories"]}),
        SimpleNamespace(score=0.45, payload={"categories": ["countertop basins"]}),
    ]
    boosted = boost_results_by_category(results, ["basins", "countertop basins"])
    assert boosted[0].payload["categories"] == ["countertop basins"]


def test_planner_price_bounds_are_post_filter_not_qdrant_payload():
    profile = _bath_profile()
    validated = validate_structured_query(
        rules_prepass("basins under 150", profile=profile),
        profile=profile,
    )
    plan = build_retrieval_plan(validated, profile=profile)
    assert plan.price_max == 150.0
    assert "max_price" not in plan.metadata_filters
    from types import SimpleNamespace
    from retrieval.post_filter import filter_results_by_price

    results = [
        SimpleNamespace(score=0.5, payload={"price": 128.0, "content_kind": "product"}),
        SimpleNamespace(score=0.6, payload={"price": 200.0, "content_kind": "product"}),
        SimpleNamespace(score=0.4, payload={"price": None, "content_kind": "product"}),
    ]
    filtered = filter_results_by_price(results, max_price=150.0)
    assert len(filtered) == 1
    assert filtered[0].payload["price"] == 128.0


def test_session_inherits_facets_until_cleared():
    profile = _bath_profile()
    first = validate_structured_query(
        rules_prepass("matt black basins", profile=profile),
        profile=profile,
    )
    second_turn = rules_prepass("under 50", profile=profile, session_query=first)
    merged = merge_session_query(first, validate_structured_query(second_turn, profile=profile))
    assert merged.price.max == 50.0
    assert merged.category.values


def test_catalog_intent_sets_product_content_kind_without_main_import():
    profile = _bath_profile()
    validated = validate_structured_query(
        rules_prepass("show me basins", profile=profile),
        profile=profile,
    )
    plan = build_retrieval_plan(validated, profile=profile)
    assert validated.intent == "catalog"
    assert plan.content_kind == "product"
