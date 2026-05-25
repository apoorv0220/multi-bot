from __future__ import annotations

import re
from typing import Any

from retrieval.post_filter import category_match_tier
from retrieval.post_filter import _facet_value_matches, _payload_facet_values


def _user_color_tokens(message: str) -> list[str]:
    tokens: list[str] = []
    for match in re.finditer(
        r"\b(red|blue|green|black|white|violet|purple|lavender|lilac|charcoal|sand|grey|gray|pink|yellow|orange|brown)\b",
        (message or "").lower(),
    ):
        t = match.group(1).lower()
        if t not in tokens:
            tokens.append(t)
    return tokens


def _product_categories(payload: dict[str, Any]) -> list[str]:
    return [str(c).strip().lower() for c in (payload.get("categories") or []) if str(c).strip()]


def build_filter_adherence(
    *,
    user_message: str,
    structured_query: Any,
    retrieval_plan: Any,
    card_results: list[Any],
    profile: dict[str, Any] | None,
    match_mode: str | None = None,
    retrieval_tier: str | None = None,
    dropped_filters: list[str] | None = None,
    hit_count: int = 0,
    product_card_count: int = 0,
    price_relaxed: bool = False,
) -> dict[str, Any] | None:
    """Build prompt hints when search diverged from the user's words."""
    notes: dict[str, Any] = {}
    user_colors = _user_color_tokens(user_message)
    applied_color: list[str] = []
    for key in ("color", "colour"):
        spec = structured_query.facets.get(key)
        if spec and spec.values:
            applied_color.extend(str(v).lower() for v in spec.values)

    if user_colors and applied_color:
        user_set = set(user_colors)
        applied_set = set(applied_color)
        if user_set - applied_set:
            notes["color_substitute"] = {
                "user": list(user_set),
                "applied": list(applied_set),
            }

    category_terms = list(retrieval_plan.category_hint_terms or structured_query.category.values or [])
    if category_terms and card_results:
        top = card_results[:10]
        tiers = [
            category_match_tier(getattr(r, "payload", None) or {}, category_terms, profile)
            for r in top
        ]
        if any(t >= 1 for t in tiers) and any(t < 1 for t in tiers):
            notes["category_hint_mixed"] = True

        soft_colors = dict(getattr(retrieval_plan, "soft_facet_boosts", None) or {})
        color_key = next((k for k in soft_colors if k in ("color", "colour")), None)
        if color_key and user_colors:
            cat_hits = [r for r, t in zip(top, tiers) if t >= 1]
            if cat_hits:
                color_matched = [
                    r
                    for r in cat_hits
                    if any(
                        _facet_value_matches(v, _payload_facet_values(getattr(r, "payload", None) or {}, color_key))
                        for v in soft_colors[color_key]
                    )
                ]
                if not color_matched:
                    notes["category_framed_color_miss"] = {
                        "user_colors": user_colors,
                        "category": structured_query.category.values[:2],
                        "price_max": structured_query.price.max,
                    }

    facet_excludes = {
        fid: list(spec.exclude_values)
        for fid, spec in structured_query.facets.items()
        if spec.exclude_values
    }
    if hit_count > 0 and product_card_count == 0:
        notes["hits_without_cards"] = {
            "hit_count": hit_count,
            "category": list(structured_query.category.values[:3]),
            "facets": {
                fid: list(spec.values[:3])
                for fid, spec in structured_query.facets.items()
                if spec.values
            },
            "facet_excludes": facet_excludes,
            "price_max": structured_query.price.max,
            "price_min": structured_query.price.min,
        }
    elif facet_excludes and product_card_count == 0:
        notes["facet_exclude_empty"] = {
            "hit_count": hit_count,
            "facet_excludes": facet_excludes,
            "category": list(structured_query.category.values[:3]),
        }

    if match_mode in ("relaxed", "semantic_fallback"):
        notes["imperfect_match"] = True
    if dropped_filters:
        notes["dropped_filters"] = list(dropped_filters)
    validation_meta = getattr(structured_query, "validation_meta", None) or {}
    if validation_meta.get("soft_facets"):
        notes["soft_facets"] = dict(validation_meta["soft_facets"])
    if validation_meta.get("soft_categories"):
        notes["soft_categories"] = list(validation_meta["soft_categories"])
    if validation_meta.get("dropped_brands"):
        notes["dropped_brands"] = list(validation_meta["dropped_brands"])
    if price_relaxed or retrieval_tier == "relaxed_price":
        notes["price_relaxed"] = {
            "max": structured_query.price.max,
            "min": structured_query.price.min,
        }

    return notes or None


