from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


SourceProvider = Literal["wordpress", "woocommerce", "magento", "static"]
ContentKind = Literal[
    "cms_page",
    "blog_post",
    "product",
    "category",
    "faq",
    "policy",
    "support_page",
]
SyncMode = Literal["full", "incremental", "targeted"]


@dataclass
class SourceContext:
    tenant_id: str
    provider: SourceProvider
    mode: SyncMode
    source_config: dict[str, Any]
    started_at: str


@dataclass
class SourceRecord:
    source_provider: SourceProvider
    content_kind: ContentKind
    entity_id: str
    title: str
    metadata: dict[str, Any] = field(default_factory=dict)
    body: str | None = None
    summary: str | None = None
    canonical_url: str | None = None
    updated_at: str | None = None
    parent_entity_id: str | None = None
    deleted: bool = False


@dataclass
class SyncBatch:
    tenant_id: str
    provider: SourceProvider
    mode: SyncMode
    records: list[SourceRecord]
    cursor: str | None = None
    has_more: bool = False


@dataclass
class SourcePlan:
    provider: SourceProvider
    source_mode: str
    include_wordpress_content: bool
    include_legacy_external: bool
    include_woocommerce_catalog: bool
    include_magento_catalog: bool
    include_static_urls: bool


class SourceAdapter(Protocol):
    provider: SourceProvider

    async def discover(self, ctx: SourceContext) -> list[SyncBatch]:
        ...
