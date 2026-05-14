from __future__ import annotations

import hashlib
import uuid


def build_parent_entity_key(*, tenant_id: str, source_provider: str, content_kind: str, entity_id: str) -> str:
    return f"{tenant_id}:{source_provider}:{content_kind}:{entity_id}"


def build_parent_point_id(*, tenant_id: str, source_provider: str, content_kind: str, entity_id: str) -> str:
    key = build_parent_entity_key(
        tenant_id=tenant_id,
        source_provider=source_provider,
        content_kind=content_kind,
        entity_id=entity_id,
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def build_chunk_point_id(
    *,
    tenant_id: str,
    source_provider: str,
    content_kind: str,
    entity_id: str,
    chunk_index: int,
) -> str:
    key = f"{build_parent_entity_key(tenant_id=tenant_id, source_provider=source_provider, content_kind=content_kind, entity_id=entity_id)}:chunk:{chunk_index}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def build_source_hash(text: str) -> str:
    return f"sha256:{hashlib.sha256((text or '').encode('utf-8')).hexdigest()}"
