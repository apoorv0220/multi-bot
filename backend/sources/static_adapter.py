from __future__ import annotations

import json

from indexing.payloads import infer_scraped_content_kind
from scraper import scrape_urls
from sources.base import SourceAdapter, SourceContext, SourceRecord, SyncBatch
from sources.config import canonicalize_source_url


class StaticUrlAdapter(SourceAdapter):
    provider = "static"

    def _get_static_urls(self, ctx: SourceContext) -> list[dict[str, str]]:
        raw = ctx.source_config.get("source_static_urls_json")
        if not raw:
            return []
        entries: list[str] = []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                entries = [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            entries = [line.strip() for line in str(raw).splitlines() if line.strip()]
        aliases = [a.strip() for a in str(ctx.source_config.get("source_domain_aliases") or "").split(",") if a.strip()]
        canonical_base = (ctx.source_config.get("source_canonical_base_url") or "").strip() or None
        seen = set()
        out: list[dict[str, str]] = []
        for entry in entries:
            cu = canonicalize_source_url(entry, domain_aliases=aliases, canonical_base=canonical_base)
            if not cu or cu in seen:
                continue
            seen.add(cu)
            out.append({"url": cu, "title": "Static website content", "description": cu})
        return out

    async def discover(self, ctx: SourceContext) -> list[SyncBatch]:
        static_urls = self._get_static_urls(ctx)
        scraped = await scrape_urls(static_urls)
        records: list[SourceRecord] = []
        for item in scraped:
            content_kind = infer_scraped_content_kind(item.get("url"), item.get("title"))
            canonical_url = item.get("url")
            records.append(
                SourceRecord(
                    source_provider="static",
                    content_kind=content_kind,  # type: ignore[arg-type]
                    entity_id=canonical_url or item.get("title") or "",
                    title=(item.get("title") or "").strip() or "Static content",
                    summary=(item.get("description") or "").strip() or None,
                    body=(item.get("content") or "").strip() or None,
                    canonical_url=canonical_url,
                    metadata={},
                )
            )
        return [
            SyncBatch(
                tenant_id=ctx.tenant_id,
                provider=self.provider,
                mode=ctx.mode,
                records=records,
            )
        ]
