from __future__ import annotations

from collections import defaultdict

from sources.base import SourceAdapter, SourceContext, SourceRecord, SyncBatch
from wordpress_fetcher import WordPressFetcher


def _parse_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


class WooCommerceCatalogAdapter(SourceAdapter):
    provider = "woocommerce"

    def _build_product_url(self, site_url: str, slug: str, product_id: str) -> str:
        site = (site_url or "").rstrip("/")
        safe_slug = (slug or "").strip()
        if safe_slug:
            return f"{site}/product/{safe_slug}/"
        return f"{site}/?post_type=product&p={product_id}"

    def _build_category_url(self, site_url: str, slug: str, category_id: str) -> str:
        site = (site_url or "").rstrip("/")
        safe_slug = (slug or "").strip()
        if safe_slug:
            return f"{site}/product-category/{safe_slug}/"
        return f"{site}/?product_cat={category_id}"

    def _fetch_products(self, fetcher: WordPressFetcher) -> list[dict]:
        connection = fetcher.get_connection()
        if not connection:
            detail = fetcher.last_connection_error or "unknown connection error"
            raise ConnectionError(f"Failed to connect to WordPress database for Woo products fetch: {detail}")
        try:
            with connection.cursor() as cursor:
                query = f"""
                SELECT
                    p.ID AS id,
                    p.post_title AS title,
                    p.post_excerpt AS excerpt,
                    p.post_content AS content,
                    p.post_name AS slug,
                    p.post_modified AS updated_at,
                    MAX(CASE WHEN pm.meta_key = '_sku' THEN pm.meta_value END) AS sku,
                    MAX(CASE WHEN pm.meta_key = '_price' THEN pm.meta_value END) AS price,
                    MAX(CASE WHEN pm.meta_key = '_sale_price' THEN pm.meta_value END) AS sale_price,
                    MAX(CASE WHEN pm.meta_key = '_stock_status' THEN pm.meta_value END) AS stock_status,
                    GROUP_CONCAT(DISTINCT CASE WHEN tt.taxonomy = 'product_cat' THEN t.name END SEPARATOR '|||') AS categories,
                    GROUP_CONCAT(DISTINCT CASE WHEN tt.taxonomy LIKE 'pa_%%' THEN CONCAT(REPLACE(tt.taxonomy, 'pa_', ''), ':', t.name) END SEPARATOR '|||') AS attributes
                FROM {fetcher.table_prefix}posts p
                LEFT JOIN {fetcher.table_prefix}postmeta pm ON p.ID = pm.post_id
                LEFT JOIN {fetcher.table_prefix}term_relationships tr ON p.ID = tr.object_id
                LEFT JOIN {fetcher.table_prefix}term_taxonomy tt ON tr.term_taxonomy_id = tt.term_taxonomy_id
                LEFT JOIN {fetcher.table_prefix}terms t ON tt.term_id = t.term_id
                WHERE p.post_type = 'product' AND p.post_status = 'publish'
                GROUP BY p.ID
                ORDER BY p.post_modified DESC
                """
                cursor.execute(query)
                return cursor.fetchall()
        finally:
            connection.close()

    def _fetch_categories(self, fetcher: WordPressFetcher) -> list[dict]:
        connection = fetcher.get_connection()
        if not connection:
            detail = fetcher.last_connection_error or "unknown connection error"
            raise ConnectionError(f"Failed to connect to WordPress database for Woo categories fetch: {detail}")
        try:
            with connection.cursor() as cursor:
                query = f"""
                SELECT
                    t.term_id AS id,
                    t.name AS title,
                    t.slug AS slug,
                    tt.description AS description,
                    tt.parent AS parent_id
                FROM {fetcher.table_prefix}term_taxonomy tt
                JOIN {fetcher.table_prefix}terms t ON t.term_id = tt.term_id
                WHERE tt.taxonomy = 'product_cat'
                ORDER BY t.name ASC
                """
                cursor.execute(query)
                return cursor.fetchall()
        finally:
            connection.close()

    async def discover(self, ctx: SourceContext) -> list[SyncBatch]:
        fetcher = WordPressFetcher(source_config=ctx.source_config, fallback_site_url=ctx.source_config.get("url_fallback_base"))
        site_url = fetcher._get_site_url()
        records: list[SourceRecord] = []

        for product in self._fetch_products(fetcher):
            attributes: dict[str, list[str]] = defaultdict(list)
            raw_attrs = (product.get("attributes") or "").split("|||") if product.get("attributes") else []
            brand = None
            for entry in raw_attrs:
                if ":" not in entry:
                    continue
                key, value = entry.split(":", 1)
                key = (key or "").strip().lower()
                value = (value or "").strip()
                if not value:
                    continue
                attributes[key].append(value)
                if key in {"brand", "manufacturer"} and not brand:
                    brand = value
            categories = [item.strip() for item in (product.get("categories") or "").split("|||") if item and item.strip()]
            records.append(
                SourceRecord(
                    source_provider="woocommerce",
                    content_kind="product",
                    entity_id=str(product.get("id")),
                    title=(product.get("title") or "").strip() or "Untitled product",
                    summary=(product.get("excerpt") or "").strip() or None,
                    body=fetcher._clean_html_content(product.get("content") or "") or None,
                    canonical_url=self._build_product_url(site_url, product.get("slug") or "", str(product.get("id"))),
                    updated_at=str(product.get("updated_at") or "") or None,
                    metadata={
                        "sku": (product.get("sku") or "").strip() or None,
                        "price": _parse_float(product.get("price")),
                        "sale_price": _parse_float(product.get("sale_price")),
                        "stock_status": (product.get("stock_status") or "").strip() or None,
                        "brand": brand,
                        "categories": categories,
                        "attributes": dict(attributes),
                    },
                )
            )

        for category in self._fetch_categories(fetcher):
            records.append(
                SourceRecord(
                    source_provider="woocommerce",
                    content_kind="category",
                    entity_id=str(category.get("id")),
                    parent_entity_id=str(category.get("parent_id")) if category.get("parent_id") not in (None, 0, "0") else None,
                    title=(category.get("title") or "").strip() or "Unnamed category",
                    summary=(category.get("description") or "").strip() or None,
                    body=(category.get("description") or "").strip() or None,
                    canonical_url=self._build_category_url(site_url, category.get("slug") or "", str(category.get("id"))),
                    metadata={"categories": [category.get("title")]},
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
