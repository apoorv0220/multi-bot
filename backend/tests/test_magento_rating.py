from sources.magento_fetcher import MagentoFetcher


def test_rating_from_summary_percent_to_stars():
    stars, reviews = MagentoFetcher.rating_from_summary(80, 12)
    assert stars == 4.0
    assert reviews == 12


def test_review_summary_sql_uses_entity_type_column():
    class FakeCursor:
        pass

    fetcher = MagentoFetcher(source_config={"table_prefix": "mage_"})
    fetcher._schema_cache = {
        "table:mage_review_entity_summary": True,
        "col:mage_review_entity_summary.entity_type_id": False,
        "col:mage_review_entity_summary.entity_type": True,
        "col:mage_review_entity_summary.store_id": True,
        "table:mage_review_entity": True,
    }

    sql = fetcher._review_summary_sql(FakeCursor())
    assert "entity_type_id" not in sql
    assert "res.entity_type =" in sql
    assert "entity_code = 'product'" in sql

