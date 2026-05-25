from __future__ import annotations

import json
from typing import Any

from retrieval.filter_adherence import filter_adherence_instruction
from retrieval.post_filter import MatchMode, RetrievalTier, catalog_match_mode_instruction


def products_within_price_bounds(
    products: list[Any],
    *,
    price_min: float | None = None,
    price_max: float | None = None,
) -> list[Any]:
    if price_min is None and price_max is None:
        return list(products)
    kept: list[Any] = []
    for product in products:
        price = getattr(product, "price", None)
        if price is None:
            continue
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue
        if price_min is not None and value < price_min:
            continue
        if price_max is not None and value > price_max:
            continue
        kept.append(product)
    return kept


def format_products_for_prompt(products: list[Any], *, limit: int = 10) -> str:
    rows: list[dict[str, Any]] = []
    for product in products[:limit]:
        row: dict[str, Any] = {
            "title": getattr(product, "title", None) or "Product",
            "url": getattr(product, "url", None) or "",
        }
        price = getattr(product, "price", None)
        if price is not None:
            row["price"] = price
        brand = getattr(product, "brand", None)
        if brand:
            row["brand"] = brand
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False)


def build_catalog_grounded_system_prompt(
    brand: str,
    *,
    match_mode: MatchMode | str | None = None,
    retrieval_tier: RetrievalTier | str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    price_relaxed: bool = False,
    site_clause: str = "",
    filter_adherence: dict[str, Any] | None = None,
    products_empty: bool = False,
) -> str:
    mode_note = catalog_match_mode_instruction(match_mode) if match_mode and match_mode != "exact" else ""
    adherence_note = filter_adherence_instruction(
        filter_adherence,
        products_empty=products_empty,
    )
    price_rule = ""
    if price_max is not None and not price_relaxed:
        price_rule = f" Only mention products whose price is at most {price_max}."
    elif price_min is not None and not price_relaxed:
        price_rule = f" Only mention products whose price is at least {price_min}."
    tier_hint = ""
    if retrieval_tier == "relaxed_price":
        tier_hint = " Price filter was relaxed to find results."
    return (
        f"You are a shopping assistant for {brand}. "
        "You will receive a JSON array `products` — the only products you may recommend. "
        "Use exact titles and prices from that list only; do not invent products or prices. "
        "Do not mention brand names unless the product's brand field in the JSON matches that brand. "
        "Do not mention a price cap or budget unless the user asked for one or every listed product is within that cap. "
        "Mention the user can open the product URL."
        f"{(' ' + mode_note) if mode_note else ''}"
        f"{adherence_note}"
        f"{tier_hint}"
        f"{price_rule}"
        f"{site_clause} "
        "Keep the reply concise (under 300 characters). List at most 3 products when products are provided."
    )
