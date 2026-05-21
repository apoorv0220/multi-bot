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

_AFFIRMATION_PATTERN = re.compile(
    r"^\s*(?:yes|yeah|yep|sure|ok|okay|those|these|same|that|them|the same|"
    r"cheaper|less expensive|more expensive|go ahead)\s*\.?\s*$",
    re.IGNORECASE,
)
_PREFERENCE_PATTERN = re.compile(
    r"\b(?:i prefer|i usually|i always|always want|my preference|preferably)\b",
    re.IGNORECASE,
)
_PRICE_ONLY_PATTERN = re.compile(
    r"^\s*(?:under|below|over|above|max|min)?\s*(?:£|\$|€)?\s*\d+(?:\.\d+)?\s*$",
    re.IGNORECASE,
)


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


def is_affirmation_follow_up(user_message: str) -> bool:
    return bool(_AFFIRMATION_PATTERN.match((user_message or "").strip()))


def is_price_only_follow_up(user_message: str, turn_query: StructuredQuery) -> bool:
    if turn_query.facets or turn_query.category.values:
        return False
    if turn_query.price.min is None and turn_query.price.max is None:
        return False
    return bool(_PRICE_ONLY_PATTERN.match((user_message or "").strip()))


def is_preference_turn(user_message: str) -> bool:
    return bool(_PREFERENCE_PATTERN.search((user_message or "").strip()))


