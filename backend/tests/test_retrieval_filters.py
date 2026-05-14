from retrieval.filters import extract_retrieval_directives, update_session_state


def test_extract_retrieval_directives_merges_filters_and_detects_catalog_intent():
    directives = extract_retrieval_directives(
        "brand:Acme category:Widgets under 50 in stock color:black",
        {"active_filters": {"attributes": {"material": "steel"}}},
    )
    assert directives.intent == "catalog"
    assert directives.filters["brand"] == "Acme"
    assert directives.filters["categories"] == ["Widgets"]
    assert directives.filters["max_price"] == 50.0
    assert directives.filters["stock_status"] == "instock"
    assert directives.filters["attributes"] == {"material": "steel", "color": "black"}
    assert directives.preferred_buckets[0] == "catalog"


def test_update_session_state_tracks_recent_queries_and_results():
    directives = extract_retrieval_directives("shipping policy")
    state = update_session_state(
        session_state={},
        user_message="shipping policy",
        directives=directives,
        result_context=[{"title": "Shipping", "content_bucket": "support"}],
    )
    assert state["conversation_intent"] == "support"
    assert state["last_result_context"][0]["title"] == "Shipping"
    assert "shipping policy" in state["conversation_summary"]
