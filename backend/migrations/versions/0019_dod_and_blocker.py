"""DoD, блокер, evidence и task.mode (спеки 033+036).

Revision ID: 0019
Revises: 0021
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fk(
    columns: list[str],
    target: str,
    name: str,
    *,
    ondelete: str | None = "RESTRICT",
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
    op.add_column(
        "task",
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("task", sa.Column("blocked_reason", sa.Text(), nullable=True))
    op.add_column("task", sa.Column("blocked_by", sa.Uuid(), nullable=True))
    op.add_column("task", sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "task",
        sa.Column("human_close_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_foreign_key(
        op.f("fk_task_blocked_by_app_user"),
        "task",
        "app_user",
        ["blocked_by"],
        ["id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="IMMEDIATE",
    )
    op.create_check_constraint(
        "blocked_reason_length",
        "task",
        "blocked_reason IS NULL OR char_length(blocked_reason) BETWEEN 1 AND 500",
    )
    op.create_check_constraint(
        "blocked_fields",
        "task",
        "(blocked = false AND blocked_reason IS NULL AND blocked_by IS NULL"
        " AND blocked_at IS NULL) OR (blocked = true AND blocked_reason IS NOT NULL"
        " AND blocked_by IS NOT NULL AND blocked_at IS NOT NULL)",
    )
    op.add_column(
        "task",
        sa.Column("mode", sa.Text(), nullable=False, server_default="routine"),
    )
    op.create_check_constraint(
        "task_mode_valid",
        "task",
        "mode IN ('routine', 'research')",
    )
    op.alter_column("task", "blocked", server_default=None)
    op.alter_column("task", "human_close_only", server_default=None)
    op.alter_column("task", "mode", server_default=None)

    op.create_table(
        "task_dod_criterion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False),
        sa.Column("checked_by", sa.Uuid(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="checklist"),
        sa.Column("evidence_ref", sa.Text(), nullable=True),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 500",
            name=op.f("ck_task_dod_criterion_body_length"),
        ),
        sa.CheckConstraint(
            "(checked = false AND checked_by IS NULL AND checked_at IS NULL) OR "
            "(checked = true AND checked_by IS NOT NULL AND checked_at IS NOT NULL)",
            name=op.f("ck_task_dod_criterion_checked_fields"),
        ),
        sa.CheckConstraint(
            "kind IN ('checklist', 'evidence')",
            name=op.f("ck_task_dod_criterion_kind_valid"),
        ),
        sa.CheckConstraint(
            "evidence_ref IS NULL OR char_length(evidence_ref) BETWEEN 1 AND 500",
            name=op.f("ck_task_dod_criterion_evidence_ref_length"),
        ),
        sa.CheckConstraint(
            "evidence_note IS NULL OR char_length(evidence_note) BETWEEN 1 AND 500",
            name=op.f("ck_task_dod_criterion_evidence_note_length"),
        ),
        _fk(
            ["workspace_id"],
            "workspace.id",
            "fk_task_dod_criterion_workspace_id_workspace",
            ondelete=None,
        ),
        _fk(
            ["task_id"],
            "task.id",
            "fk_task_dod_criterion_task_id_task",
            ondelete="CASCADE",
        ),
        _fk(["checked_by"], "app_user.id", "fk_task_dod_criterion_checked_by_app_user"),
        _fk(["created_by"], "app_user.id", "fk_task_dod_criterion_created_by_app_user"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_dod_criterion")),
    )
    op.create_index(
        op.f("ix_task_dod_criterion_workspace_id"), "task_dod_criterion", ["workspace_id"]
    )
    op.create_index(
        "ix_task_dod_criterion_task_id_position",
        "task_dod_criterion",
        ["task_id", "position"],
    )
    op.alter_column("task_dod_criterion", "kind", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_task_dod_criterion_task_id_position", table_name="task_dod_criterion")
    op.drop_index(op.f("ix_task_dod_criterion_workspace_id"), table_name="task_dod_criterion")
    op.drop_table("task_dod_criterion")
    op.drop_constraint(op.f("ck_task_task_mode_valid"), "task", type_="check")
    op.drop_constraint(op.f("ck_task_blocked_fields"), "task", type_="check")
    op.drop_constraint(op.f("ck_task_blocked_reason_length"), "task", type_="check")
    op.drop_constraint(op.f("fk_task_blocked_by_app_user"), "task", type_="foreignkey")
    op.drop_column("task", "mode")
    op.drop_column("task", "human_close_only")
    op.drop_column("task", "blocked_at")
    op.drop_column("task", "blocked_by")
    op.drop_column("task", "blocked_reason")
    op.drop_column("task", "blocked")
