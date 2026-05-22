from retrieval.post_filter import _facet_value_excludes_match


def test_wool_does_not_exclude_organic_cotton():
    assert not _facet_value_excludes_match("wool", ["nylon", "organic cotton", "spandex"])


def test_wool_excludes_wool_blend():
    assert _facet_value_excludes_match("wool", ["wool blend"])


def test_polyester_does_not_exclude_nylon_cotton():
    assert not _facet_value_excludes_match("polyester", ["nylon", "organic cotton", "spandex"])
