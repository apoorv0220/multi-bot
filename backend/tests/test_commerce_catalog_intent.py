from retrieval.chat_orchestrator import ensure_commerce_catalog_intent
from retrieval.structured_query import empty_structured_query
from retrieval.subtype_classifier import SubtypeClassification


def test_sort_browse_forces_catalog_intent():
    sq = empty_structured_query(intent="general")
    c = SubtypeClassification(response_subtype="sort_browse", sort="trending")
    updated = ensure_commerce_catalog_intent(sq, c)
    assert updated.intent == "catalog"
    assert updated.sort == "trending"
