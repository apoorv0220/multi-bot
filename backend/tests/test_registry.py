"""Tests for dialogue.registry (Phase 0b)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dialogue.registry import ExecutionMode, load_registry

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "dialogue" / "data" / "intent_registry.yaml"


@pytest.fixture(scope="module")
def registry():
    return load_registry(REGISTRY_PATH)


def test_load_registry_without_error(registry):
    assert registry.version >= 1
    assert registry.schema == "semantic-nlu-dst"
    assert len(registry.intent_ids()) >= 30


def test_no_duplicate_intent_ids(registry):
    assert len(registry.intents) == len(registry.intent_ids())


def test_every_intent_has_valid_execution(registry):
    for intent_id, intent in registry.intents.items():
        assert intent.execution in ExecutionMode
        assert intent.tool
        assert intent.subtype
        assert intent.id == intent_id


def test_bitext_map_targets_resolve(registry):
    assert registry.validate() == []
    assert registry.map_bitext_label("availability") == "variant_availability"
    assert registry.map_bitext_label("track_order") == "order_tracking"
    assert registry.map_bitext_label("unknown_bitext_label") is None


def test_nlu_fallback_present(registry):
    fallback = registry.get_intent("nlu_fallback")
    assert fallback.execution is ExecutionMode.WORKING
    assert fallback.tool == "NoTool"


def test_variant_availability_required_slots(registry):
    intent = registry.get_intent("variant_availability")
    assert "product_name" in intent.required_slots


def test_bitext_path_in_raw_registry(registry):
    bitext = registry.raw.get("sources", {}).get("bitext", {})
    assert "data/geoip/bitext-retail-ecommerce-llm-chatbot-training-dataset.csv" in str(
        bitext.get("path", "")
    )
