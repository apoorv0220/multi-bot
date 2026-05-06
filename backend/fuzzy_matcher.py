"""
Tenant-aware fuzzy quick replies: neutral code defaults + per-tenant DB rules (admin-editable).

Templates may include: ${brand_name}, ${assistant_name}, ${website_url}
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from fuzzywuzzy import fuzz
from sqlalchemy import func, select

if TYPE_CHECKING:
    from models import Tenant, TenantQuickReply

DEFAULT_QUICK_REPLY_THRESHOLD = 85

# Code-only fallbacks when a tenant has no DB row for that trigger (or all were disabled).
# Keep generic — no PII, no vertical-specific claims. Tenant-specific copy belongs in DB via admin.
NEUTRAL_QUICK_REPLY_DEFAULTS: Dict[str, str] = {
    "hi": "Hello! I'm here to help with questions related to ${brand_name}. What would you like to know?",
    "hello": "Hello! I'm here to help with questions related to ${brand_name}. What would you like to know?",
    "hey": "Hi! I'm here to help with questions related to ${brand_name}. What would you like to know?",
    "good morning": "Good morning! How can I help you today?",
    "good afternoon": "Good afternoon! How can I help you today?",
    "good evening": "Good evening! How can I help you today?",
    "thank you": "You're welcome! Let me know if you need anything else.",
    "thanks": "Glad I could help. Ask me anything else you'd like to know.",
    "who are you": "I'm an assistant for ${brand_name}, here to answer your questions using this site's information.",
    "what are you": "I'm an assistant for ${brand_name}, here to answer your questions using trusted content.",
    "what can you do": "I can answer questions using content provided for ${brand_name}. What would you like to know?",
    "how can you help": "I can look up relevant information for you. What would you like to know?",
    "help": "I'm here to help. Ask a question in your own words, and I'll search for relevant information.",
    "help me": "I'm here to help. What would you like to know?",
}

# Preseed rows for new tenants / migration: (category, trigger_phrase, response_template, priority).
# Omit vertical-specific packs (pricing, contact numbers, emergency, etc.) — tenants add those in admin.
QUICK_REPLY_PRESEED_ROWS: List[Tuple[str, str, str, int]] = [
    ("greeting", "hi", NEUTRAL_QUICK_REPLY_DEFAULTS["hi"], 10),
    ("greeting", "hello", NEUTRAL_QUICK_REPLY_DEFAULTS["hello"], 10),
    ("greeting", "hey", NEUTRAL_QUICK_REPLY_DEFAULTS["hey"], 10),
    ("greeting", "good morning", NEUTRAL_QUICK_REPLY_DEFAULTS["good morning"], 10),
    ("greeting", "good afternoon", NEUTRAL_QUICK_REPLY_DEFAULTS["good afternoon"], 10),
    ("greeting", "good evening", NEUTRAL_QUICK_REPLY_DEFAULTS["good evening"], 10),
    ("gratitude", "thank you", NEUTRAL_QUICK_REPLY_DEFAULTS["thank you"], 10),
    ("gratitude", "thanks", NEUTRAL_QUICK_REPLY_DEFAULTS["thanks"], 10),
    ("identity", "who are you", NEUTRAL_QUICK_REPLY_DEFAULTS["who are you"], 10),
    ("identity", "what are you", NEUTRAL_QUICK_REPLY_DEFAULTS["what are you"], 10),
    ("identity", "what can you do", NEUTRAL_QUICK_REPLY_DEFAULTS["what can you do"], 10),
    ("identity", "how can you help", NEUTRAL_QUICK_REPLY_DEFAULTS["how can you help"], 10),
    ("help", "help", NEUTRAL_QUICK_REPLY_DEFAULTS["help"], 10),
    ("help", "help me", NEUTRAL_QUICK_REPLY_DEFAULTS["help me"], 10),
]

_TEMPLATE_PATTERN = re.compile(r"\$\{(brand_name|assistant_name|website_url)\}")


def normalize_trigger_phrase(phrase: str) -> str:
    return (phrase or "").strip().lower()


def substitute_quick_reply_template(tenant: Optional["Tenant"], template: str) -> str:
    if not template:
        return ""
    brand = ""
    assistant = ""
    website = ""
    if tenant:
        brand = (tenant.brand_name or tenant.name or "this organisation").strip() or "this organisation"
        assistant = (tenant.widget_header_title or tenant.brand_name or tenant.name or "Assistant").strip() or "Assistant"
        website = (tenant.widget_website_url or "").strip()
    else:
        brand = "this organisation"
        assistant = "Assistant"

    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key == "brand_name":
            return brand
        if key == "assistant_name":
            return assistant
        if key == "website_url":
            return website
        return m.group(0)

    return _TEMPLATE_PATTERN.sub(repl, template)


def _build_merged_rule_map(
    db,
    tenant_id: uuid.UUID,
) -> Dict[str, Tuple[str, Optional[int], int]]:
    """trigger_lower -> (response_template, similarity_threshold or None, priority). DB overrides neutral for same trigger."""
    from models import TenantQuickReply

    rows = db.execute(
        select(TenantQuickReply)
        .where(
            TenantQuickReply.tenant_id == tenant_id,
            TenantQuickReply.enabled.is_(True),
        )
        .order_by(TenantQuickReply.priority.desc(), TenantQuickReply.created_at.asc())
    ).scalars().all()

    merged: Dict[str, Tuple[str, Optional[int], int]] = {}
    for row in rows:
        key = normalize_trigger_phrase(row.trigger_phrase)
        if not key:
            continue
        merged[key] = (row.response_template, row.similarity_threshold, row.priority)

    for trig, tmpl in NEUTRAL_QUICK_REPLY_DEFAULTS.items():
        k = normalize_trigger_phrase(trig)
        if k not in merged:
            merged[k] = (tmpl, None, 0)

    return merged


def get_tenant_quick_reply(db, tenant_id: str, query: str, tenant: Optional["Tenant"]) -> Optional[Dict[str, Any]]:
    """DB + neutral defaults; fuzzy match; return same shape as legacy fuzzy get_response."""
    from models import Tenant

    tid = uuid.UUID(str(tenant_id))
    rule_map = _build_merged_rule_map(db, tid)
    if not rule_map:
        return None

    clean_q = normalize_trigger_phrase(query)
    if not clean_q:
        return None

    best_template: Optional[str] = None
    best_score = -1
    best_priority = -10_000

    for trigger, (template, th_override, priority) in rule_map.items():
        th = th_override if th_override is not None else DEFAULT_QUICK_REPLY_THRESHOLD
        if clean_q == trigger:
            score = 100
        else:
            score = fuzz.ratio(clean_q, trigger)
        if score < th:
            continue
        if score > best_score or (score == best_score and priority > best_priority):
            best_score = score
            best_priority = priority
            best_template = template

    if not best_template:
        return None

    rendered = substitute_quick_reply_template(tenant, best_template)
    return {
        "response": rendered,
        "confidence": best_score / 100.0,
        "source": "fuzzy_match",
        "sources": [],
    }


def seed_quick_replies_for_tenant(db, tenant_id: uuid.UUID) -> int:
    """Insert preseed rows if tenant has none. Returns number of rows inserted."""
    from models import TenantQuickReply

    cnt = db.execute(
        select(func.count()).select_from(TenantQuickReply).where(TenantQuickReply.tenant_id == tenant_id)
    ).scalar_one()
    if int(cnt or 0) > 0:
        return 0

    inserted = 0
    for category, trigger, tmpl, priority in QUICK_REPLY_PRESEED_ROWS:
        db.add(
            TenantQuickReply(
                tenant_id=tenant_id,
                category=category,
                trigger_phrase=normalize_trigger_phrase(trigger),
                response_template=tmpl,
                similarity_threshold=None,
                priority=priority,
                enabled=True,
            )
        )
        inserted += 1
    return inserted


class FuzzyMatcher:
    """Backward-compatible matcher using only neutral defaults (no tenant / DB)."""

    def __init__(self, similarity_threshold: int = DEFAULT_QUICK_REPLY_THRESHOLD):
        self.similarity_threshold = similarity_threshold
        self.response_db = dict(NEUTRAL_QUICK_REPLY_DEFAULTS)

    def clean_query(self, query: str) -> str:
        return normalize_trigger_phrase(query)

    def find_best_match(self, query: str) -> Optional[Tuple[str, int]]:
        clean_query = self.clean_query(query)
        best_match = None
        best_score = 0
        for key, response in self.response_db.items():
            if clean_query == key.lower():
                return response, 100
            score = fuzz.ratio(clean_query, key.lower())
            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                best_match = response
        return (best_match, best_score) if best_match else None

    def get_response(self, query: str) -> Optional[Dict[str, Any]]:
        match_result = self.find_best_match(query)
        if not match_result:
            return None
        response, confidence = match_result
        return {
            "response": substitute_quick_reply_template(None, response),
            "confidence": confidence / 100.0,
            "source": "fuzzy_match",
            "sources": [],
        }

    def get_suggestions(self, query: str, limit: int = 5) -> List[str]:
        clean_query = self.clean_query(query)
        suggestions = []
        for key in self.response_db.keys():
            if clean_query in key.lower() or key.lower() in clean_query:
                suggestions.append(key)
                if len(suggestions) >= limit:
                    break
        return suggestions


def get_fuzzy_response(query: str) -> Optional[str]:
    matcher = FuzzyMatcher()
    result = matcher.get_response(query)
    return result["response"] if result else None
