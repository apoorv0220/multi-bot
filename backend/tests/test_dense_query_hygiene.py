from retrieval.planner import _catalog_dense_query_text, apply_retrieval_rewrite
from retrieval.rules_prepass import _strip_matched_tokens
from retrieval.structured_query import FacetSpec, empty_structured_query


def test_catalog_dense_query_strips_filler_when_slots_present():
    sq = empty_structured_query(intent="catalog")
    sq.category.values = ["jackets"]
    sq.facets["color"] = FacetSpec(values=["blue"], combine="OR")
    sq.facets["size"] = FacetSpec(values=["l"], combine="OR")
    sq.price.max = 60.0
    sq.free_text = "Can you make those blue"
    rewritten = apply_retrieval_rewrite(sq)
    dense = _catalog_dense_query_text(rewritten)
    assert "blue" in dense
    assert "jackets" in dense
    assert "can" not in dense.split()
    assert "those" not in dense.split()


def test_strip_matched_tokens_removes_duplicate_commas():
    text = _strip_matched_tokens(
        "red,, bags, and more",
        category_values=["bags"],
        facets={"color": FacetSpec(values=["red"], combine="OR")},
    )
    assert ",," not in text
    assert "bags" not in text.lower() or "more" in text.lower()
