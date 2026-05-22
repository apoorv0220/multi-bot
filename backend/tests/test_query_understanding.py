import asyncio
from types import SimpleNamespace

from retrieval.query_understanding import (
    merge_prepass_and_llm,
    run_query_understanding,
    should_skip_llm,
)
from retrieval.query_validator import validate_structured_query
from retrieval.rules_prepass import rules_prepass
from retrieval.structured_query import FacetSpec, StructuredQuery, empty_structured_query
from tests.test_structured_query import _bath_profile


def _llm_response(payload: dict):
    import json

    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def test_merge_prepass_and_llm_keeps_product_type_category_over_collection():
    prepass = empty_structured_query(intent="catalog")
    prepass.category.values = ["tops"]
    prepass.category.confidence = 0.89
    prepass.category.apply = "hint"
    llm = empty_structured_query(intent="catalog")
    llm.category.values = ["erin_recommends"]
    llm.category.confidence = 0.92
    merged = merge_prepass_and_llm(prepass, llm)
    assert merged.category.values == ["tops"]


def test_merge_prepass_and_llm_keeps_explicit_category():
    prepass = empty_structured_query(intent="catalog")
    prepass.category.values = ["basins"]
    prepass.category.confidence = 0.95
    prepass.category.apply = "filter"
    llm = empty_structured_query(intent="general")
    llm.category.values = ["widgets"]
    merged = merge_prepass_and_llm(prepass, llm)
    assert merged.category.values == ["basins"]
    assert merged.category.confidence == 0.95


def test_should_skip_llm_for_complete_prepass(monkeypatch):
    monkeypatch.setenv("QUERY_UNDERSTANDING_SKIP_LLM_WHEN_COMPLETE", "true")
    prepass = empty_structured_query(intent="catalog")
    prepass.category.values = ["basins"]
    prepass.facets["colour"] = FacetSpec(values=["black"], combine="OR")
    assert should_skip_llm(prepass, "matt black basins", mode="hybrid") is True


def test_facet_match_does_not_treat_size_s_as_substring_of_hoodies():
    profile = {
        "facets": {
            "color": {"sample_values": ["Red", "Blue"], "value_aliases": {}},
            "size": {"sample_values": ["S", "M", "L"], "value_aliases": {}},
        },
        "category_strategy": {
            "gazetteer": [
                {
                    "id": "hoodies_sweatshirts",
                    "labels": ["Hoodies & Sweatshirts"],
                    "aliases": {},
                }
            ]
        },
    }
    for message in ("red hoodies", "Do you have any hoodies"):
        sq = validate_structured_query(rules_prepass(message, profile=profile), profile=profile)
        assert "size" not in sq.facets, message
    red = validate_structured_query(rules_prepass("red hoodies", profile=profile), profile=profile)
    assert red.facets.get("color") is not None


def test_should_not_skip_llm_when_or_present():
    prepass = empty_structured_query(intent="catalog")
    prepass.category.values = ["basins"]
    assert should_skip_llm(prepass, "glossy or matt basins", mode="hybrid") is False


def test_run_query_understanding_llm_fallback(monkeypatch):
    profile = _bath_profile()
    monkeypatch.setenv("QUERY_UNDERSTANDING_MODE", "llm")

    def bad_llm(**_kwargs):
        raise RuntimeError("llm down")

    result = asyncio.run(
        run_query_understanding(
            "matt black basins",
            profile,
            None,
            llm_call=bad_llm,
        )
    )
    assert result.llm_fallback is True
    assert result.query.intent == "catalog"
    assert result.query.facets.get("colour") is not None


def test_run_query_understanding_merges_llm_facets(monkeypatch):
    profile = _bath_profile()
    profile["facets"]["material"] = {
        "sample_values": ["ceramic"],
        "value_aliases": {},
        "indexed": True,
        "coverage_pct": 40,
    }
    llm_payload = {
        "intent": "catalog",
        "free_text": "basins",
        "category": {"values": ["basins"], "confidence": 0.9},
        "facets": {"material": {"values": ["ceramic"], "combine": "AND"}},
        "price": {"min": None, "max": None},
        "stock_status": None,
        "session": {"inherit": True, "clear": {"facets": [], "category": False, "price": False, "stock_status": False}},
    }

    def ok_llm(**_kwargs):
        return _llm_response(llm_payload)

    monkeypatch.setenv("QUERY_UNDERSTANDING_MODE", "llm")
    result = asyncio.run(
        run_query_understanding(
            "ceramic basins",
            profile,
            None,
            llm_call=ok_llm,
        )
    )
    assert result.llm_used is True
    assert result.llm_fallback is False
    assert result.query.facets.get("material") is not None


def test_rules_within_facet_or_glossy_or_matt():
    profile = _bath_profile()
    profile["facets"]["finish"] = {
        "sample_values": ["glossy", "matt"],
        "value_aliases": {},
        "indexed": True,
        "coverage_pct": 50,
    }
    query = rules_prepass("glossy or matt black basins", profile=profile)
    finish = query.facets.get("finish")
    assert finish is not None
    assert len(finish.values) >= 2
    assert finish.combine == "OR"
