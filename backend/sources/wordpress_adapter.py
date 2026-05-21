from __future__ import annotations

from typing import Any

from scraper import scrape_urls
from indexing.payloads import infer_scraped_content_kind
from sources.base import SourceAdapter, SourceContext, SourceRecord, SyncBatch
from wordpress_fetcher import WordPressFetcher


class WordPressContentAdapter(SourceAdapter):
    provider = "wordpress"

    async def discover(self, ctx: SourceContext) -> list[SyncBatch]:
        fetcher = WordPressFetcher(source_config=ctx.source_config, fallback_site_url=ctx.source_config.get("url_fallback_base"))
        records: list[SourceRecord] = []

        skip_product_posts = bool(ctx.source_config.get("include_woocommerce_catalog"))
        if ctx.source_config.get("include_wordpress_content", True):
            for post in fetcher.get_all_posts():
                post_type = str(post.get("type") or "").strip().lower()
                if skip_product_posts and post_type == "product":
                    continue
                content_kind = "cms_page" if post_type == "page" else "blog_post"
                records.append(
                    SourceRecord(
                        source_provider="wordpress",
                        content_kind=content_kind,  # type: ignore[arg-type]
                        entity_id=str(post.get("id")),
                        title=(post.get("title") or "").strip() or "Untitled",
                        summary=None,
                        body=(post.get("content") or "").strip() or None,
                        canonical_url=(post.get("url") or "").strip() or None,
                        updated_at=str(post.get("date") or "") or None,
                        metadata={"type": post_type},
                    )
                )

        if ctx.source_config.get("include_legacy_external"):
            external_urls = fetcher.get_external_urls()
            scraped = await scrape_urls(external_urls)
            for item in scraped:
                content_kind = infer_scraped_content_kind(item.get("url"), item.get("title"))
                records.append(
                    SourceRecord(
                        source_provider="wordpress",
                        content_kind=content_kind,  # type: ignore[arg-type]
                        entity_id=(item.get("url") or "").strip(),
                        title=(item.get("title") or "").strip() or "External content",
                        summary=(item.get("description") or "").strip() or None,
                        body=(item.get("content") or "").strip() or None,
                        canonical_url=(item.get("url") or "").strip() or None,
                        metadata={"source_origin": "legacy_external"},
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
