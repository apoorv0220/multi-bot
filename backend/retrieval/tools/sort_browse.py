from __future__ import annotations

from typing import Any


def sort_results_by_mode(results: list[Any], sort_mode: str | None) -> list[Any]:
    if not sort_mode or sort_mode == "relevance":
        return results

    def _price(r: Any) -> float:
        p = (getattr(r, "payload", None) or {}).get("price")
        try:
            return float(p)
        except (TypeError, ValueError):
            return float("inf")

    def _rating(r: Any) -> float:
        p = (getattr(r, "payload", None) or {}).get("rating")
        try:
            return float(p)
        except (TypeError, ValueError):
            return 0.0

    def _reviews(r: Any) -> float:
        p = (getattr(r, "payload", None) or {}).get("review_count")
        try:
            return float(p)
        except (TypeError, ValueError):
            return 0.0

    def _date(r: Any) -> str:
        p = getattr(r, "payload", None) or {}
        return str(p.get("created_at") or p.get("updated_at") or "")

    def _sales(r: Any) -> float:
        p = (getattr(r, "payload", None) or {}).get("total_sales")
        try:
            return float(p)
        except (TypeError, ValueError):
            return 0.0

    if sort_mode == "price_asc":
        return sorted(results, key=_price)
    if sort_mode == "price_desc":
        return sorted(results, key=_price, reverse=True)
    if sort_mode == "rating_desc":
        return sorted(results, key=lambda r: (_rating(r), _reviews(r)), reverse=True)
    if sort_mode in ("newest", "trending", "bestseller"):
        if sort_mode == "bestseller":
            ranked = sorted(results, key=lambda r: (_sales(r), _rating(r)), reverse=True)
            if any(_sales(r) > 0 for r in results):
                return ranked
        if sort_mode == "trending":
            ranked = sorted(results, key=lambda r: (_sales(r), _rating(r), _date(r)), reverse=True)
            if any(_sales(r) > 0 for r in results):
                return ranked
        return sorted(results, key=_date, reverse=True)
    return results


def sort_browse_label(sort_mode: str | None, *, has_sales: bool, has_dates: bool) -> str:
    if sort_mode == "newest":
        return "recently added or updated" if has_dates else "recent catalog items"
    if sort_mode == "bestseller":
        return "best-selling" if has_sales else "popular (sales data not indexed; showing top-rated/recent)"
    if sort_mode == "trending":
        return "trending" if has_sales else "popular (trend data not indexed; showing recent items)"
    if sort_mode == "price_asc":
        return "lowest price"
    if sort_mode == "rating_desc":
        return "top rated"
    return "catalog"
