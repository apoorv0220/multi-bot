from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from retrieval.response_contract import ResponseSubtype, SortMode
from retrieval.catalog_coverage import resolve_catalog_block
from retrieval.tools.product_refs import extract_product_title_from_message, is_product_detail_message
from retrieval.structured_query import StructuredQuery

_LIST_CATEGORIES = re.compile(
    r"\b(?:what\s+(?:products?|categories?|do\s+you\s+(?:have|sell|carry))|"
    r"what\s+categories?\s+(?:are\s+)?available|list\s+(?:all\s+)?categories?)\b",
    re.IGNORECASE,
)
_ALL_PRODUCTS = re.compile(
    r"\b(?:show\s+(?:me\s+)?(?:all|every)\s+products?|all\s+products?)\b",
    re.IGNORECASE,
)
_CATEGORY_AVAIL = re.compile(
    r"\b(?:do\s+you\s+(?:have|carry|sell)|any)\s+(?P<cat>[a-z][\w\s&'-]{1,40})\??\s*$",
    re.IGNORECASE,
)
_SORT_NEWEST = re.compile(r"\b(?:latest|new\s+arrivals?|newest|recently\s+added)\b", re.IGNORECASE)
_SORT_BEST = re.compile(r"\b(?:best[\-\s]?selling|bestsellers?|top\s+sellers?)\b", re.IGNORECASE)
_SORT_TREND = re.compile(r"\b(?:trending|popular\s+right\s+now|what(?:'s|\s+is)\s+popular)\b", re.IGNORECASE)
_SORT_CHEAP = re.compile(r"\b(?:cheapest|lowest\s+price|budget[\-\s]?friendly|something\s+cheap)\b", re.IGNORECASE)
_PRODUCT_DETAIL = re.compile(
    r"\b(?:tell\s+me\s+(?:more\s+)?about|product\s+details?|show\s+(?:product\s+)?description|"
    r"more\s+(?:info|information|details?|description)|"
    r"(?:provide|give)\s+(?:me\s+)?(?:more\s+)?(?:description|details?)|"
    r"description\s+for\s+(?:the\s+)?(?:product|item)|"
    r"what\s+is\s+the\s+price\s+of|specifications?|is\s+this\s+(?:product\s+)?(?:available|in\s+stock))\b",
    re.IGNORECASE,
)
_VARIANT = re.compile(
    r"\b(?:what\s+(?:colors?|colours?|sizes?)\s+(?:are\s+)?available|all\s+(?:color|colour|size)\s+options?)\b",
    re.IGNORECASE,
)
_COMPARE = re.compile(
    r"\b(?:compare\s+(?:these\s+two\s+products?|prices?)|which\s+is\s+better)\b",
    re.IGNORECASE,
)
_SIMILAR = re.compile(
    r"\b(?:similar\s+products?|alternatives?\s+to|something\s+like\s+this|like\s+this\s+but\s+cheaper)\b",
    re.IGNORECASE,
)
_SUPPORT = re.compile(
    r"\b(?:return\s+policy|refund|warranty\s+policy|how\s+do\s+refunds?\s+work|can\s+i\s+return)\b",
    re.IGNORECASE,
)
_GUIDED = re.compile(
    r"\b(?:don'?t\s+know\s+what\s+to\s+buy|can\s+you\s+suggest\s+something|not\s+sure\s+what\s+to\s+(?:buy|get))\b",
    re.IGNORECASE,
)
_GENERAL = re.compile(
    r"^\s*(?:hi|hello|hey|good\s+(?:morning|afternoon|evening))\s*[!.?]*\s*$",
    re.IGNORECASE,
)
_CAPABILITIES = re.compile(
    r"\b(?:what\s+can\s+you\s+do|how\s+does\s+this\s+work)\b",
    re.IGNORECASE,
)
_GIBBERISH = re.compile(r"^[a-z]{6,}$", re.IGNORECASE)
_RESUME_CATALOG = re.compile(
    r"\b(?:show\s+me\s+more\s+(?:of\s+)?(?:those|these)|more\s+(?:of\s+)?(?:those|these))\b",
    re.IGNORECASE,
)
_THIS_PRODUCT = re.compile(r"\b(?:this\s+(?:product|item)|that\s+(?:product|item))\b", re.IGNORECASE)


