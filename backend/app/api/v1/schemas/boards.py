"""Схемы API доски и переноса карточки (plan §11.4, D-61).

``Board`` — всегда 4 колонки в порядке FR-18a; все поля ответа обязательны, ``null`` — только
у ``due_date``, ``assignee`` и ``progress``. Тело переноса: ``status`` обязателен, соседи — нет.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.api.v1.schemas.common import ProjectRef, UserRef
from app.domain.tasks.models import TaskPriority, TaskStatus


class TaskMove(BaseModel):
    """``after_task_id`` — сосед сверху, ``before_task_id`` — снизу; без соседей — в конец."""

    model_config = ConfigDict(extra="forbid")

    status: TaskStatus
    before_task_id: UUID | None = None
    after_task_id: UUID | None = None


class BoardCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    assignee: UserRef | None
    position: int
    subtask_count: int
    progress: int | None


class BoardColumn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: TaskStatus
    tasks: list[BoardCard]


class Board(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project: ProjectRef
    columns: list[BoardColumn]
