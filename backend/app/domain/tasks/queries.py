"""Выборки задач: карточка и списки (plan §11.4; D-46, D-56, D-62, FR-26, FR-27, FR-47).

Только чтение: без записи и блокировок. Несуществующая, мягко удалённая, чужого пространства
задача и задача удалённого проекта неразличимы — ``NotFound``; порядок проверок: 404 -> 403.
Число запросов не зависит от числа подзадач и размера страницы (D-62).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import defer

from app.core.errors import Forbidden, NotFound
from app.core.pagination import PageParams, paginate
from app.domain.access.policy import (
    TaskFacts,
    can_change_assignee,
    can_change_task_status,
    can_create_subtask,
    can_delete_task,
    can_edit_task_fully,
    can_read_project_content,
)
from app.domain.access.roles import Actor, Capability
from app.domain.projects.models import Project, ProjectMember
from app.domain.projects.queries import load_project_facts
from app.domain.tasks.context import load_task_context
from app.domain.tasks.models import Task, TaskPriority, TaskStatus
from app.domain.tasks.progress import progress
from app.domain.users.directory import UserRef, user_refs

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class TaskProjectRef:
    id: UUID
    name: str


@dataclass(frozen=True)
class TaskPermissions:
    edit: bool
    change_status: bool
    change_assignee: bool
    delete: bool
    create_subtask: bool


@dataclass(frozen=True)
class TaskBrief:
    id: UUID
    title: str
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    assignee: UserRef | None


@dataclass(frozen=True)
class TaskView:
    id: UUID
    project: TaskProjectRef
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


@dataclass(frozen=True)
class TaskListItem:
    id: UUID
    project: TaskProjectRef
    parent_id: UUID | None
    title: str
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    assignee: UserRef | None
    created_at: datetime


def _author(refs: dict[UUID, UserRef], user_id: UUID) -> UserRef:
    """``UserRef`` пользователя; отсутствие в пространстве — нарушение инварианта."""
    ref = refs.get(user_id)
    if ref is None:
        raise RuntimeError(f"UserRef missing for user {user_id}")
    return ref


def _ref(refs: dict[UUID, UserRef], user_id: UUID | None) -> UserRef | None:
    return None if user_id is None else _author(refs, user_id)


async def get_task(db: AsyncSession, actor: Actor, task_id: UUID) -> TaskView:
    """Карточка задачи с неудалёнными подзадачами, прогрессом и правами актора."""
    ctx = await load_task_context(db, actor, task_id)
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    row = (
        await db.execute(
            select(Task, Project.name.label("project_name"))
            .join(Project, Project.id == Task.project_id)
            .where(
                Task.id == task_id,
                Task.workspace_id == actor.workspace_id,
                Task.deleted_at.is_(None),
                Project.workspace_id == actor.workspace_id,
            )
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        raise NotFound("Задача не найдена")
    task: Task = row.Task
    # Права и поля карточки — из одного снимка строки задачи.
    facts = TaskFacts(
        created_by=task.created_by, assignee_id=task.assignee_id, parent_id=task.parent_id
    )
    subs = (
        await db.execute(
            select(Task.id, Task.title, Task.status, Task.priority, Task.due_date, Task.assignee_id)
            .where(
                Task.parent_id == task_id,
                Task.workspace_id == actor.workspace_id,
                Task.deleted_at.is_(None),
            )
            .order_by(Task.created_at, Task.id)
        )
    ).all()
    user_ids = {task.created_by, *(s.assignee_id for s in subs)}
    if task.assignee_id is not None:
        user_ids.add(task.assignee_id)
    refs = await user_refs(db, actor.workspace_id, [u for u in user_ids if u is not None])
    done = sum(1 for s in subs if s.status == TaskStatus.DONE)
    return TaskView(
        id=task.id,
        project=TaskProjectRef(id=task.project_id, name=row.project_name),
        parent_id=task.parent_id,
        title=task.title,
        description=task.description,
        status=TaskStatus(task.status),
        priority=TaskPriority(task.priority),
        due_date=task.due_date,
        assignee=_ref(refs, task.assignee_id),
        author=_author(refs, task.created_by),
        position=task.position,
        subtasks=[
            TaskBrief(
                id=s.id,
                title=s.title,
                status=TaskStatus(s.status),
                priority=TaskPriority(s.priority),
                due_date=s.due_date,
                assignee=_ref(refs, s.assignee_id),
            )
            for s in subs
        ],
        progress=progress(done, len(subs)),
        created_at=task.created_at,
        updated_at=task.updated_at,
        permissions=TaskPermissions(
            edit=can_edit_task_fully(actor, ctx.project, facts),
            change_status=can_change_task_status(actor, ctx.project, facts),
            change_assignee=can_change_assignee(actor, ctx.project, facts),
            delete=can_delete_task(actor, ctx.project, facts),
            create_subtask=facts.parent_id is None
            and can_create_subtask(actor, ctx.project, facts, actor.user_id),
        ),
    )


async def _list_items(db: AsyncSession, actor: Actor, tasks: Sequence[Task]) -> list[TaskListItem]:
    """Элементы списка: имена проектов и исполнители — по одному запросу на страницу."""
    if not tasks:
        return []
    names = {
        project_id: name
        for project_id, name in await db.execute(
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
        TaskListItem(
            id=t.id,
            project=TaskProjectRef(id=t.project_id, name=names[t.project_id]),
            parent_id=t.parent_id,
            title=t.title,
            status=TaskStatus(t.status),
            priority=TaskPriority(t.priority),
            due_date=t.due_date,
            assignee=_ref(refs, t.assignee_id),
            created_at=t.created_at,
        )
        for t in tasks
    ]


async def list_project_tasks(
    db: AsyncSession,
    actor: Actor,
    project_id: UUID,
    params: PageParams,
    *,
    assignee_id: UUID | None,
    status: TaskStatus | None,
) -> tuple[list[TaskListItem], bool]:
    """Задачи и подзадачи проекта (новые сверху); фильтры исполнителя и статуса — через «И»."""
    facts = await load_project_facts(db, actor, project_id)
    if not can_read_project_content(actor, facts):
        raise Forbidden()
    conditions: list[Any] = [
        Task.project_id == project_id,
        Task.workspace_id == actor.workspace_id,
        Task.deleted_at.is_(None),
    ]
    if assignee_id is not None:
        conditions.append(Task.assignee_id == assignee_id)
    if status is not None:
        conditions.append(Task.status == str(status))
    stmt = (
        select(Task)
        .options(defer(Task.description))
        .where(*conditions)
        .order_by(Task.created_at.desc(), Task.id.desc())
        .execution_options(populate_existing=True)
    )
    tasks, has_next = await paginate(db, stmt, params)
    return await _list_items(db, actor, tasks), has_next


async def list_my_tasks(
    db: AsyncSession, actor: Actor, params: PageParams
) -> tuple[list[TaskListItem], bool]:
    """Задачи и подзадачи, где актор — исполнитель и участник неудалённого проекта."""
    if not actor.can(Capability.BUSINESS_ACCESS):
        raise Forbidden()
    is_member = or_(
        Project.owner_id == actor.user_id,
        exists().where(
            ProjectMember.project_id == Project.id, ProjectMember.user_id == actor.user_id
        ),
    )
    stmt = (
        select(Task)
        .options(defer(Task.description))
        .join(Project, Project.id == Task.project_id)
        .where(
            Task.workspace_id == actor.workspace_id,
            Task.assignee_id == actor.user_id,
            Task.deleted_at.is_(None),
            Project.deleted_at.is_(None),
            is_member,
        )
        .order_by(Task.due_date.asc().nulls_last(), Task.id)
        .execution_options(populate_existing=True)
    )
    tasks, has_next = await paginate(db, stmt, params)
    return await _list_items(db, actor, tasks), has_next
