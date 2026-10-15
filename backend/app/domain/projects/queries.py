"""Выборки проектов (plan §11.4, §10.2, §10.4; D-45, D-56).

Только чтение (``lock`` берёт блокировку строки проекта, §10.2 п.1/п.2). Чужой, мягко удалённый
и несуществующий проект неразличимы — ``NotFound`` (FR-13). Порядок проверок: 404 -> 403.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, or_, select

from app.core.errors import Forbidden, NotFound
from app.core.pagination import PageParams, paginate
from app.domain.access.policy import (
    ProjectFacts,
    can_create_task,
    can_manage_members,
    can_manage_project,
    can_remove_self,
    can_view_project,
)
from app.domain.access.roles import Actor, Capability, Role
from app.domain.projects.models import Project, ProjectMember
from app.domain.tasks.models import Task
from app.domain.users.directory import UserRef, user_refs
from app.domain.users.models import AppUser

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ProjectPermissions:
    manage: bool
    manage_members: bool
    create_task: bool
    remove_self: bool


@dataclass(frozen=True)
class ProjectView:
    id: UUID
    name: str
    description: str
    owner: UserRef
    task_count: int
    is_member: bool
    created_at: datetime
    updated_at: datetime
    permissions: ProjectPermissions


@dataclass(frozen=True)
class ProjectListRow:
    id: UUID
    name: str
    owner: UserRef
    task_count: int


def _is_member_of(user_id: UUID) -> ColumnElement[bool]:
    return exists().where(ProjectMember.project_id == Project.id, ProjectMember.user_id == user_id)


async def load_project_facts(
    db: AsyncSession,
    actor: Actor,
    project_id: UUID,
    *,
    lock: Literal["update", "share"] | None = None,
) -> ProjectFacts:
    """Факты проекта для policy; ``NotFound`` для несуществующего, удалённого и чужого.

    Владелец всегда участник (``actor_is_member``), даже без строки членства (ревью T70).
    ``lock="update"`` — ``FOR NO KEY UPDATE`` (§10.2 п.1), ``"share"`` — ``FOR SHARE`` (п.2).
    С блокировкой факты читаются отдельным запросом после неё: ожидание блокировки не должно
    оставлять устаревший снимок состава участников.
    """
    visible = (
        Project.id == project_id,
        Project.workspace_id == actor.workspace_id,
        Project.deleted_at.is_(None),
    )
    if lock is not None:
        locking = select(Project.id).where(*visible)
        if lock == "update":
            locking = locking.with_for_update(key_share=True, of=Project)
        else:
            locking = locking.with_for_update(read=True, of=Project)
        if (await db.execute(locking)).first() is None:
            raise NotFound()
    row = (
        await db.execute(
            select(
                Project.id,
                Project.owner_id,
                or_(Project.owner_id == actor.user_id, _is_member_of(actor.user_id)).label(
                    "is_member"
                ),
            ).where(*visible)
        )
    ).one_or_none()
    if row is None:
        raise NotFound()
    return ProjectFacts(project_id=row.id, owner_id=row.owner_id, actor_is_member=row.is_member)


def _task_count_subquery() -> ColumnElement[int]:
    return (
        select(func.count())
        .where(
            Task.project_id == Project.id,
            Task.parent_id.is_(None),
            Task.deleted_at.is_(None),
        )
        .correlate(Project)
        .scalar_subquery()
    )


async def project_view(db: AsyncSession, actor: Actor, facts: ProjectFacts) -> ProjectView:
    """Карточка проекта для актора; права ``can_view_project`` проверяет вызывающий."""
    row = (
        await db.execute(
            select(
                Project.name,
                Project.description,
                Project.created_at,
                Project.updated_at,
                AppUser.login.label("owner_login"),
                _task_count_subquery().label("task_count"),
            )
            .join(AppUser, AppUser.id == Project.owner_id)
            .where(Project.id == facts.project_id)
        )
    ).one()
    return ProjectView(
        id=facts.project_id,
        name=row.name,
        description=row.description,
        owner=UserRef(id=facts.owner_id, login=row.owner_login),
        task_count=row.task_count,
        is_member=facts.actor_is_member,
        created_at=row.created_at,
        updated_at=row.updated_at,
        permissions=ProjectPermissions(
            manage=can_manage_project(actor, facts),
            manage_members=can_manage_members(actor, facts),
            create_task=can_create_task(actor, facts, actor.user_id),
            remove_self=can_remove_self(actor, facts),
        ),
    )


async def get_project(db: AsyncSession, actor: Actor, project_id: UUID) -> ProjectView:
    facts = await load_project_facts(db, actor, project_id)
    if not can_view_project(actor, facts):
        raise Forbidden()
    return await project_view(db, actor, facts)


async def list_projects(
    db: AsyncSession, actor: Actor, params: PageParams
) -> tuple[list[ProjectListRow], bool]:
    """БА и СМ — все неудалённые проекты пространства, «Пользователь» — где участник."""
    if not actor.can(Capability.BUSINESS_ACCESS):
        raise Forbidden()
    stmt = (
        select(Project)
        .where(Project.workspace_id == actor.workspace_id, Project.deleted_at.is_(None))
        .order_by(func.lower(Project.name), Project.id)
        .execution_options(populate_existing=True)
    )
    if actor.role not in (Role.BUSINESS_ADMIN, Role.MIXED):
        stmt = stmt.where(_is_member_of(actor.user_id))
    projects, has_next = await paginate(db, stmt, params)
    if not projects:
        return [], has_next
    ids = [p.id for p in projects]
    count_rows = await db.execute(
        select(Task.project_id, func.count())
        .where(Task.project_id.in_(ids), Task.parent_id.is_(None), Task.deleted_at.is_(None))
        .group_by(Task.project_id)
    )
    counts = {project_id: count for project_id, count in count_rows}
    owners = await user_refs(db, actor.workspace_id, [p.owner_id for p in projects])
    return [
        ProjectListRow(
            id=p.id, name=p.name, owner=owners[p.owner_id], task_count=counts.get(p.id, 0)
        )
        for p in projects
    ], has_next
