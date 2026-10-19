"""Схемы API задач (plan §11.4, D-51, D-52).

Входные схемы проверяют форму: длины, отсутствие NUL (PostgreSQL не принимает ``\\x00`` в
тексте), перечисления, строгий формат срока. «Название из одних пробелов» (D-52) проверяет
сервис. Все поля ответов обязательны; ``null`` — только там, где его разрешает plan §11.4.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.api.v1.schemas.common import ProjectRef, UserRef
from app.core.pagination import PageParams
from app.domain.tasks.models import TaskPriority, TaskStatus
from app.domain.tasks.service import DESCRIPTION_MAX, TITLE_MAX

_NO_NUL = r"^[^\x00]*$"
_DUE_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _strict_iso_date(value: Any) -> Any:
    """D-51: только строка ``YYYY-MM-DD``; дата-время, число и т. п. — ошибка валидации."""
    if not isinstance(value, str) or _DUE_DATE_RE.fullmatch(value) is None:
        raise ValueError("Срок: дата в формате YYYY-MM-DD")
    return value  # календарную корректность («2026-02-30») проверяет разбор ``date``


TaskTitle = Annotated[str, Field(min_length=1, max_length=TITLE_MAX, pattern=_NO_NUL)]
TaskDescription = Annotated[str, Field(max_length=DESCRIPTION_MAX, pattern=_NO_NUL)]
DueDate = Annotated[
    date,
    BeforeValidator(_strict_iso_date),
    Field(json_schema_extra={"pattern": r"^\d{4}-\d{2}-\d{2}$"}),
]


class TaskListQuery(PageParams):
    """``?assignee_id&status&page&page_size`` списка задач проекта; фильтры — через «И»."""

    assignee_id: UUID | None = None
    status: TaskStatus | None = None


class TaskCreate(BaseModel):
    """Создание задачи и подзадачи.

    ``assignee_id``: не передан — «Пользователь» назначается сам, БА — без исполнителя;
    ``null`` — явно без исполнителя (различаются по ``model_fields_set``, FR-20).
    """

    model_config = ConfigDict(extra="forbid")

    title: TaskTitle
    description: TaskDescription = ""
    assignee_id: UUID | None = None
    due_date: DueDate | None = None
    priority: TaskPriority = TaskPriority.BASE


class TaskUpdate(BaseModel):
    """Все поля необязательны; не переданное поле не меняется (``model_fields_set``).

    ``null`` допустим только у ``assignee_id`` и ``due_date`` (снимает значение). У остальных
    ``default_factory`` лишь делает поле необязательным без ``null``/``default`` в OpenAPI.
    """

    model_config = ConfigDict(extra="forbid")

    title: TaskTitle = Field(default_factory=str)
    description: TaskDescription = Field(default_factory=str)
    assignee_id: UUID | None = None
    due_date: DueDate | None = None
    priority: TaskPriority = Field(default_factory=lambda: TaskPriority.BASE)
    status: TaskStatus = Field(default_factory=lambda: TaskStatus.TODO)


class TaskPermissions(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    edit: bool
    change_status: bool
    change_assignee: bool
    delete: bool
    create_subtask: bool


class TaskBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    assignee: UserRef | None


class TaskDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project: ProjectRef
    parent_id: UUID | None
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    assignee: UserRef | None
    author: UserRef
    position: int | None
    subtasks: list[TaskBrief]
    progress: int | None
    created_at: datetime
    updated_at: datetime
    permissions: TaskPermissions


class TaskListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project: ProjectRef
    parent_id: UUID | None
    title: str
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    assignee: UserRef | None
    created_at: datetime
