from sources.config import resolve_source_plan


def test_magento_mode_includes_cms_flag():
    plan = resolve_source_plan({"source_db_type": "magento", "source_mode": "magento"})
    assert plan.include_magento_catalog is True
    assert plan.include_magento_cms is True


def test_magento_mixed_includes_cms():
    plan = resolve_source_plan({"source_db_type": "magento", "source_mode": "mixed"})
    assert plan.include_magento_cms is True
