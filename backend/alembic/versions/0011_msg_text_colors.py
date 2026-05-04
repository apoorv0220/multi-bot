"""widget user/bot message text colors for contrast

Revision ID: 0011_msg_text_colors
Revises: 0010_widget_site_colors
Create Date: 2026-05-04
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_msg_text_colors"
down_revision = "0010_widget_site_colors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("widget_user_message_text_color", sa.String(length=20), nullable=True))
    op.add_column("tenants", sa.Column("widget_bot_message_text_color", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "widget_bot_message_text_color")
    op.drop_column("tenants", "widget_user_message_text_color")
