from types import SimpleNamespace

from retrieval.catalog_cards import (
    filter_results_for_catalog_cards,
    filter_results_for_response_sources,
    is_product_card_eligible,
)


def test_product_payload_is_card_eligible():
    assert is_product_card_eligible(
        {
            "content_kind": "product",
            "url": "https://example.com/product/foo/",
            "price": 99.0,
        }
    )


def test_category_archive_url_not_eligible():
    assert not is_product_card_eligible(
        {
            "content_kind": "category",
            "content_bucket": "catalog",
            "url": "https://example.com/product-category/basins/",
            "price": None,
        }
    )


def test_product_kind_without_product_path_still_eligible():
    assert is_product_card_eligible(
        {
            "content_kind": "product",
            "url": "https://example.com/basin-mixer-123/",
            "price": 72.0,
        }
    )


def test_legacy_slug_url_with_price_is_eligible():
    assert is_product_card_eligible(
        {
            "content_kind": "cms_page",
            "content_bucket": "catalog",
            "url": "http://bathconnect.example/contract-basin-taps-chrome",
            "price": 40.0,
        }
    )


def test_canonical_product_path_eligible_without_content_kind_product():
    assert is_product_card_eligible(
        {
            "content_bucket": "catalog",
            "url": "http://bathconnect.example/product/contract-basin-taps-chrome/",
            "price": 40.0,
        }
    )


def test_support_intent_filters_products_from_sources():
    hits = [
        SimpleNamespace(payload={"content_kind": "product", "url": "https://x/p/1"}),
        SimpleNamespace(payload={"content_kind": "policy", "url": "https://x/shipping"}),
    ]
    filtered = filter_results_for_response_sources(hits, "support")
    assert len(filtered) == 1
    assert filtered[0].payload["content_kind"] == "policy"


def test_filter_results_for_catalog_cards():
    hits = [
        SimpleNamespace(payload={"content_kind": "product", "url": "https://x/p/1"}),
        SimpleNamespace(payload={"content_kind": "category", "url": "https://x/cat/"}),
    ]
    cards = filter_results_for_catalog_cards(hits)
    assert len(cards) == 1
