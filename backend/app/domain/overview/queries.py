"""Выборки «Сводки» (spec 008 FR-2…FR-9, FR-11; plan PS-1, PS-2, PS-4…PS-9).

Задачи сводки — неудалённые задачи и подзадачи неудалённых проектов пространства, где актор —
владелец или участник (как ``list_my_tasks``). Счётчики — один запрос с ``COUNT FILTER``; список —
страница (``paginate``) и отдельный ``COUNT`` под теми же фильтрами (``total``). Только чтение.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import defer

from app.core.errors import Forbidden, NotFound
from app.core.pagination import PageParams, paginate
from app.domain.access.policy import can_read_project_content
from app.domain.access.roles import Actor, Capability
from app.domain.overview.due import DuePreset, due_condition, is_hot
from app.domain.projects.models import Project, ProjectMember
from app.domain.projects.queries import load_project_facts
from app.domain.tasks.models import Task, TaskPriority, TaskStatus
from app.domain.tasks.queries import TaskProjectRef
from app.domain.users.directory import UserRef, user_refs

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class OverviewCounts:
    total: int
    todo: int
    in_progress: int
    review: int
    done: int
    needs_review: int


@dataclass(frozen=True)
class OverviewFilter:
    project_id: UUID | None = None
    status: TaskStatus | None = None
    priorities: frozenset[TaskPriority] = frozenset()
    due: DuePreset | None = None
    needs_review: bool = False


@dataclass(frozen=True)
class OverviewItem:
    id: UUID
    title: str
    project: TaskProjectRef
    parent_id: UUID | None
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    assignee: UserRef | None
    hot: bool


def _visible(actor: Actor) -> list[Any]:
    """Условия «задачи сводки» (FR-2, NFR-2); запрос обязан JOIN-ить ``Project``."""
    is_member = or_(
        Project.owner_id == actor.user_id,
        exists().where(
            ProjectMember.project_id == Project.id, ProjectMember.user_id == actor.user_id
        ),
    )
    return [
        Task.workspace_id == actor.workspace_id,
        Project.workspace_id == actor.workspace_id,
        Task.deleted_at.is_(None),
        Project.deleted_at.is_(None),
        is_member,
    ]


def _needs_review(actor: Actor) -> Any:
    """«Нужно проверить»: в ``review``, я автор задачи или владелец проекта (FR-3, Q-8)."""
    return and_(
        Task.status == TaskStatus.REVIEW,
        or_(Task.created_by == actor.user_id, Project.owner_id == actor.user_id),
    )


def _require_business(actor: Actor) -> None:
    if not actor.can(Capability.BUSINESS_ACCESS):
        raise Forbidden()


async def overview_counts(db: AsyncSession, actor: Actor) -> OverviewCounts:
    """Плитки (FR-2, FR-3): не зависят от фильтров списка (Q-2)."""
    _require_business(actor)

    def by_status(status: TaskStatus) -> Any:
        return func.count().filter(Task.status == status)

    row = (
        await db.execute(
            select(
                func.count(),
                by_status(TaskStatus.TODO),
                by_status(TaskStatus.IN_PROGRESS),
                by_status(TaskStatus.REVIEW),
                by_status(TaskStatus.DONE),
                func.count().filter(_needs_review(actor)),
            )
            .select_from(Task)
            .join(Project, Project.id == Task.project_id)
            .where(*_visible(actor))
        )
    ).one()
    total, todo, in_progress, review, done, needs_review = (int(v) for v in row)
    return OverviewCounts(total, todo, in_progress, review, done, needs_review)


async def _filter_conditions(
    db: AsyncSession, actor: Actor, f: OverviewFilter, today: date
) -> list[Any]:
    conditions = _visible(actor)
    if f.project_id is not None:
        facts = await load_project_facts(db, actor, f.project_id)  # нет/удалён/чужой — 404
        if not can_read_project_content(actor, facts):
            raise NotFound()  # не мой проект неотличим от несуществующего (FR-11)
        conditions.append(Task.project_id == f.project_id)
    if f.status is not None:
        conditions.append(Task.status == f.status)
    if f.priorities:
        conditions.append(Task.priority.in_(sorted(f.priorities)))
    if f.due is not None:
        conditions.append(due_condition(f.due, today))
    if f.needs_review:
        conditions.append(_needs_review(actor))
    return conditions


async def overview_tasks(
    db: AsyncSession, actor: Actor, f: OverviewFilter, params: PageParams, *, today: date
) -> tuple[list[OverviewItem], bool, int]:
    """Страница списка (FR-5…FR-9): срок по возрастанию, без срока в конце, затем ``id``."""
    _require_business(actor)
    conditions = await _filter_conditions(db, actor, f, today)
    stmt = (
        select(Task)
        .options(defer(Task.description))
        .join(Project, Project.id == Task.project_id)
        .where(*conditions)
        .order_by(Task.due_date.asc().nulls_last(), Task.id)
        .execution_options(populate_existing=True)
    )
    tasks, has_next = await paginate(db, stmt, params)
    total = (
        await db.execute(
            select(func.count())
            .select_from(Task)
            .join(Project, Project.id == Task.project_id)
            .where(*conditions)
        )
    ).scalar_one()
    return await _items(db, actor, tasks, today), has_next, int(total)


async def _items(
    db: AsyncSession, actor: Actor, tasks: list[Task], today: date
) -> list[OverviewItem]:
    if not tasks:
        return []
    names = {
        pid: name
        for pid, name in await db.execute(
            select(Project.id, Project.name).where(
                Project.id.in_({t.project_id for t in tasks}),
                Project.workspace_id == actor.workspace_id,
            )
        )
    }
    refs = await user_refs(
        db, actor.workspace_id, [t.assignee_id for t in tasks if t.assignee_id is not None]
    )
    return [
        OverviewItem(
            id=t.id,
            title=t.title,
            project=TaskProjectRef(id=t.project_id, name=names[t.project_id]),
            parent_id=t.parent_id,
            status=TaskStatus(t.status),
            priority=TaskPriority(t.priority),
            due_date=t.due_date,
            assignee=None if t.assignee_id is None else refs.get(t.assignee_id),
            hot=is_hot(t.priority, t.due_date, t.status, today),
        )
        for t in tasks
    ]
