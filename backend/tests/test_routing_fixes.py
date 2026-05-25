import asyncio

from retrieval.rules_prepass import rules_prepass
from retrieval.structured_query import empty_structured_query
from retrieval.subtype_classifier import classify_response_subtype
from retrieval.tools.list_categories import find_category_in_profile
from retrieval.tools.product_refs import extract_product_title_from_message, is_product_detail_message
from retrieval.tools.category_sample import resolve_plp_category
from tests.test_query_validator import _apparel_gazetteer_profile


def test_find_category_men_not_erin_recommends():
    profile = _apparel_gazetteer_profile()
    hit = find_category_in_profile("men", profile)
    assert hit is not None
    assert hit["id"] == "men"


def test_resolve_plp_category_mens_clothing_prefers_men():
    profile = _apparel_gazetteer_profile()
    for entry in profile["category_strategy"]["gazetteer"]:
        if entry.get("id") == "men":
            entry["url"] = "https://example.com/men.html"
    sq = rules_prepass("Show me some men's clothing", profile=profile)
    hit = resolve_plp_category("Show me some men's clothing", sq, profile)
    assert hit is not None
    assert hit["id"] == "men"
    assert hit["url"] == "https://example.com/men.html"


def test_classify_product_description_for_named_product():
    sq = empty_structured_query(intent="catalog")
    message = "Please provide me more description for product: Beaumont Summit Kit"
    assert is_product_detail_message(message)
    assert extract_product_title_from_message(message) == "Beaumont Summit Kit"
    c = classify_response_subtype(message, structured_query=sq)
    assert c.response_subtype == "product_detail"


def test_rules_prepass_product_detail_skips_category_extraction():
    profile = _apparel_gazetteer_profile()
    message = "Please provide me more description for product: Beaumont Summit Kit"
    sq = rules_prepass(message, profile=profile)
    assert sq.intent == "catalog"
    assert sq.category.values == []
    assert sq.free_text == "Beaumont Summit Kit"


def test_classify_all_products_sets_browse_all():
    sq = empty_structured_query(intent="catalog")
    c = classify_response_subtype("Show me all products", structured_query=sq)
    assert c.response_subtype == "category_plp_sample"
    assert c.browse_all is True


def test_resolve_plp_category_all_products_returns_none():
    profile = _apparel_gazetteer_profile()
    sq = rules_prepass("Show me all products", profile=profile)
    assert resolve_plp_category("Show me all products", sq, profile) is None


def test_product_detail_query_understanding_skips_llm_support():
    from retrieval.query_understanding import run_query_understanding

    profile = _apparel_gazetteer_profile()
    message = "Please provide me more description for product: Beaumont Summit Kit"
    result = asyncio.run(
        run_query_understanding(message, profile, session_query=None, llm_call=object())
    )
    assert result.query.intent == "catalog"
    assert result.query.free_text == "Beaumont Summit Kit"
    assert result.query.catalog_coverage.in_catalog is True
    assert result.llm_used is False


def test_classify_product_detail_before_support():
    sq = empty_structured_query(intent="support")
    message = "Please provide me more description for product: Beaumont Summit Kit"
    c = classify_response_subtype(message, structured_query=sq)
    assert c.response_subtype == "product_detail"


def test_compose_category_plp_intro_includes_website_markdown():
    from retrieval.response_composer import compose_category_plp_intro

    text = compose_category_plp_intro(
        showing=4,
        total=None,
        website_url="https://magento-test.softdemonew.info",
    )
    assert "[full catalog on our website]" in text
    assert "https://magento-test.softdemonew.info" in text

