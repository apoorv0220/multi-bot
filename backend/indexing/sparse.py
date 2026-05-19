from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from qdrant_client.http import models

logger = logging.getLogger("indexing-sparse")

_SPARSE_MODEL: Any = None
_SPARSE_UNAVAILABLE = False


def sparse_indexing_enabled() -> bool:
    if os.getenv("RETRIEVAL_HYBRID_ENABLED", "true").strip().lower() not in ("1", "true", "yes"):
        return False
    return not _sparse_unavailable()


def _sparse_unavailable() -> bool:
    global _SPARSE_UNAVAILABLE
    if _SPARSE_UNAVAILABLE:
        return True
    try:
        import fastembed  # noqa: F401
        return False
    except ImportError:
        _SPARSE_UNAVAILABLE = True
        logger.warning("fastembed not installed; sparse vectors disabled")
        return True


@lru_cache(maxsize=1)
def _sparse_model():
    from fastembed import SparseTextEmbedding

    model_name = os.getenv("SPARSE_EMBEDDING_MODEL", "Qdrant/bm25")
    return SparseTextEmbedding(model_name=model_name)


def encode_sparse(text: str) -> models.SparseVector | None:
    if not text.strip() or not sparse_indexing_enabled():
        return None
    if _sparse_unavailable():
        return None
    try:
        model = _sparse_model()
        embeddings = list(model.embed([text]))
        if not embeddings:
            return None
        emb = embeddings[0]
        indices = [int(i) for i in emb.indices]
        values = [float(v) for v in emb.values]
        if not indices:
            return None
        return models.SparseVector(indices=indices, values=values)
    except Exception as exc:
        logger.warning("Sparse encoding failed: %s", exc)
        return None
