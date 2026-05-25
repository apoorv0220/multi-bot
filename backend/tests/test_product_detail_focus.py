from retrieval.tools.product_detail_focus import infer_product_detail_focus, format_product_detail_for_message


def test_focus_price():
    assert infer_product_detail_focus("What is the price of juno jacket?") == "price"


def test_focus_specs():
    assert infer_product_detail_focus("What are the specifications of juno jacket?") == "specs"


def test_focus_description():
    assert infer_product_detail_focus("Tell me about juno jacket") == "description"


def test_price_answer_is_concise():
    payload = {
        "title": "Juno Jacket",
        "price": 77,
        "url": "https://example.com/juno-jacket.html",
    }
    text = format_product_detail_for_message(payload, "What is the price of juno jacket?")
    assert "Juno Jacket" in text
    assert "$77.00" in text
    assert "Specifications" not in text
    assert "[View product]" in text


def test_overview_has_markdown_link():
    payload = {
        "title": "Juno Jacket",
        "price": 77,
        "url": "https://example.com/juno-jacket.html",
        "stock_status": "instock",
    }
    text = format_product_detail_for_message(payload, "Show product details for juno jacket")
    assert "[View product](https://example.com/juno-jacket.html)" in text
