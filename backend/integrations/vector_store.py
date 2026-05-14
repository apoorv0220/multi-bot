from typing import Any

from qdrant_client.http import models


class VectorStoreAdapter:
    def __init__(self, qdrant_client):
        self.client = qdrant_client

    def search(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        limit: int,
        score_threshold: float | None = None,
        source_type: str | None = None,
        content_bucket: str | None = None,
        metadata_filters: dict[str, Any] | None = None,
    ) -> Any:
        must_conditions = []
        if source_type:
            must_conditions.append(
                models.FieldCondition(
                    key="source_type",
                    match=models.MatchValue(value=source_type),
                )
            )
        if content_bucket:
            must_conditions.append(
                models.FieldCondition(
                    key="content_bucket",
                    match=models.MatchValue(value=content_bucket),
                )
            )
        for key, value in (metadata_filters or {}).items():
            if value in (None, "", [], {}):
                continue
            if key == "max_price":
                must_conditions.append(
                    models.FieldCondition(
                        key="price",
                        range=models.Range(lte=float(value)),
                    )
                )
            elif key == "min_price":
                must_conditions.append(
                    models.FieldCondition(
                        key="price",
                        range=models.Range(gte=float(value)),
                    )
                )
            elif key == "categories" and isinstance(value, list):
                must_conditions.append(
                    models.FieldCondition(
                        key="categories",
                        match=models.MatchAny(any=[str(item).lower() for item in value]),
                    )
                )
            elif key == "brand":
                must_conditions.append(
                    models.FieldCondition(
                        key="brand",
                        match=models.MatchValue(value=str(value)),
                    )
                )
            elif key == "stock_status":
                must_conditions.append(
                    models.FieldCondition(
                        key="stock_status",
                        match=models.MatchValue(value=str(value)),
                    )
                )
            elif key == "attributes" and isinstance(value, dict):
                for attr_key, attr_value in value.items():
                    if attr_value in (None, "", [], {}):
                        continue
                    must_conditions.append(
                        models.FieldCondition(
                            key=f"attributes.{attr_key}",
                            match=models.MatchValue(value=str(attr_value)),
                        )
                    )
            else:
                must_conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=str(value)),
                    )
                )
        query_filter = models.Filter(must=must_conditions) if must_conditions else None
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
