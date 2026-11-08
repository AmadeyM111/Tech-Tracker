"""Вложения к задачам: ``attachment`` (spec 011 FR-5, FR-7; plan PA-3, PA-4).

Аддитивно; литералы вместо импорта кода приложения. Файлы на диске миграция не трогает.
Downgrade удаляет таблицу и индексы (файлы в ``DATA_DIR/attachments`` остаются).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachment",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_batch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('pdf','docx','xlsx','pptx','txt','csv','png','jpeg','gif','webp')",
            name=op.f("ck_attachment_kind_valid"),
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_attachment_sha256_hex")),
        sa.CheckConstraint(
            "storage_key ~ '^[0-9a-f]{32}$'", name=op.f("ck_attachment_storage_key_hex")
        ),
        sa.CheckConstraint(
            "char_length(original_name) BETWEEN 1 AND 255", name=op.f("ck_attachment_name_length")
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_attachment_size_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_attachment_created_by_app_user"),
            ondelete="RESTRICT",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_attachment_project_id_project"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["task.id"],
            name=op.f("fk_attachment_task_id_task"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name=op.f("fk_attachment_workspace_id_workspace"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachment")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_attachment_storage_key")),
    )
    op.create_index(
        "ix_attachment_deleted_at",
        "attachment",
        ["deleted_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.create_index(
        "ix_attachment_task_id_created_at",
        "attachment",
        ["task_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        op.f("ix_attachment_workspace_id"), "attachment", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_attachment_workspace_id"), table_name="attachment")
    op.drop_index(
        "ix_attachment_task_id_created_at",
        table_name="attachment",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_attachment_deleted_at",
        table_name="attachment",
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.drop_table("attachment")
