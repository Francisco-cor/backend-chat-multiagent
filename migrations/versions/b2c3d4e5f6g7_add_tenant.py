"""add tenant orgs/memberships + org_id columns

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_id", "organizations", ["id"], unique=False)
    op.create_index("ix_organizations_owner_id", "organizations", ["owner_id"], unique=False)

    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="member", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("invite_token", sa.String(length=64), nullable=True),
        sa.Column("invited_email", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memberships_id", "memberships", ["id"], unique=False)
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"], unique=False)
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"], unique=False)
    op.create_index("ix_memberships_invite_token", "memberships", ["invite_token"], unique=False)
    op.create_index("ix_membership_invite", "memberships", ["invite_token"], unique=False)
    op.create_index("ix_membership_org_user", "memberships", ["org_id", "user_id"], unique=True)

    # org_id to conversations/documents/audit_logs
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True))
        batch_op.create_index("ix_conversations_org_id", ["org_id"], unique=False)
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True))
        batch_op.create_index("ix_documents_org_id", ["org_id"], unique=False)
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True))
        batch_op.create_index("ix_audit_logs_org_id", ["org_id"], unique=False)

    # RLS comment (PG): for demo we add indexes, real RLS would be:
    # CREATE POLICY org_isolation ON conversations USING (org_id = current_setting('app.current_org')::int OR org_id IS NULL);


def downgrade() -> None:
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        batch_op.drop_index("ix_audit_logs_org_id")
        batch_op.drop_column("org_id")
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_index("ix_documents_org_id")
        batch_op.drop_column("org_id")
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.drop_index("ix_conversations_org_id")
        batch_op.drop_column("org_id")

    op.drop_index("ix_membership_org_user", table_name="memberships")
    op.drop_index("ix_membership_invite", table_name="memberships")
    op.drop_index("ix_memberships_invite_token", table_name="memberships")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_org_id", table_name="memberships")
    op.drop_index("ix_memberships_id", table_name="memberships")
    op.drop_table("memberships")

    op.drop_index("ix_organizations_owner_id", table_name="organizations")
    op.drop_index("ix_organizations_id", table_name="organizations")
    op.drop_table("organizations")
