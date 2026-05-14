from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from indexing.payloads import default_bucket_priority, infer_intent_from_query


@dataclass
class RetrievalDirectives:
    intent: str
    preferred_buckets: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    session_state: dict[str, Any] = field(default_factory=dict)


ATTRIBUTE_PATTERN = re.compile(
    r"\b(?P<key>color|material|size|brand|category)\s*[:=]\s*(?P<value>.+?)"
    r"(?=\s+\b(?:color|material|size|brand|category)\s*[:=]"
    r"|\s+\b(?:under|below|max|over|above|min)\s+\$?\d+(?:\.\d+)?"
    r"|\s+\b(?:in stock|out of stock)\b|$)",
    re.IGNORECASE,
)
UNDER_PRICE_PATTERN = re.compile(r"\b(?:under|below|max)\s+\$?(\d+(?:\.\d+)?)", re.IGNORECASE)
OVER_PRICE_PATTERN = re.compile(r"\b(?:over|above|min)\s+\$?(\d+(?:\.\d+)?)", re.IGNORECASE)


def _session_defaults(session_state: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(session_state or {})
    base.setdefault("conversation_summary", "")
    base.setdefault("active_filters", {})
    base.setdefault("user_preferences", {})
    base.setdefault("last_result_context", [])
    base.setdefault("conversation_intent", "general")
    return base


def _merge_filter_dicts(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if value in (None, "", [], {}):
            continue
        merged[key] = value
    return merged


def extract_retrieval_directives(query: str, session_state: dict[str, Any] | None = None) -> RetrievalDirectives:
    state = _session_defaults(session_state)
    filters = dict(state.get("active_filters") or {})
    extracted: dict[str, Any] = {}
    if "in stock" in (query or "").lower():
        extracted["stock_status"] = "instock"
    if "out of stock" in (query or "").lower():
        extracted["stock_status"] = "outofstock"
    under = UNDER_PRICE_PATTERN.search(query or "")
    if under:
        extracted["max_price"] = float(under.group(1))
    over = OVER_PRICE_PATTERN.search(query or "")
    if over:
        extracted["min_price"] = float(over.group(1))
    for match in ATTRIBUTE_PATTERN.finditer(query or ""):
        normalized_key = match.group("key").lower().strip()
        normalized_value = match.group("value").strip()
        if normalized_key == "category":
            extracted["categories"] = [normalized_value]
        elif normalized_key == "brand":
            extracted["brand"] = normalized_value
        else:
            attrs = dict(filters.get("attributes") or {})
            attrs[normalized_key] = normalized_value
            extracted["attributes"] = attrs
    merged_filters = _merge_filter_dicts(filters, extracted)
    intent = infer_intent_from_query(query or "")
    if any(word in (query or "").lower() for word in ("price", "stock", "buy", "product", "category", "brand:")):
        intent = "catalog"
    preferred_buckets = default_bucket_priority(intent)
    state["active_filters"] = merged_filters
    state["conversation_intent"] = intent
    return RetrievalDirectives(
        intent=intent,
        preferred_buckets=preferred_buckets,
        filters=merged_filters,
        session_state=state,
    )


def update_session_state(
    *,
    session_state: dict[str, Any] | None,
    user_message: str,
    directives: RetrievalDirectives,
    result_context: list[dict[str, Any]],
) -> dict[str, Any]:
    state = _session_defaults(session_state)
    state["active_filters"] = directives.filters
    state["conversation_intent"] = directives.intent
    state["last_result_context"] = result_context[:5]
    recent_requests = list(state.get("recent_requests") or [])
    recent_requests.append(user_message.strip())
    recent_requests = [item for item in recent_requests if item][-3:]
    state["recent_requests"] = recent_requests
    state["conversation_summary"] = (
        f"Intent={directives.intent}; Recent requests={' | '.join(recent_requests)}"
        if recent_requests
        else f"Intent={directives.intent}"
    )
    return state
