from types import SimpleNamespace

from retrieval.planner import build_retrieval_plan
from retrieval.post_filter import filter_results_by_facet_excludes
from retrieval.rules_prepass import rules_prepass
from retrieval.query_validator import validate_structured_query


def _profile():
    return {
        "facets": {
            "material": {
                "sample_values": ["Polyester", "Cotton"],
                "value_aliases": {},
                "indexed": True,
            },
            "color": {
                "sample_values": ["White", "Black", "Red"],
                "value_aliases": {},
                "indexed": True,
            },
        },
        "category_strategy": {"gazetteer": []},
        "stats": {"product_count": 50},
    }


def test_rules_prepass_nothing_in_red_excludes_not_includes():
    sq = validate_structured_query(
        rules_prepass("Show me men's t-shirts, but nothing in red", profile=_profile()),
        profile=_profile(),
    )
    color = sq.facets.get("color")
    assert color
    assert "red" in [v.lower() for v in color.exclude_values]
    assert "red" not in [v.lower() for v in color.values]


def test_rules_prepass_no_polyester_exclude():
    sq = validate_structured_query(
        rules_prepass("men's tees and no polyester", profile=_profile()),
        profile=_profile(),
    )
    assert sq.facets.get("material")
    assert "polyester" in [v.lower() for v in sq.facets["material"].exclude_values]


def test_post_filter_excludes_material():
    hits = [
        SimpleNamespace(
            score=0.9,
            payload={"attributes": {"material": ["polyester"]}},
        ),
        SimpleNamespace(
            score=0.8,
            payload={"attributes": {"material": ["cotton"]}},
        ),
    ]
    filtered = filter_results_by_facet_excludes(hits, {"material": ["polyester"]})
    assert len(filtered) == 1
    assert filtered[0].payload["attributes"]["material"] == ["cotton"]


def test_plan_carries_facet_excludes():
    sq = validate_structured_query(
        rules_prepass("shirts without white", profile=_profile()),
        profile=_profile(),
    )
    plan = build_retrieval_plan(sq, profile=_profile())
    assert plan.facet_excludes
