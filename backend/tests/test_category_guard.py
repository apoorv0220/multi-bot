from retrieval.catalog_coverage import resolve_catalog_block
from retrieval.structured_query import CatalogCoverageSpec, empty_structured_query
from retrieval.subtype_classifier import classify_response_subtype


APPAREL_GAZETTEER = {
    "category_strategy": {
        "gazetteer": [
            {"id": "jackets", "labels": ["Jackets"]},
            {"id": "pants", "labels": ["Pants"]},
            {"id": "bags", "labels": ["Bags"]},
            {"id": "tees", "labels": ["Tees"]},
        ]
    },
    "core_fields": {
        "brand": {
            "indexed": True,
            "sample_values": ["Joust", "Sprite", "Proteus"],
        }
    },
}


def test_resolve_catalog_block_semantic_shoes():
    blocked, reason = resolve_catalog_block(
        message="Show black shoes under $100",
        profile=APPAREL_GAZETTEER,
        coverage=CatalogCoverageSpec(
            in_catalog=False,
            missing_terms=["shoes"],
            confidence=0.92,
            source="llm",
        ),
    )
    assert blocked is True
    assert reason == "shoes"


def test_resolve_catalog_block_semantic_allows_jackets_with_size_price():
    blocked, reason = resolve_catalog_block(
        message="Show men's jackets in size L under $150",
        profile=APPAREL_GAZETTEER,
        coverage=CatalogCoverageSpec(in_catalog=True, confidence=0.9, source="llm"),
    )
    assert blocked is False
    assert reason is None


def test_classify_shoes_uses_semantic_coverage():
    sq = empty_structured_query(intent="catalog")
    sq.catalog_coverage = CatalogCoverageSpec(
        in_catalog=False,
        missing_terms=["shoes"],
        confidence=0.9,
        source="llm",
    )
    c = classify_response_subtype(
        "Cheap good quality shoes",
        structured_query=sq,
        profile=APPAREL_GAZETTEER,
    )
    assert c.response_subtype == "not_in_catalog"
    assert c.category_query == "shoes"


def test_classify_jackets_size_query_is_product_search():
    sq = empty_structured_query(intent="catalog")
    sq.catalog_coverage = CatalogCoverageSpec(in_catalog=True, confidence=0.9, source="llm")
    c = classify_response_subtype(
        "Show men's jackets in size L under $150",
        structured_query=sq,
        profile=APPAREL_GAZETTEER,
    )
    assert c.response_subtype == "product_search"
