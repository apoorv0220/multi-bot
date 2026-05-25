from __future__ import annotations

import re
from typing import Any, Literal

from commerce.currency import default_currency_code, format_money, normalize_currency_code

ProductDetailFocus = Literal["overview", "price", "availability", "specs", "description"]


# Weighted signal groups — highest-scoring focus wins (not a single regex).
_FOCUS_SIGNALS: dict[ProductDetailFocus, list[tuple[str, float]]] = {
    "price": [
        (r"\bhow much\b", 3.0),
        (r"\bprice\b", 2.5),
        (r"\bcost\b", 2.0),
        (r"\bpricing\b", 2.0),
        (r"\$\d", 1.5),
        (r"\b£\d", 1.5),
        (r"\bexpensive\b", 1.0),
        (r"\bcheap\b", 0.5),
    ],
    "availability": [
        (r"\bin stock\b", 3.0),
        (r"\bavailable\b", 2.5),
        (r"\bavailability\b", 2.5),
        (r"\bstock\b", 2.0),
        (r"\bout of stock\b", 2.5),
    ],
    "specs": [
        (r"\bspecifications?\b", 3.0),
        (r"\bspecs?\b", 2.5),
        (r"\bmaterials?\b", 2.0),
        (r"\bfeatures?\b", 1.5),
        (r"\bdimensions?\b", 2.0),
        (r"\bwhat(?:'s| is) it made of\b", 2.5),
    ],
    "description": [
        (r"\btell me about\b", 2.5),
        (r"\bdescribe\b", 2.5),
        (r"\bwhat is (?:the )?\w", 1.0),
        (r"\bdetails?\b", 1.5),
        (r"\babout\b", 0.5),
    ],
}


def infer_product_detail_focus(message: str) -> ProductDetailFocus:
    """Score user phrasing to pick a concise answer shape."""
    text = (message or "").strip().lower()
    if not text:
        return "overview"

    scores: dict[str, float] = {k: 0.0 for k in _FOCUS_SIGNALS}
    for focus, patterns in _FOCUS_SIGNALS.items():
        for pattern, weight in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                scores[focus] += weight

    best_focus = max(scores, key=lambda k: scores[k])
    if scores[best_focus] <= 0:
        return "overview"
    return best_focus  # type: ignore[return-value]


def _product_link(title: str, url: str | None) -> str:
    if not url:
        return ""
    safe_title = title or "View product"
    return f"[{safe_title}]({url})"


def _resolve_currency(payload: dict[str, Any], currency_code: str | None) -> str:
    if currency_code:
        return normalize_currency_code(currency_code) or default_currency_code()
    raw = payload.get("currency")
    return normalize_currency_code(str(raw) if raw else None) or default_currency_code()


def _format_price(payload: dict[str, Any], currency_code: str | None = None) -> str | None:
    price = payload.get("price")
    if price in (None, ""):
        return None
    return format_money(price, _resolve_currency(payload, currency_code))


def format_product_detail_for_message(
    payload: dict[str, Any],
    message: str,
    *,
    currency_code: str | None = None,
) -> str:
    focus = infer_product_detail_focus(message)
    title = payload.get("title") or "Product"
    url = payload.get("url")
    price_s = _format_price(payload, currency_code)

    if focus == "price":
        if price_s:
            link = _product_link("View product", url)
            tail = f" {link}" if link else ""
            return f"**{title}** is {price_s}.{tail}"
        link = _product_link("View product", url)
        return f"I don't have a price indexed for **{title}**." + (f" See {link}." if link else "")

    if focus == "availability":
        stock = payload.get("stock_status") or "unknown"
        human = "in stock" if str(stock).lower() == "instock" else str(stock).replace("_", " ")
        link = _product_link("View product", url)
        tail = f" {link}" if link else ""
        return f"**{title}** is currently {human}.{tail}"

    if focus == "specs":
        attrs = payload.get("attributes") or {}
        bits: list[str] = []
        for key, val in attrs.items():
            if val in (None, "", [], {}):
                continue
            if isinstance(val, list):
                bits.append(f"{key}: {', '.join(str(v) for v in val)}")
            else:
                bits.append(f"{key}: {val}")
        link = _product_link("View product", url)
        if bits:
            body = "; ".join(bits)
            tail = f"\n\n{link}" if link else ""
            return f"**{title}** — {body}{tail}"
        return f"I don't have detailed specifications indexed for **{title}**." + (
            f" See {link}." if link else ""
        )

    if focus == "description":
        content = (payload.get("summary") or payload.get("content") or "").strip()
        link = _product_link("View product", url)
        if content:
            snippet = content[:800] + ("…" if len(content) > 800 else "")
            parts = [f"**{title}**", snippet]
            if link:
                parts.append(link)
            return "\n\n".join(parts)
        return format_product_detail(payload, message=message, focus="overview", currency_code=currency_code)

    return format_product_detail(payload, message=message, focus="overview", currency_code=currency_code)


def format_product_detail(
    payload: dict[str, Any],
    *,
    message: str | None = None,
    focus: ProductDetailFocus | None = None,
    currency_code: str | None = None,
) -> str:
    if message and focus is None:
        return format_product_detail_for_message(payload, message, currency_code=currency_code)

    active_focus = focus or "overview"
    title = payload.get("title") or "Product"
    url = payload.get("url")

    if active_focus == "price":
        return format_product_detail_for_message(payload, "what is the price", currency_code=currency_code)

    parts = [f"**{title}**"]
    price_s = _format_price(payload, currency_code)
    if price_s:
        parts.append(f"Price: {price_s}")
    rating = payload.get("rating")
    review_count = payload.get("review_count")
    if rating not in (None, ""):
        rc = f" ({review_count} reviews)" if review_count else ""
        parts.append(f"Rating: {rating}{rc}")
    stock = payload.get("stock_status")
    if stock:
        parts.append(f"Availability: {stock}")
    attrs = payload.get("attributes") or {}
    if attrs:
        attr_bits = []
        for key, val in attrs.items():
            if val in (None, "", [], {}):
                continue
            if isinstance(val, list):
                attr_bits.append(f"{key}: {', '.join(str(v) for v in val)}")
            else:
                attr_bits.append(f"{key}: {val}")
        if attr_bits:
            parts.append("Specifications: " + "; ".join(attr_bits))
    content = (payload.get("content") or payload.get("summary") or "").strip()
    if content and active_focus in ("overview", "description"):
        snippet = content[:1200] + ("…" if len(content) > 1200 else "")
        parts.append(snippet)
    link = _product_link("View product", url)
    if link:
        parts.append(link)
    return "\n\n".join(parts)
