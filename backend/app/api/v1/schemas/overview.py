"""Схемы «Сводки» (spec 008 FR-2…FR-9; plan §4)."""

from __future__ import annotations

from datetime import date
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.v1.schemas.common import ProjectRef, UserRef
from app.api.v1.schemas.tasks import DueDate
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


class _DueRules(BaseModel):
    """Общие фильтры списка и выгрузки.

    Пресет ``due`` и диапазон ``due_from``/``due_to`` взаимоисключающие (spec 024 FR-2, Q-1);
    ``due_from > due_to`` — ошибка (FR-2). Оба нарушения — 422 ``validation_error``.
    """

    project_id: UUID | None = None
    status: TaskStatus | None = None
    priority: list[TaskPriority] = Field(default_factory=list)
    due: DuePreset | None = None
    due_from: DueDate | None = None
    due_to: DueDate | None = None
    needs_review: bool = False

    @model_validator(mode="after")
    def _range_rules(self) -> Self:
        has_range = self.due_from is not None or self.due_to is not None
        if has_range and self.due is not None:
            raise ValueError("срок-пресет нельзя задать вместе с диапазоном дат")
        if self.due_from is not None and self.due_to is not None and self.due_from > self.due_to:
            raise ValueError("дата «с» не может быть позже даты «по»")
        return self


class OverviewTaskQuery(_DueRules, PageParams):
    """``?project_id&status&priority=…&due&due_from&due_to&needs_review&page&page_size``."""


class OverviewCsvQuery(_DueRules):
    """Те же фильтры без страниц (spec 025 FR-1): выгрузка берёт всю выборку."""


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
