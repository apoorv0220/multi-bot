import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from qdrant_client import QdrantClient
from qdrant_client.http import models

from indexing.collections import DENSE_VECTOR_NAME, collection_uses_hybrid_vectors
from integrations.openai_client import OpenAIClientAdapter
from integrations.vector_store import VectorStoreAdapter
from retrieval.hybrid import hybrid_search
from retrieval.post_filter import filters_for_bucket
logger = logging.getLogger("chatbot-api")

qdrant_client: Optional[QdrantClient] = None
openai_adapter = OpenAIClientAdapter()


def tenant_collection(tenant_id: str) -> str:
    return f"tenant_{tenant_id}_docs"


def initialize_qdrant_client_with_retries(max_retries: int = 10, retry_delay: float = 2.0) -> QdrantClient:
    qdrant_host = os.getenv("QDRANT_HOST", "qdrant")
    qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            client = QdrantClient(host=qdrant_host, port=qdrant_port)
            client.get_collections()
            return client
        except Exception as exc:
            last_error = exc
            time.sleep(retry_delay)
    raise last_error


def init_qdrant_client() -> Optional[QdrantClient]:
    global qdrant_client
    try:
        qdrant_client = initialize_qdrant_client_with_retries()
    except Exception:
        qdrant_client = None
    return qdrant_client


def get_qdrant_client() -> Optional[QdrantClient]:
    return qdrant_client


def ensure_collection_for_tenant(tenant_id: str) -> None:
    if qdrant_client is None:
        return
    collection_name = tenant_collection(tenant_id)
    from indexing.collections import ensure_hybrid_collection, ensure_legacy_dense_collection
    from indexing.sparse import sparse_indexing_enabled

    if sparse_indexing_enabled():
        if not ensure_hybrid_collection(qdrant_client, collection_name, recreate=False):
            ensure_legacy_dense_collection(qdrant_client, collection_name)
    else:
        collection_names = [c.name for c in qdrant_client.get_collections().collections]
        if collection_name not in collection_names:
            ensure_legacy_dense_collection(qdrant_client, collection_name)
    index_fields = [
        ("source_provider", models.PayloadSchemaType.KEYWORD),
        ("content_kind", models.PayloadSchemaType.KEYWORD),
        ("content_bucket", models.PayloadSchemaType.KEYWORD),
        ("entity_id", models.PayloadSchemaType.KEYWORD),
        ("brand", models.PayloadSchemaType.KEYWORD),
        ("stock_status", models.PayloadSchemaType.KEYWORD),
        ("categories", models.PayloadSchemaType.KEYWORD),
        ("price", models.PayloadSchemaType.FLOAT),
    ]
    for field_name, field_schema in index_fields:
        try:
            qdrant_client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=field_schema,
            )
        except Exception:
            continue


async def generate_embedding(text: str) -> tuple[List[float], Dict[str, Any]]:
    try:
        response = openai_adapter.create_embedding(model="text-embedding-3-small", input_text=text)
        usage = response.usage or {}
        return response.data[0].embedding, {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            "model_name": "text-embedding-3-small",
        }
    except Exception as e:
        logger.error("Error generating embedding: %s", e)
        raise HTTPException(status_code=500, detail="Failed to generate embedding")


async def search_qdrant(
    tenant_id: str,
    embedding: List[float],
    limit: int = 5,
    primary_source_type: Optional[str] = None,
    preferred_buckets: Optional[List[str]] = None,
    metadata_filters: Optional[Dict[str, Any]] = None,
    content_kind: Optional[str] = None,
    use_hybrid: bool = False,
    lexical_text: Optional[str] = None,
    *,
    catalog_buckets_only: bool = False,
) -> List[Any]:
    if qdrant_client is None:
        raise HTTPException(status_code=503, detail="Qdrant service is unavailable")
    collection_name = tenant_collection(tenant_id)
    primary_st = (primary_source_type or "").strip() or None

    try:
        vector_store = VectorStoreAdapter(qdrant_client)
        named_dense = collection_uses_hybrid_vectors(qdrant_client, collection_name)
        ordered_buckets = preferred_buckets or ["cms", "support", "catalog", "static"]
        if catalog_buckets_only:
            ordered_buckets = ["catalog"]

        def _collect_bucket_hits(*, source_type: str | None) -> list[Any]:
            collected: list[Any] = []
            seen: set[Any] = set()
            for bucket in ordered_buckets:
                bucket_filters = filters_for_bucket(metadata_filters, bucket)
                if use_hybrid and bucket == "catalog":
                    bucket_results = hybrid_search(
                        qdrant_client,
                        collection_name=collection_name,
                        dense_vector=embedding,
                        lexical_text=lexical_text or "",
                        limit=limit,
                        source_type=source_type,
                        content_bucket=bucket,
                        content_kind=content_kind,
                        metadata_filters=bucket_filters or None,
                    )
                else:
                    bucket_results = vector_store.search(
                        collection_name=collection_name,
                        query_vector=embedding,
                        limit=limit,
                        source_type=source_type,
                        content_bucket=bucket,
                        content_kind=content_kind if bucket == "catalog" else None,
                        metadata_filters=bucket_filters or None,
                        vector_name=DENSE_VECTOR_NAME if named_dense else None,
                    )
                for result in bucket_results:
                    result_id = result.payload.get("entity_id") or getattr(result, "id", None)
                    if result_id in seen:
                        continue
                    seen.add(result_id)
                    collected.append(result)
                    if len(collected) >= limit:
                        break
                if len(collected) >= limit:
                    break
            return collected

        all_results = _collect_bucket_hits(source_type=primary_st)
        if not all_results and primary_st:
            all_results = _collect_bucket_hits(source_type=None)
        if not catalog_buckets_only and len(all_results) < limit:
            seen_ids = {r.payload.get("entity_id") or getattr(r, "id", None) for r in all_results}
            external_results = vector_store.search(
                collection_name=collection_name,
                query_vector=embedding,
                source_type="external",
                limit=limit,
                vector_name=DENSE_VECTOR_NAME if named_dense else None,
            )
            for result in external_results:
                result_id = result.payload.get("entity_id") or getattr(result, "id", None)
                if result_id in seen_ids:
                    continue
                seen_ids.add(result_id)
                all_results.append(result)
                if len(all_results) >= limit:
                    break
        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results[:limit]
    except Exception as e:
        logger.error("Error searching Qdrant: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to search knowledge base: {e}")
