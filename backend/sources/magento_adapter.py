from __future__ import annotations

import re
from html import unescape

from sources.base import SourceAdapter, SourceContext, SourceRecord, SyncBatch
from sources.magento_fetcher import MagentoFetcher


def _parse_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", unescape(str(text)))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _split_categories(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in str(raw).split("|||") if item and item.strip()]


class MagentoCatalogAdapter(SourceAdapter):
    provider = "magento"

    def _build_product_url(self, base_url: str, url_key: str, product_id: str) -> str:
        site = (base_url or "").rstrip("/")
        key = (url_key or "").strip()
        if site and key:
            return f"{site}/{key}.html"
        if site:
            return f"{site}/catalog/product/view/id/{product_id}/"
        return f"/catalog/product/view/id/{product_id}/"

    def _build_category_url(self, base_url: str, slug: str, category_id: str) -> str:
        site = (base_url or "").rstrip("/")
        key = (slug or "").strip()
        if site and key:
            return f"{site}/{key}.html"
        if site:
            return f"{site}/catalog/category/view/id/{category_id}/"
        return f"/catalog/category/view/id/{category_id}/"

    def _resolve_image_url(self, base_url: str, image_path: str | None) -> str | None:
        path = (image_path or "").strip()
        if not path:
            return None
        if path.startswith("http://") or path.startswith("https://"):
            return path
        site = (base_url or "").rstrip("/")
        if not site:
            return path
        return f"{site}/media/catalog/product/{path.lstrip('/')}"

    def _stock_status(self, stock_status: int | str | None) -> str | None:
        if stock_status is None:
            return None
        try:
            return "instock" if int(stock_status) == 1 else "outofstock"
        except (TypeError, ValueError):
            raw = str(stock_status).strip().lower()
            return raw or None

    async def discover(self, ctx: SourceContext) -> list[SyncBatch]:
        fetcher = MagentoFetcher(
            source_config=ctx.source_config,
            fallback_site_url=ctx.source_config.get("url_fallback_base")
            or ctx.source_config.get("source_canonical_base_url"),
        )
        base_url = fetcher.get_base_url()
        records: list[SourceRecord] = []

        for product in fetcher.fetch_products():
            facet_attrs = dict(product.get("facet_attributes") or {})
            brand_values = facet_attrs.pop("brand", None) or []
            if isinstance(brand_values, str):
                brand_values = [brand_values] if brand_values.strip() else []
            brand = brand_values[0] if brand_values else None
            attributes: dict[str, list[str]] = {}
            for key, value in facet_attrs.items():
                if isinstance(value, list):
                    cleaned = [str(v).strip() for v in value if str(v).strip()]
                    if cleaned:
                        attributes[key] = cleaned
                elif value:
                    attributes[key] = [str(value).strip()]
            categories = _split_categories(product.get("categories"))
            price, sale_price = MagentoFetcher.pick_prices(product)
            image_path = MagentoFetcher.pick_image_path(product)
            entity_id = str(product.get("id"))
            records.append(
                SourceRecord(
                    source_provider="magento",
                    content_kind="product",
                    entity_id=entity_id,
                    title=(product.get("name") or "").strip() or "Untitled product",
                    summary=_strip_html(product.get("short_description")),
                    body=_strip_html(product.get("description")),
                    canonical_url=self._build_product_url(
                        base_url,
                        product.get("url_key") or "",
                        entity_id,
                    ),
                    metadata={
                        "sku": (product.get("sku") or "").strip() or None,
                        "price": price,
                        "sale_price": sale_price,
                        "stock_status": self._stock_status(product.get("stock_status")),
                        "brand": brand,
                        "categories": categories,
                        "attributes": attributes,
                        "image_url": self._resolve_image_url(base_url, image_path),
                    },
                )
            )

        include_cms = bool(ctx.source_config.get("include_magento_cms", True))
        if include_cms:
            for page in fetcher.fetch_cms_pages():
                title = (page.get("title") or "").strip()
                body = _strip_html(page.get("content"))
                identifier = (page.get("identifier") or "").strip()
                if not title and not body:
                    continue
                page_id = str(page.get("id"))
                slug = identifier or page_id
                url = f"{base_url.rstrip('/')}/{slug}.html" if base_url else f"/{slug}"
                identifier_lower = identifier.lower()
                if any(
                    token in identifier_lower
                    for token in ("return", "refund", "shipping", "delivery", "policy", "privacy", "terms")
                ):
                    content_kind = "support_page"
                else:
                    content_kind = "cms_page"
                records.append(
                    SourceRecord(
                        source_provider="magento",
                        content_kind=content_kind,
                        entity_id=page_id,
                        title=title or identifier or "CMS page",
                        body=body,
                        summary=body[:240] if body else None,
                        canonical_url=url,
                        metadata={"identifier": identifier},
                    )
                )

        for category in fetcher.fetch_categories():
            title = (category.get("title") or "").strip()
            if not title:
                continue
            cat_id = str(category.get("id"))
            parent = category.get("parent_id")
            records.append(
                SourceRecord(
                    source_provider="magento",
                    content_kind="category",
                    entity_id=cat_id,
                    parent_entity_id=str(parent) if parent not in (None, 0, "0", 1, "1") else None,
                    title=title,
                    canonical_url=self._build_category_url(base_url, category.get("slug") or "", cat_id),
                    metadata={"categories": [title]},
                )
            )

        return [
            SyncBatch(
                tenant_id=ctx.tenant_id,
                provider=self.provider,
                mode=ctx.mode,
                records=records,
            )
        ]
