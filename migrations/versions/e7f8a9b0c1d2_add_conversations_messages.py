"""add conversations and messages tables

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-09-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("legacy_session_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_id", "conversations", ["id"], unique=False)
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"], unique=False)
    op.create_index("ix_conversations_deleted_at", "conversations", ["deleted_at"], unique=False)
    op.create_index("ix_conversations_legacy_session_id", "conversations", ["legacy_session_id"], unique=False)
    op.create_index("ix_conversations_user_updated", "conversations", ["user_id", "updated_at"], unique=False)
    op.create_index("ix_conversations_user_session", "conversations", ["user_id", "legacy_session_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("legacy_session_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_id", "messages", ["id"], unique=False)
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"], unique=False)
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at"], unique=False)

    # Backfill: best-effort migration of existing history where user_id is not null
    # Skip rows with NULL user_id to avoid FK violation (they remain in conversation_history)
    try:
        op.execute(
            sa.text(
                """
                INSERT INTO conversations (user_id, legacy_session_id, title, model, created_at, updated_at, total_tokens, total_cost_usd)
                SELECT
                    user_id,
                    session_id,
                    'Migrated: ' || session_id,
                    NULL,
                    MIN(timestamp),
                    MAX(timestamp),
                    0,
                    0
                FROM conversation_history
                WHERE session_id IS NOT NULL AND user_id IS NOT NULL
                GROUP BY user_id, session_id
                """
            )
        )
        op.execute(
            sa.text(
                """
                INSERT INTO messages (conversation_id, role, content, tokens, created_at, legacy_session_id)
                SELECT
                    c.id,
                    ch.role,
                    ch.content,
                    NULL,
                    ch.timestamp,
                    ch.session_id
                FROM conversation_history ch
                JOIN conversations c ON c.legacy_session_id = ch.session_id AND c.user_id = ch.user_id
                WHERE ch.user_id IS NOT NULL
                """
            )
        )
    except Exception:
        # Backfill is best-effort; don't fail migration if empty or SQLite quirks
        pass


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_index("ix_messages_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_user_session", table_name="conversations")
    op.drop_index("ix_conversations_user_updated", table_name="conversations")
    op.drop_index("ix_conversations_legacy_session_id", table_name="conversations")
    op.drop_index("ix_conversations_deleted_at", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_index("ix_conversations_id", table_name="conversations")
    op.drop_table("conversations")
