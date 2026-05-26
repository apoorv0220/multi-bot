from __future__ import annotations

from typing import Any

from commerce.currency import default_currency_code, format_money, normalize_currency_code

from retrieval.tools.product_detail_focus import (
    ProductDetailFocus,
    format_product_detail,
    format_product_detail_for_message,
    infer_product_detail_focus,
)


def _resolve_currency(payload: dict[str, Any], currency_code: str | None) -> str:
    if currency_code:
        return normalize_currency_code(currency_code) or default_currency_code()
    raw = payload.get("currency")
    return normalize_currency_code(str(raw) if raw else None) or default_currency_code()


def format_product_compare_multi(
    products: list[dict[str, Any]],
    *,
    currency_code: str | None = None,
) -> str:
    if len(products) < 2:
        return "Name at least two products to compare."
    lines = ["Product comparison:", ""]
    labels = "ABCDEFGH"
    for idx, payload in enumerate(products[:3]):
        label = labels[idx] if idx < len(labels) else str(idx + 1)
        title = payload.get("title") or "Product"
        price = payload.get("price")
        code = _resolve_currency(payload, currency_code)
        price_s = format_money(price, code) if price not in (None, "") else "N/A"
        rating = payload.get("rating")
        rating_s = str(rating) if rating not in (None, "") else "N/A"
        url = payload.get("url")
        link = f"[{title}]({url})" if url else title
        lines.append(f"**{label}: {link}** — Price: {price_s}, Rating: {rating_s}")
    lines.append("")
    lines.append("Open each link for full specifications.")
    return "\n".join(lines)


def format_product_compare(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    currency_code: str | None = None,
) -> str:
    return format_product_compare_multi([a, b], currency_code=currency_code)
    lines = ["Product comparison:", ""]
    for label, payload in [("A", a), ("B", b)]:
        title = payload.get("title") or "Product"
        price = payload.get("price")
        code = _resolve_currency(payload, currency_code)
        price_s = format_money(price, code) if price not in (None, "") else "N/A"
        rating = payload.get("rating")
        rating_s = str(rating) if rating not in (None, "") else "N/A"
        url = payload.get("url")
        link = f"[{title}]({url})" if url else title
        lines.append(f"**{label}: {link}** — Price: {price_s}, Rating: {rating_s}")
    lines.append("")
    lines.append("Open each link for full specifications.")
    return "\n".join(lines)


def format_variant_facets(payload: dict[str, Any], *, facet: str = "color") -> str:
    title = payload.get("title") or "Product"
    attrs = payload.get("attributes") or {}
    keys = [facet]
    if facet == "color":
        keys = ["color", "colour"]
    elif facet == "size":
        keys = ["size"]
    values: list[str] = []
    for key in keys:
        raw = attrs.get(key)
        if isinstance(raw, list):
            values.extend(str(v) for v in raw if str(v).strip())
        elif raw:
            values.append(str(raw))
    values = list(dict.fromkeys(values))
    if not values:
        return f"I don't have {facet} options indexed for {title}."
    return f"Available {facet} options for {title}: {', '.join(values)}."
