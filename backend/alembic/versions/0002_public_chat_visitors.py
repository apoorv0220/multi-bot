"""public chat visitors

Revision ID: 0002_public_chat_visitors
Revises: 0001_multitenant_baseline
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_public_chat_visitors"
down_revision = "0001_multitenant_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("visitor_id", sa.String(length=64), nullable=True))
    op.add_column("chat_sessions", sa.Column("visitor_name", sa.String(length=255), nullable=True))
    op.add_column("chat_sessions", sa.Column("visitor_email", sa.String(length=255), nullable=True))

    op.create_table(
        "chat_visitors",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("visitor_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "visitor_id", name="uq_chat_visitors_tenant_visitor"),
    )
    op.create_index("ix_chat_visitors_tenant_email", "chat_visitors", ["tenant_id", "email"])
    op.create_index("ix_chat_visitors_tenant_name", "chat_visitors", ["tenant_id", "name"])


def downgrade() -> None:
    op.drop_index("ix_chat_visitors_tenant_name", table_name="chat_visitors")
    op.drop_index("ix_chat_visitors_tenant_email", table_name="chat_visitors")
    op.drop_table("chat_visitors")

    op.drop_column("chat_sessions", "visitor_email")
    op.drop_column("chat_sessions", "visitor_name")
    op.drop_column("chat_sessions", "visitor_id")
