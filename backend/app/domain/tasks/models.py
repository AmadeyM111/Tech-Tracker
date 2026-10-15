"""Модель ``task`` (plan §11.6, D-2, D-22, D-25, D-26, D-52, D-56, FR-18, FR-21).

Подзадача — строка с ``parent_id``; позиция (``position``) есть только у задач верхнего
уровня: ``CHECK ((parent_id IS NULL) = (position IS NOT NULL))``. Статус и приоритет — ``text``
с CHECK (D-3), значения — в ``TaskStatus`` и ``TaskPriority``.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, SoftDeleteMixin, TimestampMixin, UUIDPkMixin, WorkspaceMixin


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"


class TaskPriority(StrEnum):
    BASE = "base"
    HIGH = "high"


class Task(UUIDPkMixin, TimestampMixin, WorkspaceMixin, SoftDeleteMixin, Base):
    __tablename__ = "task"
    __table_args__ = (
        CheckConstraint("char_length(title) BETWEEN 1 AND 255", name="title_length"),
        CheckConstraint("char_length(description) <= 10000", name="description_length"),
        CheckConstraint("status IN ('todo','in_progress','review','done')", name="status_valid"),
        CheckConstraint("priority IN ('base','high')", name="priority_valid"),
        CheckConstraint("(parent_id IS NULL) = (position IS NOT NULL)", name="position_top_level"),
    )

    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("project.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    assignee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        nullable=True,
    )
    position: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )


# Доска проекта: колонка статуса, порядок по позиции (только задачи верхнего уровня).
Index(
    "ix_task_project_id_status_position_created_at",
    Task.project_id,
    Task.status,
    Task.position,
    Task.created_at,
    postgresql_where=text("deleted_at IS NULL AND parent_id IS NULL"),
)
# Личный список «мои задачи».
Index(
    "ix_task_workspace_id_assignee_id_due_date",
    Task.workspace_id,
    Task.assignee_id,
    Task.due_date,
    postgresql_where=text("deleted_at IS NULL"),
)
# Список задач проекта: новые сверху.
Index(
    "ix_task_project_id_created_at",
    Task.project_id,
    Task.created_at.desc(),
    postgresql_where=text("deleted_at IS NULL"),
)
