"""tenant branding and cors

Revision ID: 0006_tenant_branding_and_cors
Revises: 0005_tenant_security_and_quota
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_tenant_branding_and_cors"
down_revision = "0005_tenant_security_and_quota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("brand_name", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("widget_header_title", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("widget_welcome_message", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("privacy_policy_url", sa.String(length=1024), nullable=True))
    op.add_column("tenants", sa.Column("avatar_url", sa.String(length=1024), nullable=True))
    op.add_column("tenants", sa.Column("cors_allowed_origins", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "cors_allowed_origins")
    op.drop_column("tenants", "avatar_url")
    op.drop_column("tenants", "privacy_policy_url")
    op.drop_column("tenants", "widget_welcome_message")
    op.drop_column("tenants", "widget_header_title")
    op.drop_column("tenants", "brand_name")
