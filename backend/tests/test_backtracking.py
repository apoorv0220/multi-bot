from retrieval.session_query import (
    classify_merge_action,
    is_backtrack_turn,
    merge_session_query,
    update_filter_stack,
)
from retrieval.structured_query import FacetSpec, empty_structured_query


def test_backtrack_detected():
    assert is_backtrack_turn("go back to previous list")


def test_backtrack_restores_filter_stack_snapshot():
    prior = empty_structured_query(intent="catalog")
    prior.category.values = ["bags"]
    prior.facets["color"] = FacetSpec(values=["red"], combine="OR")

    session = prior.copy()
    session.facets["size"] = FacetSpec(values=["m"], combine="OR")

    merged = merge_session_query(
        session,
        empty_structured_query(intent="catalog"),
        user_message="go back",
        filter_stack=[prior.to_dict()],
    )
    assert classify_merge_action(session, empty_structured_query(), user_message="go back") == "backtrack"
    assert merged.facets.get("color")
    assert "size" not in merged.facets

    stack = update_filter_stack([prior.to_dict()], before=session, after=merged, merge_action="backtrack")
    assert stack == []


def test_soft_context_switch_keeps_price():
    session = empty_structured_query(intent="catalog")
    session.category.values = ["pants"]
    session.price.max = 50.0
    session.facets["gender"] = FacetSpec(values=["men"], combine="OR")

    turn = empty_structured_query(intent="catalog")
    turn.category.values = ["tank tops"]
    merged = merge_session_query(session, turn, user_message="nvm tank tops")
    assert merged.category.values == ["tank tops"]
    assert merged.price.max == 50.0
    assert merged.facets.get("gender")
