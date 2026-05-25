from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval.match_quality import ProductMatchScore, classify_match_quality_for_results, finalize_response_subtype
from retrieval.response_composer import (
    compose_category_availability,
    compose_category_plp_intro,
    compose_general_capabilities,
    compose_gibberish_fallback,
    compose_guided_discovery,
    compose_list_categories_intro,
    compose_search_intro,
    loader_stage_for_subtype,
)
from retrieval.subtype_classifier import SubtypeClassification, classify_response_subtype
from retrieval.tools.list_categories import find_category_in_profile, list_categories_from_profile
from retrieval.tools.not_in_catalog import build_not_in_catalog_response
from commerce.currency import currency_from_profile
from retrieval.tools.product_detail import format_product_compare, format_product_detail, format_variant_facets
from retrieval.tools.product_refs import find_product_in_results, resolve_product_ref
from retrieval.tools.category_sample import build_category_actions, resolve_plp_category
from retrieval.tools.sort_browse import sort_browse_label, sort_results_by_mode
from retrieval.structured_query import StructuredQuery


@dataclass
class CommerceTurnExtras:
    response_subtype: str = "product_search"
    categories: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    products: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    match_scores: list[ProductMatchScore] = field(default_factory=list)
    intro_text: str = ""
    skip_catalog_llm: bool = False


_CATALOG_INTENT_SUBTYPES = frozenset({
    "product_search",
    "sort_browse",
    "category_plp_sample",
    "category_availability",
    "product_detail",
    "variant_facets",
    "product_compare",
    "similar_products",
    "zero_hit",
})


def ensure_commerce_catalog_intent(
    structured_query: StructuredQuery,
    classification: SubtypeClassification,
) -> StructuredQuery:
    """Browse/sort/detail turns must run catalog retrieval even when QU intent=general."""
    needs_catalog = (
        classification.response_subtype in _CATALOG_INTENT_SUBTYPES
        or classification.sort is not None
        or bool(structured_query.sort)
    )
    if not needs_catalog or structured_query.intent == "catalog":
        return structured_query
    updated = structured_query.copy()
    updated.intent = "catalog"
    if classification.sort and not updated.sort:
        updated.sort = classification.sort
    return updated


def classify_turn(
    message: str,
    *,
    structured_query: StructuredQuery,
    session_state: dict[str, Any] | None,
    profile: dict[str, Any] | None,
) -> SubtypeClassification:
    return classify_response_subtype(
        message,
        structured_query=structured_query,
        session_state=session_state,
        profile=profile,
    )


def session_structured_query_for_writeback(
    *,
    structured_query: StructuredQuery,
    session_state: dict[str, Any],
    classification: SubtypeClassification,
) -> StructuredQuery:
    if classification.preserve_catalog_session:
        prior = session_state.get("structured_query") or {}
        if prior.get("intent") == "catalog" or prior.get("category", {}).get("values"):
            return StructuredQuery.from_dict(prior)
    return structured_query


def apply_sort_to_results(results: list[Any], structured_query: StructuredQuery, classification: SubtypeClassification) -> list[Any]:
    sort_mode = structured_query.sort or classification.sort
    return sort_results_by_mode(results, sort_mode)


def score_and_label_products(
    card_results: list[Any],
    *,
    structured_query: StructuredQuery,
    user_message: str,
    profile: dict[str, Any] | None,
    retrieval_plan: Any,
    price_relaxed: bool,
    retrieval_tier: str | None,
    base_subtype: str,
) -> CommerceTurnExtras:
    scored_results, match_scores = classify_match_quality_for_results(
        card_results,
        structured_query=structured_query,
        user_message=user_message,
        profile=profile,
        category_hint_terms=list(getattr(retrieval_plan, "category_hint_terms", None) or []),
        price_relaxed=price_relaxed,
        retrieval_tier=retrieval_tier,
    )
    subtype = finalize_response_subtype(match_scores, base_subtype=base_subtype)
    currency = currency_from_profile(profile)
    intro = compose_search_intro(
        scores=match_scores,
        response_subtype=subtype,
        price_max=structured_query.price.max,
        price_min=structured_query.price.min,
        currency_code=currency,
    )
    return CommerceTurnExtras(
        response_subtype=subtype,
        match_scores=match_scores,
        intro_text=intro,
        meta={"loader_stage": loader_stage_for_subtype(subtype)},
    )


