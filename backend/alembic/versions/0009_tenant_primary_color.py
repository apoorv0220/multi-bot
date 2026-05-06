"""add tenant widget primary color

Revision ID: 0009_tenant_primary_color
Revises: 0008_idle_rating
Create Date: 2026-05-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_tenant_primary_color"
down_revision = "0008_idle_rating"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("widget_primary_color", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "widget_primary_color")
