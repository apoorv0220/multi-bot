from __future__ import annotations

import os
from typing import Any

from retrieval.planner import RetrievalPlan
from retrieval.session_query import classify_merge_action, is_session_reset_turn
from retrieval.structured_query import StructuredQuery


def retrieval_debug_enabled() -> bool:
    return os.getenv("RETRIEVAL_DEBUG_QUERY", "false").strip().lower() in ("1", "true", "yes")


def retrieval_plan_to_dict(plan: RetrievalPlan) -> dict[str, Any]:
    return {
        "metadata_filters": plan.metadata_filters,
        "dense_query_text": plan.dense_query_text,
        "lexical_query_text": plan.lexical_query_text,
        "preferred_buckets": plan.preferred_buckets,
        "content_kind": plan.content_kind,
        "price_min": plan.price_min,
        "price_max": plan.price_max,
        "category_hint_terms": plan.category_hint_terms,
        "category_values": plan.category_values,
        "use_retrieval_hybrid": plan.use_retrieval_hybrid,
    }


def build_retrieval_trace(
    *,
    user_message: str,
    session_query: StructuredQuery,
    turn_after_qu: StructuredQuery,
    turn_after_validate: StructuredQuery,
    merged: StructuredQuery,
    plan: RetrievalPlan,
    conversation_summary: str | None = None,
    merge_action: str | None = None,
    vector_primary_source_type: str | None = None,
    enhanced_query: str | None = None,
    retrieval_tier: str | None = None,
    match_mode: str | None = None,
    dropped_filters: list[str] | None = None,
    hit_count: int | None = None,
    product_card_count: int | None = None,
) -> dict[str, Any]:
    action = merge_action or classify_merge_action(
        session_query, turn_after_validate, user_message=user_message
    )
    trace: dict[str, Any] = {
        "user_message": (user_message or "").strip(),
        "merge_action": action,
        "session_reset": is_session_reset_turn(user_message, turn_after_validate),
        "session_query": session_query.to_dict(),
        "turn_after_qu": turn_after_qu.to_dict(),
        "turn_after_validate": turn_after_validate.to_dict(),
        "merged": merged.to_dict(),
        "plan": retrieval_plan_to_dict(plan),
    }
    if conversation_summary:
        trace["conversation_summary"] = conversation_summary[:500]
    if vector_primary_source_type:
        trace["vector_primary_source_type"] = vector_primary_source_type
    if enhanced_query:
        trace["enhanced_query"] = enhanced_query
    if retrieval_tier is not None:
        trace["retrieval_tier"] = retrieval_tier
    if match_mode is not None:
        trace["match_mode"] = match_mode
    if dropped_filters is not None:
        trace["dropped_filters"] = dropped_filters
    if hit_count is not None:
        trace["hit_count"] = hit_count
    if product_card_count is not None:
        trace["product_card_count"] = product_card_count
    return trace
