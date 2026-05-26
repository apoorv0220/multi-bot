from retrieval.gibberish import is_gibberish_message
from retrieval.subtype_classifier import classify_response_subtype
from retrieval.structured_query import empty_structured_query


def test_gibberish_alpha():
    assert is_gibberish_message("asdfghjkl")


def test_gibberish_digits():
    assert is_gibberish_message("123456")


def test_gibberish_punctuation():
    assert is_gibberish_message("!!!!!")


def test_gibberish_emoji():
    assert is_gibberish_message("🔥")


def test_not_gibberish_catalog_query():
    assert not is_gibberish_message("show me shoes")


def test_classifier_gibberish_numeric():
    c = classify_response_subtype("123456", structured_query=empty_structured_query())
    assert c.response_subtype == "general_chat"
