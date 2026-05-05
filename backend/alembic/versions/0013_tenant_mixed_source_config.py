"""tenant mixed source configuration fields

Revision ID: 0013_tenant_mixed_source_config
Revises: 0012_tenant_quick_replies
Create Date: 2026-05-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_tenant_mixed_source_config"
down_revision = "0012_tenant_quick_replies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("source_mode", sa.String(length=20), nullable=True))
    op.add_column("tenants", sa.Column("source_static_urls_json", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("source_domain_aliases", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("source_canonical_base_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "source_canonical_base_url")
    op.drop_column("tenants", "source_domain_aliases")
    op.drop_column("tenants", "source_static_urls_json")
    op.drop_column("tenants", "source_mode")
