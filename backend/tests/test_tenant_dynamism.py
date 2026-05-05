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


def test_normalize_source_static_urls_json_dedupes_and_strips_tracking():
    from main import _normalize_source_static_urls_json

    raw = """
https://www.chilliapple.newsoftdemo.info/about?utm_source=abc
https://www.chilliapple.co.uk/about
https://www.chilliapple.co.uk/wp-admin
"""
    normalized = _normalize_source_static_urls_json(
        raw,
        domain_aliases=["https://www.chilliapple.newsoftdemo.info"],
        canonical_base="https://www.chilliapple.co.uk",
    )
    assert normalized is not None
    urls = __import__("json").loads(normalized)
    assert urls == ["https://www.chilliapple.co.uk/about"]


def test_embedder_static_urls_use_canonical_host():
    from collections import namedtuple
    from unittest.mock import MagicMock

    Coll = namedtuple("C", ["name"])
    client = MagicMock()
    client.get_collections.return_value = MagicMock(collections=[Coll(name="tenant_test_docs")])

    e = Embedder(
        client=client,
        collection_name="tenant_test_docs",
        source_config={
            "source_mode": "mixed",
            "source_static_urls_json": '["https://www.chilliapple.newsoftdemo.info/about?utm_source=abc", "https://www.chilliapple.co.uk/about/"]',
            "source_domain_aliases": "https://www.chilliapple.newsoftdemo.info",
            "source_canonical_base_url": "https://www.chilliapple.co.uk",
        },
    )
    static_urls = e._get_static_urls()
    assert static_urls == [
        {
            "url": "https://www.chilliapple.co.uk/about",
            "title": "MRN Web Designs website content",
            "description": "Static website content from https://www.chilliapple.co.uk/about",
        }
    ]
