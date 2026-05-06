"""tenant block word categories

Revision ID: 0007_tenant_block_words
Revises: 0006_tenant_branding_and_cors
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_tenant_block_words"
down_revision = "0006_tenant_branding_and_cors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("block_triggered", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("chat_sessions", "block_triggered", server_default=None)
    op.create_table(
        "tenant_block_word_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("match_mode", sa.String(length=20), nullable=False),
        sa.Column("response_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tenant_block_word_category_name"),
    )
    op.create_index("ix_tenant_block_word_categories_tenant", "tenant_block_word_categories", ["tenant_id"])

    op.create_table(
        "tenant_block_words",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("word", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["tenant_block_word_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_id", "word", name="uq_tenant_block_word"),
    )
    op.create_index("ix_tenant_block_words_category", "tenant_block_words", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_block_words_category", table_name="tenant_block_words")
    op.drop_table("tenant_block_words")
    op.drop_index("ix_tenant_block_word_categories_tenant", table_name="tenant_block_word_categories")
    op.drop_table("tenant_block_word_categories")

    op.drop_column("chat_sessions", "block_triggered")

