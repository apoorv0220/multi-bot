from types import SimpleNamespace

from main import _get_chat_session_state, _set_chat_session_state


def test_chat_session_state_roundtrip():
    session = SimpleNamespace(
        conversation_summary=None,
        active_filters_json=None,
        user_preferences_json=None,
        last_result_context_json=None,
        conversation_intent=None,
    )
    _set_chat_session_state(
        session,
        {
            "conversation_summary": "Intent=catalog; Recent requests=buy widget",
            "active_filters": {"brand": "Acme"},
            "user_preferences": {"currency": "USD"},
            "last_result_context": [{"title": "Widget"}],
            "conversation_intent": "catalog",
        },
    )
    state = _get_chat_session_state(session)
    assert state["conversation_summary"].startswith("Intent=catalog")
    assert state["active_filters"] == {"brand": "Acme"}
    assert state["user_preferences"] == {"currency": "USD"}
    assert state["last_result_context"] == [{"title": "Widget"}]
    assert state["conversation_intent"] == "catalog"
