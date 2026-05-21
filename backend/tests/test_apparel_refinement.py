"""Apparel multi-turn refinement: possessive tokenization, facet replace, catalog dense query."""

from retrieval.profile import _aliases_for_facet_samples
from retrieval.planner import build_retrieval_plan
from retrieval.query_validator import validate_structured_query
from retrieval.rules_prepass import _tokenize, rules_prepass
from retrieval.session_query import classify_merge_action, merge_session_query
from retrieval.structured_query import FacetSpec, StructuredQuery, empty_structured_query


def _apparel_profile(*, include_letter_sizes: bool = True):
    size_samples = ["S", "M", "L", "XL"] if include_letter_sizes else ["32", "34", "36"]
    size_aliases = _aliases_for_facet_samples("size", size_samples)
    return {
        "facets": {
            "color": {"sample_values": ["Red", "Blue", "Black"], "value_aliases": {}},
            "size": {
                "sample_values": size_samples,
                "value_aliases": size_aliases,
                "indexed": True,
            },
        },
        "category_strategy": {
            "gazetteer": [
                {"id": "jackets", "labels": ["Jackets"], "aliases": {}},
                {"id": "men", "labels": ["Men"], "aliases": {}},
                {
                    "id": "hoodies_sweatshirts",
                    "labels": ["Hoodies & Sweatshirts"],
                    "aliases": {},
                },
            ]
        },
        "stats": {"product_count": 100},
    }


def test_tokenize_mens_jackets_does_not_emit_spurious_s():
    assert "s" not in _tokenize("Show me some men's jackets")
    assert "men" in _tokenize("Show me some men's jackets")
    assert "s" not in _tokenize("Show me some men\u2019s jackets")


def test_gazetteer_men_does_not_match_women_category():
    profile = _apparel_profile()
    profile["category_strategy"]["gazetteer"].append(
        {"id": "women", "labels": ["Women"], "aliases": {}},
    )
    sq = validate_structured_query(
        rules_prepass("Show me some men's jackets", profile=profile),
        profile=profile,
    )
    cats = " ".join(sq.category.values).lower()
    assert "women" not in cats
    assert "jackets" in cats
    assert "men" in sq.category.values or any("men" == v for v in sq.category.values)


def test_rules_prepass_mens_jackets_no_false_size():
    profile = _apparel_profile()
    sq = validate_structured_query(
        rules_prepass("Show me some men's jackets", profile=profile),
        profile=profile,
    )
    assert "size" not in sq.facets


def test_profile_autogen_size_large_alias_when_l_present():
    aliases = _aliases_for_facet_samples("size", ["S", "M", "L", "XL", "32"])
    assert aliases.get("large") == "L"
    assert aliases.get("ls") == "L"
    assert "large" not in _aliases_for_facet_samples("size", ["32", "34", "36"])


def test_rules_prepass_explicit_size_large():
    profile = _apparel_profile()
    sq = validate_structured_query(
        rules_prepass("I need them in size Large", profile=profile),
        profile=profile,
    )
    assert sq.facets.get("size")
    assert "l" in sq.facets["size"].values


def test_merge_replaces_size_not_unions_with_session():
    profile = _apparel_profile()
    session = validate_structured_query(
        rules_prepass("Show me some men's jackets", profile=profile),
        profile=profile,
    )
    session.facets["color"] = FacetSpec(values=["blue"], combine="OR")
    session.facets["size"] = FacetSpec(values=["s"], combine="OR")

    turn = validate_structured_query(
        rules_prepass("I need them in size Large", profile=profile),
        profile=profile,
    )
    merged = merge_session_query(session, turn, user_message="I need them in size Large")
    assert classify_merge_action(session, turn, user_message="I need them in size Large") == "facet_replace"
    assert merged.facets["size"].values == ["l"]
    assert merged.facets["color"].values == ["blue"]


def test_merge_replaces_color_on_make_those_blue():
    profile = _apparel_profile()
    session = validate_structured_query(
        rules_prepass("Show me some men's jackets", profile=profile),
        profile=profile,
    )
    turn = validate_structured_query(
        rules_prepass("Can you make those blue", profile=profile),
        profile=profile,
    )
    merged = merge_session_query(session, turn, user_message="Can you make those blue")
    assert merged.facets.get("color")
    assert merged.facets["color"].values == ["blue"]
    assert "size" not in merged.facets


def test_drill_down_four_turns_equivalent_dense_query():
    profile = _apparel_profile()
    session = empty_structured_query(intent="catalog")

    steps = [
        ("Show me some men's jackets", "Show me some men's jackets"),
        ("Can you make those blue", "Can you make those blue"),
        ("I need them in size Large", "I need them in size Large"),
        ("Keep it under $60", "Keep it under $60"),
    ]
    for user_msg, _ in steps:
        turn = validate_structured_query(rules_prepass(user_msg, profile=profile), profile=profile)
        session = merge_session_query(session, turn, user_message=user_msg)
        session = validate_structured_query(session, profile=profile)

    assert "jackets" in " ".join(session.category.values).lower() or "men" in session.category.values
    assert session.facets.get("color")
    assert "blue" in session.facets["color"].values
    assert session.facets.get("size")
    assert session.facets["size"].values == ["l"]
    assert session.price.max == 60.0
    assert "size" not in session.facets or "s" not in session.facets.get("size", FacetSpec()).values

    plan = build_retrieval_plan(session, profile=profile, tenant_profile=profile)
    dense = plan.dense_query_text.lower()
    assert "blue" in dense
    assert "jackets" in dense or "men" in dense
    assert "l" in dense.split()
    assert "60" in dense or "under" in dense
    assert dense.count(" s ") == 0 and not dense.startswith("s ")
