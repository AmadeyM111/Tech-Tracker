"""Модель идентичности: workspace, app_user, workspace_member, user_session.

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(
    columns: list[str],
    target: str,
    name: str,
    *,
    ondelete: str = "RESTRICT",
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        columns,
        [target],
        name=op.f(name),
        ondelete=ondelete,
        deferrable=True,
        initially="IMMEDIATE",
    )


def upgrade() -> None:
    op.create_table(
        "workspace",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace")),
    )

    op.create_table(
        "app_user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("login_locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "login ~ '^[a-z0-9][a-z0-9._-]{2,63}$'", name=op.f("ck_app_user_login_format")
        ),
        _fk(["created_by"], "app_user.id", "fk_app_user_created_by_app_user"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_user")),
        sa.UniqueConstraint("login", name=op.f("uq_app_user_login")),
    )

    op.create_table(
        "workspace_member",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "role IN ('tech_admin','business_admin','mixed','user')",
            name=op.f("ck_workspace_member_role_valid"),
        ),
        _fk(["workspace_id"], "workspace.id", "fk_workspace_member_workspace_id_workspace"),
        _fk(["user_id"], "app_user.id", "fk_workspace_member_user_id_app_user"),
        _fk(["created_by"], "app_user.id", "fk_workspace_member_created_by_app_user"),
        sa.PrimaryKeyConstraint("workspace_id", "user_id", name=op.f("pk_workspace_member")),
    )
    op.create_index(
        "ix_workspace_member_workspace_id_role",
        "workspace_member",
        ["workspace_id", "role"],
    )

    op.create_table(
        "user_session",
        sa.Column("id", sa.LargeBinary(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        _fk(["user_id"], "app_user.id", "fk_user_session_user_id_app_user", ondelete="CASCADE"),
        _fk(["workspace_id"], "workspace.id", "fk_user_session_workspace_id_workspace"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_session")),
    )
    op.create_index(op.f("ix_user_session_user_id"), "user_session", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_session_user_id"), table_name="user_session")
    op.drop_table("user_session")
    op.drop_index("ix_workspace_member_workspace_id_role", table_name="workspace_member")
    op.drop_table("workspace_member")
    op.drop_table("app_user")
    op.drop_table("workspace")
