"""Схемы «Сводки» (spec 008 FR-2…FR-9; plan §4)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.common import ProjectRef, UserRef
from app.core.pagination import PageParams
from app.domain.overview.due import DuePreset
from app.domain.tasks.models import TaskPriority, TaskStatus


class OverviewCountsOut(BaseModel):
    """Плитки: сумма статусов = ``total``; ``needs_review`` — подмножество ``review``."""

    model_config = ConfigDict(from_attributes=True)

    total: int
    todo: int
    in_progress: int
    review: int
    done: int
    needs_review: int


class OverviewTaskQuery(PageParams):
    """``?project_id&status&priority=…&due&needs_review&page&page_size``."""

    project_id: UUID | None = None
    status: TaskStatus | None = None
    priority: list[TaskPriority] = Field(default_factory=list)
    due: DuePreset | None = None
    needs_review: bool = False


class OverviewCsvQuery(BaseModel):
    """``?project_id&status&priority=…&due&needs_review``: фильтры списка без страниц (spec 025)."""

    project_id: UUID | None = None
    status: TaskStatus | None = None
    priority: list[TaskPriority] = Field(default_factory=list)
    due: DuePreset | None = None
    needs_review: bool = False


class OverviewTaskItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    project: ProjectRef
    parent_id: UUID | None
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    assignee: UserRef | None
    hot: bool


class OverviewTaskPage(BaseModel):
    """Страница списка; ``total`` — число задач под фильтрами (FR-9, «Показано N из M»)."""

    items: list[OverviewTaskItem]
    page: int
    page_size: int
    has_next: bool
    total: int


class OverviewProjectList(BaseModel):
    """Мои проекты для фильтра «Сводки» (без постраничности, по имени)."""

    items: list[ProjectRef]
