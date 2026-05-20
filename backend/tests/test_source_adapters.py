import asyncio

from sources.base import SourceContext
from sources.config import normalize_source_provider, parse_source_dsn, resolve_source_plan
from sources.static_adapter import StaticUrlAdapter
from sources.woocommerce_adapter import WooCommerceCatalogAdapter, resolve_product_image_url


def test_normalize_source_provider_prefers_explicit_provider():
    assert normalize_source_provider("woocommerce", source_mode="wordpress", source_db_url="mysql://db") == "woocommerce"
    assert normalize_source_provider("magento", source_mode="magento", source_db_url="mysql://db") == "magento"
    assert normalize_source_provider("static", source_static_urls_json='["https://example.com"]') == "static"


def test_resolve_source_plan_for_magento_mixed():
    plan = resolve_source_plan(
        {
            "source_db_type": "magento",
            "source_mode": "mixed",
            "source_db_url": "mysql://db",
            "source_static_urls_json": '["https://example.com/help"]',
        }
    )
    assert plan.provider == "magento"
    assert plan.include_magento_catalog is True
    assert plan.include_static_urls is True
    assert plan.include_woocommerce_catalog is False


def test_resolve_source_plan_for_woocommerce_mixed():
    plan = resolve_source_plan(
        {
            "source_db_type": "woocommerce",
            "source_mode": "mixed",
            "source_db_url": "mysql://db",
            "source_static_urls_json": '["https://example.com/help"]',
        }
    )
    assert plan.provider == "woocommerce"
    assert plan.include_wordpress_content is True
    assert plan.include_woocommerce_catalog is True
    assert plan.include_static_urls is True


def test_parse_source_dsn_tolerates_malformed_port_segment():
    cfg = parse_source_dsn("mysql://user:bad@pw@db.example.com:E6$;_K_r/store", "wp_", "wp_urls")
    assert cfg["port"] == 3306
    assert cfg["database"] == "store"


def test_static_url_adapter_normalizes_and_dedupes(monkeypatch):
    async def fake_scrape(urls):
        return [{"url": urls[0]["url"], "title": "Shipping", "description": "", "content": "Shipping details"}]

    monkeypatch.setattr("sources.static_adapter.scrape_urls", fake_scrape)
    adapter = StaticUrlAdapter()
    ctx = SourceContext(
        tenant_id="tenant-a",
        provider="static",
        mode="full",
        source_config={
            "source_static_urls_json": '["https://staging.example.com/shipping?utm_source=abc", "https://www.example.com/shipping/"]',
            "source_domain_aliases": "https://staging.example.com",
            "source_canonical_base_url": "https://www.example.com",
        },
        started_at="now",
    )
    batches = asyncio.run(adapter.discover(ctx))
    assert batches[0].records[0].canonical_url == "https://www.example.com/shipping"
    assert batches[0].records[0].content_kind == "support_page"


def test_resolve_product_image_url_prefers_attached_file_over_guid():
    url = resolve_product_image_url(
        "https://shop.example.com",
        image_attached_file="2024/01/basin.jpg",
        image_guid="https://shop.example.com/wp-content/uploads/stale.jpg",
    )
    assert url == "https://shop.example.com/wp-content/uploads/2024/01/basin.jpg"


def test_resolve_product_image_url_falls_back_to_guid():
    url = resolve_product_image_url(
        "https://shop.example.com/",
        image_attached_file=None,
        image_guid="https://cdn.example.com/media/basin.jpg",
    )
    assert url == "https://cdn.example.com/media/basin.jpg"


def test_resolve_product_image_url_returns_none_when_missing():
    assert resolve_product_image_url("https://shop.example.com", image_attached_file="", image_guid="") is None


def test_woocommerce_adapter_emits_products_and_categories(monkeypatch):
    monkeypatch.setattr("sources.woocommerce_adapter.WordPressFetcher._get_site_url", lambda self: "https://shop.example.com/")
    monkeypatch.setattr("sources.woocommerce_adapter.WordPressFetcher._clean_html_content", lambda self, text: text.replace("<p>", "").replace("</p>", ""))
    monkeypatch.setattr(
        WooCommerceCatalogAdapter,
        "_fetch_products",
        lambda self, fetcher: [
            {
                "id": 10,
                "title": "Widget",
                "excerpt": "Short widget",
                "content": "<p>Full widget body</p>",
                "slug": "widget",
                "updated_at": "2026-05-14 12:00:00",
                "sku": "W-10",
                "price": "49.99",
                "sale_price": "39.99",
                "stock_status": "instock",
                "categories": "Widgets|||Featured",
                "attributes": "brand:Acme|||color:Black",
                "image_attached_file": "2024/05/widget.jpg",
                "image_guid": "https://shop.example.com/wp-content/uploads/2024/05/widget-old.jpg",
            }
        ],
    )
    monkeypatch.setattr(
        WooCommerceCatalogAdapter,
        "_fetch_categories",
        lambda self, fetcher: [
            {"id": 22, "title": "Widgets", "slug": "widgets", "description": "All widgets", "parent_id": 0}
        ],
    )
    adapter = WooCommerceCatalogAdapter()
    ctx = SourceContext(
        tenant_id="tenant-a",
        provider="woocommerce",
        mode="full",
        source_config={"source_db_type": "woocommerce", "table_prefix": "wp_"},
        started_at="now",
    )
    batches = asyncio.run(adapter.discover(ctx))
    records = batches[0].records
    product = next(record for record in records if record.content_kind == "product")
    category = next(record for record in records if record.content_kind == "category")
    assert product.canonical_url == "https://shop.example.com/product/widget/"
    assert product.metadata["brand"] == "Acme"
    assert product.metadata["categories"] == ["Widgets", "Featured"]
    assert product.metadata["image_url"] == "https://shop.example.com/wp-content/uploads/2024/05/widget.jpg"
    assert category.canonical_url == "https://shop.example.com/product-category/widgets/"
