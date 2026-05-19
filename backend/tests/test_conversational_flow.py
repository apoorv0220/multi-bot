from retrieval.profile import build_retrieval_profile
from retrieval.query_understanding import should_skip_llm
from retrieval.rules_prepass import rules_prepass
from retrieval.session_query import merge_session_query
from retrieval.query_validator import validate_structured_query
from sources.base import SourceRecord
from tests.test_facet_profile import _product


def _bathconnect_profile():
    records = [
        _product(
            entity_id="1",
            title="Chrome Tap",
            categories=["Taps"],
            attributes={"finish": ["chrome"], "colour": ["chrome"]},
        ),
        _product(
            entity_id="2",
            title="Chrome Shower",
            categories=["Showers"],
            attributes={"finish": ["chrome"]},
        ),
        SourceRecord(
            source_provider="woocommerce",
            content_kind="category",
            entity_id="10",
            title="Taps",
            metadata={"categories": ["Taps"]},
        ),
        SourceRecord(
            source_provider="woocommerce",
            content_kind="category",
            entity_id="11",
            title="Showers",
            metadata={"categories": ["Showers"]},
        ),
    ]
    return build_retrieval_profile(records, tenant_id="tenant-bathconnect")


def test_chrome_taps_boosts_product_category_over_finish_only():
    profile = _bathconnect_profile()
    query = rules_prepass("show me chrome taps", profile=profile)
    validated = validate_structured_query(query, profile=profile)
    category_blob = " ".join(validated.category.values).lower()
    assert "tap" in category_blob
    assert validated.facets.get("finish") or validated.facets.get("colour")


def test_chrome_taps_may_skip_llm_when_category_resolved(monkeypatch):
    monkeypatch.setenv("QUERY_UNDERSTANDING_SKIP_LLM_WHEN_COMPLETE", "true")
    profile = _bathconnect_profile()
    prepass = rules_prepass("show me chrome taps", profile=profile)
    assert any("tap" in v for v in prepass.category.values)
    assert should_skip_llm(prepass, "show me chrome taps", mode="hybrid", profile=profile) is True


def test_should_not_skip_llm_when_product_type_missing_from_prepass():
    profile = _bathconnect_profile()
    prepass = rules_prepass("show me chrome", profile=profile)
    prepass.category.values = []
    prepass.category.confidence = 0.0
    assert should_skip_llm(prepass, "show me chrome taps", mode="hybrid", profile=profile) is False


def test_under_50_follow_up_inherits_session_and_price():
    profile = _bathconnect_profile()
    first = validate_structured_query(
        rules_prepass("show me chrome taps", profile=profile),
        profile=profile,
    )
    second = validate_structured_query(
        rules_prepass("under 50", profile=profile, session_query=first),
        profile=profile,
    )
    merged = merge_session_query(first, second, user_message="under 50")
    assert merged.price.max == 50.0
    assert merged.facets


def test_profile_builds_value_aliases():
    profile = _bathconnect_profile()
    finish = profile["facets"].get("finish") or {}
    aliases = finish.get("value_aliases") or {}
    assert "matte" in aliases or "matt" in (finish.get("sample_values") or [])
    gazetteer = profile["category_strategy"]["gazetteer"]
    taps_entry = next((e for e in gazetteer if e.get("id") == "taps"), None)
    assert taps_entry is not None
    assert taps_entry.get("aliases")
