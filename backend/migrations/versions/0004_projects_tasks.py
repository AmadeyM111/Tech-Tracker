"""MVP: project, project_member, task, comment и CHECK типа объекта в domain_event (plan §11.6).

Нет: label, task_label, mention, attachment, pg_trgm, GIN-индексов, project.status (D-58).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTITY_CHECK = "ck_domain_event_entity_type_valid"
_ENTITY_TYPES = "'user','project','task','comment','attachment','stage','deal'"


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


def _ts(name: str, *, nullable: bool = False) -> sa.Column[sa.DateTime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
        sa.Column("deleted_batch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 255", name=op.f("ck_project_name_length")
        ),
        sa.CheckConstraint(
            "char_length(description) <= 10000", name=op.f("ck_project_description_length")
        ),
        _fk(["workspace_id"], "workspace.id", "fk_project_workspace_id_workspace", ondelete=None),
        _fk(["owner_id"], "app_user.id", "fk_project_owner_id_app_user"),
        _fk(["created_by"], "app_user.id", "fk_project_created_by_app_user"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project")),
    )
    op.create_index(op.f("ix_project_workspace_id"), "project", ["workspace_id"])

    op.create_table(
        "project_member",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _fk(
            ["project_id"],
            "project.id",
            "fk_project_member_project_id_project",
            ondelete="CASCADE",
        ),
        _fk(["user_id"], "app_user.id", "fk_project_member_user_id_app_user"),
        _fk(
            ["workspace_id"],
            "workspace.id",
            "fk_project_member_workspace_id_workspace",
            ondelete=None,
        ),
        _fk(["created_by"], "app_user.id", "fk_project_member_created_by_app_user"),
        sa.PrimaryKeyConstraint("project_id", "user_id", name=op.f("pk_project_member")),
    )
    op.create_index(op.f("ix_project_member_user_id"), "project_member", ["user_id"])
    op.create_index(op.f("ix_project_member_workspace_id"), "project_member", ["workspace_id"])

    op.create_table(
        "task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
        sa.Column("deleted_batch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 255", name=op.f("ck_task_title_length")
        ),
        sa.CheckConstraint(
            "char_length(description) <= 10000", name=op.f("ck_task_description_length")
        ),
        sa.CheckConstraint(
            "status IN ('todo','in_progress','review','done')", name=op.f("ck_task_status_valid")
        ),
        sa.CheckConstraint("priority IN ('base','high')", name=op.f("ck_task_priority_valid")),
        sa.CheckConstraint(
            "(parent_id IS NULL) = (position IS NOT NULL)", name=op.f("ck_task_position_top_level")
        ),
        _fk(["workspace_id"], "workspace.id", "fk_task_workspace_id_workspace", ondelete=None),
        _fk(["project_id"], "project.id", "fk_task_project_id_project", ondelete="CASCADE"),
        _fk(["parent_id"], "task.id", "fk_task_parent_id_task", ondelete="CASCADE"),
        _fk(["assignee_id"], "app_user.id", "fk_task_assignee_id_app_user"),
        _fk(["created_by"], "app_user.id", "fk_task_created_by_app_user"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task")),
    )
    op.create_index(op.f("ix_task_workspace_id"), "task", ["workspace_id"])
    op.create_index(op.f("ix_task_parent_id"), "task", ["parent_id"])
    op.create_index(
        "ix_task_project_id_status_position_created_at",
        "task",
        ["project_id", "status", "position", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL AND parent_id IS NULL"),
    )
    op.create_index(
        "ix_task_workspace_id_assignee_id_due_date",
        "task",
        ["workspace_id", "assignee_id", "due_date"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_task_project_id_created_at",
        "task",
        ["project_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "comment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        _ts("edited_at", nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
        sa.Column("deleted_batch_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 10000", name=op.f("ck_comment_body_length")
        ),
        _fk(["workspace_id"], "workspace.id", "fk_comment_workspace_id_workspace", ondelete=None),
        _fk(["task_id"], "task.id", "fk_comment_task_id_task", ondelete="CASCADE"),
        _fk(["created_by"], "app_user.id", "fk_comment_created_by_app_user"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comment")),
    )
    op.create_index(op.f("ix_comment_workspace_id"), "comment", ["workspace_id"])
    op.create_index("ix_comment_task_id_created_at", "comment", ["task_id", "created_at"])

    # D-41, D-58: тип объекта журнала — одно из 7 значений EntityType. Строки не меняются.
    op.create_check_constraint(
        op.f(_ENTITY_CHECK), "domain_event", f"entity_type IN ({_ENTITY_TYPES})"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_ENTITY_CHECK), "domain_event", type_="check")
    op.drop_table("comment")
    op.drop_table("task")
    op.drop_table("project_member")
    op.drop_table("project")