def filter_adherence_instruction(
    adherence: dict[str, Any] | None,
    *,
    products_empty: bool = False,
) -> str:
    if not adherence and not products_empty:
        return ""
    parts: list[str] = []
    exclude_empty = (adherence or {}).get("facet_exclude_empty")
    if exclude_empty:
        excl = exclude_empty.get("facet_excludes") or {}
        excl_bits = ", ".join(f"no {vals[0]}" for vals in excl.values() if vals)
        parts.append(
            f"Active exclusions ({excl_bits}) removed all listable products from {exclude_empty.get('hit_count', 0)} matches. "
            f"Say briefly that nothing in the catalog matches those exclusions and suggest relaxing a filter."
        )
    gap = adherence.get("hits_without_cards") if adherence else None
    if gap and not exclude_empty:
        cats = ", ".join(gap.get("category") or []) or "that category"
        price = gap.get("price_max")
        price_bit = f" under {price:g}" if price is not None else ""
        excl = gap.get("facet_excludes") or {}
        excl_bits = ", ".join(f"no {vals[0]}" for vals in excl.values() if vals)
        if excl_bits:
            parts.append(
                f"Search found {gap.get('hit_count', 0)} related items but none could be listed as products "
                f"for {cats} with exclusions ({excl_bits}){price_bit}. "
                f"Say briefly that nothing listable matched those filters yet; suggest loosening an exclusion "
                f"or colour. Do not claim the catalog has zero {cats} and do not invent products."
            )
        else:
            parts.append(
                f"Search found {gap.get('hit_count', 0)} related items but none became listable products "
                f"with the active filters ({cats}{price_bit}, size, colour, etc.). "
                f"In one short sentence say you could not find an exact match for what they asked "
                f"(e.g. no red jackets in size M under $50) and suggest loosening colour, size, or price. "
                f"Do not invent products."
            )
    sub = (adherence or {}).get("color_substitute")
    if sub:
        user = ", ".join(sub.get("user") or [])
        applied = ", ".join(sub.get("applied") or [])
        parts.append(
            f"The catalog uses {applied} for colour, not {user}. "
            f"In one short sentence say you could not find {user} and these are {applied} matches, then list products."
        )
    miss = (adherence or {}).get("category_framed_color_miss")
    if miss:
        colors = ", ".join(miss.get("user_colors") or [])
        cats = ", ".join(miss.get("category") or []) or "items"
        price = miss.get("price_max")
        price_bit = f" under {price:g}" if price is not None else ""
        parts.append(
            f"In one short sentence say you could not find {colors} {cats}{price_bit}; "
            f"these are {cats} in that price range (not {colors} items). Then list the products."
        )
    price_rel = (adherence or {}).get("price_relaxed")
    if price_rel and not gap:
        bound = ""
        if price_rel.get("max") is not None and price_rel.get("min") is not None:
            bound = f"between {price_rel['min']:g} and {price_rel['max']:g}"
        elif price_rel.get("max") is not None:
            bound = f"under {price_rel['max']:g}"
        elif price_rel.get("min") is not None:
            bound = f"over {price_rel['min']:g}"
        if bound:
            parts.append(
                f"No products matched the requested price ({bound}) with the other filters. "
                f"The list shows closest alternatives without that price limit. "
                f"Say clearly that nothing matched the price, then list alternatives. "
                f"Do not claim any listed price satisfies the price limit."
            )
    if (adherence or {}).get("category_hint_mixed") and not miss:
        parts.append(
            "Category was a soft hint; some items may be nearby styles. Mention that briefly if relevant."
        )
    if (adherence or {}).get("imperfect_match") and not parts:
        parts.append(
            "We could not match every filter exactly; the products below are close matches. "
            "Say so briefly in one short sentence, then list the products."
        )
    soft_facets = (adherence or {}).get("soft_facets") or {}
    if soft_facets:
        bits = []
        for facet_id, values in soft_facets.items():
            if values:
                bits.append(f"{facet_id}={'/'.join(str(v) for v in values[:2])}")
        if bits:
            parts.append(
                "Some filters were approximate (" + ", ".join(bits) + "). "
                "Say results may be close matches, not exact filter matches."
            )
    dropped_brands = (adherence or {}).get("dropped_brands") or []
    if dropped_brands:
        parts.append(
            f"The requested brand ({', '.join(str(b) for b in dropped_brands[:2])}) is not sold here. "
            "Do not claim products are from that brand."
        )
    soft_categories = (adherence or {}).get("soft_categories") or []
    if soft_categories:
        parts.append(
            f"Category terms ({', '.join(str(c) for c in soft_categories[:2])}) were soft hints only; "
            "some items may be related alternatives."
        )
    if products_empty and not parts:
        parts.append(
            "The products array is empty. Explain honestly that nothing matched the filters; "
            "do not invent products or prices."
        )
    if not parts:
        return ""
    return " " + " ".join(parts)
