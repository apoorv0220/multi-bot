from __future__ import annotations

from typing import Any

from retrieval.response_composer import compose_not_in_catalog
from retrieval.tools.list_categories import category_names_for_not_in_catalog, list_categories_from_profile


def build_not_in_catalog_response(
    *,
    category_query: str,
    profile: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    available = category_names_for_not_in_catalog(profile)
    text = compose_not_in_catalog(category_query, available)
    categories = list_categories_from_profile(profile)[:12]
    return text, categories, []
