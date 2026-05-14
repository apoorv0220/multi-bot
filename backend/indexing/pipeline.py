from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from qdrant_client.http import models
from qdrant_client.http.models import PointStruct

from indexing.ids import build_chunk_point_id, build_source_hash
from indexing.payloads import build_document_text, build_qdrant_payload, chunk_record_text
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
    ) -> None:
        self.qdrant_client = qdrant_client
        self.collection_name = collection_name
        self.embedding_func = embedding_func
        self.source_label = source_label
        self.source_type = source_type
        self.progress_callback = progress_callback
        self._cleared_providers: set[str] = set()

    def _emit_progress(self, summaries: dict[str, PipelineSummary]) -> None:
        if not self.progress_callback:
            return
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

    async def _build_points_for_record(self, *, tenant_id: str, record: SourceRecord) -> list[PointStruct]:
        document_text = build_document_text(record)
        if not document_text:
            return []
        metadata = dict(record.metadata or {})
        metadata.setdefault("source_hash", build_source_hash(document_text))
        record.metadata = metadata
        chunks = chunk_record_text(record)
        points: list[PointStruct] = []
        for chunk in chunks:
            embedding = await self.embedding_func(chunk["content"])
            if not embedding:
                continue
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
                    vector=embedding,
                    payload=payload,
                )
            )
        return points

    async def process_batches(self, batches: list[SyncBatch]) -> dict[str, Any]:
        summaries: dict[str, PipelineSummary] = {}
        for batch in batches:
            summary = summaries.setdefault(
                batch.provider,
                PipelineSummary(provider=batch.provider, mode=batch.mode),
            )
            if batch.mode == "full":
                self._clear_provider_content(batch.provider)
            for record in batch.records:
                summary.total_records += 1
                try:
                    if record.deleted:
                        self._delete_record(record)
                        summary.deleted_records += 1
                        continue
                    points = await self._build_points_for_record(tenant_id=batch.tenant_id, record=record)
                    if points:
                        self.qdrant_client.upsert(
                            collection_name=self.collection_name,
                            points=points,
                        )
                    summary.indexed_records += 1
                except Exception as exc:
                    summary.failed_records += 1
                    logger.error(
                        "Failed to process source record %s/%s: %s",
                        record.source_provider,
                        record.entity_id,
                        exc,
                    )
                finally:
                    self._emit_progress(summaries)
        return {provider: summary.to_dict() for provider, summary in summaries.items()}
