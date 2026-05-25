"""Acceptance-style flow tests for commerce NLU (MT + Q gates)."""

from retrieval.profile import _aliases_for_facet_samples
from retrieval.planner import build_retrieval_plan
from retrieval.query_validator import validate_structured_query
from retrieval.rules_prepass import rules_prepass
from retrieval.session_query import merge_session_query
from retrieval.structured_query import empty_structured_query
from retrieval.subtype_classifier import classify_response_subtype
from tests.test_facet_negation import _profile as negation_profile


def _apparel_profile():
    size_aliases = _aliases_for_facet_samples("size", ["S", "M", "L", "XL"])
    return {
        "facets": {
            "color": {"sample_values": ["Red", "Blue", "Black", "Yellow"], "value_aliases": {}},
            "size": {"sample_values": ["S", "M", "L", "XL"], "value_aliases": size_aliases, "indexed": True},
            "material": {"sample_values": ["Polyester", "Cotton"], "value_aliases": {}, "indexed": True},
        },
        "category_strategy": {
            "gazetteer": [
                {"id": "jackets", "labels": ["Jackets"]},
                {"id": "men", "labels": ["Men"]},
                {"id": "tank_tops", "labels": ["Tank tops"]},
                {"id": "pants", "labels": ["Pants"]},
            ]
        },
        "mixed_match_policy": "mixed_honest",
    }


def test_mt1_drill_down_four_turns():
    profile = _apparel_profile()
    session = empty_structured_query(intent="catalog")
    steps = [
        "Show me some men's jackets",
        "Can you make those blue",
        "I need them in size Large",
        "Keep it under $60",
    ]
    for msg in steps:
        turn = validate_structured_query(rules_prepass(msg, profile=profile), profile=profile)
        session = merge_session_query(session, turn, user_message=msg)
        session = validate_structured_query(session, profile=profile)
    assert session.price.max == 60.0
    assert session.facets["size"].values == ["l"]
    assert "blue" in session.facets["color"].values
    plan = build_retrieval_plan(session, profile=profile, tenant_profile=profile)
    assert "jacket" in plan.dense_query_text.lower() or "men" in plan.dense_query_text.lower()


def test_mt7_negation_red_and_polyester():
    profile = negation_profile()
    sq = validate_structured_query(
        rules_prepass("Show me men's t-shirts, but nothing in red", profile=profile),
        profile=profile,
    )
    assert "red" in sq.facets["color"].exclude_values
    follow = validate_structured_query(
        rules_prepass("And no polyester", profile=profile),
        profile=profile,
    )
    merged = merge_session_query(sq, follow, user_message="And no polyester")
    assert "polyester" in merged.facets["material"].exclude_values


def test_q1_10_electronics_not_in_catalog():
    profile = _apparel_profile()
    c = classify_response_subtype(
        "Show products under electronics",
        structured_query=empty_structured_query(intent="catalog"),
        profile=profile,
    )
    assert c.response_subtype == "not_in_catalog"


def test_q8_1_return_policy_support():
    c = classify_response_subtype(
        "What is your return policy?",
        structured_query=empty_structured_query(intent="support"),
    )
    assert c.response_subtype == "support_faq"
    assert c.preserve_catalog_session is True


def test_q11_3_gibberish():
    c = classify_response_subtype("asdfghj", structured_query=empty_structured_query(intent="general"))
    assert c.response_subtype == "general_chat"
