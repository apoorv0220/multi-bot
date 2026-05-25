from retrieval.catalog_coverage import resolve_catalog_block
from retrieval.structured_query import CatalogCoverageSpec


def test_llm_in_catalog_true_overrides_rules_fallback():
    blocked, reason = resolve_catalog_block(
        message="Show black shoes under $100",
        profile={"category_strategy": {"gazetteer": [{"id": "jackets", "labels": ["Jackets"]}]}},
        coverage=CatalogCoverageSpec(in_catalog=True, confidence=0.95, source="llm"),
    )
    assert blocked is False
    assert reason is None
