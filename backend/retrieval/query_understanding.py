from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from retrieval.catalog_coverage import ensure_catalog_coverage, parse_catalog_coverage_blob
from retrieval.rules_prepass import rules_prepass
from retrieval.structured_query import CatalogCoverageSpec, CategorySpec, FacetSpec, StructuredQuery

logger = logging.getLogger("query-understanding")

_EXPLICIT_PREPASSES_CONFIDENCE = 0.95
_PRODUCT_TYPE_PREPASSES_CONFIDENCE = 0.89
_COLLECTION_CATEGORY_IDS = frozenset({"erin_recommends", "default_category", "sale", "new"})


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
        '  "retrieval_rewrite": "single dense search phrase combining category, facets, and product type (no filler)",\n'
        '  "category": {"values": ["..."], "confidence": 0.0-1.0},\n'
        '  "facets": {"facet_id": {"values": ["..."], "combine": "OR" | "AND"}},\n'
        '  "price": {"min": number|null, "max": number|null},\n'
        '  "stock_status": "instock" | "outofstock" | null,\n'
        '  "session": {"inherit": true, "clear": {"facets": [], "category": false, "price": false, "stock_status": false}},\n'
        '  "catalog_coverage": {"in_catalog": true|false, "missing_terms": ["..."], "confidence": 0.0-1.0}\n'
        "}\n"
        "Rules: AND across different facet keys; OR within one facet when user says or/either/slash lists. "
        "Use only facet_ids from the tenant profile. "
        "Do not invent categories or facets not supported by the profile. "
        "catalog_coverage: in_catalog=false when the user asks for product types or brands not in the tenant profile "
        "(e.g. shoes when no footwear category, Nike when brand not listed). "
        "Size/colour/price alone never make in_catalog false. "
        "Prefer catalog intent for product shopping language. "
        "For catalog turns, always populate retrieval_rewrite with a compact product search phrase "
        "(e.g. chrome taps under 50) even when free_text is only a price refinement."
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


def _parse_llm_json(raw: str) -> tuple[StructuredQuery | None, CatalogCoverageSpec | None]:
    text = (raw or "").strip()
    if not text:
        return None, None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    coverage = parse_catalog_coverage_blob(data)
    return StructuredQuery.from_dict(data), coverage


def merge_prepass_and_llm(prepass: StructuredQuery, llm: StructuredQuery) -> StructuredQuery:
    merged = prepass.copy()

    if llm.intent in ("catalog", "support", "general"):
        if prepass.intent == "general" or llm.intent != "general":
            merged.intent = llm.intent

    if llm.free_text.strip():
        merged.free_text = llm.free_text.strip()

    if llm.retrieval_rewrite.strip():
        merged.retrieval_rewrite = llm.retrieval_rewrite.strip()

    prepass_product_type = bool(
        prepass.category.values
        and prepass.category.confidence >= _PRODUCT_TYPE_PREPASSES_CONFIDENCE
        and all(str(v).strip().lower() not in _COLLECTION_CATEGORY_IDS for v in prepass.category.values)
    )
    prepass_explicit_category = (
        prepass.category.confidence >= _EXPLICIT_PREPASSES_CONFIDENCE or prepass_product_type
    )
    if not prepass_explicit_category and llm.category.values:
        llm_is_collection = all(
            str(v).strip().lower() in _COLLECTION_CATEGORY_IDS for v in llm.category.values
        )
        if not (prepass_product_type and llm_is_collection):
            if not prepass.category.values or llm.category.confidence >= prepass.category.confidence:
                merged.category = CategorySpec(
                    values=list(llm.category.values),
                    confidence=max(prepass.category.confidence, llm.category.confidence),
                    apply=prepass.category.apply,
                )

    for facet_id, spec in llm.facets.items():
        if facet_id in prepass.facets and prepass.facets[facet_id].values:
            continue
        merged.facets[facet_id] = FacetSpec(
            values=list(spec.values),
            combine=spec.combine,
            exclude_values=list(spec.exclude_values),
        )

    if prepass.price.min is None and prepass.price.max is None:
        if llm.price.min is not None:
            merged.price.min = llm.price.min
        if llm.price.max is not None:
            merged.price.max = llm.price.max

    if not prepass.stock_status and llm.stock_status:
        merged.stock_status = llm.stock_status

    if prepass.min_rating is not None:
        merged.min_rating = prepass.min_rating

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


