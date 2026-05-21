from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from .base import SourcePlan, SourceProvider


def parse_source_dsn(dsn: str | None, table_prefix: str | None, url_table: str | None) -> dict[str, Any]:
    if not dsn:
        return {
            "table_prefix": table_prefix,
            "url_table": url_table,
        }
    parsed = urlparse(dsn)
    try:
        port = int(parsed.port or 3306)
    except ValueError:
        # Do not let admin/source-plan views crash on malformed or non-URL-encoded DSNs.
        # We keep a best-effort config and let actual connection attempts fail with a clearer error.
        port = 3306
    cfg: dict[str, Any] = {
        "host": parsed.hostname or "",
        "port": port,
        "database": (parsed.path or "").lstrip("/"),
        "table_prefix": table_prefix,
        "url_table": url_table,
    }
    if parsed.username:
        cfg["user"] = unquote(parsed.username)
    if parsed.password:
        cfg["password"] = unquote(parsed.password)
    return cfg


def normalize_source_provider(
    source_db_type: str | None,
    *,
    source_mode: str | None = None,
    source_db_url: str | None = None,
    source_static_urls_json: str | None = None,
) -> SourceProvider:
    raw = (source_db_type or "").strip().lower()
    if raw in {"wordpress", "woocommerce", "magento", "static"}:
        return raw  # type: ignore[return-value]
    mode = (source_mode or "").strip().lower()
    if mode == "static" and not (source_db_url or "").strip():
        return "static"
    if (source_static_urls_json or "").strip() and not (source_db_url or "").strip():
        return "static"
    return "wordpress"


def normalize_source_mode(source_mode: str | None) -> str:
    raw = (source_mode or "").strip().lower()
    if raw in {"wordpress", "static", "mixed", "magento"}:
        return raw
    return "wordpress"


SOURCE_MODES_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    "wordpress": ("wordpress", "static", "mixed"),
    "woocommerce": ("wordpress", "static", "mixed"),
    "magento": ("magento", "mixed", "static"),
    "static": ("static",),
}


def default_source_mode_for_provider(provider: str | None) -> str:
    """First valid source_mode for a provider (matches admin UI defaults)."""
    key = (provider or "").strip().lower()
    if key not in SOURCE_MODES_BY_PROVIDER:
        key = "wordpress"
    return SOURCE_MODES_BY_PROVIDER[key][0]


def coerce_source_mode_for_provider(
    provider: str | None,
    source_mode: str | None,
) -> str:
    """Return source_mode if allowed for provider, else provider default."""
    key = (provider or "").strip().lower()
    if key not in SOURCE_MODES_BY_PROVIDER:
        key = "wordpress"
    allowed = SOURCE_MODES_BY_PROVIDER[key]
    raw = normalize_source_mode(source_mode)
    if raw in allowed:
        return raw
    return allowed[0]


def canonicalize_source_url(
    url: str,
    *,
    domain_aliases: Iterable[str] | None = None,
    canonical_base: str | None = None,
) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    query_pairs = []
    for pair in (parsed.query or "").split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0].strip().lower()
        if key.startswith("utm_") or key in {"gclid", "fbclid", "msclkid"}:
            continue
        query_pairs.append(pair)
    query = "&".join(query_pairs)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    hostname = parsed.netloc.lower()
    alias_set = {urlparse(str(a)).netloc.lower() for a in (domain_aliases or []) if str(a).strip()}
    canonical_host = ""
    if canonical_base:
        canonical_host = (urlparse(canonical_base).netloc or "").lower()
    if canonical_host and (hostname in alias_set or hostname == canonical_host):
        hostname = canonical_host
    normalized = f"https://{hostname}{path}"
    if query:
        normalized = f"{normalized}?{query}"
    return normalized


def normalize_source_static_urls_json(
    raw_value: str | None,
    *,
    domain_aliases: Iterable[str] | None = None,
    canonical_base: str | None = None,
) -> str | None:
    if raw_value is None:
        return None
    text = raw_value.strip()
    if not text:
        return None
    urls: list[str] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            urls = [str(v).strip() for v in parsed]
    except Exception:
        urls = [line.strip() for line in text.splitlines() if line.strip()]
    deny_fragments = ("/wp-admin", "/wp-login.php", "/xmlrpc.php")
    seen = set()
    normalized = []
    for url in urls:
        cu = canonicalize_source_url(
            url,
            domain_aliases=domain_aliases,
            canonical_base=canonical_base,
        )
        if not cu or cu in seen:
            continue
        if any(fragment in cu for fragment in deny_fragments):
            continue
        seen.add(cu)
        normalized.append(cu)
    return json.dumps(normalized) if normalized else None


def resolve_source_plan(source_config: dict[str, Any]) -> SourcePlan:
    provider = normalize_source_provider(
        source_config.get("source_db_type"),
        source_mode=source_config.get("source_mode"),
        source_db_url=source_config.get("source_db_url"),
        source_static_urls_json=source_config.get("source_static_urls_json"),
    )
    mode = normalize_source_mode(source_config.get("source_mode"))
    if provider == "static":
        return SourcePlan(
            provider="static",
            source_mode="static",
            include_wordpress_content=False,
            include_legacy_external=False,
            include_woocommerce_catalog=False,
            include_magento_catalog=False,
            include_static_urls=True,
        )
    if provider == "woocommerce":
        return SourcePlan(
            provider="woocommerce",
            source_mode=mode,
            include_wordpress_content=mode in {"wordpress", "mixed"},
            include_legacy_external=False,
            include_woocommerce_catalog=mode in {"wordpress", "mixed"},
            include_magento_catalog=False,
            include_static_urls=mode in {"static", "mixed"},
        )
    if provider == "magento":
        return SourcePlan(
            provider="magento",
            source_mode=mode,
            include_wordpress_content=False,
            include_legacy_external=False,
            include_woocommerce_catalog=False,
            include_magento_catalog=mode in {"magento", "wordpress", "mixed"},
            include_static_urls=mode in {"static", "mixed"},
        )
    return SourcePlan(
        provider="wordpress",
        source_mode=mode,
        include_wordpress_content=mode in {"wordpress", "mixed"},
        include_legacy_external=mode == "wordpress",
        include_woocommerce_catalog=False,
        include_magento_catalog=False,
        include_static_urls=mode in {"static", "mixed"},
    )


def plan_to_dict(plan: SourcePlan) -> dict[str, Any]:
    return asdict(plan)
