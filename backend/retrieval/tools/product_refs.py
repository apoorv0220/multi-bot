from __future__ import annotations

import re
from typing import Any


_PRODUCT_DETAIL_SIGNALS = re.compile(
    r"\b(?:"
    r"more\s+(?:info|information|details?|description)|"
    r"(?:provide|give|show|tell).{0,40}(?:description|details?)|"
    r"description\s+for\s+(?:the\s+)?(?:product|item)|"
    r"product\s+details?|"
    r"product:\s*\S|"
    r"tell\s+me\s+(?:more\s+)?about|"
    r"what\s+is\s+the\s+price\s+of|"
    r"specifications?|"
    r"is\s+(?:the\s+)?\w.+\s+(?:available|in\s+stock)"
    r")\b",
    re.IGNORECASE,
)


def _clean_product_title(title: str) -> str:
    cleaned = (title or "").strip()
    cleaned = re.sub(r"^product:\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" .")


def extract_product_title_from_message(message: str) -> str | None:
    patterns = [
        r"(?:more\s+)?(?:description|details?)\s+for\s+(?:the\s+)?(?:product:?\s*)(.+?)(?:\?|$)",
        r"(?:product\s+)?details?\s+(?:for|on)\s+(?:the\s+)?(.+?)(?:\?|$)",
        r"(?:tell\s+me\s+(?:more\s+)?about|description\s+for)\s+(?:the\s+)?(.+?)(?:\?|$)",
        r"(?:for|about|product:)\s+(.+?)(?:\?|$)",
        r"(?:what\s+is\s+the\s+price\s+of)\s+(?:the\s+)?(.+?)(?:\?|$)",
        r"(?:what are the )?specifications? (?:of|for) (?:the )?(.+?)(?:\?|$)",
        r"(?:show\s+product\s+details?\s+(?:for|on))\s+(?:the\s+)?(.+?)(?:\?|$)",
        r"(?:is\s+(?:the\s+)?(.+?)\s+(?:available|in\s+stock))\??\s*$",
        r"product:\s*(.+?)(?:\?|$)",
    ]
    for pat in patterns:
        match = re.search(pat, message, re.IGNORECASE)
        if match:
            title = _clean_product_title(match.group(1))
            if title and len(title) >= 2:
                return title
    return None


def is_product_detail_message(message: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    if _PRODUCT_DETAIL_SIGNALS.search(msg):
        return True
    if extract_product_title_from_message(msg) and re.search(r"\bproduct\b", msg, re.IGNORECASE):
        return True
    return False


def resolve_product_ref(
    message: str,
    session_state: dict[str, Any] | None,
) -> dict[str, Any] | None:
    session_state = session_state or {}
    lower = (message or "").lower()
    if re.search(r"\b(?:this|that)\s+(?:product|item)\b", lower):
        refs = session_state.get("last_product_refs") or []
        if refs:
            return refs[0]
    title = extract_product_title_from_message(message)
    if title:
        return {"title": title}
    refs = session_state.get("last_product_refs") or []
    if len(refs) == 1:
        return refs[0]
    return None


def payload_to_product_ref(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": payload.get("title"),
        "url": payload.get("url"),
        "entity_id": payload.get("entity_id"),
        "sku": (payload.get("attributes") or {}).get("sku"),
    }


def find_product_in_results(
    ref: dict[str, Any],
    results: list[Any],
) -> dict[str, Any] | None:
    title = str(ref.get("title") or "").strip().lower()
    url = str(ref.get("url") or "").strip().lower()
    entity = str(ref.get("entity_id") or "").strip()
    title_tokens = [t for t in re.split(r"\W+", title) if len(t) > 2]
    best_payload: dict[str, Any] | None = None
    best_score = 0
    for result in results:
        payload = getattr(result, "payload", None) or {}
        if entity and str(payload.get("entity_id") or "") == entity:
            return payload
        if url and str(payload.get("url") or "").strip().lower() == url:
            return payload
        pt = str(payload.get("title") or "").strip().lower()
        if title and pt == title:
            return payload
        if title and title in pt:
            # Prefer the closest title length when one title contains another.
            score = 100 - abs(len(pt) - len(title))
            if score > best_score:
                best_score = score
                best_payload = payload
            continue
        if title_tokens:
            score = sum(1 for token in title_tokens if token in pt)
            needed = max(1, min(len(title_tokens), 2))
            if score > best_score and score >= needed:
                best_score = score
                best_payload = payload
    return best_payload
