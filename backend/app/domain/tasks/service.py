"""Сервис задач: создание задачи и подзадачи (plan §11.4, §11.5, §4.5, §10.2; D-46, D-52, D-55).

Не вызывает ``commit()``: транзакцию запроса фиксирует ``get_db``. Порядок проверок: проект
или родитель (404) -> ``FOR SHARE`` проекта (§10.2 п.2) -> права (403) -> входные данные (422) ->
глубина (422, подзадача) -> получатель (422, ``FOR SHARE``, п.3) -> колонка (п.4) -> вставка.
Событий ленты нет (D-55). Название и описание хранятся как введены (D-52).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import select

from app.core.errors import ErrorCode, Forbidden, Unprocessable
from app.domain.access.policy import ProjectFacts, can_create_subtask, can_create_task
from app.domain.access.recipients import RecipientPurpose, check_recipient
from app.domain.access.roles import Actor, Role
from app.domain.projects.models import ProjectMember
from app.domain.projects.queries import load_project_facts
from app.domain.tasks.context import load_task_context
from app.domain.tasks.models import Task, TaskPriority, TaskStatus
from app.domain.tasks.positions import append_position, lock_columns
from app.domain.users.directory import load_recipient

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

TITLE_MAX: Final = 255
DESCRIPTION_MAX: Final = 10_000


class Unset(Enum):
    """Тип сентинела «поле не передано» (отличается от явного ``None``)."""

    UNSET = 0


UNSET: Final = Unset.UNSET


@dataclass(frozen=True)
class TaskCreateData:
    """``assignee``: ``UNSET`` — не передан, ``None`` — явно без исполнителя."""

    title: str
    description: str = ""
    assignee: UUID | None | Unset = UNSET
    due_date: date | None = None
    priority: str | TaskPriority = TaskPriority.BASE.value


def _invalid(message: str) -> Unprocessable:
    return Unprocessable(message, code=ErrorCode.validation_error)


def _validate(data: TaskCreateData) -> TaskPriority:
    """Проверка входных данных; возвращает приоритет. Строки не нормализуются (D-52)."""
    title, description = data.title, data.description
    if not isinstance(title, str) or not title.strip() or len(title) > TITLE_MAX:
        raise _invalid("Название задачи: от 1 до 255 символов, не только пробелы")
    if not isinstance(description, str) or len(description) > DESCRIPTION_MAX:
        raise _invalid("Описание задачи: не более 10000 символов")
    if "\x00" in title or "\x00" in description:
        raise _invalid("Текст не может содержать нулевой символ")
    due = data.due_date
    if due is not None and (not isinstance(due, date) or isinstance(due, datetime)):
        raise _invalid("Срок задачи: дата без времени")
    try:
        return TaskPriority(data.priority)
    except ValueError:
        raise _invalid("Приоритет: base или high") from None


def _effective_assignee(actor: Actor, data: TaskCreateData) -> UUID | None:
    """Не передан: «Пользователь» — сам, БА и СМ — без исполнителя (AC-109)."""
    if data.assignee is UNSET:
        return actor.user_id if actor.role == Role.USER else None
    assert not isinstance(data.assignee, Unset)
    return data.assignee


async def _check_assignee(
    db: AsyncSession, actor: Actor, project: ProjectFacts, assignee_id: UUID | None
) -> None:
    """Получатель ``TASK_ASSIGNEE`` под ``FOR SHARE`` (§10.2 п.3); владелец — всегда участник."""
    if assignee_id is None:
        return
    recipient = await load_recipient(db, actor.workspace_id, assignee_id, lock=True)
    is_member = (
        assignee_id == project.owner_id
        or (
            await db.execute(
                select(ProjectMember.user_id).where(
                    ProjectMember.project_id == project.project_id,
                    ProjectMember.user_id == assignee_id,
                )
            )
        ).first()
        is not None
    )
    check_recipient(
        recipient,
        RecipientPurpose.TASK_ASSIGNEE,
        project_member_ids=frozenset({assignee_id}) if is_member else frozenset(),
    )


async def create_task(
    db: AsyncSession, actor: Actor, project_id: UUID, data: TaskCreateData
) -> UUID:
    """Новая задача в конце колонки «К выполнению» (AC-24, AC-49, AC-61)."""
    project = await load_project_facts(db, actor, project_id, lock="share")
    assignee_id = _effective_assignee(actor, data)
    if not can_create_task(actor, project, assignee_id):
        raise Forbidden()
    priority = _validate(data)
    await _check_assignee(db, actor, project, assignee_id)
    await lock_columns(db, project_id, TaskStatus.TODO)
    task = Task(
        workspace_id=actor.workspace_id,
        project_id=project_id,
        title=data.title,
        description=data.description,
        status=TaskStatus.TODO.value,
        priority=priority.value,
        due_date=data.due_date,
        assignee_id=assignee_id,
        position=await append_position(db, project_id, TaskStatus.TODO),
        created_by=actor.user_id,
    )
    db.add(task)
    await db.flush()
    return task.id


async def create_subtask(
    db: AsyncSession, actor: Actor, parent_id: UUID, data: TaskCreateData
) -> UUID:
    """Подзадача: без позиции, статус ``todo``, проект родителя; глубина — один уровень."""
    ctx = await load_task_context(db, actor, parent_id, lock_project="share")
    assignee_id = _effective_assignee(actor, data)
    if not can_create_subtask(actor, ctx.project, ctx.task, assignee_id):
        raise Forbidden()
    priority = _validate(data)
    if ctx.task.parent_id is not None:
        raise Unprocessable(
            "Подзадачу нельзя вложить в подзадачу", code=ErrorCode.subtask_depth_exceeded
        )
    await _check_assignee(db, actor, ctx.project, assignee_id)
    task = Task(
        workspace_id=actor.workspace_id,
        project_id=ctx.project.project_id,
        parent_id=parent_id,
        title=data.title,
        description=data.description,
        status=TaskStatus.TODO.value,
        priority=priority.value,
        due_date=data.due_date,
        assignee_id=assignee_id,
        position=None,
        created_by=actor.user_id,
    )
    db.add(task)
    await db.flush()
    return task.id
