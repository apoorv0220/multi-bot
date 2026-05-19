from __future__ import annotations

import re
from typing import Any

from retrieval.rules_prepass import CLEAR_ALL_PATTERN
from retrieval.structured_query import (
    CategorySpec,
    FacetSpec,
    PriceSpec,
    StructuredQuery,
    empty_structured_query,
)

SESSION_RESET_MESSAGE = "Filters cleared. What would you like to search for?"


def is_legacy_filters_blob(blob: dict[str, Any]) -> bool:
    if not blob:
        return False
    if "intent" in blob and "free_text" in blob:
        return False
    legacy_keys = {"brand", "categories", "attributes", "max_price", "min_price", "stock_status"}
    return any(key in blob for key in legacy_keys)


def migrate_legacy_filters(blob: dict[str, Any], intent: str | None = None) -> StructuredQuery:
    sq = empty_structured_query(intent=intent or "general")  # type: ignore[arg-type]
    if blob.get("categories"):
        sq.category.values = [str(v).lower() for v in blob["categories"]]
        sq.category.confidence = 0.9
    if blob.get("brand"):
        sq.facets["brand"] = FacetSpec(values=[str(blob["brand"])], combine="OR")
    attrs = blob.get("attributes") or {}
    if isinstance(attrs, dict):
        for key, val in attrs.items():
            sq.facets[str(key).lower()] = FacetSpec(values=[str(val).lower()], combine="OR")
    if blob.get("max_price") is not None:
        sq.price.max = float(blob["max_price"])
    if blob.get("min_price") is not None:
        sq.price.min = float(blob["min_price"])
    if blob.get("stock_status"):
        sq.stock_status = str(blob["stock_status"])
    return sq


def load_structured_query_from_session(state: dict[str, Any] | None) -> StructuredQuery:
    state = state or {}
    if state.get("structured_query"):
        return StructuredQuery.from_dict(state["structured_query"])
    blob = state.get("active_filters") or {}
    if isinstance(blob, dict) and blob:
        if is_legacy_filters_blob(blob):
            return migrate_legacy_filters(blob, state.get("conversation_intent"))
        return StructuredQuery.from_dict(blob)
    intent = state.get("conversation_intent") or "general"
    if intent not in ("catalog", "support", "general"):
        intent = "general"
    return empty_structured_query(intent=intent)  # type: ignore[arg-type]


def is_session_reset_turn(user_message: str, query: StructuredQuery) -> bool:
    if CLEAR_ALL_PATTERN.search((user_message or "").strip()):
        return True
    if query.intent != "general":
        return False
    clear = query.session.clear or {}
    return bool(clear.get("category") and clear.get("price"))


def is_category_refinement_turn(user_message: str, turn_query: StructuredQuery) -> bool:
    """Short category-style query (e.g. 'basins') replaces inherited facets/price."""
    tokens = [t for t in re.findall(r"[a-z0-9]+", (user_message or "").lower()) if t]
    if not tokens or len(tokens) > 3:
        return False
    if turn_query.price.min is not None or turn_query.price.max is not None:
        return False
    if any(key for key in turn_query.facets if key != "brand"):
        return False
    return bool(turn_query.category.values)


def merge_session_query(
    session_query: StructuredQuery,
    turn_query: StructuredQuery,
    *,
    user_message: str = "",
) -> StructuredQuery:
    merged = turn_query.copy()
    if not turn_query.session.inherit:
        return merged

    if is_category_refinement_turn(user_message, turn_query):
        merged.facets = {
            key: FacetSpec.from_dict(spec.to_dict()) for key, spec in turn_query.facets.items()
        }
        merged.price = PriceSpec.from_dict(turn_query.price.to_dict())
        if turn_query.category.values:
            merged.category = CategorySpec.from_dict(turn_query.category.to_dict())
        elif session_query.category.values:
            merged.category = CategorySpec()
        return merged

    clear = turn_query.session.clear or {}
    if clear.get("category"):
        merged.category = CategorySpec()
    elif session_query.category.values and not turn_query.category.values:
        merged.category = CategorySpec.from_dict(session_query.category.to_dict())

    if clear.get("price"):
        merged.price = PriceSpec()
    elif session_query.price.min is not None and merged.price.min is None:
        merged.price.min = session_query.price.min
    elif session_query.price.max is not None and merged.price.max is None:
        merged.price.max = session_query.price.max

    if clear.get("stock_status"):
        merged.stock_status = turn_query.stock_status
    elif merged.stock_status is None:
        merged.stock_status = session_query.stock_status

    cleared_facets = set(clear.get("facets") or [])
    for facet_id, spec in session_query.facets.items():
        if facet_id in cleared_facets:
            continue
        if facet_id in merged.facets:
            combined = list(dict.fromkeys(spec.values + merged.facets[facet_id].values))
            merged.facets[facet_id] = FacetSpec(values=combined, combine=merged.facets[facet_id].combine)
        else:
            merged.facets[facet_id] = FacetSpec.from_dict(spec.to_dict())

    if merged.intent == "general" and session_query.intent != "general":
        merged.intent = session_query.intent

    return merged


def structured_query_to_session_state(
    *,
    structured_query: StructuredQuery,
    user_message: str,
    result_context: list[dict[str, Any]],
    recent_requests: list[str] | None = None,
) -> dict[str, Any]:
    recent = list(recent_requests or [])
    recent.append(user_message.strip())
    recent = [item for item in recent if item][-3:]
    summary = (
        f"Intent={structured_query.intent}; Recent requests={' | '.join(recent)}"
        if recent
        else f"Intent={structured_query.intent}"
    )
    return {
        "conversation_summary": summary,
        "structured_query": structured_query.to_dict(),
        "active_filters": structured_query.to_dict(),
        "conversation_intent": structured_query.intent,
        "last_result_context": result_context[:5],
        "recent_requests": recent,
    }
