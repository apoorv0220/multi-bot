from __future__ import annotations

import logging
import os

from qdrant_client.http import models

from indexing.sparse import sparse_indexing_enabled

logger = logging.getLogger("indexing-collections")

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


def retrieval_hybrid_enabled() -> bool:
    return os.getenv("RETRIEVAL_HYBRID_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def collection_uses_hybrid_vectors(client, collection_name: str) -> bool:
    try:
        info = client.get_collection(collection_name)
    except Exception:
        return False
    params = info.config.params
    vectors = params.vectors
    sparse_vectors = getattr(params, "sparse_vectors", None) or getattr(params, "sparse_vectors_config", None)
    if isinstance(vectors, dict) and DENSE_VECTOR_NAME in vectors:
        return bool(sparse_vectors)
    return False


def ensure_hybrid_collection(
    client,
    collection_name: str,
    *,
    dense_size: int = 1536,
    recreate: bool = False,
) -> bool:
    """Ensure collection supports dense+sparse named vectors. Returns True if hybrid-ready."""
    if not retrieval_hybrid_enabled() or not sparse_indexing_enabled():
        return False

    exists = False
    try:
        client.get_collection(collection_name)
        exists = True
    except Exception:
        exists = False

    if exists and collection_uses_hybrid_vectors(client, collection_name) and not recreate:
        return True

    if exists and recreate:
        logger.info("Recreating collection %s for hybrid vectors", collection_name)
        client.delete_collection(collection_name)
        exists = False

    if not exists:
        logger.info("Creating hybrid collection %s", collection_name)
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(size=dense_size, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams(),
            },
        )
        _ensure_payload_indexes(client, collection_name)
        return True

    if exists and not collection_uses_hybrid_vectors(client, collection_name):
        logger.warning(
            "Collection %s uses legacy single-vector schema; run full reindex with recreate to enable hybrid",
            collection_name,
        )
    return collection_uses_hybrid_vectors(client, collection_name)


def ensure_legacy_dense_collection(client, collection_name: str, *, dense_size: int = 1536) -> None:
    try:
        client.get_collection(collection_name)
        return
    except Exception:
        pass
    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=dense_size, distance=models.Distance.COSINE),
    )
    _ensure_payload_indexes(client, collection_name)


def _ensure_payload_indexes(client, collection_name: str) -> None:
    client.create_payload_index(
        collection_name=collection_name,
        field_name="source_type",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
    for field_name in (
        "source_provider",
        "content_kind",
        "content_bucket",
        "entity_id",
        "brand",
        "stock_status",
        "categories",
    ):
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass
    try:
        client.create_payload_index(
            collection_name=collection_name,
            field_name="price",
            field_schema=models.PayloadSchemaType.FLOAT,
        )
    except Exception:
        pass
