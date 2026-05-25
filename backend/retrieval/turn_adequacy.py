from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from retrieval.tools.category_sample import build_category_actions
from retrieval.tools.product_refs import extract_product_title_from_message, is_product_detail_message

logger = logging.getLogger("turn-adequacy")

_SUPPORT_CMS_MARKERS = (
    "could not find return or policy information",
    "magento cms tables",
    "static policy url",
)
_BROWSE_ALL_RE = re.compile(
    r"\b(?:show\s+(?:me\s+)?(?:all|every)\s+products?|all\s+products?)\b",
    re.IGNORECASE,
)


def turn_adequacy_enabled() -> bool:
    return os.getenv("TURN_ADEQUACY_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def turn_adequacy_llm_enabled() -> bool:
    return os.getenv("TURN_ADEQUACY_LLM_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def is_support_cms_fallback(answer: str) -> bool:
    lower = (answer or "").strip().lower()
    return any(marker in lower for marker in _SUPPORT_CMS_MARKERS)


def is_browse_all_message(message: str, *, browse_all: bool = False) -> bool:
    return browse_all or bool(_BROWSE_ALL_RE.search(message or ""))


def _normalize_url(url: str | None) -> str | None:
    raw = (url or "").strip()
    return raw.rstrip("/") if raw else None


def _url_in_text(text: str, url: str | None) -> bool:
    site = _normalize_url(url)
    if not site or not text:
        return False
    if site in text:
        return True
    parsed = urlparse(site)
    if parsed.netloc and parsed.netloc in text:
        return True
    return False


def _has_website_link(answer: str, actions: list[dict[str, Any]] | None, website_url: str | None) -> bool:
    if _url_in_text(answer, website_url):
        return True
    site = _normalize_url(website_url)
    if not site:
        return False
    for action in actions or []:
        action_url = _normalize_url(str(action.get("url") or ""))
        if not action_url:
            continue
        if action_url == site or action_url.startswith(f"{site}/"):
            return True
    return False


def _product_dicts(products: list[Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for product in products or []:
        if hasattr(product, "model_dump"):
            rows.append(product.model_dump())
        elif isinstance(product, dict):
            rows.append(product)
    return rows


def _title_tokens(title: str) -> list[str]:
    return [t for t in re.split(r"\W+", title.lower()) if len(t) > 2]


def _answer_mentions_product(answer: str, title: str | None, products: list[dict[str, Any]]) -> bool:
    text = (answer or "").lower()
    if title:
        title_lower = title.lower()
        if title_lower in text:
            return True
        tokens = _title_tokens(title)
        if tokens and sum(1 for token in tokens if token in text) >= min(2, len(tokens)):
            return True
    for product in products:
        product_title = str(product.get("title") or "").strip().lower()
        if product_title and product_title in text:
            return True
    return False


def _infer_website_url(website_url: str | None, products: list[dict[str, Any]]) -> str | None:
    site = _normalize_url(website_url)
    if site:
        return site
    for product in products:
        url = str(product.get("url") or "").strip()
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return None


@dataclass
class TurnAdequacyResult:
    answer: str
    actions: list[dict[str, Any]] | None = None
    products: list[Any] | None = None
    response_subtype: str | None = None
    passed: bool = True
    repaired: bool = False
    issues: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def _rules_check_and_repair(
    *,
    user_message: str,
    answer: str,
    response_subtype: str | None,
    browse_all: bool,
    products: list[dict[str, Any]],
    actions: list[dict[str, Any]] | None,
    website_url: str | None,
    structured_query_intent: str | None,
) -> TurnAdequacyResult:
    result = TurnAdequacyResult(
        answer=answer,
        actions=list(actions) if actions else None,
        products=None,
        response_subtype=response_subtype,
        passed=True,
    )
    product_detail_turn = is_product_detail_message(user_message)
    browse_all_turn = is_browse_all_message(user_message, browse_all=browse_all)
    title = extract_product_title_from_message(user_message)

    if product_detail_turn:
        wrong_support = (
            is_support_cms_fallback(answer)
            or structured_query_intent == "support"
            or response_subtype == "support_faq"
        )
        if wrong_support:
            label = title or "that product"
            result.answer = (
                f"I couldn't find details for **{label}** in our catalog. "
                "Try checking the spelling or browse products on the store."
            )
            result.response_subtype = "product_detail"
            result.issues.append("product_detail_inadequate")
            result.passed = False
            result.repaired = True
        elif not _answer_mentions_product(answer, title, products) and not products:
            label = title or "that product"
            result.answer = (
                f"I couldn't find details for **{label}** in our catalog. "
                "Try checking the spelling or browse products on the store."
            )
            result.response_subtype = "product_detail"
            result.issues.append("product_detail_not_found")
            result.passed = False
            result.repaired = True

    if browse_all_turn:
        site = _infer_website_url(website_url, products)
        if site and not _has_website_link(result.answer, result.actions, site):
            if not _url_in_text(result.answer, site):
                result.answer = (
                    f"{result.answer.rstrip()}\n\n"
                    f"Browse the [full catalog on our website]({site})."
                ).strip()
            if not _has_website_link("", result.actions, site):
                result.actions = build_category_actions(category=None, website_url=site)
            result.issues.append("browse_all_missing_website_link")
            result.passed = False
            result.repaired = True
        elif not site:
            result.issues.append("browse_all_missing_website_url")
            result.passed = False

    return result


async def _llm_adequacy_review(
    *,
    user_message: str,
    answer: str,
    response_subtype: str | None,
    products: list[dict[str, Any]],
    actions: list[dict[str, Any]] | None,
    website_url: str | None,
    issues: list[str],
    llm_call: Callable[..., Any],
) -> tuple[str, bool]:
    model = os.getenv(
        "TURN_ADEQUACY_LLM_MODEL",
        os.getenv("RESPONSE_VERIFY_LLM_MODEL", "gpt-4o-mini"),
    )
    timeout_s = max(0.5, int(os.getenv("TURN_ADEQUACY_TIMEOUT_MS", "3000")) / 1000.0)
    messages = [
        {
            "role": "system",
            "content": (
                "You verify whether an ecommerce chatbot reply adequately answers the user. "
                "Return ONLY JSON: "
                '{"ok": true|false, "revised_answer": "...", "revised_actions": [{"type":"link","label":"...","url":"..."}]|null}\n'
                "Rules:\n"
                "- ok=false when a product-detail question gets policy/CMS/support copy instead of product info.\n"
                "- ok=false when user asks to see all products but the reply lacks any store/catalog website link.\n"
                "- ok=false when the answer ignores a named product the user asked about.\n"
                "- If ok=false, revised_answer must be concise and grounded in allowed products JSON.\n"
                "- revised_actions may add a website browse link; use null to keep existing actions."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_message": user_message,
                    "response_subtype": response_subtype,
                    "website_url": website_url,
                    "known_issues": issues,
                    "products": products[:8],
                    "actions": actions or [],
                    "assistant_answer": answer,
                },
                ensure_ascii=False,
            ),
        },
    ]

    async def _call():
        return await asyncio.to_thread(llm_call, model=model, messages=messages)

    try:
        response = await asyncio.wait_for(_call(), timeout=timeout_s)
        content = response.choices[0].message.content or ""
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("Turn adequacy LLM skipped: %s", exc)
        return answer, False

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return answer, False

    revised = str(data.get("revised_answer") or answer).strip()
    ok = bool(data.get("ok", True))
    return revised, ok


async def apply_turn_adequacy(
    *,
    user_message: str,
    answer: str,
    response_subtype: str | None = None,
    browse_all: bool = False,
    products: list[Any] | None = None,
    actions: list[dict[str, Any]] | None = None,
    website_url: str | None = None,
    structured_query_intent: str | None = None,
    llm_call: Callable[..., Any] | None = None,
) -> TurnAdequacyResult:
    """Validate and optionally repair a commerce reply before it is sent to the user."""
    if not turn_adequacy_enabled() or not (answer or "").strip():
        return TurnAdequacyResult(answer=answer, actions=actions, products=products, response_subtype=response_subtype)

    product_rows = _product_dicts(products)
    result = _rules_check_and_repair(
        user_message=user_message,
        answer=answer,
        response_subtype=response_subtype,
        browse_all=browse_all,
        products=product_rows,
        actions=actions,
        website_url=website_url,
        structured_query_intent=structured_query_intent,
    )

    if (
        turn_adequacy_llm_enabled()
        and llm_call
        and (not result.passed or result.issues)
    ):
        revised, ok = await _llm_adequacy_review(
            user_message=user_message,
            answer=result.answer,
            response_subtype=result.response_subtype or response_subtype,
            products=product_rows,
            actions=result.actions,
            website_url=_infer_website_url(website_url, product_rows),
            issues=result.issues,
            llm_call=llm_call,
        )
        if not ok and revised:
            result.answer = revised
            result.repaired = True
            result.passed = False

    result.meta = {
        "turn_adequacy": {
            "passed": result.passed,
            "repaired": result.repaired,
            "issues": list(result.issues),
        }
    }
    if result.issues:
        logger.info(
            "Turn adequacy issues=%s repaired=%s subtype=%s",
            result.issues,
            result.repaired,
            result.response_subtype or response_subtype,
        )
    return result
