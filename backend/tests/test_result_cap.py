from retrieval.max_results import parse_explicit_result_cap


def test_parse_top_n():
    assert parse_explicit_result_cap("Show only top 5 products") == 5
    assert parse_explicit_result_cap("show me top 3 jackets") == 3


def test_parse_no_cap():
    assert parse_explicit_result_cap("show me shoes") is None
