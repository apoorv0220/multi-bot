"""Acceptance matrix rows → golden eval records (Phase 0c)."""

from __future__ import annotations

import re
from typing import Any


def _slug(text: str, prefix: str = "acc") -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]
    return f"{prefix}-{base}"


def _row(
    utterance: str,
    expected_intent: str,
    *,
    section: str,
    status: str = "",
    notes: str = "",
    expected_policy: str = "proceed",
    expected_merge: str | None = None,
    expected_execution: str | None = None,
    eval_layers: list[str] | None = None,
    tags: list[str] | None = None,
    session_seed: dict[str, Any] | None = None,
    row_id: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": row_id or _slug(utterance, prefix=f"acc-{section[:8]}"),
        "utterance": utterance,
        "expected_intent": expected_intent,
        "source": "acceptance",
        "expected_policy": expected_policy,
        "eval_layers": eval_layers or ["nlu"],
        "tags": tags or ["acceptance", section.replace(" ", "_")],
    }
    if notes:
        record["notes"] = notes
    if status:
        record["notes"] = "; ".join(x for x in [record.get("notes"), f"status={status}"] if x)
    if expected_merge:
        record["expected_merge"] = expected_merge
        record["eval_layers"] = ["nlu", "policy"]
    if expected_execution:
        record["expected_execution"] = expected_execution
    if session_seed:
        record["session_seed"] = session_seed
        record["eval_layers"] = ["nlu", "policy"]
    return record


