"""Regression tests for tenant-aware chat / indexing behaviour (no external I/O)."""

from types import SimpleNamespace

from embedder import Embedder, LEGACY_VECTOR_PRIMARY_SOURCE_LABEL, LEGACY_VECTOR_PRIMARY_SOURCE_TYPE


def test_tenant_chat_brand_label_fallback():
    from main import _tenant_chat_brand_label

    assert _tenant_chat_brand_label(None) == "MRN Web Designs"
    assert _tenant_chat_brand_label(SimpleNamespace(brand_name="", name="Acme")) == "Acme"
    assert _tenant_chat_brand_label(SimpleNamespace(brand_name="Brand", name="Acme")) == "Brand"


def test_embedder_vector_payload_defaults():
    """Constructor should default to legacy payload tags when omitted."""
    from collections import namedtuple
    from unittest.mock import MagicMock

    Coll = namedtuple("C", ["name"])
    client = MagicMock()
    client.get_collections.return_value = MagicMock(collections=[Coll(name="tenant_test_docs")])

    e = Embedder(
        client=client,
        collection_name="tenant_test_docs",
        source_config={},
    )
    assert e.vector_payload_source_type == LEGACY_VECTOR_PRIMARY_SOURCE_TYPE
    assert e.vector_payload_source_label == LEGACY_VECTOR_PRIMARY_SOURCE_LABEL
