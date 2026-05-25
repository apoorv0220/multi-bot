from __future__ import annotations

import os
from typing import Any

# ISO 4217 codes we format explicitly; unknown codes fall back to "CODE amount".
_CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "GBP": "£",
    "EUR": "€",
    "AUD": "A$",
    "CAD": "C$",
    "NZD": "NZ$",
    "INR": "₹",
    "JPY": "¥",
    "CNY": "¥",
    "CHF": "CHF ",
    "SEK": "kr ",
    "NOK": "kr ",
    "DKK": "kr ",
}


def default_currency_code() -> str:
    raw = (os.getenv("TENANT_DEFAULT_CURRENCY") or "USD").strip().upper()
    return normalize_currency_code(raw) or "USD"


def normalize_currency_code(value: str | None) -> str | None:
    code = (value or "").strip().upper()
    if not code:
        return None
    if len(code) == 3 and code.isalpha():
        return code
    aliases = {
        "$": "USD",
        "US$": "USD",
        "£": "GBP",
        "GB£": "GBP",
        "€": "EUR",
        "EURO": "EUR",
    }
    return aliases.get(code, None)


def currency_symbol(currency_code: str | None) -> str:
    code = normalize_currency_code(currency_code) or default_currency_code()
    return _CURRENCY_SYMBOLS.get(code, f"{code} ")


def format_money(amount: Any, currency_code: str | None = None) -> str:
    """Format a numeric catalog price with the tenant store currency."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    code = normalize_currency_code(currency_code) or default_currency_code()
    symbol = _CURRENCY_SYMBOLS.get(code)
    if symbol:
        if code == "JPY":
            return f"{symbol}{value:,.0f}"
        if symbol.endswith(" "):
            return f"{symbol}{value:,.2f}"
        return f"{symbol}{value:,.2f}"
    return f"{code} {value:,.2f}"


def currency_from_profile(profile: dict[str, Any] | None) -> str:
    if profile:
        core = profile.get("core_fields") or {}
        price_meta = core.get("price") or {}
        code = price_meta.get("currency")
        normalized = normalize_currency_code(str(code) if code else None)
        if normalized:
            return normalized
        stats = profile.get("stats") or {}
        code = stats.get("currency")
        normalized = normalize_currency_code(str(code) if code else None)
        if normalized:
            return normalized
    return default_currency_code()
