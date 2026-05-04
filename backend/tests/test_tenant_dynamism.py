"""Regression tests for tenant-aware chat / indexing behaviour (no external I/O)."""

from types import SimpleNamespace

from embedder import Embedder, LEGACY_VECTOR_PRIMARY_SOURCE_LABEL, LEGACY_VECTOR_PRIMARY_SOURCE_TYPE


def test_legacy_fuzzy_matcher_gating():
    from main import _tenant_uses_legacy_fuzzy_matcher

    assert _tenant_uses_legacy_fuzzy_matcher(None) is True
    assert _tenant_uses_legacy_fuzzy_matcher(SimpleNamespace(widget_source_type=None)) is True
    assert _tenant_uses_legacy_fuzzy_matcher(SimpleNamespace(widget_source_type="")) is True
    assert _tenant_uses_legacy_fuzzy_matcher(SimpleNamespace(widget_source_type="  ")) is True
    assert _tenant_uses_legacy_fuzzy_matcher(SimpleNamespace(widget_source_type=LEGACY_VECTOR_PRIMARY_SOURCE_TYPE)) is True
    assert _tenant_uses_legacy_fuzzy_matcher(SimpleNamespace(widget_source_type="migraine_ie")) is False


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
