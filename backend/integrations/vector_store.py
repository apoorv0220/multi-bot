from typing import Any

from qdrant_client.http import models


class VectorStoreAdapter:
    def __init__(self, qdrant_client):
        self.client = qdrant_client

    def search(self, *, collection_name: str, query_vector: list[float], limit: int, score_threshold: float | None = None, source_type: str | None = None) -> Any:
        query_filter = None
        if source_type:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_type",
                        match=models.MatchValue(value=source_type),
                    )
                ]
            )
        kwargs = {
            "collection_name": collection_name,
            "query_vector": query_vector,
            "limit": limit,
        }
        if score_threshold is not None:
            kwargs["score_threshold"] = score_threshold
        if query_filter is not None:
            kwargs["query_filter"] = query_filter
        return self.client.search(**kwargs)
