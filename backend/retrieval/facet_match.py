from __future__ import annotations

import os
from typing import Any


def default_facet_match_mode() -> str:
    raw = os.getenv("RETRIEVAL_FACET_MATCH_MODE_DEFAULT", "soft").strip().lower()
    return "strict" if raw == "strict" else "soft"


def facet_match_mode(facet_id: str, profile: dict[str, Any] | None) -> str:
    """Per-facet match strength from retrieval profile (default soft)."""
    if facet_id == "brand":
        return "strict"
    meta = ((profile or {}).get("facets") or {}).get(facet_id) or {}
    raw = str(meta.get("match_mode") or default_facet_match_mode()).strip().lower()
    return "strict" if raw == "strict" else "soft"
