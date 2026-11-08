"""Журнал запусков резервного копирования: ``backup_run`` (spec 009 FR-4, plan PB-5).

Аддитивно; литералы вместо импорта кода приложения. Глобальная таблица без ``workspace_id``.
``down_revision`` — ``0010`` (фича 019 влита в main первой, решение 2026-11-08).
Downgrade удаляет всё созданное.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("schema_revision", sa.Text(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('ok','failed')", name=op.f("ck_backup_run_status_valid")),
        sa.CheckConstraint(
            "finished_at >= started_at", name=op.f("ck_backup_run_finished_after_started")
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0", name=op.f("ck_backup_run_size_non_negative")
        ),
        sa.CheckConstraint(
            "(status = 'ok') = (error_code IS NULL)",
            name=op.f("ck_backup_run_error_code_iff_failed"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_run")),
    )
    op.create_index(
        "ix_backup_run_finished_at", "backup_run", [sa.text("finished_at DESC")], unique=False
    )
    op.create_index(
        "ix_backup_run_ok_finished_at",
        "backup_run",
        [sa.text("finished_at DESC")],
        unique=False,
        postgresql_where=sa.text("status = 'ok'"),
    )


def downgrade() -> None:
    op.drop_index("ix_backup_run_ok_finished_at", table_name="backup_run")
    op.drop_index("ix_backup_run_finished_at", table_name="backup_run")
    op.drop_table("backup_run")
