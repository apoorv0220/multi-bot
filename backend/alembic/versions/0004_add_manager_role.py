"""add manager role

Revision ID: 0004_add_manager_role
Revises: 0003_usage_tracking
Create Date: 2026-04-28
"""

from alembic import op


revision = "0004_add_manager_role"
down_revision = "0003_usage_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'manager'")


def downgrade() -> None:
    # Postgres enum value removal is intentionally omitted for safety.
    pass
