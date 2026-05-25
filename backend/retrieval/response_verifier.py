from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Callable

logger = logging.getLogger("response-verifier")


def response_verify_enabled() -> bool:
    return os.getenv("RESPONSE_VERIFY_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def _extract_prices(text: str) -> set[str]:
    found: set[str] = set()
    for m in re.finditer(r"\$?\d+(?:\.\d{1,2})?", text or ""):
        raw = m.group(0).lstrip("$")
        try:
            found.add(f"{float(raw):g}")
        except ValueError:
            continue
    return found


async def verify_catalog_response(
    *,
    user_message: str,
    answer: str,
    products: list[dict[str, Any]],
    llm_call: Callable[..., Any] | None,
) -> tuple[str, bool]:
    """
    Optional faithfulness check: ensure answer does not invent prices/brands
    beyond the product JSON. Returns (answer, passed).
    """
    if not response_verify_enabled() or not llm_call or not answer.strip():
        return answer, True

    if not products:
        return answer, True

    allowed_prices = set()
    for p in products:
        price = p.get("price")
        if price not in (None, ""):
            try:
                allowed_prices.add(f"{float(price):g}")
            except (TypeError, ValueError):
                pass

    answer_prices = _extract_prices(answer)
    if allowed_prices and answer_prices - allowed_prices:
        logger.info("Response verifier: answer prices %s not in allowed %s", answer_prices, allowed_prices)

    model = os.getenv("RESPONSE_VERIFY_LLM_MODEL", os.getenv("QUERY_UNDERSTANDING_LLM_MODEL", "gpt-4o-mini"))
    timeout_s = max(0.5, int(os.getenv("RESPONSE_VERIFY_TIMEOUT_MS", "3000")) / 1000.0)
    products_json = json.dumps(products[:8], ensure_ascii=False)
    messages = [
        {
            "role": "system",
            "content": (
                "You verify ecommerce chatbot answers. Return ONLY JSON: "
                '{"ok": true|false, "revised_answer": "..."}\n'
                "Rules: ok=false if the answer mentions products, prices, or brands not in the JSON. "
                "If ok=false, revised_answer must fix the reply using only JSON facts (concise). "
                "If ok=true, revised_answer should repeat the original answer."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User asked: {user_message}\n\n"
                f"Allowed products JSON:\n{products_json}\n\n"
                f"Assistant answer:\n{answer}"
            ),
        },
    ]

    async def _call():
        return await asyncio.to_thread(llm_call, model=model, messages=messages)

    try:
        response = await asyncio.wait_for(_call(), timeout=timeout_s)
        content = response.choices[0].message.content or ""
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("Response verify skipped: %s", exc)
        return answer, True

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return answer, True

    revised = str(data.get("revised_answer") or answer).strip()
    ok = bool(data.get("ok", True))
    if not ok and revised:
        return revised, False
    return answer, ok
