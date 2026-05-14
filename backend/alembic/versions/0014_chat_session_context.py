"""add chat session context columns

Revision ID: 0014_chat_session_context
Revises: 0013_tenant_mixed_source_config
Create Date: 2026-05-14 15:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0014_chat_session_context"
down_revision = "0013_tenant_mixed_source_config"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_sessions", sa.Column("conversation_summary", sa.Text(), nullable=True))
    op.add_column("chat_sessions", sa.Column("active_filters_json", sa.JSON(), nullable=True))
    op.add_column("chat_sessions", sa.Column("user_preferences_json", sa.JSON(), nullable=True))
    op.add_column("chat_sessions", sa.Column("last_result_context_json", sa.JSON(), nullable=True))
    op.add_column("chat_sessions", sa.Column("conversation_intent", sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column("chat_sessions", "conversation_intent")
    op.drop_column("chat_sessions", "last_result_context_json")
    op.drop_column("chat_sessions", "user_preferences_json")
    op.drop_column("chat_sessions", "active_filters_json")
    op.drop_column("chat_sessions", "conversation_summary")
