"""initial

Revision ID: 9949a26b4f37
Revises:
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9949a26b4f37"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_id", "users", ["id"], unique=False)

    op.create_table(
        "conversation_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_history_id", "conversation_history", ["id"], unique=False)
    op.create_index("ix_conversation_history_session_id", "conversation_history", ["session_id"], unique=False)
    op.create_index("ix_session_id_timestamp", "conversation_history", ["session_id", "timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_session_id_timestamp", table_name="conversation_history")
    op.drop_index("ix_conversation_history_session_id", table_name="conversation_history")
    op.drop_index("ix_conversation_history_id", table_name="conversation_history")
    op.drop_table("conversation_history")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
