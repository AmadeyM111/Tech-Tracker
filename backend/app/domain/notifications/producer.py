"""Создание уведомлений по действиям (spec 012 FR-1, FR-3, FR-8; plan PN-1, PN-2).

Вызывается сервисами задач и комментариев в той же транзакции, что и действие (NFR-2). Получатель:
не автор действия (FR-3), активный участник проекта задачи с ролью; один человек в нескольких ролях
получает одно уведомление (FR-8). Повторы гасит ``ON CONFLICT DO NOTHING`` по уникальному ключу.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.domain.notifications.mentions import parse_mentions
from app.domain.notifications.models import CommentMention, Notification, NotificationKind
from app.domain.projects.models import Project, ProjectMember
from app.domain.tasks.models import TaskStatus
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

# ТА уведомлений не получает (FR-7): только роли с бизнес-доступом
BUSINESS_ROLES = ("user", "business_admin")

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.access.roles import Actor


def _member_filter(project_id: UUID) -> ColumnElement[bool]:
    return or_(
        exists().where(Project.id == project_id, Project.owner_id == AppUser.id),
        exists().where(ProjectMember.project_id == project_id, ProjectMember.user_id == AppUser.id),
    )


async def eligible(
    db: AsyncSession, workspace_id: UUID, project_id: UUID, user_ids: Iterable[UUID]
) -> set[UUID]:
    """Из ``user_ids`` — активные пользователи пространства с ролью, участники проекта."""
    wanted = set(user_ids)
    if not wanted:
        return set()
    rows = await db.execute(
        select(AppUser.id)
        .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
        .where(
            AppUser.id.in_(wanted),
            AppUser.is_blocked.is_(False),
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role.in_(BUSINESS_ROLES),
            _member_filter(project_id),
        )
    )
    return {r[0] for r in rows}


async def notify(
    db: AsyncSession,
    actor: Actor | None,
    *,
    recipients: Iterable[UUID | None],
    kind: NotificationKind,
    task_id: UUID,
    project_id: UUID,
    comment_id: UUID | None = None,
    dedup_key: str | None = None,
) -> int:
    """Вставляет уведомления; возвращает число новых строк (повторы не считаются)."""
    actor_id = None if actor is None else actor.user_id
    workspace_id = (
        actor.workspace_id
        if actor is not None
        else (
            await db.execute(select(Project.workspace_id).where(Project.id == project_id))
        ).scalar_one()
    )
    targets = {r for r in recipients if r is not None and r != actor_id}
    targets = await eligible(db, workspace_id, project_id, targets)
    if not targets:
        return 0
    key = dedup_key or uuid4().hex
    stmt = (
        insert(Notification)
        .values(
            [
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "recipient_id": user_id,
                    "kind": kind.value,
                    "task_id": task_id,
                    "project_id": project_id,
                    "actor_id": actor_id,
                    "comment_id": comment_id,
                    "dedup_key": key,
                }
                for user_id in sorted(targets)
            ]
        )
        .on_conflict_do_nothing(constraint="uq_notification_dedup")
        .returning(Notification.id)
    )
    return len((await db.execute(stmt)).all())


async def on_assigned(
    db: AsyncSession, actor: Actor, *, task_id: UUID, project_id: UUID, assignee_id: UUID | None
) -> None:
    """«Назначили исполнителем» — новому исполнителю (создание задачи/подзадачи, смена)."""
    await notify(
        db,
        actor,
        recipients=[assignee_id],
        kind=NotificationKind.ASSIGNED,
        task_id=task_id,
        project_id=project_id,
    )


async def on_status_changed(
    db: AsyncSession,
    actor: Actor,
    *,
    task_id: UUID,
    project_id: UUID,
    owner_id: UUID,
    created_by: UUID,
    assignee_id: UUID | None,
    old: str,
    new: str,
) -> None:
    """В «На проверке» — автору и владельцу; возврат из проверки — исполнителю (FR-3)."""
    if old == new:
        return
    if new == TaskStatus.REVIEW:
        await notify(
            db,
            actor,
            recipients=[created_by, owner_id],
            kind=NotificationKind.REVIEW_REQUESTED,
            task_id=task_id,
            project_id=project_id,
        )
    elif old == TaskStatus.REVIEW and new in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
        await notify(
            db,
            actor,
            recipients=[assignee_id],
            kind=NotificationKind.REVIEW_RETURNED,
            task_id=task_id,
            project_id=project_id,
        )


async def _mentioned_ids(db: AsyncSession, actor: Actor, project_id: UUID, body: str) -> set[UUID]:
    logins = parse_mentions(body)
    if not logins:
        return set()
    rows = await db.execute(select(AppUser.id).where(AppUser.login.in_(sorted(logins))))
    candidates = {r[0] for r in rows} - {actor.user_id}
    return await eligible(db, actor.workspace_id, project_id, candidates)


async def _record_mentions(
    db: AsyncSession, actor: Actor, comment_id: UUID, user_ids: set[UUID]
) -> set[UUID]:
    """Добавляет новые ``comment_mention``; возвращает тех, кого раньше не упоминали."""
    if not user_ids:
        return set()
    stmt = (
        insert(CommentMention)
        .values(
            [
                {"comment_id": comment_id, "user_id": u, "workspace_id": actor.workspace_id}
                for u in sorted(user_ids)
            ]
        )
        .on_conflict_do_nothing()
        .returning(CommentMention.user_id)
    )
    return {r[0] for r in (await db.execute(stmt)).all()}


async def on_comment(
    db: AsyncSession,
    actor: Actor,
    *,
    comment_id: UUID,
    body: str,
    task_id: UUID,
    project_id: UUID,
    created_by: UUID,
    assignee_id: UUID | None,
    is_new: bool,
) -> None:
    """Упомянутым — «упомянули»; при создании автору и исполнителю — «новый комментарий».

    Правка уведомляет только новых упомянутых (FR-1). Упомянутый получает одно уведомление.
    """
    mentioned = await _mentioned_ids(db, actor, project_id, body)
    fresh = await _record_mentions(db, actor, comment_id, mentioned)
    key = comment_id.hex
    await notify(
        db,
        actor,
        recipients=fresh,
        kind=NotificationKind.MENTIONED,
        task_id=task_id,
        project_id=project_id,
        comment_id=comment_id,
        dedup_key=key,
    )
    if is_new:
        await notify(
            db,
            actor,
            recipients=[r for r in (created_by, assignee_id) if r not in mentioned],
            kind=NotificationKind.COMMENTED,
            task_id=task_id,
            project_id=project_id,
            comment_id=comment_id,
            dedup_key=key,
        )
