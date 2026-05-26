from __future__ import annotations

from retrieval.structured_query import StructuredQuery


def apply_price_bounds_validation(query: StructuredQuery) -> StructuredQuery:
    """Reject non-positive price bounds; surface reason in validation_meta."""
    updated = query.copy()
    meta = dict(updated.validation_meta or {})
    invalid = False
    if updated.price.max is not None and updated.price.max <= 0:
        updated.price.max = None
        invalid = True
    if updated.price.min is not None and updated.price.min < 0:
        updated.price.min = None
        invalid = True
    if invalid:
        meta["invalid_price"] = True
        updated.validation_meta = meta
    return updated


def has_invalid_price(query: StructuredQuery) -> bool:
    return bool((query.validation_meta or {}).get("invalid_price"))
