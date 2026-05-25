from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Callable

from retrieval.category_guard import should_block_catalog_search
from retrieval.structured_query import CatalogCoverageSpec

logger = logging.getLogger("catalog-coverage")

_CATALOG_COVERAGE_SCHEMA = (
    '  "catalog_coverage": {\n'
    '    "in_catalog": true | false,\n'
    '    "missing_terms": ["product types or brands not sold here"],\n'
    '    "confidence": 0.0-1.0\n'
    "  }\n"
)


def catalog_coverage_mode() -> str:
    mode = (os.getenv("CATALOG_COVERAGE_MODE", "llm") or "llm").strip().lower()
    if mode not in ("llm", "rules", "hybrid"):
        return "llm"
    return mode


def catalog_coverage_min_confidence() -> float:
    raw = os.getenv("CATALOG_COVERAGE_LLM_MIN_CONFIDENCE", "0.65")
    try:
        return max(0.0, min(float(raw), 1.0))
    except (TypeError, ValueError):
        return 0.65


def catalog_coverage_fallback_rules() -> bool:
    return os.getenv("CATALOG_COVERAGE_FALLBACK_RULES", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def parse_catalog_coverage_blob(data: dict[str, Any] | None) -> CatalogCoverageSpec:
    if not data:
        return CatalogCoverageSpec()
    coverage = CatalogCoverageSpec.from_dict(data.get("catalog_coverage"))
    if coverage.in_catalog is not None and not coverage.source:
        coverage.source = "llm"
    return coverage


def build_catalog_coverage_prompt(message: str, profile: dict[str, Any] | None) -> list[dict[str, str]]:
    from retrieval.query_understanding import _profile_slice

    profile_json = json.dumps(_profile_slice(profile), ensure_ascii=False)
    brand_meta = ((profile or {}).get("core_fields") or {}).get("brand") or {}
    brand_samples = list((brand_meta.get("sample_values") or [])[:20])
    system = (
        "You decide whether a shopper's request can be fulfilled using ONLY the tenant catalog profile. "
        "Return ONLY valid JSON:\n"
        "{\n"
        f"{_CATALOG_COVERAGE_SCHEMA}"
        "}\n"
        "Rules:\n"
        "- in_catalog=false when the user asks for product types, categories, or brands absent from the profile.\n"
        "- Size, colour, and price constraints alone never make in_catalog false.\n"
        "- 'in size L under $150' is in_catalog=true when jackets/pants/etc. exist in the gazetteer.\n"
        "- missing_terms: short labels the user asked for that are not sold (e.g. shoes, Nike).\n"
        "- Do not block when the request maps to an existing category (jeans → pants).\n"
        f"- Known brands in this store: {json.dumps(brand_samples)}. Unknown brand requests → in_catalog=false.\n"
        "- confidence: how sure you are about in_catalog."
    )
    user = f"Tenant profile:\n{profile_json}\n\nUser message:\n{message}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_coverage_json(raw: str) -> CatalogCoverageSpec | None:
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
    coverage = CatalogCoverageSpec.from_dict(data.get("catalog_coverage") or data)
    if coverage.in_catalog is None:
        return None
    coverage.source = "llm"
    return coverage


async def assess_catalog_coverage_llm(
    message: str,
    profile: dict[str, Any] | None,
    *,
    llm_call: Callable[..., Any],
) -> CatalogCoverageSpec | None:
    messages = build_catalog_coverage_prompt(message, profile)
    model = os.getenv("QUERY_UNDERSTANDING_LLM_MODEL", "gpt-4o-mini")
    timeout_s = max(0.5, int(os.getenv("CATALOG_COVERAGE_LLM_TIMEOUT_MS", "4000")) / 1000.0)

    async def _call():
        return await asyncio.to_thread(llm_call, model=model, messages=messages)

    try:
        response = await asyncio.wait_for(_call(), timeout=timeout_s)
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("Catalog coverage LLM failed: %s", exc)
        return None

    content = ""
    try:
        content = response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        content = str(response)
    return _parse_coverage_json(content)


def assess_catalog_coverage_rules(
    message: str,
    profile: dict[str, Any] | None,
) -> CatalogCoverageSpec:
    blocked, reason = should_block_catalog_search(message, profile)
    if blocked and reason:
        return CatalogCoverageSpec(
            in_catalog=False,
            missing_terms=[reason],
            confidence=0.85,
            source="rules",
        )
    return CatalogCoverageSpec(in_catalog=True, confidence=0.5, source="rules")


async def ensure_catalog_coverage(
    message: str,
    profile: dict[str, Any] | None,
    coverage: CatalogCoverageSpec | None,
    *,
    intent: str,
    llm_call: Callable[..., Any] | None,
) -> CatalogCoverageSpec:
    if intent != "catalog":
        return coverage or CatalogCoverageSpec()
    existing = coverage or CatalogCoverageSpec()
    if existing.in_catalog is not None and existing.source == "llm":
        return existing

    mode = catalog_coverage_mode()
    if mode == "rules":
        return assess_catalog_coverage_rules(message, profile)

    if llm_call is not None and mode in ("llm", "hybrid"):
        started = time.perf_counter()
        llm_cov = await assess_catalog_coverage_llm(message, profile, llm_call=llm_call)
        if llm_cov is not None:
            return llm_cov
        logger.info("Catalog coverage LLM unavailable after %.0fms", (time.perf_counter() - started) * 1000)

    if catalog_coverage_fallback_rules():
        return assess_catalog_coverage_rules(message, profile)
    return CatalogCoverageSpec(in_catalog=True, confidence=0.0, source="unknown")


def resolve_catalog_block(
    *,
    message: str,
    profile: dict[str, Any] | None,
    coverage: CatalogCoverageSpec | None,
) -> tuple[bool, str | None]:
    cov = coverage or CatalogCoverageSpec()
    min_conf = catalog_coverage_min_confidence()

    if cov.in_catalog is True and cov.source == "llm":
        return False, None

    if cov.in_catalog is False and cov.missing_terms:
        if cov.source == "llm" or cov.confidence >= min_conf:
            return True, cov.missing_terms[0]

    if cov.in_catalog is None and catalog_coverage_fallback_rules():
        blocked, reason = should_block_catalog_search(message, profile)
        return blocked, reason

    return False, None
