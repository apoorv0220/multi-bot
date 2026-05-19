from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

_CMS_PATH_PREFIXES = (
    "wp-",
    "cart",
    "checkout",
    "my-account",
    "feed",
    "sitemap",
    "faq",
    "shipping",
    "returns",
    "privacy",
    "terms",
)


def _payload_price(payload: dict[str, Any]) -> float | None:
    raw = payload.get("price")
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def is_catalog_product_url(url: str) -> bool:
    """Woo canonical /product/… or legacy single-segment product slugs on the store root."""
    lower = (url or "").strip().lower()
    if not lower:
        return False
    if "product-category" in lower:
        return False
    if "/product/" in lower:
        return True
    path = urlparse(lower).path.strip("/")
    if not path or "/" in path:
        return False
    head = path.split("/")[0]
    return not any(head.startswith(prefix) for prefix in _CMS_PATH_PREFIXES)


def is_product_card_eligible(payload: dict[str, Any]) -> bool:
    """True when a hit should appear as a catalog product card."""
    if not payload:
        return False
    url = (payload.get("url") or "").strip()
    if not url:
        return False
    if "product-category" in url.lower():
        return False
    if payload.get("content_kind") == "product":
        return True
    if not is_catalog_product_url(url):
        return False
    if payload.get("content_bucket") != "catalog":
        return False
    return _payload_price(payload) is not None


def filter_results_for_catalog_cards(results: list[Any]) -> list[Any]:
    return [r for r in results if is_product_card_eligible(getattr(r, "payload", None) or {})]


def filter_results_for_response_sources(results: list[Any], intent: str) -> list[Any]:
    """Align API sources with intent: support/general should not surface product SKUs."""
    if intent in ("support", "general"):
        return [
            r
            for r in results
            if (getattr(r, "payload", None) or {}).get("content_kind") != "product"
        ]
    return list(results)
