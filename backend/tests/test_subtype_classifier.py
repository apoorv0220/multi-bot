from retrieval.rules_prepass import rules_prepass
from retrieval.structured_query import CatalogCoverageSpec, empty_structured_query
from retrieval.subtype_classifier import classify_response_subtype


def test_classify_list_categories():
    sq = empty_structured_query(intent="catalog")
    c = classify_response_subtype("What categories are available?", structured_query=sq)
    assert c.response_subtype == "list_categories"


def test_classify_not_in_catalog():
    profile = {
        "category_strategy": {
            "gazetteer": [{"id": "jackets", "labels": ["Jackets"]}],
        }
    }
    sq = empty_structured_query(intent="catalog")
    sq.catalog_coverage = CatalogCoverageSpec(
        in_catalog=False,
        missing_terms=["electronics"],
        confidence=0.9,
        source="llm",
    )
    c = classify_response_subtype(
        "Show products under electronics",
        structured_query=sq,
        profile=profile,
    )
    assert c.response_subtype == "not_in_catalog"


def test_classify_help_me_buy_is_not_support_when_shopping():
    sq = rules_prepass("Help me buy a travel bag for trekking", profile={})
    assert sq.intent == "catalog"


def test_classify_general_gibberish():
    sq = empty_structured_query(intent="general")
    c = classify_response_subtype("asdfghj", structured_query=sq)
    assert c.response_subtype == "general_chat"


def test_classify_sort_browse_newest():
    sq = empty_structured_query(intent="catalog")
    c = classify_response_subtype("Show me latest products", structured_query=sq)
    assert c.response_subtype == "sort_browse"
    assert c.sort == "newest"