def acceptance_rows() -> list[dict[str, Any]]:
    """One golden row per query in commerce-feedback-and-acceptance.md matrix."""
    rows: list[dict[str, Any]] = []

    def add(section: str, utterance: str, intent: str, **kwargs: Any) -> None:
        rows.append(_row(utterance, intent, section=section, **kwargs))

    # Ambiguous queries
    sec = "ambiguous"
    add(sec, "Show me shoes", "new_search", status="handled (partial)")
    add(sec, "I want something cheap", "new_search", status="handled (partial)")
    add(sec, "Show me good products", "new_search", status="handled (partial)")
    add(sec, "I need clothes", "new_search", status="handled (partial)")
    add(sec, "Show me something nice", "new_search", status="handled (partial)")
    add(sec, "I want to buy something for daily use", "new_search", status="handled (partial)")
    add(sec, "Show me options", "expand_search", status="handled (partial)")

    # Multi-intent
    sec = "multi_intent"
    add(
        sec,
        "Find jackets under $150 and compare top 3",
        "comparison",
        status="handled (partial)",
        eval_layers=["nlu", "policy"],
    )
    add(sec, "Red dresses and sort by price low to high", "new_search", status="handled (partial)")
    add(
        sec,
        "Similar products and filter by size M",
        "refine_search",
        status="handled (partial)",
        notes="similar + facet stack",
    )
    add(
        sec,
        "Show me items under $100 and add cheapest to cart",
        "cart_management",
        status="out_of_scope",
        expected_execution="coming_soon",
        notes="cart not implemented; NLU still classifies",
    )
    add(
        sec,
        "Recommend under $50 and add to wishlist",
        "cart_management",
        status="out_of_scope",
        expected_execution="coming_soon",
    )

    # Contextual follow-ups
    sec = "contextual"
    add(sec, "Show me shoes under $100", "new_search", status="handled")
    add(
        sec,
        "Now only show black ones",
        "refine_search",
        status="handled",
        expected_merge="inherit",
        session_seed={"structured_query": {"intent": "catalog"}, "filter_stack": []},
    )
    add(
        sec,
        "Only size 9",
        "refine_search",
        status="handled (partial)",
        expected_merge="inherit",
        session_seed={"structured_query": {"intent": "catalog"}},
    )
    add(
        sec,
        "Sort by rating",
        "refine_search",
        status="handled (partial)",
        expected_merge="inherit",
    )
    add(
        sec,
        "Add first one to cart",
        "cart_management",
        status="out_of_scope",
        expected_execution="coming_soon",
    )

    # Sorting and pagination
    sec = "sorting"
    add(sec, "Sort by price low to high", "refine_search", status="handled")
    add(sec, "Sort by highest rating", "refine_search", status="handled")
    add(sec, "Show top rated products", "new_search", status="handled (partial)")
    add(
        sec,
        "Show next page",
        "refine_search",
        status="out_of_scope",
        notes="true pagination out_of_scope; intent maps to session refine",
    )
    add(sec, "Show more results", "refine_search", status="handled (partial)")
    add(sec, "Show only top 5 products", "refine_search", status="handled")

    # Reviews and ratings
    sec = "reviews"
    add(
        sec,
        "Show product reviews",
        "product_detail",
        status="out_of_scope",
        notes="review body not indexed; detail intent",
    )
    add(sec, "What do customers say about this?", "product_detail", status="out_of_scope")
    add(sec, "What is the rating of this product?", "product_detail", status="handled")
    add(sec, "Show 5-star rated products", "new_search", status="handled")
    add(sec, "Show products with rating above 4", "new_search", status="handled")

    # Discounts and deals
    sec = "deals"
    add(sec, "Show products on sale", "deals_browse", status="handled (partial)")
    add(sec, "What products have discounts?", "deals_browse", status="handled (partial)")
    add(sec, "Show clearance items", "deals_browse", status="handled (partial)")
    add(sec, "What is the discount on this product?", "product_detail", status="handled (partial)")
    add(
        sec,
        "Show buy 1 get 1 offers",
        "deals_browse",
        status="out_of_scope",
        notes="no promo engine",
    )
    add(sec, "Show best deals under $100", "deals_browse", status="handled (partial)")

    # Inventory and availability
    sec = "inventory"
    add(sec, "Show only in-stock products", "in_stock_only", status="handled")
    add(
        sec,
        "Notify me when this is available",
        "variant_availability",
        status="out_of_scope",
        notes="alerts out_of_scope",
    )
    add(sec, "Is this available in my size?", "variant_availability", status="handled (partial)")
    add(
        sec,
        "Show limited stock items",
        "in_stock_only",
        status="out_of_scope",
        notes="no low-stock field",
    )
    add(sec, "Is this discontinued?", "product_detail", status="out_of_scope")

    # Location-based
    sec = "location"
    add(sec, "Do you deliver to my location?", "delivery_before_buy", status="handled (partial)")
    add(sec, "Delivery time for my location", "delivery_before_buy", status="handled (partial)")
    add(
        sec,
        "Products available in my region",
        "not_in_catalog",
        status="out_of_scope",
        notes="no geo inventory",
    )
    add(sec, "Is cash on delivery available?", "support_faq", status="handled (partial)")

    # Payment queries
    sec = "payment"
    add(sec, "What payment methods are available?", "support_faq", status="handled (partial)")
    add(sec, "Can I pay using PayPal?", "support_faq", status="handled (partial)")
    add(sec, "Is EMI available?", "support_faq", status="handled (partial)")
    add(
        sec,
        "Why is my payment failing?",
        "payment_support",
        status="out_of_scope",
        expected_execution="coming_soon",
    )
    add(
        sec,
        "Apply coupon SAVE10",
        "checkout_facilitation",
        status="out_of_scope",
        expected_execution="coming_soon",
    )
    add(
        sec,
        "Why is coupon not working?",
        "payment_support",
        status="out_of_scope",
        expected_execution="coming_soon",
    )

    # Account issues
    sec = "account"
    add(
        sec,
        "Forgot password",
        "account_support",
        status="out_of_scope",
        expected_execution="coming_soon",
    )
    add(
        sec,
        "I cannot login",
        "account_support",
        status="out_of_scope",
        expected_execution="coming_soon",
    )
    add(
        sec,
        "My order is not showing",
        "order_tracking",
        status="out_of_scope",
        expected_execution="coming_soon",
    )
    add(
        sec,
        "Payment deducted but order not placed",
        "order_tracking",
        status="out_of_scope",
        expected_execution="coming_soon",
    )
    add(
        sec,
        "Update my email address",
        "account_support",
        status="out_of_scope",
        expected_execution="coming_soon",
    )

    # Intent switching
    sec = "intent_switch"
    add(sec, "Show shoes under $100", "new_search", status="handled", row_id="acc-switch-shoes-100")
    add(sec, "Actually show jackets instead", "pivot", status="handled (partial)", expected_merge="replace")
    add(sec, "No, go back to shoes", "backtrack", status="handled (partial)", expected_merge="backtrack")
    add(sec, "Show premium ones", "refine_search", status="handled (partial)", expected_merge="inherit")

    # Synonyms
    sec = "synonyms"
    add(sec, "Show budget shoes", "new_search", status="handled (partial)")
    add(sec, "Show premium jackets", "new_search", status="handled (partial)")
    add(sec, "Show best quality products", "new_search", status="handled (partial)")
    add(sec, "Show affordable options", "new_search", status="handled (partial)")

    # Conflicting
    sec = "conflicting"
    add(
        sec,
        "Cheap but premium",
        "new_search",
        status="handled (partial)",
        notes="conflicting price signals",
    )
    add(sec, "Cheapest high-end items", "new_search", status="handled (partial)")

    # Invalid
    sec = "invalid"
    add(
        sec,
        "Under $0",
        "new_search",
        status="handled",
        expected_policy="clarify",
        notes="invalid price; policy should clarify",
        eval_layers=["nlu", "policy"],
    )
    add(sec, "Size XXXL", "refine_search", status="handled (partial)")
    add(sec, "Show invisible products", "not_in_catalog", status="handled (partial)")
    add(sec, "Products from Mars", "not_in_catalog", status="handled")

    # Garbage
    sec = "garbage"
    add(sec, "asdfghjkl", "nlu_fallback", status="handled", tags=["acceptance", "garbage"])
    add(sec, "123456", "nlu_fallback", status="handled", row_id="acc-garbage-numeric")
    add(sec, "!!!!!!", "nlu_fallback", status="handled", row_id="acc-garbage-punct")
    add(sec, "🔥", "nlu_fallback", status="handled", row_id="acc-garbage-emoji")

    # Human / vague shopper
    sec = "vague"
    add(sec, "Something for office wear", "new_search", status="handled (partial)")
    add(sec, "Suggest something for summer", "new_search", status="handled (partial)")
    add(sec, "Stylish but not too expensive", "new_search", status="handled (partial)")
    add(sec, "Gift for my wife", "new_search", status="handled (partial)")
    add(sec, "Show me something trendy", "new_search", status="handled (partial)")
    add(sec, "What are people buying these days?", "new_search", status="handled (partial)")

    return rows


