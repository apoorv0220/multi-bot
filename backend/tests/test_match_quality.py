from types import SimpleNamespace

from retrieval.match_quality import classify_match_quality_for_results, finalize_response_subtype
from retrieval.structured_query import FacetSpec, empty_structured_query


def _hit(**payload):
    return SimpleNamespace(score=0.9, payload=payload)


def test_full_match_when_all_constraints_met():
    sq = empty_structured_query(intent="catalog")
    sq.facets["color"] = FacetSpec(values=["yellow"], combine="OR")
    sq.price.max = 100.0
    results = [
        _hit(
            title="Yellow Bag",
            url="https://x/bag",
            price=80,
            categories=["bags"],
            attributes={"color": ["yellow"]},
        )
    ]
    ordered, scores = classify_match_quality_for_results(
        results,
        structured_query=sq,
        user_message="yellow bag under 100",
        profile=None,
        category_hint_terms=["bags"],
    )
    assert scores[0].match_quality == "full"
    assert finalize_response_subtype(scores) == "product_search"


def test_partial_match_when_color_missing():
    sq = empty_structured_query(intent="catalog")
    sq.facets["color"] = FacetSpec(values=["yellow"], combine="OR")
    sq.price.max = 100.0
    results = [
        _hit(
            title="Blue Bag",
            url="https://x/bag",
            price=80,
            categories=["bags"],
            attributes={"color": ["blue"]},
        )
    ]
    _, scores = classify_match_quality_for_results(
        results,
        structured_query=sq,
        user_message="yellow bag under 100",
        profile=None,
        category_hint_terms=["bags"],
    )
    assert scores[0].match_quality == "partial"
    assert "color" in scores[0].missed_constraints
    assert finalize_response_subtype(scores) == "product_search_mixed"


def test_exact_only_policy_drops_partials():
    sq = empty_structured_query(intent="catalog")
    sq.facets["color"] = FacetSpec(values=["yellow"], combine="OR")
    results = [
        _hit(title="Blue", url="https://x/1", attributes={"color": ["blue"]}, categories=["bags"]),
        _hit(title="Yellow", url="https://x/2", attributes={"color": ["yellow"]}, categories=["bags"]),
    ]
    ordered, scores = classify_match_quality_for_results(
        results,
        structured_query=sq,
        user_message="yellow bag",
        profile={"mixed_match_policy": "exact_only"},
        category_hint_terms=["bags"],
    )
    assert len(ordered) == 1
    assert scores[0].match_quality == "full"
