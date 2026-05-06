"""idle rating settings and session ratings

Revision ID: 0008_idle_rating
Revises: 0007_tenant_block_words
Create Date: 2026-04-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_idle_rating"
down_revision = "0007_tenant_block_words"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("idle_rating_wait_seconds", sa.Integer(), nullable=False, server_default="120"))
    op.alter_column("tenants", "idle_rating_wait_seconds", server_default=None)

    op.create_table(
        "session_experience_ratings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_id", sa.String(length=64), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_session_experience_rating_session"),
    )
    op.create_index("ix_session_experience_ratings_tenant", "session_experience_ratings", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_session_experience_ratings_tenant", table_name="session_experience_ratings")
    op.drop_table("session_experience_ratings")
    op.drop_column("tenants", "idle_rating_wait_seconds")
