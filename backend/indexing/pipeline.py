from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from qdrant_client.http import models
from qdrant_client.http.models import PointStruct

from indexing.collections import (
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    collection_uses_hybrid_vectors,
    ensure_hybrid_collection,
)
from indexing.ids import build_chunk_point_id, build_source_hash
from indexing.payloads import build_document_text, build_qdrant_payload, chunk_record_text
from indexing.sparse import encode_sparse, sparse_indexing_enabled
from sources.base import SourceRecord, SyncBatch


logger = logging.getLogger("indexing-pipeline")


@dataclass
class PipelineSummary:
    provider: str
    mode: str
    total_records: int = 0
    indexed_records: int = 0
    deleted_records: int = 0
    failed_records: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "mode": self.mode,
            "total_records": self.total_records,
            "indexed_records": self.indexed_records,
            "deleted_records": self.deleted_records,
            "failed_records": self.failed_records,
        }


class IndexingPipeline:
    def __init__(
        self,
        *,
        qdrant_client,
        collection_name: str,
        embedding_func: Callable[[str], Any],
        source_label: str,
        source_type: str,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        embedding_concurrency: int | None = None,
        record_concurrency: int | None = None,
    ) -> None:
        self.qdrant_client = qdrant_client
        self.collection_name = collection_name
        self.embedding_func = embedding_func
        self.source_label = source_label
        self.source_type = source_type
        self.progress_callback = progress_callback
        self.embedding_concurrency = max(
            1,
            int(embedding_concurrency or os.getenv("EMBEDDING_BATCH_SIZE", "10")),
        )
        self.record_concurrency = max(
            1,
            int(record_concurrency or os.getenv("INDEXING_RECORD_CONCURRENCY", "5")),
        )
        self._cleared_providers: set[str] = set()
        self._hybrid_collection_prepared = False
        self._embed_sem = asyncio.Semaphore(self.embedding_concurrency)
        self._record_sem = asyncio.Semaphore(self.record_concurrency)
        self._last_progress_emit_at = 0.0
        self._progress_emit_interval_s = max(
            0.5,
            float(os.getenv("REINDEX_PROGRESS_EMIT_INTERVAL_SECONDS", "1")),
        )

    def _emit_progress(self, summaries: dict[str, PipelineSummary], *, force: bool = False) -> None:
        if not self.progress_callback:
            return
        now = asyncio.get_event_loop().time()
        if not force and (now - self._last_progress_emit_at) < self._progress_emit_interval_s:
            return
        self._last_progress_emit_at = now
        progress = {
            "status": "processing",
            "providers": {provider: summary.to_dict() for provider, summary in summaries.items()},
        }
        self.progress_callback(progress)

    def _clear_provider_content(self, provider: str) -> None:
        if provider in self._cleared_providers:
            return
        self.qdrant_client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_provider",
                            match=models.MatchValue(value=provider),
                        )
                    ]
                )
            ),
        )
        self._cleared_providers.add(provider)

    def _delete_record(self, record: SourceRecord) -> None:
        self.qdrant_client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_provider",
                            match=models.MatchValue(value=record.source_provider),
                        ),
                        models.FieldCondition(
                            key="content_kind",
                            match=models.MatchValue(value=record.content_kind),
                        ),
                        models.FieldCondition(
                            key="entity_id",
                            match=models.MatchValue(value=record.entity_id),
                        ),
                    ]
                )
            ),
        )

    async def _embed_text(self, text: str) -> Any:
        async with self._embed_sem:
            return await self.embedding_func(text)

    async def _build_points_for_record(self, *, tenant_id: str, record: SourceRecord) -> list[PointStruct]:
        document_text = build_document_text(record)
        if not document_text:
            return []
        metadata = dict(record.metadata or {})
        metadata.setdefault("source_hash", build_source_hash(document_text))
        record.metadata = metadata
        chunks = chunk_record_text(record)
        if not chunks:
            return []
        embeddings = await asyncio.gather(
            *[self._embed_text(chunk["content"]) for chunk in chunks],
            return_exceptions=True,
        )
        points: list[PointStruct] = []
        for chunk, embedding in zip(chunks, embeddings):
            if isinstance(embedding, Exception):
                logger.error(
                    "Embedding failed for %s/%s chunk %s: %s",
                    record.source_provider,
                    record.entity_id,
                    chunk.get("chunk_index"),
                    embedding,
                )
                continue
            if not embedding:
                continue
            if collection_uses_hybrid_vectors(self.qdrant_client, self.collection_name):
                vector_payload: Any = {DENSE_VECTOR_NAME: embedding}
                sparse_vector = encode_sparse(chunk["content"])
                if sparse_vector is not None:
                    vector_payload[SPARSE_VECTOR_NAME] = sparse_vector
            else:
                vector_payload = embedding
            payload = build_qdrant_payload(
                record=record,
                chunk_content=chunk["content"],
                chunk_index=chunk["chunk_index"],
                source_label=self.source_label,
                source_type=self.source_type,
            )
            points.append(
                PointStruct(
                    id=build_chunk_point_id(
                        tenant_id=tenant_id,
                        source_provider=record.source_provider,
                        content_kind=record.content_kind,
                        entity_id=record.entity_id,
                        chunk_index=chunk["chunk_index"],
                    ),
                    vector=vector_payload,
                    payload=payload,
                )
            )
        return points

    def _prepare_hybrid_collection_if_needed(self, batches: list[SyncBatch]) -> None:
        if self._hybrid_collection_prepared:
            return
        self._hybrid_collection_prepared = True
        if not sparse_indexing_enabled():
            return
        if not any(batch.mode == "full" for batch in batches):
            return
        ensure_hybrid_collection(self.qdrant_client, self.collection_name, recreate=True)

    async def _process_record(
        self,
        *,
        batch: SyncBatch,
        record: SourceRecord,
        summary: PipelineSummary,
        summaries: dict[str, PipelineSummary],
        summary_lock: asyncio.Lock,
    ) -> None:
        async with self._record_sem:
            try:
                if record.deleted:
                    self._delete_record(record)
                    async with summary_lock:
                        summary.deleted_records += 1
                    return
                points = await self._build_points_for_record(tenant_id=batch.tenant_id, record=record)
                if points:
                    self.qdrant_client.upsert(
                        collection_name=self.collection_name,
                        points=points,
                    )
                async with summary_lock:
                    summary.indexed_records += 1
            except Exception as exc:
                async with summary_lock:
                    summary.failed_records += 1
                logger.error(
                    "Failed to process source record %s/%s: %s",
                    record.source_provider,
                    record.entity_id,
                    exc,
                )
            finally:
                async with summary_lock:
                    self._emit_progress(summaries)

    async def process_batches(self, batches: list[SyncBatch]) -> dict[str, Any]:
        summaries: dict[str, PipelineSummary] = {}
        summary_lock = asyncio.Lock()
        self._prepare_hybrid_collection_if_needed(batches)
        for batch in batches:
            summary = summaries.setdefault(
                batch.provider,
                PipelineSummary(provider=batch.provider, mode=batch.mode),
            )
            summary.total_records += len(batch.records)
            if batch.mode == "full":
                self._clear_provider_content(batch.provider)
            self._emit_progress(summaries, force=True)
            await asyncio.gather(
                *[
                    self._process_record(
                        batch=batch,
                        record=record,
                        summary=summary,
                        summaries=summaries,
                        summary_lock=summary_lock,
                    )
                    for record in batch.records
                ]
            )
        self._emit_progress(summaries, force=True)
        return {provider: summary.to_dict() for provider, summary in summaries.items()}
