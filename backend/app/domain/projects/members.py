"""Участники проекта (plan §11.4, §10.2 п.1/п.3; D-46, D-47, D-55).

Не вызывает ``commit()``. Изменение состава берёт ``FOR NO KEY UPDATE`` на строке проекта до
любых проверок состава (§10.2 п.1), получатель — ``FOR SHARE`` (п.3). Событий нет (D-55).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import load_only

from app.core.clock import utcnow
from app.core.db import commit_durably
from app.core.errors import ErrorCode, Forbidden, NotFound, RateLimited, Unprocessable
from app.core.pagination import PageParams, paginate
from app.domain.access.policy import (
    can_add_member,
    can_manage_members,
    can_remove_self,
    can_view_project,
)
from app.domain.access.recipients import RecipientPurpose, check_recipient
from app.domain.access.roles import Actor, Role
from app.domain.events.catalog import EventAction
from app.domain.events.models import DomainEvent
from app.domain.events.writer import FieldChange, record_event
from app.domain.projects.models import ProjectMember
from app.domain.projects.queries import load_project_facts
from app.domain.tasks.models import Task
from app.domain.users.directory import UserRef, find_member_candidate, load_recipient, user_refs
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

MAX_MEMBERS = 100  # спека 027, Q-4: участников на проект
ADD_ATTEMPTS_PER_HOUR = 20  # спека 027, Q-7: добавлений по логину/email в час на владельца

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
        .options(load_only(AppUser.id, AppUser.login_display, AppUser.is_blocked))
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
            user=UserRef(id=u.id, login=u.login_display),
            role=roles.get(u.id),
            is_blocked=u.is_blocked,
            is_owner=u.id == facts.owner_id,
        )
        for u in users
    ], has_next


async def _resolve_candidate(
    db: AsyncSession,
    actor: Actor,
    project_id: UUID,
    *,
    login: str | None,
    email: str | None,
) -> UUID:
    """Добавление по логину или email (spec 027 FR-4, Q-1, Q-7).

    «Пользователь» ограничен ``ADD_ATTEMPTS_PER_HOUR`` попытками в час (успешные добавления и
    неудачи вместе): без этого по ответам можно перебирать адреса. Неудача пишется в журнал
    аудита (``user.member_add_failed``: автор и проект, без введённого значения) и фиксируется
    до ответа 422. Для любой причины отказа (нет, ТА, без роли, заблокирован) ответ один.
    """
    if actor.role is Role.USER:
        since = utcnow() - timedelta(hours=1)
        attempts = await db.scalar(
            select(func.count())
            .select_from(DomainEvent)
            .where(
                DomainEvent.workspace_id == actor.workspace_id,
                DomainEvent.actor_id == actor.user_id,
                DomainEvent.action.in_(
                    [EventAction.MEMBER_ADDED.value, EventAction.USER_MEMBER_ADD_FAILED.value]
                ),
                DomainEvent.occurred_at >= since,
            )
        )
        if (attempts or 0) >= ADD_ATTEMPTS_PER_HOUR:
            raise RateLimited()
    found = await find_member_candidate(db, actor.workspace_id, login=login, email=email)
    if found is None:
        await record_event(
            db,
            workspace_id=actor.workspace_id,
            actor_id=actor.user_id,
            action=EventAction.USER_MEMBER_ADD_FAILED,
            entity_id=actor.user_id,
            project_id=project_id,
        )
        await commit_durably(db)  # неудача и счётчик попыток не откатываются вместе с 422
        raise Unprocessable(
            "Пользователь с таким логином или email не зарегистрирован",
            code=ErrorCode.recipient_not_found,
        )
    return found


async def add_member(
    db: AsyncSession,
    actor: Actor,
    project_id: UUID,
    user_id: UUID | None = None,
    *,
    login: str | None = None,
    email: str | None = None,
) -> None:
    """Добавляет участника по ``user_id`` (БА) либо по точному логину или email.

    «Пользователь» (владелец своего проекта) добавляет только по логину или email (FR-4).
    Уже участник: по ``user_id`` — без изменений (D-46), по логину/email — 422
    ``member_already_added`` (макет: ошибка поля). Предел — ``MAX_MEMBERS`` участников.
    """
    facts = await load_project_facts(db, actor, project_id, lock="update")
    if not can_add_member(actor, facts, user_id or actor.user_id):
        raise Forbidden()
    by_key = user_id is None
    if by_key:
        user_id = await _resolve_candidate(db, actor, project_id, login=login, email=email)
    elif actor.role is Role.USER:
        raise Unprocessable(
            "Укажите логин или email", code=ErrorCode.validation_error
        )  # «Пользователь» не добавляет по идентификатору (027 FR-4)
    assert user_id is not None
    recipient = await load_recipient(db, actor.workspace_id, user_id, lock=True)
    check_recipient(recipient, RecipientPurpose.PROJECT_MEMBER, project_member_ids=None)
    existing = await db.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(ProjectMember.project_id == project_id)
    )
    already = (
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
    if already:
        if by_key:
            raise Unprocessable(
                "Этот пользователь уже в проекте", code=ErrorCode.member_already_added
            )
        return  # по user_id повтор — без изменений (D-46)
    if (existing or 0) >= MAX_MEMBERS:
        raise Unprocessable(code=ErrorCode.limit_reached)
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
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.MEMBER_ADDED,
        entity_id=user_id,
        project_id=project_id,
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
    unassigned_ids = (
        await db.scalars(
            update(Task)
            .where(Task.project_id == project_id, Task.assignee_id == user_id)
            .values(assignee_id=None)
            .returning(Task.id)
        )
    ).all()
    await db.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )
    await _record_removal(db, actor, project_id, user_id, unassigned_ids)


async def _record_removal(
    db: AsyncSession, actor: Actor, project_id: UUID, user_id: UUID, unassigned_ids: Sequence[UUID]
) -> None:
    """Лента: снятие исполнителя (FR-15a) и исключение участника; значения — у исполнителя."""
    if unassigned_ids:
        refs = await user_refs(db, actor.workspace_id, [user_id])
        old = refs[user_id]
        change: FieldChange = {
            "field": "assignee_id",
            "old": {"id": str(old.id), "login": old.login},
            "new": None,
        }
        for task_id in unassigned_ids:
            await record_event(
                db,
                workspace_id=actor.workspace_id,
                actor_id=actor.user_id,
                action=EventAction.TASK_UNASSIGNED_MEMBER_REMOVED,
                entity_id=task_id,
                project_id=project_id,
                changed_fields=["assignee_id"],
                changes=[change],
            )
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.MEMBER_REMOVED,
        entity_id=user_id,
        project_id=project_id,
    )
