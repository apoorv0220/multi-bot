from retrieval.rules_prepass import _match_category_product_type


def _profile_with_tees_and_erin():
    return {
        "category_strategy": {
            "gazetteer": [
                {"id": "erin_recommends", "labels": ["Erin Recommends"], "aliases": {}},
                {"id": "tops", "labels": ["Tops"], "aliases": {}},
                {"id": "tees", "labels": ["Tees"], "aliases": {}},
                {"id": "pants", "labels": ["Pants"], "aliases": {}},
            ]
        }
    }


def test_t_shirts_prefers_tee_category_over_erin_recommends():
    profile = _profile_with_tees_and_erin()
    values, conf = _match_category_product_type(
        "Show me men's t-shirts, but nothing in red",
        profile,
    )
    assert values
    assert values[0] in {"tees", "tops"}
    assert conf >= 0.85


def test_pants_phrase_matches_pants_gazetteer():
    profile = _profile_with_tees_and_erin()
    values, conf = _match_category_product_type("Show me men's pants", profile)
    assert values == ["pants"]
    assert conf >= 0.85
