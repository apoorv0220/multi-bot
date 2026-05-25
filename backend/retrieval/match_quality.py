from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from retrieval.post_filter import _facet_value_matches, _payload_facet_values, category_match_tier
from retrieval.response_contract import MatchQuality, MixedMatchPolicy, mixed_match_policy
from retrieval.structured_query import StructuredQuery


@dataclass
class ProductMatchScore:
    match_quality: MatchQuality
    missed_constraints: list[str] = field(default_factory=list)


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


def _price_in_bounds(price: Any, *, price_min: float | None, price_max: float | None) -> bool:
    if price in (None, ""):
        return price_min is None and price_max is None
    try:
        value = float(price)
    except (TypeError, ValueError):
        return False
    if price_min is not None and value < price_min:
        return False
    if price_max is not None and value > price_max:
        return False
    return True


def _facet_constraints(structured_query: StructuredQuery, user_message: str) -> dict[str, list[str]]:
    constraints: dict[str, list[str]] = {}
    for facet_id, spec in structured_query.facets.items():
        if spec.values and not spec.exclude_values:
            constraints[facet_id] = [str(v).lower() for v in spec.values]
    user_colors = _user_color_tokens(user_message)
    if user_colors:
        key = "color" if "color" in constraints or "colour" not in constraints else "colour"
        if key not in constraints:
            constraints[key] = user_colors
    return constraints


def score_product_match(
    payload: dict[str, Any],
    *,
    structured_query: StructuredQuery,
    user_message: str,
    profile: dict[str, Any] | None,
    category_hint_terms: list[str] | None = None,
    price_relaxed: bool = False,
    retrieval_tier: str | None = None,
) -> ProductMatchScore:
    missed: list[str] = []
    hints = list(category_hint_terms or structured_query.category.values or [])

    cat_ok = True
    if hints:
        tier = category_match_tier(payload, hints, profile)
        if tier == 0:
            cat_ok = False
            missed.append("category")

    price_ok = True
    if not price_relaxed and (structured_query.price.min is not None or structured_query.price.max is not None):
        if not _price_in_bounds(payload.get("price"), price_min=structured_query.price.min, price_max=structured_query.price.max):
            price_ok = False
            missed.append("price")

    facet_ok = True
    for facet_id, values in _facet_constraints(structured_query, user_message).items():
        payload_vals = _payload_facet_values(payload, facet_id)
        if not any(_facet_value_matches(v, payload_vals) for v in values):
            facet_ok = False
            missed.append(facet_id)

    if cat_ok and price_ok and facet_ok:
        return ProductMatchScore(match_quality="full", missed_constraints=[])

    if retrieval_tier in ("semantic_catalog", "relaxed_price", "relaxed_facets", "relaxed_category"):
        if cat_ok or price_ok:
            return ProductMatchScore(match_quality="alternative", missed_constraints=missed)
        return ProductMatchScore(match_quality="alternative", missed_constraints=missed or ["filters"])

    partial_score = sum([cat_ok, price_ok, facet_ok])
    if partial_score >= 2:
        return ProductMatchScore(match_quality="partial", missed_constraints=missed)
    if partial_score == 1:
        return ProductMatchScore(match_quality="partial", missed_constraints=missed)
    return ProductMatchScore(match_quality="alternative", missed_constraints=missed or ["filters"])


def classify_match_quality_for_results(
    results: list[Any],
    *,
    structured_query: StructuredQuery,
    user_message: str,
    profile: dict[str, Any] | None,
    category_hint_terms: list[str] | None = None,
    price_relaxed: bool = False,
    retrieval_tier: str | None = None,
    policy: MixedMatchPolicy | None = None,
) -> tuple[list[Any], list[ProductMatchScore]]:
    policy = policy or mixed_match_policy(profile)
    scored: list[tuple[Any, ProductMatchScore]] = []
    for result in results:
        payload = getattr(result, "payload", None) or {}
        score = score_product_match(
            payload,
            structured_query=structured_query,
            user_message=user_message,
            profile=profile,
            category_hint_terms=category_hint_terms,
            price_relaxed=price_relaxed,
            retrieval_tier=retrieval_tier,
        )
        scored.append((result, score))

    if policy == "exact_only":
        scored = [(r, s) for r, s in scored if s.match_quality == "full"]

    order = {"full": 0, "partial": 1, "alternative": 2}
    scored.sort(key=lambda item: order.get(item[1].match_quality, 3))
    results_out = [item[0] for item in scored]
    scores_out = [item[1] for item in scored]
    return results_out, scores_out


def finalize_response_subtype(
    scores: list[ProductMatchScore],
    *,
    base_subtype: str = "product_search",
) -> str:
    if not scores:
        return "zero_hit"
    if any(s.match_quality in ("partial", "alternative") for s in scores):
        if any(s.match_quality == "full" for s in scores):
            return "product_search_mixed"
        return "product_search_mixed"
    return base_subtype
