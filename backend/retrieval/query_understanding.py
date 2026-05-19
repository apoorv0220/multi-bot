from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from retrieval.rules_prepass import rules_prepass
from retrieval.structured_query import CategorySpec, FacetSpec, StructuredQuery

logger = logging.getLogger("query-understanding")

_EXPLICIT_PREPASSES_CONFIDENCE = 0.95


@dataclass
class QueryUnderstandingResult:
    query: StructuredQuery
    prepass_ms: float = 0.0
    llm_ms: float = 0.0
    validation_ms: float = 0.0
    mode: str = "hybrid"
    llm_used: bool = False
    llm_fallback: bool = False


def query_understanding_mode() -> str:
    mode = (os.getenv("QUERY_UNDERSTANDING_MODE", "hybrid") or "hybrid").strip().lower()
    if mode not in ("llm", "rules", "hybrid"):
        return "hybrid"
    return mode


def _profile_slice(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not profile:
        return {}
    facets_out: dict[str, Any] = {}
    for facet_id, meta in (profile.get("facets") or {}).items():
        if not isinstance(meta, dict):
            continue
        facets_out[str(facet_id)] = {
            "sample_values": list((meta.get("sample_values") or [])[:15]),
            "value_aliases": meta.get("value_aliases") or {},
            "within_facet_combine_default": meta.get("within_facet_combine_default", "OR"),
        }
    gazetteer = []
    for entry in (profile.get("category_strategy") or {}).get("gazetteer") or []:
        gazetteer.append(
            {
                "id": entry.get("id"),
                "labels": (entry.get("labels") or [])[:8],
            }
        )
    return {
        "category_strategy": {
            "confidence_threshold": (profile.get("category_strategy") or {}).get(
                "confidence_threshold", 0.75
            ),
            "gazetteer": gazetteer[:40],
        },
        "facets": facets_out,
        "cross_facet_combine": profile.get("cross_facet_combine", "AND"),
    }


def build_llm_prompt(
    message: str,
    profile: dict[str, Any] | None,
    session_query: StructuredQuery | None,
    prepass_query: StructuredQuery,
    *,
    conversation_summary: str | None = None,
) -> list[dict[str, str]]:
    session_snapshot = session_query.to_dict() if session_query else {}
    prepass_snapshot = prepass_query.to_dict()
    profile_json = json.dumps(_profile_slice(profile), ensure_ascii=False)
    system = (
        "You extract ecommerce catalog search constraints from the user message. "
        "Return ONLY valid JSON matching this schema:\n"
        "{\n"
        '  "intent": "catalog" | "support" | "general",\n'
        '  "free_text": "remaining semantic query after extracting filters",\n'
        '  "category": {"values": ["..."], "confidence": 0.0-1.0},\n'
        '  "facets": {"facet_id": {"values": ["..."], "combine": "OR" | "AND"}},\n'
        '  "price": {"min": number|null, "max": number|null},\n'
        '  "stock_status": "instock" | "outofstock" | null,\n'
        '  "session": {"inherit": true, "clear": {"facets": [], "category": false, "price": false, "stock_status": false}}\n'
        "}\n"
        "Rules: AND across different facet keys; OR within one facet when user says or/either/slash lists. "
        "Use only facet_ids from the tenant profile. "
        "Do not invent categories or facets not supported by the profile. "
        "Prefer catalog intent for product shopping language."
    )
    summary_block = ""
    if conversation_summary and len((message or "").strip()) < 20:
        summary_block = f"\nRecent conversation (for short follow-ups):\n{conversation_summary.strip()}\n"
    user = (
        f"Tenant profile:\n{profile_json}\n\n"
        f"Session structured query:\n{json.dumps(session_snapshot, ensure_ascii=False)}\n\n"
        f"Rules prepass (authoritative for explicit syntax like category: and clears):\n"
        f"{json.dumps(prepass_snapshot, ensure_ascii=False)}\n"
        f"{summary_block}\n"
        f"User message:\n{message}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_llm_json(raw: str) -> StructuredQuery | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return StructuredQuery.from_dict(data)


def merge_prepass_and_llm(prepass: StructuredQuery, llm: StructuredQuery) -> StructuredQuery:
    merged = prepass.copy()

    if llm.intent in ("catalog", "support", "general"):
        if prepass.intent == "general" or llm.intent != "general":
            merged.intent = llm.intent

    if llm.free_text.strip():
        merged.free_text = llm.free_text.strip()

    prepass_explicit_category = prepass.category.confidence >= _EXPLICIT_PREPASSES_CONFIDENCE
    if not prepass_explicit_category and llm.category.values:
        if not prepass.category.values or llm.category.confidence >= prepass.category.confidence:
            merged.category = CategorySpec(
                values=list(llm.category.values),
                confidence=max(prepass.category.confidence, llm.category.confidence),
                apply=prepass.category.apply,
            )

    for facet_id, spec in llm.facets.items():
        if facet_id in prepass.facets and prepass.facets[facet_id].values:
            continue
        merged.facets[facet_id] = FacetSpec(values=list(spec.values), combine=spec.combine)

    if prepass.price.min is None and prepass.price.max is None:
        if llm.price.min is not None:
            merged.price.min = llm.price.min
        if llm.price.max is not None:
            merged.price.max = llm.price.max

    if not prepass.stock_status and llm.stock_status:
        merged.stock_status = llm.stock_status

    clear = dict(prepass.session.clear)
    llm_clear = llm.session.clear or {}
    for key in ("category", "price", "stock_status"):
        if llm_clear.get(key):
            clear[key] = True
    llm_facets_clear = llm_clear.get("facets") or []
    if llm_facets_clear:
        clear["facets"] = list(dict.fromkeys(list(clear.get("facets") or []) + list(llm_facets_clear)))
    merged.session.clear = clear

    return merged


_PRODUCT_TYPE_PATTERN = re.compile(
    r"\b(?:taps?|faucets?|basins?|sinks?|toilets?|showers?|baths?|wcs?)\b",
    re.IGNORECASE,
)
_PRICE_ONLY_PATTERN = re.compile(
    r"^\s*(?:under|below|over|above|max|min)?\s*\$?\d+(?:\.\d+)?\s*$",
    re.IGNORECASE,
)


def _normalize_token(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _prepass_reflects_product_type(message: str, prepass: StructuredQuery, profile: dict[str, Any] | None) -> bool:
    if not profile:
        return True
    category_blob = " ".join(_normalize_token(v) for v in prepass.category.values)
    gazetteer = (profile.get("category_strategy") or {}).get("gazetteer") or []
    for match in _PRODUCT_TYPE_PATTERN.finditer(message):
        token = _normalize_token(match.group(0))
        stem = token.rstrip("s")
        if not token:
            continue
        if stem in category_blob or token in category_blob:
            continue
        for entry in gazetteer:
            cat_id = _normalize_token(str(entry.get("id") or ""))
            label_norms = {_normalize_token(str(label)) for label in (entry.get("labels") or [])}
            label_norms.add(cat_id)
            token_variants = {token, stem, f"{stem}s"}
            if not token_variants.intersection(label_norms) and stem != cat_id.rstrip("s"):
                continue
            if cat_id in category_blob or any(label in category_blob for label in label_norms):
                break
            return False
    return True


def should_skip_llm(
    prepass: StructuredQuery,
    message: str,
    *,
    mode: str,
    profile: dict[str, Any] | None = None,
    session_query: StructuredQuery | None = None,
) -> bool:
    if mode == "rules":
        return True
    if mode == "llm":
        return False
    if os.getenv("QUERY_UNDERSTANDING_SKIP_LLM_WHEN_COMPLETE", "true").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    if prepass.intent != "catalog":
        return False
    if profile and _PRODUCT_TYPE_PATTERN.search(message) and not _prepass_reflects_product_type(
        message, prepass, profile
    ):
        return False
    if re.search(r"\b(?:or|either)\b", message, re.IGNORECASE):
        return False
    if "/" in message and len(message.split()) <= 8:
        return False
    has_category = bool(prepass.category.values)
    has_facets = bool(prepass.facets)
    has_price = prepass.price.min is not None or prepass.price.max is not None
    if not (has_category or has_facets):
        return False
    if re.search(r"\b(?:under|below|over|above|min|max)\s+\$?\d", message, re.IGNORECASE) and not has_price:
        return False
    if _PRICE_ONLY_PATTERN.match(message.strip()):
        session_has_filters = bool(
            session_query and (session_query.category.values or session_query.facets)
        )
        if session_has_filters and has_price and not has_category and not has_facets:
            return False
    return len(message.split()) <= 12


async def extract_with_llm(
    message: str,
    profile: dict[str, Any] | None,
    session_query: StructuredQuery | None,
    prepass_query: StructuredQuery,
    *,
    llm_call: Callable[..., Any],
    conversation_summary: str | None = None,
) -> tuple[StructuredQuery | None, float]:
    messages = build_llm_prompt(
        message,
        profile,
        session_query,
        prepass_query,
        conversation_summary=conversation_summary,
    )
    model = os.getenv("QUERY_UNDERSTANDING_LLM_MODEL", "gpt-4o-mini")
    timeout_s = max(0.5, int(os.getenv("QUERY_UNDERSTANDING_LLM_TIMEOUT_MS", "2500")) / 1000.0)
    started = time.perf_counter()

    async def _call():
        return await asyncio.to_thread(
            llm_call,
            model=model,
            messages=messages,
        )

    try:
        response = await asyncio.wait_for(_call(), timeout=timeout_s)
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("LLM query understanding failed: %s", exc)
        return None, (time.perf_counter() - started) * 1000.0

    content = ""
    try:
        content = response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        content = str(response)

    parsed = _parse_llm_json(content)
    return parsed, (time.perf_counter() - started) * 1000.0


async def run_query_understanding(
    message: str,
    profile: dict[str, Any] | None,
    session_query: StructuredQuery | None,
    *,
    llm_call: Callable[..., Any] | None = None,
    conversation_summary: str | None = None,
) -> QueryUnderstandingResult:
    mode = query_understanding_mode()
    prepass_started = time.perf_counter()
    prepass = rules_prepass(message, profile=profile, session_query=session_query)
    prepass_ms = (time.perf_counter() - prepass_started) * 1000.0

    llm_ms = 0.0
    llm_used = False
    llm_fallback = False

    if (
        should_skip_llm(
            prepass,
            message,
            mode=mode,
            profile=profile,
            session_query=session_query,
        )
        or llm_call is None
    ):
        return QueryUnderstandingResult(
            query=prepass,
            prepass_ms=prepass_ms,
            llm_ms=0.0,
            mode=mode,
            llm_used=False,
            llm_fallback=False,
        )

    llm_query, llm_ms = await extract_with_llm(
        message,
        profile,
        session_query,
        prepass,
        llm_call=llm_call,
        conversation_summary=conversation_summary,
    )
    if llm_query is None:
        llm_fallback = True
        return QueryUnderstandingResult(
            query=prepass,
            prepass_ms=prepass_ms,
            llm_ms=llm_ms,
            mode=mode,
            llm_used=True,
            llm_fallback=True,
        )

    merged = merge_prepass_and_llm(prepass, llm_query)
    return QueryUnderstandingResult(
        query=merged,
        prepass_ms=prepass_ms,
        llm_ms=llm_ms,
        mode=mode,
        llm_used=True,
        llm_fallback=False,
    )
