"""add user_id to conversation_history

Revision ID: b2c3d4e5f6a7
Revises: 9949a26b4f37
Create Date: 2026-04-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "9949a26b4f37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_history",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index(
        "ix_conv_history_user_id",
        "conversation_history",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_conv_history_user_session",
        "conversation_history",
        ["user_id", "session_id", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_conv_history_user_session", table_name="conversation_history")
    op.drop_index("ix_conv_history_user_id", table_name="conversation_history")
    op.drop_column("conversation_history", "user_id")
