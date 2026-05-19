from retrieval.planner import (
    _catalog_dense_query_text,
    _should_apply_product_type_category_filter,
    build_retrieval_plan,
)
from retrieval.rules_prepass import rules_prepass
from retrieval.session_query import merge_session_query
from retrieval.query_validator import validate_structured_query
from retrieval.structured_query import empty_structured_query
from sources.base import SourceRecord
from tests.test_facet_profile import _product


def _taps_profile():
    records = [
        _product(
            entity_id="1",
            title="Chrome Tap",
            categories=["Taps"],
            attributes={"finish": ["chrome"], "colour": ["chrome"]},
        ),
        SourceRecord(
            source_provider="woocommerce",
            content_kind="category",
            entity_id="10",
            title="Taps",
            metadata={"categories": ["Taps"]},
        ),
    ]
    from retrieval.profile import build_retrieval_profile

    return build_retrieval_profile(records, tenant_id="tenant-taps")


def test_catalog_dense_query_rebuilds_after_strip():
    profile = _taps_profile()
    query = validate_structured_query(
        rules_prepass("chrome taps under 100", profile=profile),
        profile=profile,
    )
    dense = _catalog_dense_query_text(query)
    assert "tap" in dense.lower()
    assert "chrome" in dense.lower()
    assert "100" in dense


def test_product_type_category_filter_on_combined_query():
    profile = _taps_profile()
    query = validate_structured_query(
        rules_prepass("chrome taps under 100", profile=profile),
        profile=profile,
    )
    assert query.category.apply == "filter"
    plan = build_retrieval_plan(query, profile=profile)
    assert plan.metadata_filters.get("categories")
    assert "tap" in plan.dense_query_text.lower()


def test_price_follow_up_dense_query_includes_session_context():
    profile = _taps_profile()
    first = validate_structured_query(
        rules_prepass("chrome taps", profile=profile),
        profile=profile,
    )
    second = validate_structured_query(
        rules_prepass("under 100", profile=profile, session_query=first),
        profile=profile,
    )
    merged = merge_session_query(first, second, user_message="under 100")
    plan = build_retrieval_plan(merged, profile=profile)
    assert plan.price_max == 100.0
    assert "tap" in plan.dense_query_text.lower()
    assert plan.metadata_filters.get("categories") or plan.category_hint_terms
