"""usage tracking

Revision ID: 0003_usage_tracking
Revises: 0002_public_chat_visitors
Create Date: 2026-04-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_usage_tracking"
down_revision = "0002_public_chat_visitors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    usage_type = postgresql.ENUM(
        "chat_completion",
        "chat_embedding",
        "index_embedding",
        name="usagetype",
        create_type=False,
    )
    usage_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "usage_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("session_id", sa.UUID(), sa.ForeignKey("chat_sessions.id"), nullable=True),
        sa.Column("message_id", sa.UUID(), sa.ForeignKey("chat_messages.id"), nullable=True),
        sa.Column("usage_type", usage_type, nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_usage_events_tenant_created", "usage_events", ["tenant_id", "created_at"])
    op.create_index("ix_usage_events_session_created", "usage_events", ["session_id", "created_at"])
    op.create_index("ix_usage_events_type_created", "usage_events", ["usage_type", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_usage_events_type_created", table_name="usage_events")
    op.drop_index("ix_usage_events_session_created", table_name="usage_events")
    op.drop_index("ix_usage_events_tenant_created", table_name="usage_events")
    op.drop_table("usage_events")
    sa.Enum(name="usagetype").drop(op.get_bind(), checkfirst=True)
