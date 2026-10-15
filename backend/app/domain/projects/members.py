"""Участники проекта (plan §11.4, §10.2 п.1/п.3; D-46, D-47, D-55).

Не вызывает ``commit()``. Изменение состава берёт ``FOR NO KEY UPDATE`` на строке проекта до
любых проверок состава (§10.2 п.1), получатель — ``FOR SHARE`` (п.3). Событий нет (D-55).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import load_only

from app.core.errors import ErrorCode, Forbidden, NotFound, Unprocessable
from app.core.pagination import PageParams, paginate
from app.domain.access.policy import (
    can_add_member,
    can_manage_members,
    can_remove_self,
    can_view_project,
)
from app.domain.access.recipients import RecipientPurpose, check_recipient
from app.domain.access.roles import Actor, Role
from app.domain.projects.models import ProjectMember
from app.domain.projects.queries import load_project_facts
from app.domain.tasks.models import Task
from app.domain.users.directory import UserRef, load_recipient
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ProjectMemberRow:
    user: UserRef
    role: Role | None
    is_blocked: bool
    is_owner: bool


async def list_members(
    db: AsyncSession, actor: Actor, project_id: UUID, params: PageParams
) -> tuple[list[ProjectMemberRow], bool]:
    facts = await load_project_facts(db, actor, project_id)
    if not can_view_project(actor, facts):
        raise Forbidden()
    stmt = (
        select(AppUser)
        .options(load_only(AppUser.id, AppUser.login, AppUser.is_blocked))
        .join(ProjectMember, ProjectMember.user_id == AppUser.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(AppUser.login, AppUser.id)
    )
    users, has_next = await paginate(db, stmt, params)
    if not users:
        return [], has_next
    role_rows = await db.execute(
        select(WorkspaceMember.user_id, WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == actor.workspace_id,
            WorkspaceMember.user_id.in_([u.id for u in users]),
        )
    )
    roles = {row.user_id: None if row.role is None else Role(row.role) for row in role_rows}
    return [
        ProjectMemberRow(
            user=UserRef(id=u.id, login=u.login),
            role=roles.get(u.id),
            is_blocked=u.is_blocked,
            is_owner=u.id == facts.owner_id,
        )
        for u in users
    ], has_next


async def add_member(db: AsyncSession, actor: Actor, project_id: UUID, user_id: UUID) -> None:
    facts = await load_project_facts(db, actor, project_id, lock="update")
    if not can_add_member(actor, facts, user_id):
        raise Forbidden()
    recipient = await load_recipient(db, actor.workspace_id, user_id, lock=True)
    check_recipient(recipient, RecipientPurpose.PROJECT_MEMBER, project_member_ids=None)
    # уже участник — без изменений (D-46); проект заблокирован, ON CONFLICT — страховка
    await db.execute(
        pg_insert(ProjectMember)
        .values(
            project_id=project_id,
            user_id=user_id,
            workspace_id=actor.workspace_id,
            created_by=actor.user_id,
        )
        .on_conflict_do_nothing(index_elements=["project_id", "user_id"])
    )


async def remove_member(db: AsyncSession, actor: Actor, project_id: UUID, user_id: UUID) -> None:
    facts = await load_project_facts(db, actor, project_id, lock="update")
    # видимость проекта раньше «цель не участник»: иначе 404 раскрывает состав (D-45, ревью T71)
    if not can_view_project(actor, facts):
        raise Forbidden()
    is_member = (
        user_id == facts.owner_id
        or (
            await db.execute(
                select(ProjectMember.user_id).where(
                    ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
                )
            )
        ).first()
        is not None
    )
    if not is_member:
        raise NotFound()
    if not (
        can_manage_members(actor, facts)
        or (user_id == actor.user_id and can_remove_self(actor, facts))
    ):
        raise Forbidden()
    if user_id == facts.owner_id:
        raise Unprocessable(
            "Владельца нельзя исключить: сначала передайте владение проектом",
            code=ErrorCode.owner_cannot_be_removed,
        )
    # исполнитель снимается со всех задач проекта, включая подзадачи и удалённые (Q-7)
    await db.execute(
        update(Task)
        .where(Task.project_id == project_id, Task.assignee_id == user_id)
        .values(assignee_id=None)
    )
    await db.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )
