from sources.base import SourceRecord

from retrieval.profile import build_retrieval_profile, retrieval_profile_summary


def _product(**metadata):
    return SourceRecord(
        source_provider="woocommerce",
        content_kind="product",
        entity_id=metadata.pop("entity_id", "1"),
        title=metadata.pop("title", "Product"),
        metadata=metadata,
    )


def test_build_retrieval_profile_includes_facets_above_coverage():
    records = [
        _product(
            entity_id="1",
            price=49.0,
            stock_status="instock",
            brand="Acme",
            categories=["Shorts"],
            attributes={"color": ["black"], "finish": ["matt"], "material": ["denim"]},
        ),
        _product(
            entity_id="2",
            price=39.0,
            stock_status="instock",
            brand="Acme",
            categories=["Shorts"],
            attributes={"color": ["white"], "finish": ["glossy"], "material": ["denim"]},
        ),
        SourceRecord(
            source_provider="woocommerce",
            content_kind="category",
            entity_id="10",
            title="Shorts",
            metadata={"categories": ["Shorts"]},
        ),
    ]
    profile = build_retrieval_profile(records, tenant_id="tenant-a", previous_version=2)
    assert profile["profile_version"] == 3
    assert "color" in profile["facets"]
    assert "finish" in profile["facets"]
    assert profile["core_fields"]["price"]["indexed"] is True
    gazetteer_ids = {entry["id"] for entry in profile["category_strategy"]["gazetteer"]}
    assert "shorts" in gazetteer_ids


def test_build_retrieval_profile_drops_low_coverage_facet():
    records = [
        _product(entity_id=str(i), attributes={"color": ["black"]})
        for i in range(20)
    ]
    records.append(
        _product(entity_id="99", attributes={"color": ["black"], "rare_tag": ["x"]}),
    )
    profile = build_retrieval_profile(records, tenant_id="tenant-b")
    assert "color" in profile["facets"]
    assert "rare_tag" not in profile["facets"]


def test_retrieval_profile_summary_shape():
    profile = build_retrieval_profile(
        [_product(entity_id="1", attributes={"color": ["black"]})],
        tenant_id="tenant-c",
    )
    summary = retrieval_profile_summary(profile)
    assert summary["facet_ids"] == ["color"]
    assert summary["product_count"] == 1
