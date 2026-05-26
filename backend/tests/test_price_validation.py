from retrieval.price_validation import apply_price_bounds_validation, has_invalid_price
from retrieval.rules_prepass import rules_prepass
from retrieval.structured_query import empty_structured_query


def test_under_zero_price_rejected():
    sq = rules_prepass("Show jackets under $0", profile=None)
    assert has_invalid_price(sq)
    assert sq.price.max is None


def test_negative_min_price_rejected():
    sq = apply_price_bounds_validation(empty_structured_query())
    sq.price.min = -5.0
    sq = apply_price_bounds_validation(sq)
    assert has_invalid_price(sq)
    assert sq.price.min is None
