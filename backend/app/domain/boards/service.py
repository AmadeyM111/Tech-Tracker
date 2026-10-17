"""Выборка доски проекта (plan §11.4 ``Board``; D-61, FR-18a, FR-28, FR-28a, FR-47).

Только чтение. Порядок проверок: проект (404) -> участник (403). Четыре колонки всегда, в
порядке FR-18a; карточки — неудалённые задачи верхнего уровня в порядке ``COLUMN_ORDER``;
без пагинации (исключение из FR-47). Карточки с ``subtask_count``/``progress`` читаются одним
агрегирующим запросом, поэтому число запросов не зависит от числа карточек. Перенос карточки —
``app.domain.tasks.service.move``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from app.core.errors import Forbidden, NotFound
from app.domain.access.policy import can_read_project_content
from app.domain.projects.models import Project
from app.domain.projects.queries import load_project_facts
from app.domain.tasks.models import Task, TaskPriority, TaskStatus
from app.domain.tasks.positions import COLUMN_ORDER
from app.domain.tasks.progress import progress
from app.domain.tasks.queries import TaskProjectRef
from app.domain.users.directory import UserRef, user_refs

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.access.roles import Actor


@dataclass(frozen=True)
class BoardCard:
    id: UUID
    title: str
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    assignee: UserRef | None
    position: int
    subtask_count: int
    progress: int | None


@dataclass(frozen=True)
class BoardColumn:
    status: TaskStatus
    tasks: list[BoardCard]


@dataclass(frozen=True)
class BoardView:
    project: TaskProjectRef
    columns: list[BoardColumn]


async def get_board(db: AsyncSession, actor: Actor, project_id: UUID) -> BoardView:
    """Доска проекта: 4 колонки (пустые тоже) с карточками задач верхнего уровня."""
    facts = await load_project_facts(db, actor, project_id)
    if not can_read_project_content(actor, facts):
        raise Forbidden()
    name = (
        await db.execute(
            select(Project.name).where(
                Project.id == project_id,
                Project.workspace_id == actor.workspace_id,
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if name is None:
        raise NotFound("Проект не найден")

    # Подзадачи — один агрегат на всю доску; считаются только неудалённые.
    subs = (
        select(
            Task.parent_id.label("parent_id"),
            func.count().label("total"),
            func.count().filter(Task.status == TaskStatus.DONE.value).label("done"),
        )
        .where(
            Task.project_id == project_id,
            Task.workspace_id == actor.workspace_id,
            Task.parent_id.is_not(None),
            Task.deleted_at.is_(None),
        )
        .group_by(Task.parent_id)
        .subquery("subs")
    )
    # ``description`` не выбирается: карточке она не нужна.
    rows = (
        await db.execute(
            select(
                Task.id,
                Task.title,
                Task.status,
                Task.priority,
                Task.due_date,
                Task.assignee_id,
                Task.position,
                func.coalesce(subs.c.total, 0).label("total"),
                func.coalesce(subs.c.done, 0).label("done"),
            )
            .outerjoin(subs, subs.c.parent_id == Task.id)
            .where(
                Task.project_id == project_id,
                Task.workspace_id == actor.workspace_id,
                Task.parent_id.is_(None),
                Task.deleted_at.is_(None),
            )
            .order_by(*COLUMN_ORDER)
        )
    ).all()

    refs = await user_refs(
        db, actor.workspace_id, list({r.assignee_id for r in rows if r.assignee_id is not None})
    )
    columns = {status: BoardColumn(status=status, tasks=[]) for status in TaskStatus}
    for r in rows:
        if r.assignee_id is not None and r.assignee_id not in refs:
            raise RuntimeError(f"UserRef missing for user {r.assignee_id}")  # инвариант
        status = TaskStatus(r.status)
        columns[status].tasks.append(
            BoardCard(
                id=r.id,
                title=r.title,
                status=status,
                priority=TaskPriority(r.priority),
                due_date=r.due_date,
                assignee=None if r.assignee_id is None else refs[r.assignee_id],
                position=int(r.position),
                subtask_count=int(r.total),
                progress=progress(int(r.done), int(r.total)),
            )
        )
    return BoardView(
        project=TaskProjectRef(id=project_id, name=name), columns=list(columns.values())
    )
