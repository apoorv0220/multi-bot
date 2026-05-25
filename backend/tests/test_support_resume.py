from retrieval.session_query import merge_session_query, structured_query_to_session_state
from retrieval.structured_query import empty_structured_query
from retrieval.subtype_classifier import classify_response_subtype
from retrieval.chat_orchestrator import session_structured_query_for_writeback


def test_support_turn_preserves_catalog_session_on_writeback():
    catalog = empty_structured_query(intent="catalog")
    catalog.category.values = ["bags"]
    catalog.facets_raw = {}
    session_state = structured_query_to_session_state(
        structured_query=catalog,
        user_message="Show me red bags under $40",
        result_context=[],
    )
    support = empty_structured_query(intent="support")
    classification = classify_response_subtype(
        "What is your return policy?",
        structured_query=support,
        session_state=session_state,
    )
    assert classification.response_subtype == "support_faq"
    assert classification.preserve_catalog_session is True
    write_sq = session_structured_query_for_writeback(
        structured_query=support,
        session_state=session_state,
        classification=classification,
    )
    assert write_sq.category.values == ["bags"]


def test_resume_more_bags_routes_to_product_search():
    catalog = empty_structured_query(intent="catalog")
    catalog.category.values = ["bags"]
    session_state = structured_query_to_session_state(
        structured_query=catalog,
        user_message="Show me red bags under $40",
        result_context=[],
    )
    c = classify_response_subtype(
        "Okay, show me more of those bags",
        structured_query=empty_structured_query(intent="catalog"),
        session_state=session_state,
    )
    assert c.response_subtype == "product_search"
    assert c.preserve_catalog_session is True
