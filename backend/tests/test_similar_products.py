from retrieval.chat_orchestrator import build_static_response
from retrieval.subtype_classifier import SubtypeClassification
from retrieval.structured_query import empty_structured_query
from types import SimpleNamespace


def test_similar_products_static_intro():
    hits = [
        SimpleNamespace(
            payload={
                "title": "Anchor Jacket",
                "url": "https://x/a",
                "categories": ["jackets"],
                "entity_id": "1",
            }
        ),
        SimpleNamespace(
            payload={
                "title": "Other Jacket",
                "url": "https://x/b",
                "categories": ["jackets"],
                "entity_id": "2",
            }
        ),
    ]
    session = {"last_product_refs": [{"title": "Anchor Jacket", "url": "https://x/a"}]}
    extras = build_static_response(
        "show similar products",
        classification=SubtypeClassification(response_subtype="similar_products"),
        structured_query=empty_structured_query(intent="catalog"),
        session_state=session,
        profile=None,
        brand="Test",
        website_url=None,
        card_results=hits,
    )
    assert extras is not None
    assert extras.response_subtype == "similar_products"
    assert "similar" in extras.intro_text.lower()
