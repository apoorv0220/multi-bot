from retrieval.category_match import (
    has_hard_filter_category,
    prepass_missing_hard_filter_category,
)
from retrieval.planner import build_retrieval_plan
from retrieval.query_validator import validate_structured_query
from retrieval.rules_prepass import rules_prepass
from retrieval.structured_query import empty_structured_query
from tests.test_apparel_refinement import _apparel_profile


def test_bags_not_hard_filter_without_gazetteer_flag():
    profile = _apparel_profile()
    profile["category_strategy"]["gazetteer"].append(
        {"id": "bags", "labels": ["Bags"], "aliases": {"bag": "bags"}},
    )
    assert not has_hard_filter_category(["bags"], profile)


def test_hard_filter_requires_gazetteer_flag():
    profile = _apparel_profile()
    for entry in profile["category_strategy"]["gazetteer"]:
        if entry.get("id") == "jackets":
            entry["hard_filter"] = True
    assert has_hard_filter_category(["jackets"], profile)


def test_red_bags_plan_uses_soft_category_not_qdrant_categories():
    profile = _apparel_profile()
    profile["category_strategy"]["gazetteer"].append(
        {"id": "bags", "labels": ["Bags"], "aliases": {"bag": "bags"}},
    )
    query = validate_structured_query(
        rules_prepass("red bags under 40", profile=profile),
        profile=profile,
    )
    plan = build_retrieval_plan(query, profile=profile)
    assert "categories" not in (plan.metadata_filters or {})
    assert any("bag" in t for t in plan.category_hint_terms)


def test_prepass_missing_hard_filter_category():
    profile = _apparel_profile()
    profile["category_strategy"]["gazetteer"].append(
        {
            "id": "taps",
            "labels": ["Taps"],
            "aliases": {"tap": "taps"},
            "hard_filter": True,
        }
    )
    prepass = empty_structured_query(intent="catalog")
    prepass.category.values = []
    assert prepass_missing_hard_filter_category("show me chrome taps", prepass, profile)
