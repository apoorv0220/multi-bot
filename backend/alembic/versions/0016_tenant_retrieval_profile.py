"""tenant retrieval facet profile (query understanding phase 1)

Revision ID: 0016_tenant_retrieval_profile
Revises: 0015_tenant_chat_max_results
Create Date: 2026-05-15 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_tenant_retrieval_profile"
down_revision = "0015_tenant_chat_max_results"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("retrieval_profile_json", sa.JSON(), nullable=True))
    op.add_column(
        "tenants",
        sa.Column("retrieval_profile_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("tenants", "retrieval_profile_version")
    op.drop_column("tenants", "retrieval_profile_json")
