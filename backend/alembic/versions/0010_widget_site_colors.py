"""tenant widget website url, source type, and message bubble colors

Revision ID: 0010_widget_site_colors
Revises: 0009_tenant_primary_color
Create Date: 2026-05-04

widget_source_type: Qdrant payload filter keyword for primary vector search (e.g. mrnwebdesigns_ie).

Note: revision id must fit alembic_version.version_num (varchar(32)).
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_widget_site_colors"
down_revision = "0009_tenant_primary_color"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("widget_website_url", sa.String(length=1024), nullable=True))
    op.add_column("tenants", sa.Column("widget_source_type", sa.String(length=64), nullable=True))
    op.add_column("tenants", sa.Column("widget_user_message_color", sa.String(length=20), nullable=True))
    op.add_column("tenants", sa.Column("widget_bot_message_color", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "widget_bot_message_color")
    op.drop_column("tenants", "widget_user_message_color")
    op.drop_column("tenants", "widget_source_type")
    op.drop_column("tenants", "widget_website_url")
