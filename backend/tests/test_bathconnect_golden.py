"""Golden-path NLU + retrieval policy tests using a slim BathConnect profile fixture.

Fixture source: tenant 6d46d90e-696d-4831-810f-bf124071b554 (exported from Postgres).
These tests catch regressions that unit tests with toy catalogs miss (e.g. shower
accessory at price cap ranking above taps).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from indexing.payloads import default_bucket_priority
from retrieval.catalog_cards import filter_results_for_response_sources
from retrieval.planner import build_retrieval_plan
from retrieval.post_filter import (
    filter_results_by_category_hints,
    filter_results_by_category_tier,
    filter_results_by_price,
    sort_results_by_category_tier,
)
from retrieval.query_understanding import run_query_understanding
from retrieval.rules_prepass import rules_prepass
from retrieval.session_query import is_session_reset_turn, merge_session_query
from retrieval.query_validator import validate_structured_query

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "bathconnect_profile_golden.json"


@pytest.fixture(scope="module")
def bathconnect_profile() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _validate(message: str, profile: dict, session_query=None):
    prepass = rules_prepass(message, profile=profile, session_query=session_query)
    return validate_structured_query(prepass, profile=profile)


def _hit(title: str, categories: list[str], price: float, *, entity_id: str):
    return SimpleNamespace(
        score=0.5,
        payload={
            "content_kind": "product",
            "entity_id": entity_id,
            "title": title,
            "categories": categories,
            "price": price,
            "attributes": {"finish": ["chrome"], "colour": ["chrome"]},
        },
    )


def test_chrome_taps_structured_query_has_taps_category(bathconnect_profile):
    query = _validate("chrome taps", bathconnect_profile)
    assert query.intent == "catalog"
    category_blob = " ".join(query.category.values).lower()
    assert "tap" in category_blob
    assert query.facets.get("finish") or query.facets.get("colour")


def test_chrome_taps_plan_applies_product_type_category_filter(bathconnect_profile):
    query = _validate("chrome taps", bathconnect_profile)
    plan = build_retrieval_plan(query, profile=bathconnect_profile)
    assert plan.metadata_filters.get("categories")
    assert "tap" in plan.dense_query_text.lower()
    assert "chrome" in plan.dense_query_text.lower()


def test_under_100_follow_up_keeps_taps_and_price(bathconnect_profile):
    first = _validate("chrome taps", bathconnect_profile)
    second = _validate("under 100", bathconnect_profile, session_query=first)
    merged = merge_session_query(first, second, user_message="under 100")
    assert merged.price.max == 100.0
    assert any("tap" in v.lower() for v in merged.category.values)
    plan = build_retrieval_plan(merged, profile=bathconnect_profile)
    assert plan.price_max == 100.0
    assert "tap" in plan.dense_query_text.lower()
    assert plan.metadata_filters.get("categories")


def test_chrome_taps_under_100_combined_query(bathconnect_profile):
    query = _validate("chrome taps under 100", bathconnect_profile)
    assert query.price.max == 100.0
    assert any("tap" in v.lower() for v in query.category.values)
    plan = build_retrieval_plan(query, profile=bathconnect_profile)
    assert plan.metadata_filters.get("categories")
    assert plan.price_max == 100.0
    dense = plan.dense_query_text.lower()
    assert "tap" in dense and "chrome" in dense and "100" in dense


def test_category_post_filter_drops_shower_enclosure_for_taps_hints(bathconnect_profile):
    """Regression: ZEBA Extension Profile (Shower Enclosures) at £100 must not beat taps."""
    query = _validate("chrome taps under 100", bathconnect_profile)
    plan = build_retrieval_plan(query, profile=bathconnect_profile)
    hits = [
        _hit(
            "ZEBA Extension Profile Chrome 30mm",
            ["Shower Enclosures"],
            100.0,
            entity_id="zeba",
        ),
        _hit(
            "CONTRACT Basin Mixer Chrome",
            ["Basin Taps & Mixers", "Taps"],
            72.0,
            entity_id="contract",
        ),
        _hit(
            "HARROW Cloakroom Basin Mixer Chrome",
            ["Cloakroom Basin Taps & Mixers", "Taps"],
            84.0,
            entity_id="harrow",
        ),
    ]
    priced = filter_results_by_price(hits, max_price=plan.price_max)
    assert len(priced) == 3
    if plan.category_hint_terms:
        filtered = filter_results_by_category_hints(
            priced,
            plan.category_hint_terms,
            require_match=not bool(plan.metadata_filters.get("categories")),
        )
        titles = [h.payload["title"] for h in filtered]
        assert "ZEBA" not in " ".join(titles)
        assert any("Basin Mixer" in t for t in titles)


def test_hybrid_mode_runs_llm_when_skip_disabled(bathconnect_profile, monkeypatch):
    monkeypatch.setenv("QUERY_UNDERSTANDING_MODE", "hybrid")
    monkeypatch.setenv("QUERY_UNDERSTANDING_SKIP_LLM_WHEN_COMPLETE", "false")

    called = {"n": 0}

    def fake_llm(**_kwargs):
        called["n"] += 1
        payload = {
            "intent": "catalog",
            "free_text": "chrome taps",
            "category": {"values": ["taps"], "confidence": 0.9},
            "facets": {"finish": {"values": ["chrome"], "combine": "OR"}},
            "price": {"min": None, "max": None},
            "stock_status": None,
            "session": {
                "inherit": True,
                "clear": {"facets": [], "category": False, "price": False, "stock_status": False},
            },
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    result = asyncio.run(
        run_query_understanding(
            "chrome taps",
            bathconnect_profile,
            None,
            llm_call=fake_llm,
        )
    )
    assert called["n"] == 1
    assert result.llm_used is True
    assert result.query.intent == "catalog"


def test_basins_natural_uses_category_filter(bathconnect_profile):
    query = _validate("basins", bathconnect_profile)
    assert query.intent == "catalog"
    assert query.category.apply == "filter"
    plan = build_retrieval_plan(query, profile=bathconnect_profile)
    assert plan.metadata_filters.get("categories")


def test_category_basins_explicit_filter(bathconnect_profile):
    query = _validate("category: basins", bathconnect_profile)
    assert query.category.apply == "filter"
    assert "basin" in " ".join(query.category.values).lower()
    plan = build_retrieval_plan(query, profile=bathconnect_profile)
    assert plan.metadata_filters.get("categories")


def test_basins_ranking_prefers_wash_basins_over_mixers(bathconnect_profile):
    query = _validate("basins", bathconnect_profile)
    plan = build_retrieval_plan(query, profile=bathconnect_profile)
    hits = [
        _hit(
            "Basin Mixer Chrome",
            ["Basin Taps & Mixers"],
            65.0,
            entity_id="mixer",
        ),
        _hit(
            "Wash Basin 500",
            ["Basins", "Countertop Basins"],
            40.0,
            entity_id="wash",
        ),
    ]
    ranked = sort_results_by_category_tier(hits, plan.category_hint_terms)
    assert ranked[0].payload["entity_id"] == "wash"
    filtered = filter_results_by_category_tier(ranked, plan.category_hint_terms)
    assert all("mixer" not in h.payload["entity_id"] for h in filtered)


def test_basins_and_category_basins_top3_overlap(bathconnect_profile):
    natural = _validate("basins", bathconnect_profile)
    explicit = _validate("category: basins", bathconnect_profile)
    plan_nat = build_retrieval_plan(natural, profile=bathconnect_profile)
    plan_exp = build_retrieval_plan(explicit, profile=bathconnect_profile)
    hits = [
        _hit("Wash A", ["Basins"], 50.0, entity_id="a"),
        _hit("Wash B", ["Countertop Basins", "Basins"], 60.0, entity_id="b"),
        _hit("Mixer", ["Basin Taps & Mixers"], 70.0, entity_id="c"),
        _hit("Wash C", ["Basins"], 45.0, entity_id="d"),
    ]
    nat_ranked = sort_results_by_category_tier(hits, plan_nat.category_hint_terms)[:3]
    exp_ranked = sort_results_by_category_tier(hits, plan_exp.category_hint_terms)[:3]
    nat_ids = {h.payload["entity_id"] for h in nat_ranked}
    exp_ids = {h.payload["entity_id"] for h in exp_ranked}
    assert len(nat_ids & exp_ids) >= 2


def test_support_intent_excludes_catalog_from_sources(bathconnect_profile):
    query = _validate("shipping policy", bathconnect_profile)
    assert query.intent == "support"
    assert "catalog" not in default_bucket_priority("support")
    hits = [
        _hit("SKU", ["Taps"], 10.0, entity_id="sku"),
        SimpleNamespace(
            score=0.6,
            payload={
                "content_kind": "policy",
                "entity_id": "ship",
                "title": "Shipping",
                "categories": [],
                "url": "https://example.com/shipping-policy/",
            },
        ),
    ]
    filtered = filter_results_for_response_sources(hits, query.intent)
    assert all((h.payload or {}).get("content_kind") != "product" for h in filtered)


def test_start_over_is_reset_turn(bathconnect_profile):
    prepass = rules_prepass("start over", profile=bathconnect_profile)
    query = validate_structured_query(prepass, profile=bathconnect_profile)
    merged = merge_session_query(
        _validate("chrome taps", bathconnect_profile),
        query,
        user_message="start over",
    )
    assert is_session_reset_turn("start over", merged)
