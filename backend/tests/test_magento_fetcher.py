from sources.magento_fetcher import MagentoFetcher


def test_resolve_option_labels_multiselect_ids():
    fetcher = MagentoFetcher()
    option_labels = {
        99: {144: "Fleece", 145: "Hemp", 38: "Polyester"},
    }
    labels = fetcher._resolve_option_labels(
        "144,145,38",
        attribute_id=99,
        frontend_input="multiselect",
        option_labels=option_labels,
    )
    assert labels == ["Fleece", "Hemp", "Polyester"]


def test_resolve_option_labels_select_id():
    fetcher = MagentoFetcher()
    option_labels = {10: {194: "Color-Blocked"}}
    labels = fetcher._resolve_option_labels(
        "194",
        attribute_id=10,
        frontend_input="select",
        option_labels=option_labels,
    )
    assert labels == ["Color-Blocked"]


def test_resolve_option_labels_plain_text_passthrough():
    fetcher = MagentoFetcher()
    labels = fetcher._resolve_option_labels(
        "Chrome",
        attribute_id=1,
        frontend_input="select",
        option_labels={},
    )
    assert labels == ["Chrome"]


def test_pick_prices_prefers_index_final_price():
    price, sale = MagentoFetcher.pick_prices(
        {"price": "99", "final_price": "54", "special_price": "49"}
    )
    assert price == 54.0
    assert sale == 49.0


def test_pick_image_path_prefers_gallery_when_base_empty():
    path = MagentoFetcher.pick_image_path(
        {"image": "no_selection", "gallery_image": "/m/h/product.jpg"}
    )
    assert path == "/m/h/product.jpg"


def test_gallery_image_sql_omits_store_id_when_column_missing():
    fetcher = MagentoFetcher(source_config={"database": "testdb", "table_prefix": ""})

    def fake_table_exists(_cursor, logical_name: str) -> bool:
        return logical_name in (
            "catalog_product_entity_media_gallery_value_to_entity",
            "catalog_product_entity_media_gallery",
        )

    def fake_has_column(_cursor, logical_name: str, column: str) -> bool:
        return column not in ("store_id", "disabled", "position")

    fetcher._table_exists = fake_table_exists  # type: ignore[method-assign]
    fetcher._has_column = fake_has_column  # type: ignore[method-assign]

    sql = fetcher._gallery_image_sql(cursor=None)
    assert "mgte.store_id" not in sql
    assert "gallery_image" in sql
