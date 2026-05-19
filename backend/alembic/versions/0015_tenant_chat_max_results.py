"""tenant chat max_results for general vs catalog

Revision ID: 0015_tenant_chat_max_results
Revises: 0014_chat_session_context
Create Date: 2026-05-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_tenant_chat_max_results"
down_revision = "0014_chat_session_context"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("chat_max_results", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("chat_max_results_catalog", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("tenants", "chat_max_results_catalog")
    op.drop_column("tenants", "chat_max_results")
