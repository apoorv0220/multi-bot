from __future__ import annotations

import os
from typing import Any

from retrieval.rules_prepass import term_present_as_word
from retrieval.structured_query import StructuredQuery

# Per gazetteer entry (retrieval profile):
#   hard_filter: bool — Qdrant categories must-match when this category is in the query
#   demote_accessory_substrings: bool — drop substring-only category hits (e.g. basin taps)
#   fixture_stem: str — stem for exact fixture label check (default: entry id without 's')
#   accessory_keywords: list[str] — substrings that indicate accessory branches when demoting


def category_hard_filter_enabled() -> bool:
    raw = os.getenv(
        "RETRIEVAL_CATEGORY_HARD_FILTER_ENABLED",
        os.getenv("RETRIEVAL_CATEGORY_FILTER_ON_PRODUCT_TYPE", "true"),
    )
    return str(raw).strip().lower() in ("1", "true", "yes")


def _gazetteer_entries(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not profile:
        return []
    return list((profile.get("category_strategy") or {}).get("gazetteer") or [])


def _entry_terms(entry: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    entry_id = str(entry.get("id") or "").strip().lower()
    if entry_id:
        terms.add(entry_id)
    for label in (entry.get("labels") or []) + (entry.get("normalized") or []):
        norm = str(label).strip().lower()
        if norm:
            terms.add(norm)
    aliases = entry.get("aliases") or {}
    if isinstance(aliases, dict):
        for alias, canonical in aliases.items():
            for val in (alias, canonical):
                norm = str(val).strip().lower()
                if norm:
                    terms.add(norm)
    return terms


def _value_matches_entry(value: str, entry: dict[str, Any]) -> bool:
    v = str(value).strip().lower()
    if not v:
        return False
    terms = _entry_terms(entry)
    if v in terms:
        return True
    return any(v in t or t in v for t in terms if len(t) >= 3)


def resolve_entries_for_values(values: list[str], profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not values or not profile:
        return []
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in _gazetteer_entries(profile):
        entry_id = str(entry.get("id") or "")
        if entry_id in seen:
            continue
        if any(_value_matches_entry(val, entry) for val in values):
            matched.append(entry)
            seen.add(entry_id)
    return matched


def has_hard_filter_category(values: list[str], profile: dict[str, Any] | None) -> bool:
    return any(entry.get("hard_filter") for entry in resolve_entries_for_values(values, profile))


def _category_confidence_threshold(profile: dict[str, Any] | None) -> float:
    if profile:
        try:
            return float(
                (profile.get("category_strategy") or {}).get("confidence_threshold")
                or os.getenv("RETRIEVAL_CATEGORY_CONFIDENCE_THRESHOLD", "0.75")
            )
        except (TypeError, ValueError):
            pass
    try:
        return float(os.getenv("RETRIEVAL_CATEGORY_CONFIDENCE_THRESHOLD", "0.75"))
    except ValueError:
        return 0.75


def should_apply_hard_category_filter(query: StructuredQuery, profile: dict[str, Any] | None) -> bool:
    if not category_hard_filter_enabled():
        return False
    if query.category.apply == "filter":
        return False
    if not query.category.values:
        return False
    if query.category.confidence < _category_confidence_threshold(profile):
        return False
    return has_hard_filter_category(query.category.values, profile)


def resolve_entries_for_hint_terms(hint_terms: list[str], profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not hint_terms or not profile:
        return []
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    tokens = {str(t).strip().lower() for t in hint_terms if str(t).strip()}
    for entry in _gazetteer_entries(profile):
        entry_id = str(entry.get("id") or "")
        if entry_id in seen:
            continue
        terms = _entry_terms(entry)
        if tokens & terms or any(t in term or term in t for t in tokens for term in terms if len(term) >= 3):
            matched.append(entry)
            seen.add(entry_id)
    return matched


def demote_accessory_config(hint_terms: list[str], profile: dict[str, Any] | None) -> dict[str, Any] | None:
    for entry in resolve_entries_for_hint_terms(hint_terms, profile):
        if not entry.get("demote_accessory_substrings"):
            continue
        entry_id = str(entry.get("id") or "").strip().lower()
        fixture_stem = str(entry.get("fixture_stem") or entry_id.rstrip("s") or "").strip().lower()
        keywords = entry.get("accessory_keywords") or ["tap", "mixer"]
        if not fixture_stem:
            continue
        return {
            "fixture_stem": fixture_stem,
            "accessory_keywords": [str(k).strip().lower() for k in keywords if str(k).strip()],
        }
    return None


def hard_filter_terms_in_message(message: str, profile: dict[str, Any] | None) -> list[str]:
    """Gazetteer category ids/terms mentioned in message with hard_filter set."""
    if not profile:
        return []
    q_norm = " ".join((message or "").lower().split())
    hits: list[str] = []
    for entry in _gazetteer_entries(profile):
        if not entry.get("hard_filter"):
            continue
        entry_id = str(entry.get("id") or "").strip().lower()
        for term in _entry_terms(entry):
            if len(term) < 3:
                continue
            if term in q_norm.split() or term_present_as_word(term, message):
                if entry_id and entry_id not in hits:
                    hits.append(entry_id)
                break
    return hits


def prepass_missing_hard_filter_category(
    message: str,
    prepass: StructuredQuery,
    profile: dict[str, Any] | None,
) -> bool:
    """True when user mentioned a hard_filter category not captured in prepass."""
    if not profile:
        return False
    mentioned = hard_filter_terms_in_message(message, profile)
    if not mentioned:
        return False
    category_blob = " ".join(str(v).strip().lower() for v in prepass.category.values)
    for term in mentioned:
        stem = term.rstrip("s")
        if term in category_blob or stem in category_blob:
            continue
        return True
    return False


def hard_filter_category_terms_in_message(message: str, profile: dict[str, Any] | None) -> list[str]:
    """Category ids from gazetteer (hard_filter entries only) found in message."""
    if not profile:
        return []
    q_tokens = set((message or "").lower().split())
    q_norm = " ".join((message or "").lower().split())
    hits: list[str] = []
    for entry in _gazetteer_entries(profile):
        if not entry.get("hard_filter"):
            continue
        cat_id = str(entry.get("id") or "").strip().lower()
        for label in _entry_terms(entry):
            if not label:
                continue
            if label in q_tokens or label in q_norm or term_present_as_word(label, message):
                if cat_id and cat_id not in hits:
                    hits.append(cat_id)
                break
    return list(dict.fromkeys(hits))
