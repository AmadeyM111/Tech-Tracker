"""Слои знаний: ``knowledge_record`` (спека 037, ADR-0033, CD-08/CD-09).

Аддитивно: новая таблица. ``task`` не меняется. 0019 и 0020 не занимаем.

Revision ID: 0021
Revises: 0018
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_record",
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("confirmed_with", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "scope IN ('space','project')",
            name=op.f("ck_knowledge_record_scope_valid"),
        ),
        sa.CheckConstraint(
            "kind IN ('decision','reason','agreement')",
            name=op.f("ck_knowledge_record_kind_valid"),
        ),
        sa.CheckConstraint(
            "(scope = 'space' AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL)",
            name=op.f("ck_knowledge_record_scope_project"),
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 255",
            name=op.f("ck_knowledge_record_title_length"),
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 10000",
            name=op.f("ck_knowledge_record_body_length"),
        ),
        sa.CheckConstraint(
            "(kind = 'agreement' AND confirmed_with IS NOT NULL "
            "AND char_length(confirmed_with) BETWEEN 1 AND 255) OR "
            "(kind <> 'agreement' AND confirmed_with IS NULL)",
            name=op.f("ck_knowledge_record_confirmed_with"),
        ),
        sa.CheckConstraint(
            "client_name IS NULL OR char_length(client_name) BETWEEN 1 AND 64",
            name=op.f("ck_knowledge_record_client_name_length"),
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["app_user.id"],
            name=op.f("fk_knowledge_record_confirmed_by_app_user"),
            ondelete="RESTRICT",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_knowledge_record_created_by_app_user"),
            ondelete="RESTRICT",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_knowledge_record_project_id_project"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name=op.f("fk_knowledge_record_workspace_id_workspace"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_record")),
    )
    op.create_index(
        "ix_knowledge_record_workspace_id_scope_created_at",
        "knowledge_record",
        ["workspace_id", "scope", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_record_workspace_id"),
        "knowledge_record",
        ["workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_record_workspace_id"), table_name="knowledge_record")
    op.drop_index(
        "ix_knowledge_record_workspace_id_scope_created_at",
        table_name="knowledge_record",
    )
    op.drop_table("knowledge_record")
