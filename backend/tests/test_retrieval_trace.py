from retrieval.planner import build_retrieval_plan
from retrieval.query_validator import validate_structured_query
from retrieval.rules_prepass import rules_prepass
from retrieval.session_query import classify_merge_action, merge_session_query
from retrieval.structured_query import FacetSpec
from retrieval.trace import build_retrieval_trace, retrieval_debug_enabled, retrieval_plan_to_dict
from retrieval.structured_query import FacetSpec, PriceSpec, StructuredQuery, empty_structured_query
from tests.test_structured_query import _bath_profile


def test_classify_merge_action_context_switch():
    session = empty_structured_query(intent="catalog")
    session.category.values = ["bathroom_taps"]
    turn = empty_structured_query(intent="catalog")
    turn.category.values = ["kitchen_basins"]
    assert (
        classify_merge_action(session, turn, user_message="show me kitchen basins instead")
        == "context_switch"
    )


def test_classify_merge_action_inherit():
    session = empty_structured_query(intent="catalog")
    session.facets["color"] = FacetSpec(values=["red"], combine="OR")
    turn = empty_structured_query(intent="catalog")
    turn.facets["size"] = FacetSpec(values=["l"], combine="OR")
    turn.session.inherit = True
    assert classify_merge_action(session, turn, user_message="size large") == "inherit"


def test_classify_merge_action_facet_replace():
    session = empty_structured_query(intent="catalog")
    session.facets["size"] = FacetSpec(values=["s"], combine="OR")
    turn = empty_structured_query(intent="catalog")
    turn.facets["size"] = FacetSpec(values=["l"], combine="OR")
    assert (
        classify_merge_action(session, turn, user_message="I need them in size Large")
        == "facet_replace"
    )


def test_build_retrieval_trace_contains_pipeline_stages():
    profile = _bath_profile()
    session = empty_structured_query(intent="catalog")
    session.facets["color"] = FacetSpec(values=["chrome"], combine="OR")
    turn = validate_structured_query(rules_prepass("under 50", profile=profile), profile=profile)
    merged = merge_session_query(session, turn, user_message="under 50")
    merged = validate_structured_query(merged, profile=profile)
    plan = build_retrieval_plan(merged, profile=profile, tenant_profile=profile)
    trace = build_retrieval_trace(
        user_message="under 50",
        session_query=session,
        turn_after_qu=turn,
        turn_after_validate=turn,
        merged=merged,
        plan=plan,
        merge_action="inherit",
        hit_count=3,
    )
    assert trace["merge_action"] == "inherit"
    assert trace["session_query"]["facets"]["color"]["values"] == ["chrome"]
    assert trace["turn_after_validate"]["price"]["max"] == 50.0
    assert trace["plan"]["dense_query_text"]
    assert trace["hit_count"] == 3
    assert "metadata_filters" in trace["plan"]


def test_retrieval_plan_to_dict_keys():
    query = empty_structured_query(intent="catalog")
    query.free_text = "red hoodies"
    plan = build_retrieval_plan(query, profile=_bath_profile(), tenant_profile=_bath_profile())
    keys = set(retrieval_plan_to_dict(plan).keys())
    assert {"dense_query_text", "metadata_filters", "content_kind"}.issubset(keys)