def _normalize_category_token(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _category_sets_overlap(session_values: list[str], turn_values: list[str]) -> bool:
    if not session_values or not turn_values:
        return True
    session_norm = {_normalize_category_token(v) for v in session_values if v}
    turn_norm = {_normalize_category_token(v) for v in turn_values if v}
    for turn_val in turn_norm:
        for session_val in session_norm:
            if turn_val == session_val:
                return True
            if turn_val in session_val or session_val in turn_val:
                return True
            turn_stem = turn_val.rstrip("s")
            session_stem = session_val.rstrip("s")
            if turn_stem and session_stem and turn_stem == session_stem:
                return True
    return False


def is_context_switch_turn(
    session_query: StructuredQuery,
    turn_query: StructuredQuery,
    *,
    user_message: str = "",
) -> bool:
    """New product context (e.g. bathroom taps -> kitchen basins) clears stale filters."""
    if not turn_query.category.values or not session_query.category.values:
        return False
    if is_category_refinement_turn(user_message, turn_query):
        return False
    if is_price_only_follow_up(user_message, turn_query):
        return False
    if is_affirmation_follow_up(user_message):
        return False
    return not _category_sets_overlap(session_query.category.values, turn_query.category.values)


def _turn_explicitly_set_facet(turn_query: StructuredQuery, facet_id: str) -> bool:
    spec = turn_query.facets.get(facet_id)
    return bool(spec and spec.values)


def _facet_replace_turn(session_query: StructuredQuery, turn_query: StructuredQuery) -> bool:
    """True when this turn sets facet value(s) that should replace session slots, not union."""
    return any(
        _turn_explicitly_set_facet(turn_query, facet_id) and facet_id in session_query.facets
        for facet_id in turn_query.facets
    )


def classify_merge_action(
    session_query: StructuredQuery,
    turn_query: StructuredQuery,
    *,
    user_message: str = "",
) -> str:
    """Label how this turn combined session state with the validated turn query."""
    if is_context_switch_turn(session_query, turn_query, user_message=user_message):
        return "context_switch"
    if is_affirmation_follow_up(user_message):
        return "affirmation"
    if not turn_query.session.inherit:
        return "no_inherit"
    if is_category_refinement_turn(user_message, turn_query):
        return "category_refinement"
    if is_price_only_follow_up(user_message, turn_query):
        return "price_only_inherit"
    if _facet_replace_turn(session_query, turn_query):
        return "facet_replace"
    return "inherit"


def merge_session_query(
    session_query: StructuredQuery,
    turn_query: StructuredQuery,
    *,
    user_message: str = "",
) -> StructuredQuery:
    if is_context_switch_turn(session_query, turn_query, user_message=user_message):
        switched = turn_query.copy()
        switched.session.inherit = False
        return switched

    if is_affirmation_follow_up(user_message):
        merged = session_query.copy()
        if turn_query.price.min is not None:
            merged.price.min = turn_query.price.min
        if turn_query.price.max is not None:
            merged.price.max = turn_query.price.max
        if turn_query.stock_status:
            merged.stock_status = turn_query.stock_status
        if turn_query.intent in ("catalog", "support", "general"):
            merged.intent = turn_query.intent
        return merged

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
            if _turn_explicitly_set_facet(turn_query, facet_id):
                continue
            combined = list(dict.fromkeys(spec.values + merged.facets[facet_id].values))
            merged.facets[facet_id] = FacetSpec(values=combined, combine=merged.facets[facet_id].combine)
        else:
            merged.facets[facet_id] = FacetSpec.from_dict(spec.to_dict())

    if merged.intent == "general" and session_query.intent != "general":
        merged.intent = session_query.intent

    if is_price_only_follow_up(user_message, turn_query) and session_query.retrieval_rewrite.strip():
        merged.retrieval_rewrite = session_query.retrieval_rewrite.strip()

    return merged


def _facet_summary(facets: dict[str, FacetSpec]) -> str:
    parts: list[str] = []
    for facet_id in sorted(facets.keys()):
        spec = facets[facet_id]
        if not spec.values:
            continue
        vals = ", ".join(str(v) for v in spec.values[:4])
        parts.append(f"{facet_id}={vals}")
    return "; ".join(parts)


def _build_conversation_summary(
    structured_query: StructuredQuery,
    *,
    recent_requests: list[str],
) -> str:
    chunks: list[str] = [f"Intent={structured_query.intent}"]
    if structured_query.category.values:
        cats = ", ".join(structured_query.category.values[:4])
        chunks.append(f"category={cats}")
    facet_blob = _facet_summary(structured_query.facets)
    if facet_blob:
        chunks.append(facet_blob)
    if structured_query.price.max is not None:
        chunks.append(f"price_max={structured_query.price.max:g}")
    if structured_query.price.min is not None:
        chunks.append(f"price_min={structured_query.price.min:g}")
    if structured_query.retrieval_rewrite.strip():
        chunks.append(f"search={structured_query.retrieval_rewrite.strip()[:120]}")
    if recent_requests:
        chunks.append(f"Recent={' | '.join(recent_requests[-3:])}")
    return "; ".join(chunks)


def _merge_user_preferences(
    existing: dict[str, Any],
    structured_query: StructuredQuery,
) -> dict[str, Any]:
    prefs = dict(existing or {})
    facet_prefs = dict(prefs.get("facets") or {})
    for facet_id, spec in structured_query.facets.items():
        if not spec.values:
            continue
        facet_prefs[str(facet_id)] = list(spec.values)
    if facet_prefs:
        prefs["facets"] = facet_prefs
    return prefs


def structured_query_to_session_state(
    *,
    structured_query: StructuredQuery,
    user_message: str,
    result_context: list[dict[str, Any]],
    recent_requests: list[str] | None = None,
    user_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recent = list(recent_requests or [])
    recent.append(user_message.strip())
    recent = [item for item in recent if item][-3:]

    prefs = dict(user_preferences or {})
    if is_preference_turn(user_message):
        prefs = _merge_user_preferences(prefs, structured_query)

    summary = _build_conversation_summary(structured_query, recent_requests=recent)
    return {
        "conversation_summary": summary,
        "structured_query": structured_query.to_dict(),
        "active_filters": structured_query.to_dict(),
        "conversation_intent": structured_query.intent,
        "last_result_context": result_context[:5],
        "recent_requests": recent,
        "user_preferences": prefs,
    }
