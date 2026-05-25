from __future__ import annotations

import re
from typing import Any

from retrieval.query_validator import _category_id_matches_token
from retrieval.rules_prepass import _normalize_label, term_present_as_word

SKIP_COLLECTION_CATEGORY_IDS = frozenset(
    {"default_category", "sale", "new", "erin_recommends", "root"}
)


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (label or "").strip().lower()).strip("_")


def score_category_query_match(query: str, entry: dict[str, Any]) -> int:
    """Score how well a short category token/phrase matches a gazetteer entry."""
    q = _normalize_label(query)
    if not q:
        return 0
    entry_id = str(entry.get("id") or "").strip().lower()
    if not entry_id or entry_id in SKIP_COLLECTION_CATEGORY_IDS:
        return 0

    if q == entry_id:
        return 100
    if _category_id_matches_token(entry_id, q):
        score = 85
    else:
        score = 0

    labels = list(entry.get("labels") or []) + list(entry.get("normalized") or [])
    aliases = entry.get("aliases") or {}
    if isinstance(aliases, dict):
        labels.extend(str(alias) for alias in aliases.keys())
    for label in labels:
        lab = _normalize_label(str(label))
        if not lab:
            continue
        if q == lab:
            return max(score, 95)
        if q.rstrip("s") == lab.rstrip("s"):
            score = max(score, 90)
        elif term_present_as_word(lab, q) or term_present_as_word(q, lab):
            score = max(score, 75)
    return score


def list_categories_from_profile(
    profile: dict[str, Any] | None,
    *,
    website_url: str | None = None,
) -> list[dict[str, Any]]:
    site = (website_url or "").rstrip("/")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in (profile.get("category_strategy") or {}).get("gazetteer") or []:
        cid = str(entry.get("id") or "").strip()
        if not cid or cid in seen:
            continue
        if cid.lower() in SKIP_COLLECTION_CATEGORY_IDS:
            continue
        seen.add(cid)
        labels = entry.get("labels") or []
        name = str(labels[0] if labels else cid).strip()
        url = str(entry.get("url") or "").strip()
        if not url and site:
            url = f"{site}/catalog/category/view/id/{cid}/"
        rows.append({"name": name, "url": url or None, "id": cid, "product_count": None})
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def find_category_in_profile(
    query: str,
    profile: dict[str, Any] | None,
    *,
    min_score: int = 70,
) -> dict[str, Any] | None:
    q = (query or "").strip()
    if not q or not profile:
        return None

    best_entry: dict[str, Any] | None = None
    best_score = 0
    for entry in (profile.get("category_strategy") or {}).get("gazetteer") or []:
        score = score_category_query_match(q, entry)
        if score > best_score:
            best_score = score
            best_entry = entry

    if not best_entry or best_score < min_score:
        return None

    cid = str(best_entry.get("id") or "")
    labels = best_entry.get("labels") or [cid]
    return {"id": cid, "name": str(labels[0]), "url": best_entry.get("url")}


def category_names_for_not_in_catalog(profile: dict[str, Any] | None, *, limit: int = 10) -> list[str]:
    return [r["name"] for r in list_categories_from_profile(profile)[:limit]]
