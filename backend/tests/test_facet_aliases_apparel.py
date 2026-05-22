from retrieval.profile import resolve_facet_value_to_sample


def test_violet_maps_to_purple_when_sample_exists():
    meta = {"sample_values": ["Purple", "Red"], "value_aliases": {}}
    assert resolve_facet_value_to_sample("color", "violet", meta) == "purple"


def test_denim_material_alias():
    meta = {"sample_values": ["Denim", "Cotton"], "value_aliases": {}}
    assert resolve_facet_value_to_sample("material", "denim", meta) == "denim"
