from retrieval.query_validator import validate_structured_query
from retrieval.structured_query import FacetSpec, StructuredQuery


def test_soft_facet_kept_when_not_in_samples():
    profile = {
        "facets": {
            "color": {
                "indexed": True,
                "sample_values": ["red", "blue", "black"],
            }
        },
        "category_strategy": {"gazetteer": [{"id": "jackets", "labels": ["Jackets"]}]},
    }
    query = StructuredQuery(
        intent="catalog",
        facets={"color": FacetSpec(values=["lavender"])},
    )
    validated = validate_structured_query(query, profile=profile)
    assert validated.facets["color"].values == ["lavender"]
    assert validated.validation_meta.get("soft_facets", {}).get("color") == ["lavender"]


def test_brand_dropped_when_not_in_samples():
    profile = {
        "core_fields": {
            "brand": {"indexed": True, "sample_values": ["Joust", "Sprite"]},
        },
        "facets": {},
        "category_strategy": {"gazetteer": []},
    }
    query = StructuredQuery(
        intent="catalog",
        facets={"brand": FacetSpec(values=["Nike"])},
    )
    validated = validate_structured_query(query, profile=profile)
    assert "brand" not in validated.facets
    assert validated.validation_meta.get("dropped_brands") == ["Nike"]