@dataclass
class SubtypeClassification:
    response_subtype: ResponseSubtype
    sort: SortMode | None = None
    preserve_catalog_session: bool = False
    category_query: str | None = None
    browse_all: bool = False


def classify_response_subtype(
    message: str,
    *,
    structured_query: StructuredQuery,
    session_state: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> SubtypeClassification:
    msg = (message or "").strip()
    lower = msg.lower()
    session_state = session_state or {}

    if _RESUME_CATALOG.search(msg) and session_state.get("structured_query"):
        sq = session_state.get("structured_query") or {}
        if sq.get("intent") == "catalog" or sq.get("category", {}).get("values"):
            return SubtypeClassification(response_subtype="product_search", preserve_catalog_session=True)

    if _GENERAL.match(msg):
        return SubtypeClassification(response_subtype="general_chat")
    if _CAPABILITIES.search(msg):
        return SubtypeClassification(response_subtype="general_chat")
    if len(msg) >= 6 and _GIBBERISH.match(msg) and " " not in msg:
        return SubtypeClassification(response_subtype="general_chat")

    if _GUIDED.search(msg):
        return SubtypeClassification(response_subtype="guided_discovery")

    if is_product_detail_message(msg) or extract_product_title_from_message(msg):
        return SubtypeClassification(response_subtype="product_detail")

    if structured_query.intent == "support" or _SUPPORT.search(msg):
        return SubtypeClassification(response_subtype="support_faq", preserve_catalog_session=True)

    blocked, reason = resolve_catalog_block(
        message=msg,
        profile=profile,
        coverage=structured_query.catalog_coverage,
    )
    if blocked and reason:
        return SubtypeClassification(response_subtype="not_in_catalog", category_query=reason)

    if _LIST_CATEGORIES.search(msg):
        return SubtypeClassification(response_subtype="list_categories")
    if _ALL_PRODUCTS.search(msg):
        return SubtypeClassification(response_subtype="category_plp_sample", browse_all=True)

    if _SORT_NEWEST.search(msg):
        return SubtypeClassification(response_subtype="sort_browse", sort="newest")
    if _SORT_BEST.search(msg):
        return SubtypeClassification(response_subtype="sort_browse", sort="bestseller")
    if _SORT_TREND.search(msg):
        return SubtypeClassification(response_subtype="sort_browse", sort="trending")
    if _SORT_CHEAP.search(msg):
        return SubtypeClassification(response_subtype="sort_browse", sort="price_asc")

    if _COMPARE.search(msg):
        return SubtypeClassification(response_subtype="product_compare")
    if _SIMILAR.search(msg):
        return SubtypeClassification(response_subtype="similar_products")

    if _VARIANT.search(msg) or re.search(r"\b(?:colors?|colours?|sizes?)\s+available\b", lower):
        return SubtypeClassification(response_subtype="variant_facets")

    if _PRODUCT_DETAIL.search(msg) or (_THIS_PRODUCT.search(msg) and session_state.get("last_product_refs")):
        return SubtypeClassification(response_subtype="product_detail")

    avail = _CATEGORY_AVAIL.match(msg)
    if avail and not structured_query.price.max and not structured_query.facets:
        return SubtypeClassification(
            response_subtype="category_availability",
            category_query=avail.group("cat").strip(),
        )

    if structured_query.intent == "catalog":
        if structured_query.category.values and re.search(
            r"\b(?:show\s+me|men'?s|women'?s)\b", lower
        ):
            if not structured_query.facets and structured_query.price.max is None:
                if re.search(r"\b(?:clothing|jackets?|shirts?|pants|bags?)\b", lower):
                    return SubtypeClassification(response_subtype="category_plp_sample")

    return SubtypeClassification(response_subtype="product_search")
