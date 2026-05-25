from retrieval.tools.list_categories import list_categories_from_profile, find_category_in_profile


def test_list_categories_from_gazetteer():
    profile = {
        "category_strategy": {
            "gazetteer": [
                {"id": "jackets", "labels": ["Jackets"], "url": "https://shop/jackets"},
                {"id": "men", "labels": ["Men"]},
            ]
        }
    }
    cats = list_categories_from_profile(profile)
    assert any(c["name"] == "Jackets" for c in cats)
    assert find_category_in_profile("jackets", profile)["id"] == "jackets"
