import os

from commerce.currency import (
    currency_from_profile,
    default_currency_code,
    format_money,
    normalize_currency_code,
)
from retrieval.profile import build_retrieval_profile
from sources.base import SourceRecord


def test_normalize_currency_code():
    assert normalize_currency_code("usd") == "USD"
    assert normalize_currency_code("£") == "GBP"
    assert normalize_currency_code("$") == "USD"


def test_format_money_usd_and_gbp():
    assert format_money(77, "USD") == "$77.00"
    assert format_money(77, "GBP") == "£77.00"


def test_default_currency_from_env(monkeypatch):
    monkeypatch.setenv("TENANT_DEFAULT_CURRENCY", "GBP")
    assert default_currency_code() == "GBP"


def test_build_retrieval_profile_aggregates_currency():
    records = [
        SourceRecord(
            source_provider="magento",
            content_kind="product",
            entity_id="1",
            title="A",
            canonical_url="https://example.com/a",
            metadata={"price": 10, "currency": "USD"},
        ),
        SourceRecord(
            source_provider="magento",
            content_kind="product",
            entity_id="2",
            title="B",
            canonical_url="https://example.com/b",
            metadata={"price": 20, "currency": "USD"},
        ),
    ]
    profile = build_retrieval_profile(records, tenant_id="tenant-currency")
    assert profile["core_fields"]["price"]["currency"] == "USD"
    assert profile["stats"]["currency"] == "USD"
    assert currency_from_profile(profile) == "USD"


def test_currency_from_profile_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("TENANT_DEFAULT_CURRENCY", "USD")
    assert currency_from_profile(None) == "USD"
    assert currency_from_profile({}) == "USD"
