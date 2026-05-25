from __future__ import annotations

from typing import Any

from commerce.currency import default_currency_code, format_money
from retrieval.match_quality import ProductMatchScore


def compose_validation_relaxation_intro(validation_meta: dict[str, Any] | None) -> str:
    meta = validation_meta or {}
    parts: list[str] = []
    dropped = meta.get("dropped_brands") or []
    if dropped:
        brands = ", ".join(str(b) for b in dropped[:3])
        parts.append(f"We don't carry {brands} in this store.")
    soft_facets = meta.get("soft_facets") or {}
    if soft_facets:
        bits: list[str] = []
        for facet_id, values in soft_facets.items():
            if not values:
                continue
            label = facet_id.replace("_", " ")
            bits.append(f"{label} {'/'.join(str(v) for v in values[:3])}")
        if bits:
            parts.append(
                "Some requested filters (" + "; ".join(bits) + ") are approximate — results may be close matches."
            )
    soft_categories = meta.get("soft_categories") or []
    if soft_categories:
        cats = ", ".join(str(c) for c in soft_categories[:3])
        parts.append(f"'{cats}' isn't an exact category here; showing the closest matches.")
    return " ".join(parts).strip()


def compose_search_intro(
    *,
    scores: list[ProductMatchScore],
    response_subtype: str,
    price_max: float | None = None,
    price_min: float | None = None,
    validation_meta: dict[str, Any] | None = None,
    currency_code: str | None = None,
) -> str:
    code = currency_code or default_currency_code()
    relaxation = compose_validation_relaxation_intro(validation_meta)
    if response_subtype == "zero_hit":
        bound = ""
        if price_max is not None:
            bound = f" under {format_money(price_max, code)}"
        elif price_min is not None:
            bound = f" over {format_money(price_min, code)}"
        base = f"I couldn't find products matching all your criteria{bound}."
        return f"{base} {relaxation}".strip() if relaxation else base

    if not scores:
        return relaxation

    full = sum(1 for s in scores if s.match_quality == "full")
    partial = sum(1 for s in scores if s.match_quality == "partial")
    alt = sum(1 for s in scores if s.match_quality == "alternative")

    if response_subtype == "product_search" or (full and not partial and not alt):
        return relaxation

    if full and (partial or alt):
        parts = [f"I found {full} exact match{'es' if full != 1 else ''}"]
        if partial:
            parts.append(f"{partial} close match{'es' if partial != 1 else ''}")
        if alt:
            parts.append(f"{alt} alternative{'s' if alt != 1 else ''}")
        intro = "; ".join(parts) + "."
        return f"{intro} {relaxation}".strip() if relaxation else intro

    if not full and (partial or alt):
        missed: set[str] = set()
        for s in scores:
            missed.update(s.missed_constraints)
        miss_bits = ", ".join(sorted(missed)) if missed else "some filters"
        price_bit = ""
        if price_max is not None:
            price_bit = f" under {format_money(price_max, code)}"
        intro = (
            f"I couldn't find an exact match for {miss_bits}{price_bit}. "
            f"Here are some related options:"
        )
        return f"{intro} {relaxation}".strip() if relaxation else intro

    return relaxation


def compose_category_plp_intro(*, showing: int, total: int | None, website_url: str | None = None) -> str:
    if total and total > showing:
        intro = (
            f"Here are {showing} top products from our catalog"
            f" (showing {showing} of {total}). Browse the full range using the link below."
        )
    else:
        intro = f"Here are {showing} products from our catalog."
    site = (website_url or "").rstrip("/")
    if site:
        intro = f"{intro}\n\nBrowse the [full catalog on our website]({site})."
    return intro


def compose_list_categories_intro(count: int) -> str:
    return f"We carry products in {count} categories:"


def compose_not_in_catalog(category: str, available: list[str]) -> str:
    cats = ", ".join(available[:8]) if available else "our listed categories"
    return (
        f"We don't have a '{category}' category in this store. "
        f"Available categories include: {cats}."
    )


def compose_category_availability(category: str, *, found: bool) -> str:
    if found:
        return f"Yes, we carry {category}. Here are some options:"
    return f"We don't currently list {category} in our catalog."


def compose_guided_discovery(*, category_names: list[str]) -> str:
    preview = ", ".join(category_names[:6]) if category_names else "clothing and accessories"
    return (
        f"I can help you find products. We have categories such as {preview}. "
        f"What are you shopping for — occasion, budget, or a product type?"
    )


def compose_general_capabilities(*, brand: str) -> str:
    return (
        f"Hi! I'm the shopping assistant for {brand}. I can search products, "
        f"list categories, answer questions about items, and explain store policies."
    )


def compose_gibberish_fallback(*, currency_code: str | None = None) -> str:
    code = currency_code or default_currency_code()
    example = format_money(60, code)
    return (
        "I didn't quite understand that. Try asking about a product type, "
        f'colour, size, or budget — for example: "Show me men\'s jackets under {example}".'
    )


def loader_stage_for_subtype(subtype: str | None) -> str | None:
    from retrieval.response_contract import LOADER_STAGES

    if not subtype:
        return None
    return LOADER_STAGES.get(subtype)
