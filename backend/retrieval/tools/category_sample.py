from __future__ import annotations

import re
from typing import Any

from retrieval.tools.list_categories import (
    SKIP_COLLECTION_CATEGORY_IDS,
    find_category_in_profile,
    score_category_query_match,
)


_ALL_PRODUCTS = re.compile(
    r"\b(?:show\s+(?:me\s+)?(?:all|every)\s+products?|all\s+products?)\b",
    re.IGNORECASE,
)


def build_category_actions(
    *,
    category: dict[str, Any] | None,
    website_url: str | None,
    label_prefix: str = "View more",
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    site = (website_url or "").rstrip("/")
    if category and category.get("url"):
        actions.append(
            {
                "type": "link",
                "label": f"{label_prefix} {category.get('name')}",
                "url": category["url"],
            }
        )
    elif site:
        actions.append(
            {
                "type": "link",
                "label": "Browse all products on our website",
                "url": site,
            }
        )
    return actions


def resolve_plp_category(message: str, structured_query: Any, profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if _ALL_PRODUCTS.search(message or ""):
        return None

    lower = (message or "").lower()
    if re.search(r"\bmen'?s\b", lower):
        hit = find_category_in_profile("men", profile)
        if hit:
            return hit
    if re.search(r"\bwomen'?s\b", lower):
        hit = find_category_in_profile("women", profile)
        if hit:
            return hit

    best_hit: dict[str, Any] | None = None
    best_score = 0
    gazetteer = (profile.get("category_strategy") or {}).get("gazetteer") or [] if profile else []
    gazetteer_by_id = {str(entry.get("id") or "").lower(): entry for entry in gazetteer}

    for val in structured_query.category.values or []:
        raw = str(val).strip()
        if not raw or raw.lower() in SKIP_COLLECTION_CATEGORY_IDS:
            continue
        entry = gazetteer_by_id.get(raw.lower())
        score = score_category_query_match(raw, entry) if entry else 0
        hit = find_category_in_profile(raw, profile)
        if hit and score >= best_score:
            best_score = score
            best_hit = hit

    if best_hit:
        return best_hit

    if len((message or "").split()) <= 8:
        return find_category_in_profile(message, profile)
    return None
