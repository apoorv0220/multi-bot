import asyncio

from indexing.pipeline import IndexingPipeline
from sources.base import SourceRecord, SyncBatch


class FakeQdrantClient:
    def __init__(self):
        self.deleted = []
        self.upserts = []

    def delete(self, **kwargs):
        self.deleted.append(kwargs)

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)


async def _fake_embedding(_text):
    return [0.1, 0.2, 0.3]


def test_indexing_pipeline_clears_provider_once_and_upserts_records(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_HYBRID_ENABLED", "false")
    client = FakeQdrantClient()
    pipeline = IndexingPipeline(
        qdrant_client=client,
        collection_name="tenant_a_docs",
        embedding_func=_fake_embedding,
        source_label="Acme",
        source_type="acme",
    )
    batch = SyncBatch(
        tenant_id="tenant-a",
        provider="woocommerce",
        mode="full",
        records=[
            SourceRecord(
                source_provider="woocommerce",
                content_kind="product",
                entity_id="10",
                title="Widget",
                body="Widget body",
                canonical_url="https://shop.example.com/product/widget/",
                metadata={
                    "categories": ["Widgets"],
                    "brand": "Acme",
                    "image_url": "https://shop.example.com/wp-content/uploads/widget.jpg",
                },
            ),
            SourceRecord(
                source_provider="woocommerce",
                content_kind="category",
                entity_id="22",
                title="Widgets",
                body="Category body",
                canonical_url="https://shop.example.com/product-category/widgets/",
            ),
        ],
    )
    result = asyncio.run(pipeline.process_batches([batch]))
    assert len(client.deleted) == 1
    assert len(client.upserts) == 2
    assert result["woocommerce"]["indexed_records"] == 2
    payloads = [upsert["points"][0].payload for upsert in client.upserts]
    product_payload = next(p for p in payloads if p.get("content_kind") == "product")
    assert product_payload.get("image_url") == "https://shop.example.com/wp-content/uploads/widget.jpg"


def test_indexing_pipeline_honors_deleted_records(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_HYBRID_ENABLED", "false")
    client = FakeQdrantClient()
    pipeline = IndexingPipeline(
        qdrant_client=client,
        collection_name="tenant_a_docs",
        embedding_func=_fake_embedding,
        source_label="Acme",
        source_type="acme",
    )
    batch = SyncBatch(
        tenant_id="tenant-a",
        provider="woocommerce",
        mode="incremental",
        records=[
            SourceRecord(
                source_provider="woocommerce",
                content_kind="product",
                entity_id="10",
                title="Widget",
                deleted=True,
            )
        ],
    )
    result = asyncio.run(pipeline.process_batches([batch]))
    assert len(client.deleted) == 1
    assert client.upserts == []
    assert result["woocommerce"]["deleted_records"] == 1