def build_static_response(
    message: str,
    *,
    classification: SubtypeClassification,
    structured_query: StructuredQuery,
    session_state: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    brand: str,
    website_url: str | None,
    card_results: list[Any] | None = None,
    search_results: list[Any] | None = None,
) -> CommerceTurnExtras | None:
    subtype = classification.response_subtype
    site = (website_url or "").rstrip("/")

    if subtype == "general_chat":
        if len(message.strip()) >= 6 and message.strip().isalpha() and " " not in message.strip():
            return CommerceTurnExtras(
                response_subtype="general_chat",
                intro_text=compose_gibberish_fallback(currency_code=currency_from_profile(profile)),
                skip_catalog_llm=True,
                meta={"loader_stage": loader_stage_for_subtype("general_chat")},
            )
        return CommerceTurnExtras(
            response_subtype="general_chat",
            intro_text=compose_general_capabilities(brand=brand),
            skip_catalog_llm=True,
            meta={"loader_stage": loader_stage_for_subtype("general_chat")},
        )

    if subtype == "guided_discovery":
        cats = list_categories_from_profile(profile, website_url=website_url)
        names = [c["name"] for c in cats[:8]]
        return CommerceTurnExtras(
            response_subtype="guided_discovery",
            categories=cats[:12],
            intro_text=compose_guided_discovery(category_names=names),
            skip_catalog_llm=True,
            meta={"loader_stage": loader_stage_for_subtype("guided_discovery")},
        )

    if subtype == "list_categories":
        cats = list_categories_from_profile(profile, website_url=website_url)
        return CommerceTurnExtras(
            response_subtype="list_categories",
            categories=cats,
            intro_text=compose_list_categories_intro(len(cats)),
            skip_catalog_llm=True,
            meta={"loader_stage": loader_stage_for_subtype("list_categories"), "total": len(cats)},
        )

    if subtype == "not_in_catalog":
        cat_q = classification.category_query or "that category"
        text, cats, _ = build_not_in_catalog_response(category_query=cat_q, profile=profile)
        return CommerceTurnExtras(
            response_subtype="not_in_catalog",
            categories=cats,
            intro_text=text,
            skip_catalog_llm=True,
            meta={"loader_stage": loader_stage_for_subtype("not_in_catalog")},
        )

    hits = card_results or search_results or []

    if subtype == "product_detail":
        ref = resolve_product_ref(message, session_state)
        payload = find_product_in_results(ref or {}, hits) if ref else None
        if payload:
            currency = currency_from_profile(profile)
            url = payload.get("url") or ""
            title = payload.get("title") or "Product"
            actions = []
            if url:
                actions.append({"type": "link", "label": f"View {title}", "url": url})
            products = []
            if url:
                products.append(
                    {
                        "title": title,
                        "url": url,
                        "price": payload.get("price"),
                        "brand": payload.get("brand"),
                        "image_url": payload.get("image_url"),
                        "rating": payload.get("rating"),
                        "review_count": payload.get("review_count"),
                        "currency": payload.get("currency") or currency,
                    }
                )
            return CommerceTurnExtras(
                response_subtype="product_detail",
                intro_text=format_product_detail(payload, message=message, currency_code=currency),
                skip_catalog_llm=True,
                actions=actions,
                products=products,
                meta={"loader_stage": loader_stage_for_subtype("product_detail")},
            )
        return CommerceTurnExtras(
            response_subtype="product_detail",
            intro_text="Which product would you like details for? You can name it or tap a product from the results above.",
            skip_catalog_llm=True,
        )

    if subtype == "variant_facets":
        ref = resolve_product_ref(message, session_state)
        payload = find_product_in_results(ref or {}, hits) if ref else None
        facet = "size" if "size" in message.lower() else "color"
        if payload:
            return CommerceTurnExtras(
                response_subtype="variant_facets",
                intro_text=format_variant_facets(payload, facet=facet),
                skip_catalog_llm=True,
                meta={"loader_stage": loader_stage_for_subtype("variant_facets")},
            )
        return CommerceTurnExtras(
            response_subtype="variant_facets",
            intro_text="Which product's options should I look up?",
            skip_catalog_llm=True,
        )

    if subtype == "product_compare":
        refs = (session_state or {}).get("last_product_refs") or []
        if len(refs) >= 2 and hits:
            a = find_product_in_results(refs[0], hits) or refs[0]
            b = find_product_in_results(refs[1], hits) or refs[1]
            if isinstance(a, dict) and isinstance(b, dict) and a.get("title") and b.get("title"):
                return CommerceTurnExtras(
                    response_subtype="product_compare",
                    intro_text=format_product_compare(
                        a,
                        b,
                        currency_code=currency_from_profile(profile),
                    ),
                    skip_catalog_llm=True,
                )
        return CommerceTurnExtras(
            response_subtype="product_compare",
            intro_text="Name two products to compare, or browse two items first.",
            skip_catalog_llm=True,
        )

    if subtype == "category_availability":
        cat_q = classification.category_query or message
        cat = find_category_in_profile(cat_q, profile)
        found = bool(cat)
        actions = build_category_actions(category=cat, website_url=website_url) if cat else []
        return CommerceTurnExtras(
            response_subtype="category_availability",
            actions=actions,
            intro_text=compose_category_availability(cat_q, found=found),
            skip_catalog_llm=not found,
            meta={"loader_stage": loader_stage_for_subtype("category_availability")},
        )

    if subtype == "category_plp_sample" and hits:
        cat = None if classification.browse_all else resolve_plp_category(message, structured_query, profile)
        actions = build_category_actions(category=cat, website_url=website_url)
        intro = compose_category_plp_intro(
            showing=len(hits),
            total=None,
            website_url=website_url,
        )
        return CommerceTurnExtras(
            response_subtype="category_plp_sample",
            actions=actions,
            intro_text=intro,
            skip_catalog_llm=True,
            meta={"loader_stage": loader_stage_for_subtype("category_plp_sample"), "showing": len(hits)},
        )

    if subtype == "sort_browse" and hits:
        sorted_hits = sort_results_by_mode(hits, classification.sort or structured_query.sort)
        has_sales = any((getattr(r, "payload", None) or {}).get("total_sales") for r in sorted_hits)
        has_dates = any(
            (getattr(r, "payload", None) or {}).get("created_at")
            or (getattr(r, "payload", None) or {}).get("updated_at")
            for r in sorted_hits
        )
        label = sort_browse_label(classification.sort, has_sales=has_sales, has_dates=has_dates)
        return CommerceTurnExtras(
            response_subtype="sort_browse",
            intro_text=f"Here are our {label} products:",
            meta={
                "loader_stage": loader_stage_for_subtype("sort_browse"),
                "sort": classification.sort or structured_query.sort,
                "showing": len(sorted_hits),
            },
        )

    return None
