from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from typing import Any

import pymysql
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("magento_fetcher")

ENTITY_CATALOG_PRODUCT = 4
ENTITY_CATALOG_CATEGORY = 3

# facet_id -> EAV attribute_code candidates (SyncCatalog extractSelectAttribute alt codes)
FACET_ATTRIBUTE_ALIASES: dict[str, list[str]] = {
    "brand": ["manufacturer"],
    "color": ["color", "colour"],
    "size": ["size"],
    "material": ["material"],
    "pattern": ["pattern"],
    "climate": ["climate"],
}


class MagentoFetcher:
    """Read-only Magento 2 catalog access via MySQL (EAV)."""

    def __init__(self, source_config: dict[str, Any] | None = None, fallback_site_url: str | None = None):
        source_config = source_config or {}
        self.fallback_site_url = (fallback_site_url or "").strip() or None
        self.host = source_config.get("host") or os.getenv("MAGENTO_DB_HOST")
        self.port = int(source_config.get("port") or os.getenv("MAGENTO_DB_PORT", 3306))
        self.user = source_config.get("user") or os.getenv("MAGENTO_DB_USER")
        self.password = source_config.get("password") or os.getenv("MAGENTO_DB_PASSWORD")
        self.database = source_config.get("database") or os.getenv("MAGENTO_DB_NAME")
        self.table_prefix = source_config.get("table_prefix") or ""
        try:
            self.store_id = int(source_config.get("magento_store_id") or 1)
        except (TypeError, ValueError):
            self.store_id = 1
        raw_map = source_config.get("magento_attribute_map") or {}
        self.attribute_map_override: dict[str, str] = dict(raw_map) if isinstance(raw_map, dict) else {}
        self.last_connection_error: str | None = None
        self._attribute_meta: dict[str, dict[str, Any]] | None = None
        self._schema_cache: dict[str, bool] = {}

    def _t(self, table: str) -> str:
        return f"{self.table_prefix}{table}"

    def _physical_table(self, logical_name: str) -> str:
        return self._t(logical_name)

    def _table_exists(self, cursor, logical_name: str) -> bool:
        physical = self._physical_table(logical_name)
        cache_key = f"table:{physical}"
        if cache_key in self._schema_cache:
            return self._schema_cache[cache_key]
        cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            """,
            (self.database, physical),
        )
        row = cursor.fetchone()
        exists = bool(row and int(row.get("cnt") or 0) > 0)
        self._schema_cache[cache_key] = exists
        return exists

    def _has_column(self, cursor, logical_name: str, column: str) -> bool:
        physical = self._physical_table(logical_name)
        cache_key = f"col:{physical}.{column}"
        if cache_key in self._schema_cache:
            return self._schema_cache[cache_key]
        cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
            """,
            (self.database, physical, column),
        )
        row = cursor.fetchone()
        exists = bool(row and int(row.get("cnt") or 0) > 0)
        self._schema_cache[cache_key] = exists
        return exists

    def get_connection(self):
        try:
            self.last_connection_error = None
            return pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
            )
        except Exception as exc:
            self.last_connection_error = str(exc)
            logger.error("Magento DB connection failed: %s", exc)
            return None

    def _load_attribute_meta(self, cursor) -> dict[str, dict[str, Any]]:
        if self._attribute_meta is not None:
            return self._attribute_meta
        # frontend_input lives on eav_attribute (not catalog_eav_attribute on all M2 versions)
        cursor.execute(
            f"""
            SELECT
                ea.attribute_id,
                ea.attribute_code,
                ea.backend_type,
                COALESCE(ea.frontend_input, '') AS frontend_input
            FROM {self._t("eav_attribute")} ea
            WHERE ea.entity_type_id = %s
            """,
            (ENTITY_CATALOG_PRODUCT,),
        )
        meta: dict[str, dict[str, Any]] = {}
        for row in cursor.fetchall():
            code = str(row.get("attribute_code") or "").strip()
            if code:
                meta[code] = row
        self._attribute_meta = meta
        return meta

    def _attribute_table(self, backend_type: str) -> str:
        mapping = {
            "varchar": "catalog_product_entity_varchar",
            "text": "catalog_product_entity_text",
            "int": "catalog_product_entity_int",
            "decimal": "catalog_product_entity_decimal",
            "datetime": "catalog_product_entity_datetime",
        }
        return self._t(mapping.get(backend_type, "catalog_product_entity_varchar"))

    def _eav_value_sql(self, alias: str, attribute_code: str, meta: dict[str, dict[str, Any]]) -> str:
        override_code = self.attribute_map_override.get(attribute_code, attribute_code)
        row = meta.get(override_code)
        if not row:
            return f"NULL AS {alias}"
        attr_id = int(row["attribute_id"])
        table = self._attribute_table(str(row.get("backend_type") or "varchar"))
        return f"""(
            SELECT v.value
            FROM {table} v
            WHERE v.entity_id = cpe.entity_id
              AND v.attribute_id = {attr_id}
              AND v.store_id IN (0, {self.store_id})
            ORDER BY v.store_id DESC
            LIMIT 1
        ) AS {alias}"""

    def _load_option_labels(self, cursor, attribute_ids: list[int]) -> dict[int, dict[int, str]]:
        """option_id -> label per attribute_id (store-scoped, prefers current store)."""
        if not attribute_ids:
            return {}
        placeholders = ",".join(["%s"] * len(attribute_ids))
        cursor.execute(
            f"""
            SELECT o.attribute_id, o.option_id, ov.value, ov.store_id
            FROM {self._t("eav_attribute_option")} o
            INNER JOIN {self._t("eav_attribute_option_value")} ov
              ON ov.option_id = o.option_id
            WHERE o.attribute_id IN ({placeholders})
              AND ov.store_id IN (0, %s)
            ORDER BY o.attribute_id, o.option_id, ov.store_id DESC
            """,
            (*attribute_ids, self.store_id),
        )
        labels: dict[int, dict[int, str]] = defaultdict(dict)
        for row in cursor.fetchall():
            attr_id = int(row["attribute_id"])
            option_id = int(row["option_id"])
            if option_id not in labels[attr_id]:
                label = str(row.get("value") or "").strip()
                if label:
                    labels[attr_id][option_id] = label
        return labels

    @staticmethod
    def _split_option_ids(raw: str) -> list[str]:
        return [part.strip() for part in re.split(r"[,|]", raw) if part.strip()]

    def _resolve_option_labels(
        self,
        raw: Any,
        *,
        attribute_id: int,
        frontend_input: str,
        option_labels: dict[int, dict[int, str]],
    ) -> list[str]:
        """Resolve Magento select/multiselect raw values to human-readable labels."""
        if raw is None:
            return []
        text = str(raw).strip()
        if not text or text in {"0", "false"}:
            return []

        attr_options = option_labels.get(attribute_id) or {}
        frontend = (frontend_input or "").lower()
        is_multiselect = frontend == "multiselect" or (
            "," in text and all(p.strip().isdigit() for p in self._split_option_ids(text))
        )
        parts = self._split_option_ids(text) if ("," in text or "|" in text or is_multiselect) else [text]

        resolved: list[str] = []
        seen: set[str] = set()
        for part in parts:
            label = part
            if part.isdigit() or (part.lstrip("-").isdigit() and part.startswith("-")):
                try:
                    option_id = int(part)
                    label = attr_options.get(option_id) or ""
                except ValueError:
                    label = ""
            label = (label or "").strip()
            if label and label not in seen:
                seen.add(label)
                resolved.append(label)
        return resolved

    def _facet_codes_to_fetch(self, meta: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
        """Return (attribute_code, facet_id) pairs to SELECT."""
        pairs: list[tuple[str, str]] = []
        seen_codes: set[str] = set()
        for facet_id, candidates in FACET_ATTRIBUTE_ALIASES.items():
            override = self.attribute_map_override.get(facet_id)
            codes = [override] if override else []
            codes.extend(candidates)
            for code in codes:
                if code in meta and code not in seen_codes:
                    seen_codes.add(code)
                    pairs.append((code, facet_id))
        return pairs

    def _load_website_id(self, cursor) -> int:
        cursor.execute(
            f"SELECT website_id FROM {self._t('store')} WHERE store_id = %s LIMIT 1",
            (self.store_id,),
        )
        row = cursor.fetchone()
        if row and row.get("website_id") is not None:
            return int(row["website_id"])
        return 1

    def _indexed_final_price_sql(self, cursor, website_id: int) -> str:
        """catalog_product_index_price.final_price (SyncCatalog getFinalPrice parity)."""
        if not self._table_exists(cursor, "catalog_product_index_price"):
            return "NULL AS final_price"
        return f"""(
            SELECT idx.final_price
            FROM {self._t("catalog_product_index_price")} idx
            WHERE idx.entity_id = cpe.entity_id
              AND idx.website_id = {website_id}
              AND idx.customer_group_id = 0
            LIMIT 1
        ) AS final_price"""

    def _gallery_image_sql(self, cursor) -> str:
        """First gallery image path (SyncCatalog getProductImageUrl fallback)."""
        mgte_table = "catalog_product_entity_media_gallery_value_to_entity"
        mg_table = "catalog_product_entity_media_gallery"
        if not self._table_exists(cursor, mgte_table) or not self._table_exists(cursor, mg_table):
            return "NULL AS gallery_image"

        conditions = [
            "mgte.entity_id = cpe.entity_id",
            "mg.value IS NOT NULL",
            "mg.value != ''",
            "mg.value != 'no_selection'",
        ]
        if self._has_column(cursor, mgte_table, "store_id"):
            conditions.append(f"mgte.store_id IN (0, {self.store_id})")
        if self._has_column(cursor, mgte_table, "disabled"):
            conditions.append("(mgte.disabled IS NULL OR mgte.disabled = 0)")
        elif self._has_column(cursor, mg_table, "disabled"):
            conditions.append("(mg.disabled IS NULL OR mg.disabled = 0)")

        order_clause = (
            "mgte.position ASC"
            if self._has_column(cursor, mgte_table, "position")
            else "mgte.value_id ASC"
        )
        where_clause = " AND ".join(conditions)
        return f"""(
            SELECT mg.value
            FROM {self._t(mgte_table)} mgte
            INNER JOIN {self._t(mg_table)} mg ON mg.value_id = mgte.value_id
            WHERE {where_clause}
            ORDER BY {order_clause}
            LIMIT 1
        ) AS gallery_image"""

    @staticmethod
    def pick_image_path(row: dict[str, Any]) -> str | None:
        for field in ("image", "gallery_image", "small_image", "thumbnail"):
            raw = str(row.get(field) or "").strip()
            if not raw or raw == "no_selection":
                continue
            if "placeholder" in raw.lower():
                continue
            return raw
        return None

    @staticmethod
    def pick_prices(row: dict[str, Any]) -> tuple[float | None, float | None]:
        """Return (display_price, sale_price) using index final price when present."""
        indexed = row.get("final_price")
        eav_price = row.get("price")
        special = row.get("special_price")
        try:
            final_val = float(indexed) if indexed not in (None, "") else None
        except (TypeError, ValueError):
            final_val = None
        try:
            base_val = float(eav_price) if eav_price not in (None, "") else None
        except (TypeError, ValueError):
            base_val = None
        try:
            special_val = float(special) if special not in (None, "") else None
        except (TypeError, ValueError):
            special_val = None
        price = final_val if final_val and final_val > 0 else base_val
        sale = None
        if special_val and special_val > 0:
            if price and special_val < price:
                sale = special_val
            elif not price:
                price = special_val
        return price, sale

    def _build_facet_attributes(
        self,
        row: dict[str, Any],
        facet_pairs: list[tuple[str, str]],
        meta: dict[str, dict[str, Any]],
        option_labels: dict[int, dict[int, str]],
    ) -> dict[str, list[str]]:
        facets: dict[str, list[str]] = {}
        for code, facet_id in facet_pairs:
            safe_alias = code.replace("-", "_")
            raw = row.get(safe_alias)
            if raw in (None, ""):
                continue
            attr_row = meta.get(code) or {}
            attr_id = int(attr_row.get("attribute_id") or 0)
            if not attr_id:
                continue
            labels = self._resolve_option_labels(
                raw,
                attribute_id=attr_id,
                frontend_input=str(attr_row.get("frontend_input") or ""),
                option_labels=option_labels,
            )
            if not labels:
                continue
            key = facet_id
            existing = facets.setdefault(key, [])
            for label in labels:
                if label not in existing:
                    existing.append(label)
        return facets

    def _load_configurable_variant_facets(
        self,
        cursor,
        parent_ids: list[int],
        meta: dict[str, dict[str, Any]],
        option_labels: dict[int, dict[int, str]],
    ) -> dict[int, dict[str, list[str]]]:
        """Aggregate color/size from simple children (SyncCatalog getVariantAttributes parity)."""
        if not parent_ids:
            return {}
        variant_codes = []
        for code in ("color", "colour", "size"):
            if code in meta:
                variant_codes.append(code)
        if not variant_codes:
            return {}

        parent_ph = ",".join(["%s"] * len(parent_ids))
        cursor.execute(
            f"""
            SELECT parent_id, child_id
            FROM {self._t("catalog_product_relation")}
            WHERE parent_id IN ({parent_ph})
            """,
            tuple(parent_ids),
        )
        relations = cursor.fetchall()
        if not relations:
            return {}

        child_ids = list({int(r["child_id"]) for r in relations})
        child_ph = ",".join(["%s"] * len(child_ids))
        attr_selects = []
        for code in variant_codes:
            safe = code.replace("-", "_")
            attr_selects.append(self._eav_value_sql(safe, code, meta))
        cursor.execute(
            f"""
            SELECT cpe.entity_id AS child_id, {", ".join(attr_selects)}
            FROM {self._t("catalog_product_entity")} cpe
            WHERE cpe.entity_id IN ({child_ph})
            """,
            tuple(child_ids),
        )
        child_rows = {int(r["child_id"]): r for r in cursor.fetchall()}

        parent_children: dict[int, list[int]] = defaultdict(list)
        for rel in relations:
            parent_children[int(rel["parent_id"])].append(int(rel["child_id"]))

        aggregated: dict[int, dict[str, list[str]]] = {}
        variant_pairs: list[tuple[str, str]] = []
        for code in variant_codes:
            facet_id = "color" if code == "colour" else code
            variant_pairs.append((code, facet_id))

        for parent_id, children in parent_children.items():
            merged: dict[str, list[str]] = {}
            for child_id in children:
                child_row = child_rows.get(child_id)
                if not child_row:
                    continue
                child_facets = self._build_facet_attributes(child_row, variant_pairs, meta, option_labels)
                for facet_id, values in child_facets.items():
                    bucket = merged.setdefault(facet_id, [])
                    for val in values:
                        if val not in bucket:
                            bucket.append(val)
            if merged:
                aggregated[parent_id] = merged
        return aggregated

    def get_base_url(self) -> str:
        if self.fallback_site_url:
            return self.fallback_site_url.rstrip("/")
        connection = self.get_connection()
        if not connection:
            return ""
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT value FROM {self._t("core_config_data")}
                    WHERE path = 'web/unsecure/base_url'
                      AND scope = 'stores'
                      AND scope_id = %s
                    LIMIT 1
                    """,
                    (self.store_id,),
                )
                row = cursor.fetchone()
                if row and row.get("value"):
                    return str(row["value"]).rstrip("/")
                cursor.execute(
                    f"""
                    SELECT value FROM {self._t("core_config_data")}
                    WHERE path = 'web/unsecure/base_url' AND scope = 'default' AND scope_id = 0
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
                return str(row.get("value") or "").rstrip("/") if row else ""
        finally:
            connection.close()

    def fetch_products(self) -> list[dict[str, Any]]:
        connection = self.get_connection()
        if not connection:
            detail = self.last_connection_error or "unknown connection error"
            raise ConnectionError(f"Failed to connect to Magento database for products: {detail}")
        try:
            with connection.cursor() as cursor:
                meta = self._load_attribute_meta(cursor)
                facet_pairs = self._facet_codes_to_fetch(meta)
                option_attr_ids = [
                    int((meta.get(code) or {}).get("attribute_id") or 0)
                    for code, _ in facet_pairs
                    if (meta.get(code) or {}).get("attribute_id")
                ]
                option_labels = self._load_option_labels(cursor, option_attr_ids)
                website_id = self._load_website_id(cursor)

                attr_selects = [
                    self._eav_value_sql("name", "name", meta),
                    self._eav_value_sql("short_description", "short_description", meta),
                    self._eav_value_sql("description", "description", meta),
                    self._eav_value_sql("url_key", "url_key", meta),
                    self._eav_value_sql("image", "image", meta),
                    self._gallery_image_sql(cursor),
                    self._eav_value_sql("small_image", "small_image", meta),
                    self._eav_value_sql("thumbnail", "thumbnail", meta),
                    self._eav_value_sql("price", "price", meta),
                    self._indexed_final_price_sql(cursor, website_id),
                    self._eav_value_sql("special_price", "special_price", meta),
                    self._eav_value_sql("status", "status", meta),
                    self._eav_value_sql("visibility", "visibility", meta),
                ]
                for code, _facet_id in facet_pairs:
                    safe_alias = code.replace("-", "_")
                    attr_selects.append(self._eav_value_sql(safe_alias, code, meta))

                query = f"""
                SELECT
                    cpe.entity_id AS id,
                    cpe.sku AS sku,
                    cpe.type_id AS type_id,
                    {", ".join(attr_selects)},
                    stock.stock_status AS stock_status,
                    GROUP_CONCAT(DISTINCT cat_name.value ORDER BY cat_name.value SEPARATOR '|||') AS categories
                FROM {self._t("catalog_product_entity")} cpe
                LEFT JOIN {self._t("cataloginventory_stock_status")} stock
                  ON stock.product_id = cpe.entity_id AND stock.website_id = 0
                LEFT JOIN {self._t("catalog_category_product")} ccp ON ccp.product_id = cpe.entity_id
                LEFT JOIN {self._t("catalog_category_entity")} ce ON ce.entity_id = ccp.category_id
                LEFT JOIN {self._t("catalog_category_entity_varchar")} cat_name
                  ON cat_name.entity_id = ce.entity_id
                  AND cat_name.attribute_id = (
                    SELECT attribute_id FROM {self._t("eav_attribute")}
                    WHERE attribute_code = 'name' AND entity_type_id = {ENTITY_CATALOG_CATEGORY}
                    LIMIT 1
                  )
                  AND cat_name.store_id IN (0, {self.store_id})
                GROUP BY cpe.entity_id, cpe.sku, cpe.type_id, stock.stock_status
                """
                cursor.execute(query)
                rows = cursor.fetchall()

                configurable_ids = [
                    int(r["id"])
                    for r in rows
                    if str(r.get("type_id") or "").lower() == "configurable"
                ]
                variant_facets = self._load_configurable_variant_facets(
                    cursor, configurable_ids, meta, option_labels
                )
        finally:
            connection.close()

        products: list[dict[str, Any]] = []
        for row in rows:
            status = row.get("status")
            visibility = row.get("visibility")
            try:
                if status is not None and int(status) != 1:
                    continue
            except (TypeError, ValueError):
                pass
            try:
                if visibility is not None and int(visibility) not in (2, 3, 4):
                    continue
            except (TypeError, ValueError):
                pass
            type_id = str(row.get("type_id") or "").lower()
            if type_id not in {"", "simple", "configurable", "virtual", "downloadable"}:
                continue

            entity_id = int(row["id"])
            facet_attributes = self._build_facet_attributes(row, facet_pairs, meta, option_labels)

            # Merge variant color/size from children when parent is configurable
            child_facets = variant_facets.get(entity_id) or {}
            for facet_id, values in child_facets.items():
                if facet_id in ("color", "size") and not facet_attributes.get(facet_id):
                    facet_attributes[facet_id] = list(values)
                elif facet_id in ("color", "size"):
                    bucket = facet_attributes[facet_id]
                    for val in values:
                        if val not in bucket:
                            bucket.append(val)

            products.append(
                {
                    **row,
                    "facet_attributes": facet_attributes,
                }
            )
        return products

    def fetch_categories(self) -> list[dict[str, Any]]:
        connection = self.get_connection()
        if not connection:
            detail = self.last_connection_error or "unknown connection error"
            raise ConnectionError(f"Failed to connect to Magento database for categories: {detail}")
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        ce.entity_id AS id,
                        ce.parent_id AS parent_id,
                        (
                            SELECT v.value
                            FROM {self._t("catalog_category_entity_varchar")} v
                            WHERE v.entity_id = ce.entity_id
                              AND v.attribute_id = (
                                SELECT attribute_id FROM {self._t("eav_attribute")}
                                WHERE attribute_code = 'name' AND entity_type_id = {ENTITY_CATALOG_CATEGORY}
                                LIMIT 1
                              )
                              AND v.store_id IN (0, {self.store_id})
                            ORDER BY v.store_id DESC
                            LIMIT 1
                        ) AS title,
                        (
                            SELECT v.value
                            FROM {self._t("catalog_category_entity_varchar")} v
                            WHERE v.entity_id = ce.entity_id
                              AND v.attribute_id = (
                                SELECT attribute_id FROM {self._t("eav_attribute")}
                                WHERE attribute_code = 'url_key' AND entity_type_id = {ENTITY_CATALOG_CATEGORY}
                                LIMIT 1
                              )
                              AND v.store_id IN (0, {self.store_id})
                            ORDER BY v.store_id DESC
                            LIMIT 1
                        ) AS slug
                    FROM {self._t("catalog_category_entity")} ce
                    WHERE ce.level > 0
                    ORDER BY ce.position ASC, ce.entity_id ASC
                    """
                )
                return cursor.fetchall()
        finally:
            connection.close()

    def fetch_cms_pages(self) -> list[dict[str, Any]]:
        connection = self.get_connection()
        if not connection:
            detail = self.last_connection_error or "unknown connection error"
            raise ConnectionError(f"Failed to connect to Magento database for CMS pages: {detail}")
        try:
            with connection.cursor() as cursor:
                if not self._table_exists(cursor, "cms_page"):
                    return []
                cursor.execute(
                    f"""
                    SELECT
                        page_id AS id,
                        title,
                        content,
                        identifier,
                        is_active
                    FROM {self._t("cms_page")}
                    WHERE is_active = 1
                    ORDER BY page_id ASC
                    """
                )
                return cursor.fetchall()
        finally:
            connection.close()