def manual_rows() -> list[dict[str, Any]]:
    """Confused pairs, clarify triggers, multi-turn, and registry gap-fill."""
    rows: list[dict[str, Any]] = [
        {
            "id": "gen-greeting-01",
            "utterance": "Hello!",
            "expected_intent": "greeting",
            "source": "generated",
            "expected_policy": "proceed",
            "eval_layers": ["nlu"],
            "tags": ["greeting"],
        },
        {
            "id": "gen-clarification-user-confused",
            "utterance": "I don't understand what you mean",
            "expected_intent": "clarification",
            "source": "generated",
            "expected_policy": "proceed",
            "eval_layers": ["nlu"],
            "tags": ["clarification"],
            "notes": "user confused; not bot clarify policy",
        },
        {
            "id": "gen-list-categories",
            "utterance": "What categories do you have?",
            "expected_intent": "list_categories",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-variant-list",
            "utterance": "What colors does this jacket come in?",
            "expected_intent": "variant_list",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-size-guide",
            "utterance": "What size should I pick?",
            "expected_intent": "size_guide",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-similar",
            "utterance": "Show me something similar to this",
            "expected_intent": "similar_products",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-affirmation-yes",
            "utterance": "Yes, that's the one",
            "expected_intent": "affirmation",
            "source": "generated",
            "expected_policy": "proceed",
            "eval_layers": ["nlu", "policy"],
            "session_seed": {"pending_clarification": {"slot": "product_name"}},
            "tags": ["affirmation", "mt-flow"],
        },
        # Confused pairs: product_detail vs variant_availability (3+ each)
        {
            "id": "pair-detail-01",
            "utterance": "Tell me about the Nike Air Max",
            "expected_intent": "product_detail",
            "source": "manual",
            "eval_layers": ["nlu"],
            "tags": ["confused_pair", "product_detail"],
        },
        {
            "id": "pair-detail-02",
            "utterance": "What is the description of the blue hoodie?",
            "expected_intent": "product_detail",
            "source": "manual",
            "eval_layers": ["nlu"],
            "tags": ["confused_pair", "product_detail"],
        },
        {
            "id": "pair-detail-03",
            "utterance": "Give me specs for the running shoes",
            "expected_intent": "product_detail",
            "source": "manual",
            "eval_layers": ["nlu"],
            "tags": ["confused_pair", "product_detail"],
        },
        {
            "id": "pair-avail-01",
            "utterance": "Is the Nike Air Max in stock?",
            "expected_intent": "variant_availability",
            "source": "manual",
            "eval_layers": ["nlu"],
            "tags": ["confused_pair", "variant_availability"],
        },
        {
            "id": "pair-avail-02",
            "utterance": "Do you have size M in the blue hoodie?",
            "expected_intent": "variant_availability",
            "source": "manual",
            "eval_layers": ["nlu"],
            "tags": ["confused_pair", "variant_availability"],
        },
        {
            "id": "pair-avail-03",
            "utterance": "Tell me about the Nike Air Max stock",
            "expected_intent": "variant_availability",
            "source": "manual",
            "eval_layers": ["nlu"],
            "tags": ["confused_pair", "variant_availability"],
            "notes": "ambiguous phrasing; availability over detail",
        },
        # Confused pairs: new_search vs refine_search
        {
            "id": "pair-search-01",
            "utterance": "Show me men's jackets",
            "expected_intent": "new_search",
            "source": "manual",
            "eval_layers": ["nlu"],
            "tags": ["confused_pair", "new_search"],
        },
        {
            "id": "pair-search-02",
            "utterance": "I'm looking for running shoes",
            "expected_intent": "new_search",
            "source": "manual",
            "eval_layers": ["nlu"],
            "tags": ["confused_pair", "new_search"],
        },
        {
            "id": "pair-search-03",
            "utterance": "Browse winter coats",
            "expected_intent": "new_search",
            "source": "manual",
            "eval_layers": ["nlu"],
            "tags": ["confused_pair", "new_search"],
        },
        {
            "id": "pair-refine-01",
            "utterance": "Only in blue",
            "expected_intent": "refine_search",
            "source": "manual",
            "eval_layers": ["nlu", "policy"],
            "expected_merge": "inherit",
            "session_seed": {"structured_query": {"intent": "catalog"}},
            "tags": ["confused_pair", "refine_search"],
        },
        {
            "id": "pair-refine-02",
            "utterance": "Make them under fifty dollars",
            "expected_intent": "refine_search",
            "source": "manual",
            "eval_layers": ["nlu", "policy"],
            "expected_merge": "inherit",
            "tags": ["confused_pair", "refine_search"],
        },
        {
            "id": "pair-refine-03",
            "utterance": "Filter to large sizes only",
            "expected_intent": "refine_search",
            "source": "manual",
            "eval_layers": ["nlu", "policy"],
            "expected_merge": "inherit",
            "tags": ["confused_pair", "refine_search"],
        },
        # Clarify rows (>=10)
        {
            "id": "gen-clarify-referent-01",
            "utterance": "Is that one in stock?",
            "expected_intent": "variant_availability",
            "expected_policy": "clarify",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "session_seed": {
                "last_result_context": [{"title": "Blue Hoodie"}, {"title": "Red Hoodie"}]
            },
            "tags": ["referent", "clarify"],
        },
        {
            "id": "gen-clarify-referent-02",
            "utterance": "What about the first one?",
            "expected_intent": "product_detail",
            "expected_policy": "clarify",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "session_seed": {
                "last_result_context": [{"title": "Item A"}, {"title": "Item B"}, {"title": "Item C"}]
            },
            "tags": ["referent", "clarify"],
        },
        {
            "id": "gen-clarify-variant-no-product",
            "utterance": "Is purple size S available?",
            "expected_intent": "variant_availability",
            "expected_policy": "clarify",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "tags": ["clarify", "variant"],
            "notes": "missing product_name referent",
        },
        {
            "id": "gen-clarify-ambiguous-intent",
            "utterance": "help",
            "expected_intent": "nlu_fallback",
            "expected_policy": "clarify",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "tags": ["clarify"],
        },
        {
            "id": "gen-clarify-confirm-reset",
            "utterance": "start over completely",
            "expected_intent": "pivot",
            "expected_policy": "confirm",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "expected_merge": "clear",
            "tags": ["clarify", "reset"],
        },
        {
            "id": "gen-clarify-price-absurd",
            "utterance": "Show me things under negative ten dollars",
            "expected_intent": "new_search",
            "expected_policy": "clarify",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "tags": ["clarify"],
        },
        {
            "id": "gen-clarify-which-color",
            "utterance": "in that color",
            "expected_intent": "refine_search",
            "expected_policy": "clarify",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "session_seed": {"structured_query": {"intent": "catalog"}},
            "tags": ["clarify"],
        },
        {
            "id": "gen-clarify-two-intents",
            "utterance": "track my order and show me shoes",
            "expected_intent": "order_tracking",
            "expected_policy": "clarify",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "tags": ["clarify", "multi_intent"],
            "notes": "multi-intent may need disambiguation",
        },
        {
            "id": "gen-clarify-empty-followup",
            "utterance": "and also",
            "expected_intent": "refine_search",
            "expected_policy": "clarify",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "tags": ["clarify"],
        },
        {
            "id": "gen-clarify-compare-need-two",
            "utterance": "Compare them",
            "expected_intent": "comparison",
            "expected_policy": "clarify",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "tags": ["clarify"],
            "notes": "needs two product referents",
        },
        # Multi-turn session_seed rows (>=5 beyond acceptance contextual)
        {
            "id": "mt-drill-down-04",
            "utterance": "Keep it under $60",
            "expected_intent": "refine_search",
            "expected_policy": "proceed",
            "expected_merge": "inherit",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "session_seed": {
                "structured_query": {
                    "intent": "catalog",
                    "facets": {"color": {"values": ["blue"]}, "size": {"values": ["l"]}},
                }
            },
            "tags": ["mt-flow"],
        },
        {
            "id": "mt-negation-follow",
            "utterance": "And no polyester",
            "expected_intent": "refine_search",
            "expected_policy": "proceed",
            "expected_merge": "inherit",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "session_seed": {"structured_query": {"intent": "catalog"}},
            "tags": ["mt-flow"],
        },
        {
            "id": "mt-backtrack-context",
            "utterance": "Never mind, show tanks instead",
            "expected_intent": "pivot",
            "expected_policy": "proceed",
            "expected_merge": "replace",
            "source": "generated",
            "eval_layers": ["nlu", "policy"],
            "session_seed": {"structured_query": {"intent": "catalog", "categories": ["jackets"]}},
            "tags": ["mt-flow"],
        },
        # coming_soon gap-fill
        {
            "id": "gen-returns-01",
            "utterance": "I want to return this item",
            "expected_intent": "returns",
            "expected_execution": "coming_soon",
            "expected_policy": "proceed",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-delivery-issue-01",
            "utterance": "My package arrived damaged",
            "expected_intent": "delivery_issue",
            "expected_execution": "coming_soon",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-delivery-tracking-01",
            "utterance": "Where is my delivery?",
            "expected_intent": "delivery_tracking",
            "expected_execution": "coming_soon",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-store-info-01",
            "utterance": "What are your store hours?",
            "expected_intent": "store_info",
            "expected_execution": "coming_soon",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-feedback-01",
            "utterance": "I want to leave feedback",
            "expected_intent": "feedback",
            "expected_execution": "coming_soon",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-product-issue-01",
            "utterance": "The product I received is defective",
            "expected_intent": "product_issue",
            "expected_execution": "coming_soon",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-order-cancel-01",
            "utterance": "Cancel my order please",
            "expected_intent": "order_cancellation",
            "expected_execution": "coming_soon",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-order-modify-01",
            "utterance": "Change the shipping address on my order",
            "expected_intent": "order_modification",
            "expected_execution": "coming_soon",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
        {
            "id": "gen-checkout-01",
            "utterance": "I'm ready to checkout",
            "expected_intent": "checkout_facilitation",
            "expected_execution": "coming_soon",
            "source": "generated",
            "eval_layers": ["nlu"],
        },
    ]
    return rows
