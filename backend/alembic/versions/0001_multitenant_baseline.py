"""multitenant baseline

Revision ID: 0001_multitenant_baseline
Revises:
Create Date: 2026-04-21
"""
import os
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_multitenant_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    user_role = postgresql.ENUM("superadmin", "admin", name="userrole", create_type=False)
    sender_type = postgresql.ENUM("user", "assistant", "system", name="sendertype", create_type=False)
    feedback_vote = postgresql.ENUM("up", "down", name="feedbackvote", create_type=False)
    reindex_scope = postgresql.ENUM("tenant", "all", name="reindexscope", create_type=False)

    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)
    sender_type.create(bind, checkfirst=True)
    feedback_vote.create(bind, checkfirst=True)
    reindex_scope.create(bind, checkfirst=True)

    op.create_table(
        "tenants",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("source_db_url", sa.Text(), nullable=True),
        sa.Column("source_db_type", sa.String(50), nullable=True),
        sa.Column("source_table_prefix", sa.String(50), nullable=True),
        sa.Column("source_url_table", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "user_tenants",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("membership_role", sa.String(50), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default="New Chat"),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_sessions_tenant_last_message", "chat_sessions", ["tenant_id", "last_message_at"])
    op.create_index("ix_chat_sessions_user_last_message", "chat_sessions", ["created_by_user_id", "last_message_at"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("session_id", sa.UUID(), sa.ForeignKey("chat_sessions.id"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("sender_type", sender_type, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("token_usage_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"])
    op.create_index("ix_chat_messages_tenant_created", "chat_messages", ["tenant_id", "created_at"])
    op.create_table(
        "message_feedback",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("message_id", sa.UUID(), sa.ForeignKey("chat_messages.id"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("vote", feedback_vote, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_feedback_user"),
    )
    op.create_table(
        "reindex_jobs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("triggered_by_user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scope", reindex_scope, nullable=False, server_default="tenant"),
        sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_reindex_jobs_tenant_created", "reindex_jobs", ["tenant_id", "created_at"])
    op.create_index("ix_reindex_jobs_status_created", "reindex_jobs", ["status", "created_at"])
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("actor_user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_role", sa.String(50), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_logs_tenant_created", "audit_logs", ["tenant_id", "created_at"])
    op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_user_id", "created_at"])
    op.create_index("ix_audit_logs_action_created", "audit_logs", ["action", "created_at"])

    tenant_id = uuid.uuid4()
    password_hash = os.getenv(
        "BOOTSTRAP_SUPERADMIN_PASSWORD_HASH",
        "",
    )
    email = os.getenv("BOOTSTRAP_SUPERADMIN_EMAIL", "superadmin@example.com")

    op.execute(
        sa.text(
            "INSERT INTO tenants (id,name,slug,status,source_db_url,source_db_type,source_table_prefix,source_url_table,created_at,updated_at) "
            "VALUES (:id,:name,:slug,:status,:source_db_url,:source_db_type,:source_table_prefix,:source_url_table,NOW(),NOW())"
        ).bindparams(
            id=tenant_id,
            name="Default Tenant",
            slug="default-tenant",
            status="active",
            source_db_url=None,
            source_db_type=None,
            source_table_prefix=None,
            source_url_table=None,
        )
    )
    if password_hash and email:
        user_id = uuid.uuid4()
        op.execute(
            sa.text(
                "INSERT INTO users (id,email,password_hash,role,is_active,created_at,updated_at) "
                "VALUES (:id,:email,:password_hash,:role,true,NOW(),NOW())"
            ).bindparams(id=user_id, email=email, password_hash=password_hash, role="superadmin")
        )
        op.execute(
            sa.text(
                "INSERT INTO user_tenants (id,user_id,tenant_id,membership_role,created_at) "
                "VALUES (:id,:user_id,:tenant_id,:membership_role,NOW())"
            ).bindparams(id=uuid.uuid4(), user_id=user_id, tenant_id=tenant_id, membership_role="owner")
        )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_action_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_reindex_jobs_status_created", table_name="reindex_jobs")
    op.drop_index("ix_reindex_jobs_tenant_created", table_name="reindex_jobs")
    op.drop_table("reindex_jobs")
    op.drop_table("message_feedback")
    op.drop_index("ix_chat_messages_tenant_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_user_last_message", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_tenant_last_message", table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_table("user_tenants")
    op.drop_table("users")
    op.drop_table("tenants")

    bind = op.get_bind()
    sa.Enum(name="reindexscope").drop(bind, checkfirst=True)
    sa.Enum(name="feedbackvote").drop(bind, checkfirst=True)
    sa.Enum(name="sendertype").drop(bind, checkfirst=True)
    sa.Enum(name="userrole").drop(bind, checkfirst=True)
