from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Optional

from sources.config import normalize_source_provider

if TYPE_CHECKING:
    from models import Tenant

_TOP_N_PATTERN = re.compile(
    r"\b(?:show\s+only\s+(?:the\s+)?)?(?:top|first)\s+(\d{1,2})\b",
    re.IGNORECASE,
)
_ONLY_N_PRODUCTS = re.compile(
    r"\bshow\s+only\s+(?:the\s+)?(\d{1,2})\s+products?\b",
    re.IGNORECASE,
)


def parse_explicit_result_cap(message: str | None) -> int | None:
    """Parse phrases like 'top 5' or 'show only 3 products' into a result cap."""
    text = (message or "").strip()
    if not text:
        return None
    for pattern in (_TOP_N_PATTERN, _ONLY_N_PRODUCTS):
        match = pattern.search(text)
        if match:
            try:
                value = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if 1 <= value <= 50:
                return value
    return None


def effective_chat_max_results(*, tenant: Optional["Tenant"], request_max: Optional[int]) -> int:
    """Resolve Qdrant hit limit for chat: tenant defaults, ecommerce vs general, client cap, global ceiling."""
    abs_ceiling = max(1, int(os.getenv("CHAT_MAX_RESULTS_ABSOLUTE_CEILING", "50")))
    env_general = max(1, min(int(os.getenv("CHAT_MAX_RESULTS_DEFAULT_GENERAL", "5")), abs_ceiling))
    env_catalog = max(1, min(int(os.getenv("CHAT_MAX_RESULTS_DEFAULT_CATALOG", "8")), abs_ceiling))

    if tenant is None:
        cap = env_general
        default = env_general
        chosen = request_max if request_max is not None else default
        return max(1, min(chosen, cap))

    provider = normalize_source_provider(
        tenant.source_db_type,
        source_mode=tenant.source_mode,
        source_db_url=tenant.source_db_url,
        source_static_urls_json=tenant.source_static_urls_json,
    )
    is_woo = provider == "woocommerce"

    if is_woo:
        if tenant.chat_max_results_catalog is not None:
            cap_val = int(tenant.chat_max_results_catalog)
            default_val = cap_val
        elif tenant.chat_max_results is not None:
            cap_val = int(tenant.chat_max_results)
            default_val = cap_val
        else:
            cap_val = env_catalog
            default_val = env_catalog
    else:
        if tenant.chat_max_results is not None:
            cap_val = int(tenant.chat_max_results)
            default_val = cap_val
        else:
            cap_val = env_general
            default_val = env_general

    cap_val = max(1, min(cap_val, abs_ceiling))
    default_val = max(1, min(default_val, cap_val))
    chosen = request_max if request_max is not None else default_val
    return max(1, min(chosen, cap_val))
