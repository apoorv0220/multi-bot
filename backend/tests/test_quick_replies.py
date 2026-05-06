from types import SimpleNamespace

from fuzzy_matcher import get_tenant_quick_reply, normalize_trigger_phrase, substitute_quick_reply_template


def test_normalize_trigger():
    assert normalize_trigger_phrase("  Hello ") == "hello"


def test_substitute_quick_reply_template():
    tenant = SimpleNamespace(
        brand_name="Acme",
        name="Acme Inc",
        widget_header_title="Helper Bot",
        widget_website_url="https://acme.example",
    )
    out = substitute_quick_reply_template(
        tenant,
        "Hi from ${assistant_name} — ${brand_name} — ${website_url}",
    )
    assert "Helper Bot" in out
    assert "Acme" in out
    assert "https://acme.example" in out


def test_get_tenant_quick_reply_uses_db_row():
    """When DB has a row, response uses template + substitution."""
    from unittest.mock import MagicMock

    tenant = SimpleNamespace(
        brand_name="BrandX",
        name="BrandX",
        widget_header_title="",
        widget_website_url="",
    )
    row = MagicMock()
    row.trigger_phrase = "hello"
    row.response_template = "Hey from ${brand_name}"
    row.similarity_threshold = None
    row.priority = 10
    row.enabled = True

    db = MagicMock()

    def exec_side_effect(q, *a, **kw):
        m = MagicMock()
        m.scalars.return_value.all.return_value = [row]
        return m

    db.execute.side_effect = exec_side_effect

    out = get_tenant_quick_reply(db, "00000000-0000-0000-0000-000000000001", "hello", tenant)
    assert out is not None
    assert "BrandX" in out["response"]
    assert out["source"] == "fuzzy_match"
