from __future__ import annotations

import logging
import os
from typing import Any

from qdrant_client.http import models

from indexing.collections import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME, collection_uses_hybrid_vectors
from indexing.sparse import encode_sparse
from integrations.vector_store import VectorStoreAdapter

logger = logging.getLogger("retrieval-hybrid")


def _rrf_k() -> int:
    try:
        return max(1, int(os.getenv("RETRIEVAL_HYBRID_RRF_K", "60")))
    except ValueError:
        return 60


def hybrid_search(
    client,
    *,
    collection_name: str,
    dense_vector: list[float],
    lexical_text: str,
    limit: int,
    source_type: str | None = None,
    content_bucket: str | None = None,
    content_kind: str | None = None,
    metadata_filters: dict[str, Any] | None = None,
) -> list[Any]:
    if not collection_uses_hybrid_vectors(client, collection_name):
        adapter = VectorStoreAdapter(client)
        return adapter.search(
            collection_name=collection_name,
            query_vector=dense_vector,
            limit=limit,
            source_type=source_type,
            content_bucket=content_bucket,
            content_kind=content_kind,
            metadata_filters=metadata_filters,
            vector_name=DENSE_VECTOR_NAME,
        )

    sparse_vector = encode_sparse(lexical_text or "")
    if sparse_vector is None:
        adapter = VectorStoreAdapter(client)
        return adapter.search(
            collection_name=collection_name,
            query_vector=dense_vector,
            limit=limit,
            source_type=source_type,
            content_bucket=content_bucket,
            content_kind=content_kind,
            metadata_filters=metadata_filters,
            vector_name=DENSE_VECTOR_NAME,
        )

    adapter = VectorStoreAdapter(client)
    query_filter = adapter.build_query_filter(
        source_type=source_type,
        content_bucket=content_bucket,
        content_kind=content_kind,
        metadata_filters=metadata_filters,
    )
    prefetch_limit = max(limit * 3, 20)
    try:
        response = client.query_points(
            collection_name=collection_name,
            prefetch=[
                models.Prefetch(
                    query=dense_vector,
                    using=DENSE_VECTOR_NAME,
                    limit=prefetch_limit,
                    filter=query_filter,
                ),
                models.Prefetch(
                    query=sparse_vector,
                    using=SPARSE_VECTOR_NAME,
                    limit=prefetch_limit,
                    filter=query_filter,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return list(response.points or [])
    except Exception as exc:
        logger.warning("Hybrid search failed, falling back to dense: %s", exc)
        return adapter.search(
            collection_name=collection_name,
            query_vector=dense_vector,
            limit=limit,
            source_type=source_type,
            content_bucket=content_bucket,
            content_kind=content_kind,
            metadata_filters=metadata_filters,
            vector_name=DENSE_VECTOR_NAME,
        )
