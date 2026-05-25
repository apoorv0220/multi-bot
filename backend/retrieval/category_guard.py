from __future__ import annotations

import re
from typing import Any

from retrieval.profile import _normalize_label

# Product-type words users mention that are not covered by _PRODUCT_TYPE_CATEGORY_PATTERNS.
_EXTRA_PRODUCT_TYPE_PATTERNS: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (re.compile(r"\b(?:shoes?|footwear|sneakers?|boots?)\b", re.IGNORECASE), ("shoe", "footwear")),
    (re.compile(r"\b(?:jeans?|denim)\b", re.IGNORECASE), ("jean", "denim", "pants")),
    (re.compile(r"\b(?:shorts?)\b", re.IGNORECASE), ("short",)),
    (re.compile(r"\b(?:dresses?|gowns?)\b", re.IGNORECASE), ("dress",)),
]

_PRICE_TAIL = re.compile(r"\bunder\s+\$?\d", re.IGNORECASE)
_SIZE_IN_PHRASE = re.compile(r"\bin\s+size\b", re.IGNORECASE)

# Prepositions that must not start a "category" capture (legacy bug: "in size L under").
_FALSE_CATEGORY_PREFIXES = frozenset({"size", "sizes", "color", "colour", "colors", "colours"})


def _gazetteer_entries(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not profile:
        return []
    return list((profile.get("category_strategy") or {}).get("gazetteer") or [])


def _stem_in_gazetteer(stem: str, profile: dict[str, Any] | None) -> bool:
    from retrieval.rules_prepass import _category_id_matches_stem, term_present_as_word

    stem = stem.strip().lower()
    if not stem:
        return False
    for entry in _gazetteer_entries(profile):
        cat_id = str(entry.get("id") or "").strip().lower()
        if _category_id_matches_stem(cat_id, stem):
            return True
        for label in (entry.get("labels") or []) + (entry.get("normalized") or []):
            lab = str(label).strip().lower()
            if term_present_as_word(stem, lab) or term_present_as_word(stem.rstrip("s"), lab):
                return True
    return False


def _stems_in_gazetteer(stems: tuple[str, ...], profile: dict[str, Any] | None) -> bool:
    return any(_stem_in_gazetteer(stem, profile) for stem in stems)


def mentioned_product_types(message: str) -> list[str]:
    """Human-facing product type labels mentioned in the message."""
    from retrieval.rules_prepass import _PRODUCT_TYPE_CATEGORY_PATTERNS

    found: list[str] = []
    all_patterns = list(_PRODUCT_TYPE_CATEGORY_PATTERNS) + list(_EXTRA_PRODUCT_TYPE_PATTERNS)
    for pattern, stems in all_patterns:
        if pattern.search(message or ""):
            label = stems[0]
            if label.endswith("s"):
                label = label
            elif stems[0] in ("jean", "pant", "trouser"):
                label = "jeans" if "jean" in stems else "pants"
            elif stems[0] == "tee":
                label = "tees"
            elif stems[0] == "shoe":
                label = "shoes"
            elif stems[0] == "short":
                label = "shorts"
            else:
                label = f"{stems[0]}s" if not stems[0].endswith("s") else stems[0]
            if label not in found:
                found.append(label)
    return found


def unknown_product_types_in_message(message: str, profile: dict[str, Any] | None) -> list[str]:
    """Product types the user asked for that do not exist in the tenant gazetteer."""
    unknown: list[str] = []
    for label in mentioned_product_types(message):
        # Re-derive stems for this label
        stems_map = {
            "shoes": ("shoe",),
            "jeans": ("jean", "pants"),
            "pants": ("pant", "pants"),
            "jackets": ("jacket",),
            "bags": ("bag",),
            "tees": ("tee", "shirt"),
            "shorts": ("short",),
            "dresses": ("dress",),
        }
        stems = stems_map.get(label, (label.rstrip("s"),))
        if not _stems_in_gazetteer(stems, profile):
            unknown.append(label)
    return unknown


def vertical_category_miss(message: str, profile: dict[str, Any] | None) -> str | None:
    """Detect 'products under electronics' style vertical misses only."""
    m = re.search(
        r"\b(?:products?\s+under|(?:show|find)\s+(?:me\s+)?(?:products?\s+)?under)\s+"
        r"(?P<cat>[a-z][a-z\s&'-]{2,30})\b",
        message or "",
        re.IGNORECASE,
    )
    if not m:
        return None
    cat = m.group("cat").strip().lower()
    if _PRICE_TAIL.search(cat) or cat.startswith("$"):
        return None
    if _stem_in_gazetteer(cat.split()[0], profile):
        return None
    if _stems_in_gazetteer((cat.replace(" ", "_"),), profile):
        return None
    # Single-word vertical only — avoid "size l under" false positives.
    if " " in cat:
        return None
    if cat in _FALSE_CATEGORY_PREFIXES:
        return None
    for entry in _gazetteer_entries(profile):
        cid = str(entry.get("id") or "").lower()
        if cat == cid or cat in cid.split("_"):
            return None
        for label in entry.get("labels") or []:
            if cat == str(label).lower():
                return None
    return cat


_BRAND_PRODUCTS = re.compile(
    r"\b(?:show|find|list|any|do\s+you\s+(?:have|carry|sell))\s+(?:me\s+)?"
    r"(?P<brand>[A-Za-z][\w&'-]+(?:\s+[A-Za-z][\w&'-]+)?)\s+(?:products?|items?|gear)\b",
    re.IGNORECASE,
)


def _brand_samples(profile: dict[str, Any] | None) -> set[str]:
    brand_meta = ((profile or {}).get("core_fields") or {}).get("brand") or {}
    return {_normalize_label(str(v)) for v in (brand_meta.get("sample_values") or []) if v}


def _brand_in_catalog(name: str, profile: dict[str, Any] | None) -> bool:
    norm = _normalize_label(name)
    if not norm:
        return False
    samples = _brand_samples(profile)
    if not samples:
        return False
    if norm in samples:
        return True
    for sample in samples:
        if norm in sample or sample in norm:
            return True
    return False


def unknown_brand_in_message(message: str, profile: dict[str, Any] | None) -> str | None:
    brand_meta = ((profile or {}).get("core_fields") or {}).get("brand") or {}
    if not brand_meta.get("indexed", True):
        return None
    samples = _brand_samples(profile)
    if not samples:
        return None
    m = _BRAND_PRODUCTS.search(message or "")
    if m:
        brand = m.group("brand").strip()
        generic = {"all", "some", "your", "new", "latest", "best", "top", "cheap", "men", "mens", "women", "womens"}
        if _normalize_label(brand) in generic:
            return None
        if not _brand_in_catalog(brand, profile):
            return brand
    return None


def should_block_catalog_search(message: str, profile: dict[str, Any] | None) -> tuple[bool, str | None]:
    """
    Return (True, reason) when the user asked for a product type / vertical
    that is not in this tenant's gazetteer. Never treat size/price tails as categories.
    """
    brand_miss = unknown_brand_in_message(message, profile)
    if brand_miss:
        return True, brand_miss

    if _SIZE_IN_PHRASE.search(message or "") and _PRICE_TAIL.search(message or ""):
        # "in size L under $150" — valid filtered search, not a category miss.
        vertical = vertical_category_miss(message, profile)
        if vertical:
            return True, vertical
        unknown_types = unknown_product_types_in_message(message, profile)
        return (bool(unknown_types), unknown_types[0] if unknown_types else None)

    unknown_types = unknown_product_types_in_message(message, profile)
    if unknown_types:
        return True, unknown_types[0]

    vertical = vertical_category_miss(message, profile)
    if vertical:
        return True, vertical

    return False, None