_PRICE_ONLY_PATTERN = re.compile(
    r"^\s*(?:under|below|over|above|max|min)?\s*\$?\d+(?:\.\d+)?\s*$",
    re.IGNORECASE,
)


def _normalize_token(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


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
    from retrieval.category_match import prepass_missing_hard_filter_category

    if profile and prepass_missing_hard_filter_category(message, prepass, profile):
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
) -> tuple[StructuredQuery | None, CatalogCoverageSpec | None, float]:
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
        return None, None, (time.perf_counter() - started) * 1000.0

    content = ""
    try:
        content = response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        content = str(response)

    parsed, coverage = _parse_llm_json(content)
    return parsed, coverage, (time.perf_counter() - started) * 1000.0


async def run_query_understanding(
    message: str,
    profile: dict[str, Any] | None,
    session_query: StructuredQuery | None,
    *,
    llm_call: Callable[..., Any] | None = None,
    conversation_summary: str | None = None,
) -> QueryUnderstandingResult:
    from retrieval.tools.product_refs import extract_product_title_from_message, is_product_detail_message

    mode = query_understanding_mode()
    prepass_started = time.perf_counter()
    prepass = rules_prepass(message, profile=profile, session_query=session_query)
    prepass_ms = (time.perf_counter() - prepass_started) * 1000.0

    if is_product_detail_message(message):
        title = extract_product_title_from_message(message) or prepass.free_text.strip()
        query = prepass.copy()
        query.intent = "catalog"
        query.category = CategorySpec()
        query.facets = {}
        if title:
            query.free_text = title
            query.retrieval_rewrite = title
        query.catalog_coverage = CatalogCoverageSpec(
            in_catalog=True,
            missing_terms=[],
            confidence=1.0,
            source="rules",
        )
        return QueryUnderstandingResult(
            query=query,
            prepass_ms=prepass_ms,
            llm_ms=0.0,
            mode=mode,
            llm_used=False,
            llm_fallback=False,
        )

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
        coverage = await ensure_catalog_coverage(
            message,
            profile,
            prepass.catalog_coverage,
            intent=prepass.intent,
            llm_call=llm_call,
        )
        query = prepass.copy()
        query.catalog_coverage = coverage
        return QueryUnderstandingResult(
            query=query,
            prepass_ms=prepass_ms,
            llm_ms=0.0,
            mode=mode,
            llm_used=False,
            llm_fallback=False,
        )

    llm_query, llm_coverage, llm_ms = await extract_with_llm(
        message,
        profile,
        session_query,
        prepass,
        llm_call=llm_call,
        conversation_summary=conversation_summary,
    )
    if llm_query is None:
        llm_fallback = True
        merged = prepass.copy()
    else:
        merged = merge_prepass_and_llm(prepass, llm_query)
        if llm_coverage and llm_coverage.in_catalog is not None:
            merged.catalog_coverage = llm_coverage

    coverage = await ensure_catalog_coverage(
        message,
        profile,
        merged.catalog_coverage,
        intent=merged.intent,
        llm_call=llm_call,
    )
    merged.catalog_coverage = coverage

    if llm_query is None:
        return QueryUnderstandingResult(
            query=merged,
            prepass_ms=prepass_ms,
            llm_ms=llm_ms,
            mode=mode,
            llm_used=True,
            llm_fallback=True,
        )

    return QueryUnderstandingResult(
        query=merged,
        prepass_ms=prepass_ms,
        llm_ms=llm_ms,
        mode=mode,
        llm_used=True,
        llm_fallback=False,
    )
