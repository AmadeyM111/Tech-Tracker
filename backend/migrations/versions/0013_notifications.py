"""Упоминания и уведомления: ``comment_mention``, ``notification`` (spec 012; plan PN-2…PN-4).

Аддитивно; литералы вместо импорта кода приложения. Downgrade удаляет обе таблицы.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comment_mention",
        sa.Column("comment_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            ["comment.id"],
            name=op.f("fk_comment_mention_comment_id_comment"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_comment_mention_user_id_app_user"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name=op.f("fk_comment_mention_workspace_id_workspace"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("comment_id", "user_id", name=op.f("pk_comment_mention")),
    )
    op.create_index(
        op.f("ix_comment_mention_workspace_id"), "comment_mention", ["workspace_id"], unique=False
    )
    op.create_table(
        "notification",
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("comment_id", sa.Uuid(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('assigned','review_requested','review_returned','mentioned','commented',"
            "'due_tomorrow','overdue')",
            name=op.f("ck_notification_kind_valid"),
        ),
        sa.CheckConstraint(
            "char_length(dedup_key) BETWEEN 1 AND 64", name=op.f("ck_notification_dedup_key_length")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["app_user.id"],
            name=op.f("fk_notification_actor_id_app_user"),
            ondelete="SET NULL",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            ["comment.id"],
            name=op.f("fk_notification_comment_id_comment"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_notification_project_id_project"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["app_user.id"],
            name=op.f("fk_notification_recipient_id_app_user"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["task.id"],
            name=op.f("fk_notification_task_id_task"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name=op.f("fk_notification_workspace_id_workspace"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification")),
        sa.UniqueConstraint(
            "recipient_id", "kind", "task_id", "dedup_key", name="uq_notification_dedup"
        ),
    )
    op.create_index("ix_notification_created_at", "notification", ["created_at"], unique=False)
    op.create_index(
        "ix_notification_recipient_id_read_at_created_at",
        "notification",
        ["recipient_id", "read_at", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_workspace_id"), "notification", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_workspace_id"), table_name="notification")
    op.drop_index("ix_notification_recipient_id_read_at_created_at", table_name="notification")
    op.drop_index("ix_notification_created_at", table_name="notification")
    op.drop_table("notification")
    op.drop_index(op.f("ix_comment_mention_workspace_id"), table_name="comment_mention")
    op.drop_table("comment_mention")
