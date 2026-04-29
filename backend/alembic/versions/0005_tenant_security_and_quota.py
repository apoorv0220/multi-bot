"""tenant security and quota

Revision ID: 0005_tenant_security_and_quota
Revises: 0004_add_manager_role
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_tenant_security_and_quota"
down_revision = "0004_add_manager_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("monthly_message_limit", sa.Integer(), nullable=False, server_default="15000"))
    op.add_column(
        "tenants",
        sa.Column(
            "quota_reached_message",
            sa.Text(),
            nullable=False,
            server_default="Monthly message limit reached. Please try again next month.",
        ),
    )

    op.create_table(
        "tenant_blocked_ips",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "ip_address", name="uq_tenant_blocked_ip"),
    )
    op.create_index("ix_tenant_blocked_ips_tenant", "tenant_blocked_ips", ["tenant_id"])

    op.create_table(
        "tenant_blocked_countries",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "country_code", name="uq_tenant_blocked_country"),
    )
    op.create_index("ix_tenant_blocked_countries_tenant", "tenant_blocked_countries", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_blocked_countries_tenant", table_name="tenant_blocked_countries")
    op.drop_table("tenant_blocked_countries")
    op.drop_index("ix_tenant_blocked_ips_tenant", table_name="tenant_blocked_ips")
    op.drop_table("tenant_blocked_ips")
    op.drop_column("tenants", "quota_reached_message")
    op.drop_column("tenants", "monthly_message_limit")
