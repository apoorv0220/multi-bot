from types import SimpleNamespace

from retrieval.filter_adherence import build_filter_adherence, filter_adherence_instruction
from retrieval.planner import build_retrieval_plan
from retrieval.structured_query import FacetSpec, StructuredQuery, empty_structured_query


def _hit(categories=None, attributes=None, score=0.9):
    return SimpleNamespace(
        score=score,
        payload={
            "categories": categories or [],
            "attributes": attributes or {},
        },
    )


def _sq(**kwargs):
    sq = empty_structured_query()
    sq.intent = "catalog"
    for key, val in kwargs.items():
        if key == "category":
            sq.category.values = val
        elif key == "price_max":
            sq.price.max = val
        elif key == "facets":
            for facet_id, values in val.items():
                sq.facets[facet_id] = FacetSpec(values=values)
    return sq


def test_color_substitute_violet_to_purple():
    sq = _sq(facets={"color": ["purple"]})
    plan = build_retrieval_plan(sq, profile={"facets": {"color": {"match_mode": "soft"}}})
    adherence = build_filter_adherence(
        user_message="Show me violet hoodies",
        structured_query=sq,
        retrieval_plan=plan,
        card_results=[_hit(categories=["hoodies"], attributes={"color": ["purple"]})],
        profile={"gazetteer": [{"id": "hoodies", "label": "Hoodies"}]},
    )
    assert adherence and "color_substitute" in adherence
    instr = filter_adherence_instruction(adherence)
    assert "purple" in instr.lower()
    assert "violet" in instr.lower()


def test_category_framed_color_miss_red_bags():
    sq = _sq(category=["bags"], price_max=40.0, facets={"color": ["red"]})
    profile = {
        "gazetteer": [{"id": "bags", "label": "Bags", "aliases": ["bag"]}],
        "facets": {"color": {"match_mode": "soft"}},
    }
    plan = build_retrieval_plan(sq, profile=profile)
    hits = [
        _hit(categories=["bags"], attributes={"color": ["black"]}, score=0.95),
        _hit(categories=["bags"], attributes={"color": ["navy"]}, score=0.9),
    ]
    adherence = build_filter_adherence(
        user_message="red bags under 40",
        structured_query=sq,
        retrieval_plan=plan,
        card_results=hits,
        profile=profile,
        match_mode="exact",
        hit_count=2,
        product_card_count=2,
    )
    assert adherence and adherence.get("category_framed_color_miss")
    instr = filter_adherence_instruction(adherence)
    assert "red" in instr.lower()
    assert "bags" in instr.lower()


def test_no_adherence_when_exact_color_match():
    sq = _sq(category=["bags"], facets={"color": ["red"]})
    profile = {
        "gazetteer": [{"id": "bags", "label": "Bags"}],
        "facets": {"color": {"match_mode": "soft"}},
    }
    plan = build_retrieval_plan(sq, profile=profile)
    hits = [_hit(categories=["bags"], attributes={"color": ["red"]})]
    adherence = build_filter_adherence(
        user_message="red bags",
        structured_query=sq,
        retrieval_plan=plan,
        card_results=hits,
        profile=profile,
    )
    assert adherence is None or "category_framed_color_miss" not in adherence


def test_hits_without_cards_signal():
    sq = _sq(category=["jackets"], price_max=50.0, facets={"color": ["red"]})
    plan = build_retrieval_plan(sq, profile={"facets": {"color": {"match_mode": "soft"}}})
    adherence = build_filter_adherence(
        user_message="red jackets under 50",
        structured_query=sq,
        retrieval_plan=plan,
        card_results=[],
        profile={},
        hit_count=5,
        product_card_count=0,
    )
    assert adherence and adherence.get("hits_without_cards")
    instr = filter_adherence_instruction(adherence, products_empty=True)
    assert "5" in instr
