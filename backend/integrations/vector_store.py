from typing import Any

from qdrant_client.http import models


class VectorStoreAdapter:
    def __init__(self, qdrant_client):
        self.client = qdrant_client

    def build_query_filter(
        self,
        *,
        source_type: str | None = None,
        content_bucket: str | None = None,
        content_kind: str | None = None,
        metadata_filters: dict[str, Any] | None = None,
    ) -> models.Filter | None:
        must_conditions = self._build_must_conditions(
            source_type=source_type,
            content_bucket=content_bucket,
            content_kind=content_kind,
            metadata_filters=metadata_filters,
        )
        return models.Filter(must=must_conditions) if must_conditions else None

    def _build_must_conditions(
        self,
        *,
        source_type: str | None = None,
        content_bucket: str | None = None,
        content_kind: str | None = None,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[Any]:
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
        if content_kind:
            must_conditions.append(
                models.FieldCondition(
                    key="content_kind",
                    match=models.MatchValue(value=content_kind),
                )
            )
        for key, value in (metadata_filters or {}).items():
            if value in (None, "", [], {}):
                continue
            if key == "facet_filters":
                if not isinstance(value, dict):
                    continue
                for facet_id, facet_spec in value.items():
                    if not isinstance(facet_spec, dict):
                        continue
                    facet_values = facet_spec.get("values") or []
                    combine = facet_spec.get("combine") or "OR"
                    if not facet_values:
                        continue
                    attr_key = f"attributes.{facet_id}"
                    if combine == "OR" and len(facet_values) > 1:
                        should = [
                            models.FieldCondition(
                                key=attr_key,
                                match=models.MatchValue(value=str(item).lower()),
                            )
                            for item in facet_values
                        ]
                        must_conditions.append(models.Filter(should=should))
                    else:
                        for item in facet_values:
                            must_conditions.append(
                                models.FieldCondition(
                                    key=attr_key,
                                    match=models.MatchValue(value=str(item).lower()),
                                )
                            )
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
                            match=models.MatchValue(value=str(attr_value).lower()),
                        )
                    )
            else:
                must_conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=str(value)),
                    )
                )
        return must_conditions

    def search(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        limit: int,
        score_threshold: float | None = None,
        source_type: str | None = None,
        content_bucket: str | None = None,
        content_kind: str | None = None,
        metadata_filters: dict[str, Any] | None = None,
        vector_name: str | None = None,
    ) -> Any:
        must_conditions = self._build_must_conditions(
            source_type=source_type,
            content_bucket=content_bucket,
            content_kind=content_kind,
            metadata_filters=metadata_filters,
        )
        query_filter = models.Filter(must=must_conditions) if must_conditions else None
        if vector_name:
            query_vector_arg = models.NamedVector(name=vector_name, vector=query_vector)
        else:
            query_vector_arg = query_vector
        kwargs = {
            "collection_name": collection_name,
            "query_vector": query_vector_arg,
            "limit": limit,
        }
        if score_threshold is not None:
            kwargs["score_threshold"] = score_threshold
        if query_filter is not None:
            kwargs["query_filter"] = query_filter
        return self.client.search(**kwargs)
