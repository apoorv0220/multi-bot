from types import SimpleNamespace

from retrieval.catalog_response import (
    build_price_relaxed_deterministic_answer,
    format_products_for_prompt,
    products_within_price_bounds,
    should_use_price_relaxed_template,
)


def _product(**kwargs):
    return SimpleNamespace(**kwargs)


def test_products_within_price_bounds():
    products = [
        _product(title="A", url="https://x/a", price=40.0),
        _product(title="B", url="https://x/b", price=120.0),
    ]
    assert len(products_within_price_bounds(products, price_max=50.0)) == 1


def test_should_use_price_relaxed_template_when_nothing_in_range():
    products = [
        _product(title="A", url="https://x/a", price=400.0),
    ]
    assert should_use_price_relaxed_template(
        price_relaxed=True,
        products=products,
        price_min=None,
        price_max=50.0,
    )


def test_price_relaxed_deterministic_answer():
    products = [
        _product(title="Chrome Shower", url="https://x/s", price=499.0),
    ]
    answer = build_price_relaxed_deterministic_answer(
        brand="BathConnect",
        products=products,
        price_min=None,
        price_max=50.0,
    )
    assert answer is not None
    assert "under 50" in answer.lower()
    assert "Chrome Shower" in answer


def test_format_products_for_prompt_json():
    products = [_product(title="Tap", url="https://x/t", price=29.5)]
    payload = format_products_for_prompt(products)
    assert '"title": "Tap"' in payload
    assert "29.5" in payload
