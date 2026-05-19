from unittest.mock import MagicMock

from qdrant_client.http import models

from indexing.sparse import encode_sparse
from integrations.vector_store import VectorStoreAdapter
from retrieval.hybrid import hybrid_search
from retrieval.planner import build_retrieval_plan
from retrieval.structured_query import FacetSpec, empty_structured_query
from tests.test_structured_query import _bath_profile
from retrieval.query_validator import validate_structured_query
from retrieval.rules_prepass import rules_prepass


def test_vector_store_builds_or_facet_filter():
    adapter = VectorStoreAdapter(MagicMock())
    filt = adapter.build_query_filter(
        metadata_filters={
            "facet_filters": {
                "finish": {"values": ["glossy", "matt"], "combine": "OR"},
            }
        }
    )
    assert filt is not None
    assert len(filt.must) == 1
    nested = filt.must[0]
    assert hasattr(nested, "should")
    assert len(nested.should) == 2


def test_planner_enables_hybrid_for_catalog_with_products():
    profile = _bath_profile()
    profile["stats"] = {"product_count": 25}
    query = validate_structured_query(
        rules_prepass("black basins", profile=profile),
        profile=profile,
    )
    plan = build_retrieval_plan(query, profile=profile)
    assert plan.use_retrieval_hybrid is True
    assert plan.lexical_query_text


def test_hybrid_search_uses_query_points_when_hybrid_collection(monkeypatch):
    client = MagicMock()
    client.get_collection.return_value = MagicMock(
        config=MagicMock(
            params=MagicMock(
                vectors={"dense": MagicMock()},
                sparse_vectors={"sparse": MagicMock()},
            )
        )
    )
    client.query_points.return_value = MagicMock(points=[])

    monkeypatch.setattr(
        "retrieval.hybrid.collection_uses_hybrid_vectors",
        lambda _c, _n: True,
    )
    monkeypatch.setattr(
        "retrieval.hybrid.encode_sparse",
        lambda _t: models.SparseVector(indices=[1, 2], values=[0.5, 0.3]),
    )

    hybrid_search(
        client,
        collection_name="tenant_x_docs",
        dense_vector=[0.1, 0.2],
        lexical_text="basin sku ABC-123",
        limit=5,
        content_bucket="catalog",
        metadata_filters={"brand": "Acme"},
    )
    assert client.query_points.called
    call_kwargs = client.query_points.call_args.kwargs
    assert len(call_kwargs["prefetch"]) == 2
    assert call_kwargs["prefetch"][0].filter == call_kwargs["prefetch"][1].filter


def test_encode_sparse_returns_none_when_disabled(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_HYBRID_ENABLED", "false")
    assert encode_sparse("black basin product") is None
