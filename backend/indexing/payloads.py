from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sources.base import SourceRecord


SUPPORT_PATH_KEYWORDS = (
    "faq",
    "support",
    "help",
    "shipping",
    "returns",
    "refund",
    "warranty",
    "privacy",
    "policy",
    "terms",
    "installation",
)


def infer_content_bucket(record: SourceRecord) -> str:
    if record.content_kind in {"product", "category"}:
        return "catalog"
    if record.content_kind in {"faq", "policy", "support_page"}:
        return "support"
    if record.source_provider == "static":
        return "static"
    return "cms"


def infer_scraped_content_kind(url: str | None, title: str | None = None) -> str:
    candidate = f"{url or ''} {title or ''}".lower()
    if "faq" in candidate:
        return "faq"
    if any(token in candidate for token in SUPPORT_PATH_KEYWORDS):
        if any(policy in candidate for policy in {"privacy", "terms", "policy"}):
            return "policy"
        return "support_page"
    return "cms_page"


def build_document_text(record: SourceRecord) -> str:
    sections = []
    if record.title:
        sections.append(record.title.strip())
    if record.summary:
        sections.append(record.summary.strip())
    if record.body:
        sections.append(record.body.strip())
    metadata = record.metadata or {}
    categories = metadata.get("categories") or []
    if categories:
        sections.append(f"Categories: {', '.join(str(v) for v in categories)}")
    brand = metadata.get("brand")
    if brand:
        sections.append(f"Brand: {brand}")
    price = metadata.get("price")
    if price not in (None, ""):
        sections.append(f"Price: {price}")
    attributes = metadata.get("attributes") or {}
    attr_parts = []
    for key, value in attributes.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            attr_parts.append(f"{key}: {', '.join(str(item) for item in value)}")
        else:
            attr_parts.append(f"{key}: {value}")
    if attr_parts:
        sections.append("Attributes: " + "; ".join(attr_parts))
    return "\n\n".join(section for section in sections if section).strip()


def chunk_record_text(record: SourceRecord, *, max_chars: int = 2200) -> list[dict[str, Any]]:
    text = build_document_text(record)
    if not text:
        return []
    if record.content_kind in {"category"}:
        return [{"chunk_index": 0, "content": text}]
    if record.content_kind == "product" and len(text) <= max_chars:
        return [{"chunk_index": 0, "content": text}]

    chunks: list[dict[str, Any]] = []
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    current = ""
    chunk_index = 0
    for paragraph in paragraphs:
        next_candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if current and len(next_candidate) > max_chars:
            chunks.append({"chunk_index": chunk_index, "content": current})
            chunk_index += 1
            current = paragraph
        else:
            current = next_candidate
    if current:
        chunks.append({"chunk_index": chunk_index, "content": current})
    return chunks or [{"chunk_index": 0, "content": text[:max_chars]}]


def _normalized_metadata(record: SourceRecord) -> dict[str, Any]:
    metadata = dict(record.metadata or {})
    metadata["content_bucket"] = metadata.get("content_bucket") or infer_content_bucket(record)
    metadata.setdefault("categories", [])
    metadata.setdefault("attributes", {})
    return metadata


def build_qdrant_payload(
    *,
    record: SourceRecord,
    chunk_content: str,
    chunk_index: int,
    source_label: str,
    source_type: str,
) -> dict[str, Any]:
    metadata = _normalized_metadata(record)
    payload = {
        "title": record.title,
        "content": chunk_content,
        "url": record.canonical_url or "",
        "source": source_label,
        "source_type": source_type,
        "source_provider": record.source_provider,
        "content_kind": record.content_kind,
        "content_bucket": metadata.get("content_bucket"),
        "entity_id": record.entity_id,
        "parent_entity_id": record.parent_entity_id,
        "chunk_index": chunk_index,
        "updated_at": record.updated_at,
        "summary": record.summary,
    }
    payload.update(metadata)
    return payload


def build_result_context_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": payload.get("title"),
        "url": payload.get("url"),
        "source_provider": payload.get("source_provider"),
        "content_kind": payload.get("content_kind"),
        "content_bucket": payload.get("content_bucket"),
        "entity_id": payload.get("entity_id"),
        "brand": payload.get("brand"),
        "categories": payload.get("categories") or [],
        "stock_status": payload.get("stock_status"),
        "price": payload.get("price"),
    }


def infer_intent_from_query(query: str) -> str:
    q = (query or "").lower()
    if any(word in q for word in ("buy", "price", "stock", "product", "category", "shop", "order")):
        return "catalog"
    if any(word in q for word in SUPPORT_PATH_KEYWORDS):
        return "support"
    return "general"


def default_bucket_priority(intent: str) -> list[str]:
    if intent == "catalog":
        return ["catalog", "support", "cms", "static"]
    if intent == "support":
        return ["support", "cms", "catalog", "static"]
    return ["cms", "support", "catalog", "static"]


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    netloc = urlparse(url).netloc.strip().lower()
    return netloc or None
