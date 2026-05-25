import asyncio

from retrieval.turn_adequacy import (
    apply_turn_adequacy,
    is_support_cms_fallback,
)


CMS_ANSWER = (
    "I could not find return or policy information in the indexed content for this store. "
    "It may not be in the Magento CMS tables yet—add a CMS page or include a static policy URL "
    "in tenant source settings, then reindex."
)


def test_support_cms_fallback_detection():
    assert is_support_cms_fallback(CMS_ANSWER)


def test_product_detail_cms_answer_is_repaired():
    message = "Please provide me more description for product: Beaumont Summit Kit"
    result = asyncio.run(
        apply_turn_adequacy(
            user_message=message,
            answer=CMS_ANSWER,
            response_subtype="support_faq",
            structured_query_intent="support",
            llm_call=None,
        )
    )
    assert result.repaired is True
    assert result.passed is False
    assert "Beaumont Summit Kit" in result.answer
    assert "return or policy" not in result.answer.lower()
    assert result.meta["turn_adequacy"]["issues"]


def test_browse_all_missing_website_link_is_repaired():
    message = "Show me all products"
    result = asyncio.run(
        apply_turn_adequacy(
            user_message=message,
            answer="Here are 4 products from our catalog.",
            response_subtype="category_plp_sample",
            browse_all=True,
            products=[{"title": "Bag", "url": "https://store.example.com/bag.html"}],
            website_url=None,
            llm_call=None,
        )
    )
    assert result.repaired is True
    assert "store.example.com" in result.answer
    assert result.actions
    assert result.actions[0]["url"] == "https://store.example.com"


def test_adequate_product_detail_passes():
    message = "Please provide me more description for product: Beaumont Summit Kit"
    answer = "**Beaumont Summit Kit**\n\nA lightweight training kit for summit hikes."
    result = asyncio.run(
        apply_turn_adequacy(
            user_message=message,
            answer=answer,
            response_subtype="product_detail",
            structured_query_intent="catalog",
            products=[{"title": "Beaumont Summit Kit", "url": "https://store.example.com/beaumont.html"}],
            llm_call=None,
        )
    )
    assert result.passed is True
    assert result.repaired is False
