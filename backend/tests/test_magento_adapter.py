import asyncio

from sources.base import SourceContext
from sources.magento_adapter import MagentoCatalogAdapter


def test_magento_adapter_emits_products_and_categories(monkeypatch):
    monkeypatch.setattr(
        "sources.magento_adapter.MagentoFetcher.get_base_url",
        lambda self: "https://shop.example.com",
    )
    monkeypatch.setattr(
        "sources.magento_adapter.MagentoFetcher.fetch_products",
        lambda self: [
            {
                "id": 101,
                "sku": "BASIN-01",
                "name": "Chrome Basin Tap",
                "short_description": "<p>Short</p>",
                "description": "<p>Full description</p>",
                "url_key": "chrome-basin-tap",
                "image": "/c/h/chrome.jpg",
                "price": "99.00",
                "special_price": "79.00",
                "stock_status": 1,
                "categories": "Basins|||Taps",
                "facet_attributes": {
                    "brand": ["Acme"],
                    "color": ["Chrome", "Black"],
                    "material": ["Brass"],
                    "pattern": ["Color-Blocked"],
                },
            }
        ],
    )
    monkeypatch.setattr(
        "sources.magento_adapter.MagentoFetcher.fetch_categories",
        lambda self: [
            {"id": 5, "title": "Basins", "slug": "basins", "parent_id": 2},
        ],
    )
    monkeypatch.setattr(
        "sources.magento_adapter.MagentoFetcher.fetch_cms_pages",
        lambda self: [],
    )
    adapter = MagentoCatalogAdapter()
    ctx = SourceContext(
        tenant_id="tenant-m",
        provider="magento",
        mode="full",
        source_config={"source_db_type": "magento", "magento_store_id": 1},
        started_at="now",
    )
    batches = asyncio.run(adapter.discover(ctx))
    records = batches[0].records
    product = next(r for r in records if r.content_kind == "product")
    category = next(r for r in records if r.content_kind == "category")

    assert product.entity_id == "101"
    assert product.canonical_url == "https://shop.example.com/chrome-basin-tap.html"
    assert product.metadata["sku"] == "BASIN-01"
    assert product.metadata["brand"] == "Acme"
    assert product.metadata["stock_status"] == "instock"
    assert product.metadata["price"] == 99.0
    assert product.metadata["sale_price"] == 79.0
    assert product.metadata["categories"] == ["Basins", "Taps"]
    assert product.metadata["attributes"]["color"] == ["Chrome", "Black"]
    assert product.metadata["attributes"]["pattern"] == ["Color-Blocked"]
    assert product.metadata["image_url"] == "https://shop.example.com/media/catalog/product/c/h/chrome.jpg"
    assert category.title == "Basins"
    assert category.canonical_url == "https://shop.example.com/basins.html"
