from types import SimpleNamespace

from sources.magento_fetcher import MagentoFetcher


def test_expand_category_path_womens_jacket_chain():
    id_to_name = {
        1: "Root Catalog",
        2: "Default Category",
        20: "Women",
        21: "Tops",
        23: "Jackets",
    }
    names = MagentoFetcher.expand_category_path("1/2/20/21/23", id_to_name)
    assert names == ["Women", "Tops", "Jackets"]


def test_expand_category_path_mens_jacket_chain():
    id_to_name = {
        1: "Root Catalog",
        2: "Default Category",
        19: "Men",
        22: "Tops",
        24: "Jackets",
    }
    names = MagentoFetcher.expand_category_path("1/2/19/22/24", id_to_name)
    assert names == ["Men", "Tops", "Jackets"]


def test_merge_product_category_paths_unions_assignments():
    id_to_name = {20: "Women", 21: "Tops", 23: "Jackets", 12: "Sale"}
    merged = MagentoFetcher.merge_product_category_paths(
        "1/2/20/21/23|||1/2/12",
        id_to_name,
    )
    assert merged == ["Women", "Tops", "Jackets", "Sale"]


def test_rules_prepass_mens_jackets_keeps_men_and_garment_type():
    profile = {
        "facets": {"color": {"sample_values": ["Red"], "value_aliases": {}, "indexed": True}},
        "category_strategy": {
            "gazetteer": [
                {"id": "men", "labels": ["Men"], "aliases": {}},
                {"id": "women", "labels": ["Women"], "aliases": {}},
                {"id": "jackets", "labels": ["Jackets"], "aliases": {}},
            ]
        },
        "stats": {"product_count": 100},
    }
    from retrieval.query_validator import validate_structured_query
    from retrieval.rules_prepass import rules_prepass

    sq = validate_structured_query(
        rules_prepass("Show me some men's jackets", profile=profile),
        profile=profile,
    )
    assert "men" in sq.category.values
    assert "jackets" in sq.category.values


def test_filter_results_by_audience_excludes_opposite_gender():
    from retrieval.post_filter import filter_results_by_audience

    womens = SimpleNamespace(
        payload={"categories": ["women", "tops", "jackets"], "title": "WJ03"},
        score=0.9,
    )
    mens = SimpleNamespace(
        payload={"categories": ["men", "tops", "jackets"], "title": "MJ01"},
        score=0.8,
    )
    hits = filter_results_by_audience([womens, mens], ["jackets", "men"])
    assert len(hits) == 1
    assert hits[0].payload["title"] == "MJ01"


def test_filter_results_by_audience_neutral_query_unchanged():
    from retrieval.post_filter import filter_results_by_audience

    womens = SimpleNamespace(payload={"categories": ["women", "jackets"]}, score=0.9)
    mens = SimpleNamespace(payload={"categories": ["men", "jackets"]}, score=0.8)
    hits = filter_results_by_audience([womens, mens], ["jackets"])
    assert len(hits) == 2
