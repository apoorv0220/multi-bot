from types import SimpleNamespace

from retrieval.match_quality import score_product_match
from retrieval.post_filter import _payload_rating, filter_results_by_min_rating, filter_results_on_sale
from retrieval.rules_prepass import _extract_min_rating, rules_prepass
from retrieval.planner import build_retrieval_plan
from retrieval.session_query import merge_session_query
from retrieval.structured_query import empty_structured_query, FacetSpec
from retrieval.subtype_classifier import classify_response_subtype


def _hit(rating: float | None, price: float = 100.0, sale: float | None = None):
    payload = {"rating": rating, "price": price}
    if sale is not None:
        payload["sale_price"] = sale
    return SimpleNamespace(score=0.5, payload=payload)


def test_filter_min_rating():
    hits = [_hit(3.5), _hit(4.2), _hit(5.0)]
    filtered = filter_results_by_min_rating(hits, min_rating=4.0)
    assert len(filtered) == 2


def test_payload_rating_normalizes_magento_percent():
    assert _payload_rating({"rating": 80}) == 4.0
    assert _payload_rating({"rating": 4.2}) == 4.2


def test_extract_only_above_rating_word_order():
    assert _extract_min_rating("show me red jackets only above 4 rating") == 4.0
    assert _extract_min_rating("only above 4 rating") == 4.0
    assert _extract_min_rating("only those above 3 rating") == 3.0


def test_rules_five_star():
    sq = rules_prepass("Show 5-star rated products", profile=None)
    assert sq.min_rating == 5.0


def test_rules_rating_above_four():
    sq = rules_prepass("Show products with rating above 4", profile=None)
    assert sq.min_rating == 4.0


def test_follow_up_only_those_above_three():
    session = empty_structured_query(intent="catalog")
    session.facets["color"] = FacetSpec(values=["brown"])
    session.price.max = 60.0
    turn = rules_prepass("Only those above 3 rating", profile=None)
    assert turn.min_rating == 3.0
    merged = merge_session_query(session, turn, user_message="Only those above 3 rating")
    assert merged.min_rating == 3.0
    assert merged.price.max == 60.0
    assert "brown" in merged.facets["color"].values


def test_on_sale_filter():
    hits = [_hit(4.0, price=100.0, sale=80.0), _hit(4.0, price=50.0, sale=None)]
    filtered = filter_results_on_sale(hits, on_sale_only=True)
    assert len(filtered) == 1


def test_plan_carries_rating():
    sq = rules_prepass("red jackets only above 4 rating", profile=None)
    plan = build_retrieval_plan(sq, profile=None)
    assert plan.min_rating == 4.0


def test_match_quality_requires_rating_when_min_set():
    sq = empty_structured_query(intent="catalog")
    sq.min_rating = 4.0
    score = score_product_match(
        {"rating": 60, "price": 50},
        structured_query=sq,
        user_message="only above 4 rating",
        profile=None,
    )
    assert score.match_quality != "full"
    assert "rating" in score.missed_constraints


def test_vague_query_not_product_detail():
    c = classify_response_subtype(
        "I need something for office wear",
        structured_query=empty_structured_query(intent="catalog"),
    )
    assert c.response_subtype != "product_detail"
