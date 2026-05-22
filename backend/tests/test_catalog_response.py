from types import SimpleNamespace

from retrieval.catalog_response import format_products_for_prompt, products_within_price_bounds
from retrieval.filter_adherence import filter_adherence_instruction


def _product(**kwargs):
    return SimpleNamespace(**kwargs)


def test_products_within_price_bounds():
    products = [
        _product(title="A", url="https://x/a", price=40.0),
        _product(title="B", url="https://x/b", price=120.0),
    ]
    assert len(products_within_price_bounds(products, price_max=50.0)) == 1


def test_filter_adherence_instruction_price_relaxed():
    instr = filter_adherence_instruction({"price_relaxed": {"max": 50.0, "min": None}})
    assert "under 50" in instr.lower()
    assert "nothing matched the price" in instr.lower()


def test_filter_adherence_instruction_category_framed_miss():
    instr = filter_adherence_instruction(
        {
            "category_framed_color_miss": {
                "user_colors": ["red"],
                "category": ["bags"],
                "price_max": 40.0,
            }
        }
    )
    assert "red" in instr.lower()
    assert "bags" in instr.lower()


def test_filter_adherence_instruction_hits_without_cards():
    instr = filter_adherence_instruction(
        {"hits_without_cards": {"hit_count": 5, "category": ["jackets"], "price_max": 50.0}},
        products_empty=True,
    )
    assert "5" in instr
    assert "could not find" in instr.lower()


def test_format_products_for_prompt_json():
    products = [_product(title="Tap", url="https://x/t", price=29.5)]
    payload = format_products_for_prompt(products)
    assert '"title": "Tap"' in payload
    assert "29.5" in payload
