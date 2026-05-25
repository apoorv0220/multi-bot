from retrieval.query_validator import _canonical_gazetteer_category, validate_structured_query
from retrieval.rules_prepass import rules_prepass


def _apparel_gazetteer_profile():
    return {
        "facets": {},
        "category_strategy": {
            "gazetteer": [
                {"id": "erin_recommends", "labels": ["Erin Recommends"], "aliases": {}},
                {"id": "fitness_equipment", "labels": ["Fitness Equipment"], "aliases": {}},
                {"id": "jackets", "labels": ["Jackets"], "aliases": {}},
                {"id": "men", "labels": ["Men"], "aliases": {}},
                {"id": "men_sale", "labels": ["Men Sale"], "aliases": {}},
                {"id": "women", "labels": ["Women"], "aliases": {}},
                {"id": "women_sale", "labels": ["Women Sale"], "aliases": {}},
            ]
        },
        "stats": {"product_count": 100},
    }


def test_canonical_men_not_erin_recommends():
    profile = _apparel_gazetteer_profile()
    assert _canonical_gazetteer_category("men", profile) == "men"


def test_canonical_women_not_men():
    profile = _apparel_gazetteer_profile()
    assert _canonical_gazetteer_category("women", profile) == "women"


def test_validate_mens_jackets_keeps_men_and_jackets():
    profile = _apparel_gazetteer_profile()
    sq = validate_structured_query(
        rules_prepass("Show me some men's jackets", profile=profile),
        profile=profile,
    )
    assert "men" in sq.category.values
    assert "jackets" in sq.category.values
    assert "erin_recommends" not in sq.category.values


def test_canonical_jacket_matches_jackets_id():
    profile = _apparel_gazetteer_profile()
    assert _canonical_gazetteer_category("jacket", profile) == "jackets"
