from retrieval.response_composer import compose_search_intro
from retrieval.match_quality import ProductMatchScore


def test_compose_mixed_intro_one_full_two_partial():
    scores = [
        ProductMatchScore("full", []),
        ProductMatchScore("partial", ["color"]),
        ProductMatchScore("partial", ["color"]),
    ]
    text = compose_search_intro(scores=scores, response_subtype="product_search_mixed")
    assert "exact match" in text.lower()
    assert "close match" in text.lower()
