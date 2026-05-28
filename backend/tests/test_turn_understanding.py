"""Tests for dialogue.turn_understanding contract (Phase 0a)."""

from __future__ import annotations

import json

from dialogue.turn_understanding import (
    IntentCandidate,
    MergeAction,
    PolicyAction,
    TurnUnderstanding,
)


def test_turn_understanding_defaults():
    u = TurnUnderstanding()
    assert u.intent == ""
    assert u.entities == {}
    assert u.intent_confidence == 0.0
    assert u.intent_candidates == []
    assert u.policy_action is PolicyAction.PROCEED
    assert u.merge_action is MergeAction.INHERIT
    assert u.session_context == {}
    assert u.pending_clarification is None


def test_policy_action_members():
    assert {m.value for m in PolicyAction} == {
        "proceed",
        "clarify",
        "confirm",
        "reset",
    }


def test_merge_action_members():
    assert {m.value for m in MergeAction} == {
        "inherit",
        "replace",
        "append",
        "clear",
        "backtrack",
    }


def test_intent_candidate_to_dict():
    c = IntentCandidate(intent="new_search", score=0.91)
    assert c.to_dict() == {"intent": "new_search", "score": 0.91}


def test_to_debug_dict_round_trip_json():
    u = TurnUnderstanding(
        intent="variant_availability",
        entities={"color": "purple", "size": "s"},
        intent_confidence=0.88,
        intent_candidates=[
            IntentCandidate("variant_availability", 0.88),
            IntentCandidate("product_detail", 0.42),
        ],
        policy_action=PolicyAction.CLARIFY,
        merge_action=MergeAction.INHERIT,
        session_context={"structured_query": {"intent": "catalog"}},
        pending_clarification={"slot": "product_name"},
    )
    payload = u.to_debug_dict()
    assert payload["policy_action"] == "clarify"
    assert payload["merge_action"] == "inherit"
    assert payload["intent_candidates"][0]["intent"] == "variant_availability"
    assert payload["pending_clarification"] == {"slot": "product_name"}
    # Must be JSON-serializable for debug meta
    json.dumps(payload)
