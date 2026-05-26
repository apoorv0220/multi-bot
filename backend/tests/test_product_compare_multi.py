from retrieval.tools.product_detail import format_product_compare_multi


def test_compare_three_products():
    text = format_product_compare_multi(
        [
            {"title": "A", "url": "https://x/a", "price": 10, "rating": 4.5},
            {"title": "B", "url": "https://x/b", "price": 20, "rating": 4.0},
            {"title": "C", "url": "https://x/c", "price": 30, "rating": 3.5},
        ],
        currency_code="USD",
    )
    assert "A:" in text or "**A:" in text
    assert "B:" in text or "**B:" in text
    assert "C:" in text or "**C:" in text
