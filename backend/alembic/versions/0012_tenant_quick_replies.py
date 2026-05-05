"""tenant quick replies (fuzzy canned responses)

Revision ID: 0012_tenant_quick_replies
Revises: 0011_msg_text_colors
Create Date: 2026-05-04
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0012_tenant_quick_replies"
down_revision = "0011_msg_text_colors"
branch_labels = None
depends_on = None

# Keep in sync with fuzzy_matcher.QUICK_REPLY_PRESEED_ROWS / NEUTRAL_QUICK_REPLY_DEFAULTS.
_SEEDS: list[tuple[str, str, str, int]] = [
    (
        "greeting",
        "hi",
        "Hello! I'm here to help with questions related to ${brand_name}. What would you like to know?",
        10,
    ),
    (
        "greeting",
        "hello",
        "Hello! I'm here to help with questions related to ${brand_name}. What would you like to know?",
        10,
    ),
    (
        "greeting",
        "hey",
        "Hi! I'm here to help with questions related to ${brand_name}. What would you like to know?",
        10,
    ),
    ("greeting", "good morning", "Good morning! How can I help you today?", 10),
    ("greeting", "good afternoon", "Good afternoon! How can I help you today?", 10),
    ("greeting", "good evening", "Good evening! How can I help you today?", 10),
    ("gratitude", "thank you", "You're welcome! Let me know if you need anything else.", 10),
    ("gratitude", "thanks", "Glad I could help. Ask me anything else you'd like to know.", 10),
    (
        "identity",
        "who are you",
        "I'm an assistant for ${brand_name}, here to answer your questions using this site's information.",
        10,
    ),
    (
        "identity",
        "what are you",
        "I'm an assistant for ${brand_name}, here to answer your questions using trusted content.",
        10,
    ),
    (
        "identity",
        "what can you do",
        "I can answer questions using content provided for ${brand_name}. What would you like to know?",
        10,
    ),
    (
        "identity",
        "how can you help",
        "I can look up relevant information for you. What would you like to know?",
        10,
    ),
    (
        "help",
        "help",
        "I'm here to help. Ask a question in your own words, and I'll search for relevant information.",
        10,
    ),
    (
        "help",
        "help me",
        "I'm here to help. What would you like to know?",
        10,
    ),
]


def upgrade() -> None:
    op.create_table(
        "tenant_quick_replies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False, server_default=sa.text("'general'")),
        sa.Column("trigger_phrase", sa.String(length=255), nullable=False),
        sa.Column("response_template", sa.Text(), nullable=False),
        sa.Column("similarity_threshold", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("tenant_id", "trigger_phrase", name="uq_tenant_quick_reply_trigger"),
    )
    op.create_index("ix_tenant_quick_replies_tenant", "tenant_quick_replies", ["tenant_id"])

    conn = op.get_bind()
    tenants = conn.execute(sa.text("SELECT id FROM tenants")).fetchall()
    now = datetime.utcnow()
    for (tid,) in tenants:
        for cat, trig, tmpl, pri in _SEEDS:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO tenant_quick_replies
                    (id, tenant_id, category, trigger_phrase, response_template, similarity_threshold, priority, enabled, created_at, updated_at)
                    VALUES (:id, :tid, :cat, :trig, :tmpl, NULL, :pri, true, :ts, :ts)
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tid,
                    "cat": cat,
                    "trig": trig.strip().lower(),
                    "tmpl": tmpl,
                    "pri": pri,
                    "ts": now,
                },
            )


def downgrade() -> None:
    op.drop_index("ix_tenant_quick_replies_tenant", table_name="tenant_quick_replies")
    op.drop_table("tenant_quick_replies")
