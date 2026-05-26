from __future__ import annotations

import re

_ALPHA_GIBBERISH = re.compile(r"^[a-z]{6,}$", re.IGNORECASE)
_DIGITS_ONLY = re.compile(r"^\d+$")
_PUNCT_ONLY = re.compile(r"^[^\w\s]+$", re.UNICODE)


def is_gibberish_message(message: str) -> bool:
    """Single-token inputs that are not plausible catalog queries."""
    msg = (message or "").strip()
    if not msg or " " in msg:
        return False
    if len(msg) >= 6 and _ALPHA_GIBBERISH.match(msg):
        return True
    if len(msg) >= 4 and _DIGITS_ONLY.match(msg):
        return True
    if len(msg) >= 3 and _PUNCT_ONLY.match(msg):
        return True
    if not any(ch.isalnum() for ch in msg):
        return True
    return False
