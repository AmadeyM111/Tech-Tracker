"""Внешние сообщения MCP inbox (спека 034, ADR-0030).

Новая таблица ``external_message``. Цепочка: 0018 → 0021 → 0019 → 0020.
``down_revision=0019``. Downgrade удаляет таблицу.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_message",
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("comment_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("source IN ('telegram')", name=op.f("ck_external_message_source_valid")),
        sa.CheckConstraint(
            "char_length(external_id) BETWEEN 1 AND 256",
            name=op.f("ck_external_message_external_id_length"),
        ),
        sa.CheckConstraint(
            "url IS NULL OR char_length(url) BETWEEN 1 AND 2048",
            name=op.f("ck_external_message_url_length"),
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            ["comment.id"],
            name=op.f("fk_external_message_comment_id_comment"),
            ondelete="CASCADE",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["task.id"],
            name=op.f("fk_external_message_task_id_task"),
            ondelete="CASCADE",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name=op.f("fk_external_message_workspace_id_workspace"),
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_message")),
        sa.UniqueConstraint(
            "workspace_id",
            "source",
            "external_id",
            name="uq_external_message_source_external_id",
        ),
    )
    op.create_index(
        op.f("ix_external_message_workspace_id"),
        "external_message",
        ["workspace_id"],
        unique=False,
    )
    op.create_index("ix_external_message_task_id", "external_message", ["task_id"], unique=False)
    op.create_index(
        "ix_external_message_comment_id", "external_message", ["comment_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_external_message_comment_id", table_name="external_message")
    op.drop_index("ix_external_message_task_id", table_name="external_message")
    op.drop_index(op.f("ix_external_message_workspace_id"), table_name="external_message")
    op.drop_table("external_message")
