from retrieval.planner import build_retrieval_plan
from retrieval.profile import apply_retrieval_profile_to_tenant, build_retrieval_profile, merge_gazetteer_match_flags
from retrieval.query_validator import validate_structured_query
from retrieval.rules_prepass import rules_prepass
from sources.base import SourceRecord
from tests.test_facet_profile import _product


def _minimal_profile_with_gazetteer():
    records = [
        _product(entity_id="1", title="Basin", categories=["Basins"], attributes={"colour": ["white"]}),
        SourceRecord(
            source_provider="woocommerce",
            content_kind="category",
            entity_id="10",
            title="Basins",
            metadata={"categories": ["Basins"]},
        ),
    ]
    return build_retrieval_profile(records, tenant_id="tenant-merge")


def test_merge_gazetteer_match_flags_preserves_hard_filter():
    old = _minimal_profile_with_gazetteer()
    for entry in old["category_strategy"]["gazetteer"]:
        if entry["id"] == "basins":
            entry["hard_filter"] = True
            entry["demote_accessory_substrings"] = True
            entry["fixture_stem"] = "basin"
    new = build_retrieval_profile(
        [
            _product(entity_id="2", title="Tap", categories=["Taps"], attributes={}),
            SourceRecord(
                source_provider="woocommerce",
                content_kind="category",
                entity_id="11",
                title="Taps",
                metadata={"categories": ["Taps"]},
            ),
        ],
        tenant_id="tenant-merge",
    )
    merged = merge_gazetteer_match_flags(old, new)
    basins = next((e for e in merged["category_strategy"]["gazetteer"] if e["id"] == "basins"), None)
    assert basins is None
    taps = next((e for e in merged["category_strategy"]["gazetteer"] if e["id"] == "taps"), None)
    assert taps is not None
    assert "hard_filter" not in taps


def test_merge_restores_flags_for_same_id_after_reindex():
    old = _minimal_profile_with_gazetteer()
    for entry in old["category_strategy"]["gazetteer"]:
        if entry["id"] == "basins":
            entry["hard_filter"] = True
    new = _minimal_profile_with_gazetteer()
    merged = merge_gazetteer_match_flags(old, new)
    basins = next(e for e in merged["category_strategy"]["gazetteer"] if e["id"] == "basins")
    assert basins.get("hard_filter") is True


class _FakeTenant:
    retrieval_profile_json = None
    retrieval_profile_version = 0


def test_apply_retrieval_profile_merges_flags():
    tenant = _FakeTenant()
    old = _minimal_profile_with_gazetteer()
    for entry in old["category_strategy"]["gazetteer"]:
        if entry["id"] == "basins":
            entry["hard_filter"] = True
    tenant.retrieval_profile_json = old
    new = _minimal_profile_with_gazetteer()
    new["profile_version"] = 2
    apply_retrieval_profile_to_tenant(tenant, new)
    basins = next(e for e in tenant.retrieval_profile_json["category_strategy"]["gazetteer"] if e["id"] == "basins")
    assert basins.get("hard_filter") is True
    assert tenant.retrieval_profile_version == 2


def test_hard_filter_plan_after_profile_flag():
    profile = _minimal_profile_with_gazetteer()
    for entry in profile["category_strategy"]["gazetteer"]:
        if entry["id"] == "basins":
            entry["hard_filter"] = True
    query = validate_structured_query(rules_prepass("show me basins", profile=profile), profile=profile)
    plan = build_retrieval_plan(query, profile=profile)
    assert plan.metadata_filters.get("categories")
