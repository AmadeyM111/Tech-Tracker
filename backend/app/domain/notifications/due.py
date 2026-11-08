"""Напоминания о сроке (spec 012 FR-4; Q-1…Q-3) и очистка старых уведомлений (FR-9, Q-4).

«Срок завтра» — ``due_date = сегодня + 1``; «срок прошёл» — ``due_date < сегодня``; сегодня — по
Europe/Moscow (ADR-0007). Один раз на задачу, вид и дату срока: ``dedup_key`` = дата срока, вставка
``ON CONFLICT DO NOTHING`` — повторный запуск ничего не дублирует. Получатель — исполнитель
незавершённой живой задачи, активный участник проекта с ролью. Подзадачи — наравне (Q-3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import String, cast, delete, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.core.clock import today_msk
from app.core.db import transaction
from app.domain.notifications.models import Notification, NotificationKind
from app.domain.projects.models import Project, ProjectMember
from app.domain.tasks.models import Task, TaskStatus
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

# ТА уведомлений не получает (FR-7): только роли с бизнес-доступом
BUSINESS_ROLES: Final = ("user", "business_admin")

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

RETENTION: Final = timedelta(days=90)
# «Срок прошёл» — только для сроков не старше 30 дней: первый запуск не засыпает старыми задачами,
# а после очистки (90 дней) напоминание не приходит повторно (ревью 012, п. 1–2; Q-2 «один раз»).
OVERDUE_WINDOW: Final = timedelta(days=30)


@dataclass(frozen=True)
class DueReport:
    due_tomorrow: int
    overdue: int


def _candidates(kind: NotificationKind, condition: Any, now: datetime) -> Any:
    member = or_(
        Project.owner_id == Task.assignee_id,
        exists().where(
            ProjectMember.project_id == Project.id, ProjectMember.user_id == Task.assignee_id
        ),
    )
    return (
        select(
            func.gen_random_uuid(),
            Task.workspace_id,
            Task.assignee_id,
            literal(kind.value),
            Task.id,
            Task.project_id,
            cast(Task.due_date, String),
            literal(now),
        )
        .join(Project, Project.id == Task.project_id)
        .join(AppUser, AppUser.id == Task.assignee_id)
        .join(
            WorkspaceMember,
            (WorkspaceMember.user_id == Task.assignee_id)
            & (WorkspaceMember.workspace_id == Task.workspace_id),
        )
        .where(
            condition,
            Task.deleted_at.is_(None),
            Task.status != TaskStatus.DONE,
            Project.deleted_at.is_(None),
            AppUser.is_blocked.is_(False),
            WorkspaceMember.role.in_(BUSINESS_ROLES),
            member,
        )
    )


async def _insert(db: AsyncSession, kind: NotificationKind, condition: Any, now: datetime) -> int:
    stmt = (
        insert(Notification)
        .from_select(
            [
                "id",
                "workspace_id",
                "recipient_id",
                "kind",
                "task_id",
                "project_id",
                "dedup_key",
                "created_at",
            ],
            _candidates(kind, condition, now),
        )
        .on_conflict_do_nothing(constraint="uq_notification_dedup")
        .returning(Notification.id)
    )
    return len((await db.execute(stmt)).all())


async def notify_due(sessionmaker: async_sessionmaker[AsyncSession], *, now: datetime) -> DueReport:
    """Создаёт напоминания на момент ``now`` (сегодня — по МСК); возвращает число новых."""
    today = today_msk(now)
    async with transaction(sessionmaker) as db:
        tomorrow = await _insert(
            db, NotificationKind.DUE_TOMORROW, Task.due_date == today + timedelta(days=1), now
        )
        overdue = await _insert(
            db,
            NotificationKind.OVERDUE,
            Task.due_date.between(today - OVERDUE_WINDOW, today - timedelta(days=1)),
            now,
        )
    return DueReport(tomorrow, overdue)


async def purge_notifications(
    sessionmaker: async_sessionmaker[AsyncSession], *, now: datetime, dry_run: bool
) -> int:
    """Удаляет уведомления старше 90 дней (FR-9); ``dry_run`` — только счёт."""
    old = Notification.created_at < now - RETENTION
    async with transaction(sessionmaker) as db:
        if dry_run:
            return int(
                (
                    await db.execute(select(func.count()).select_from(Notification).where(old))
                ).scalar_one()
            )
        return len(
            (await db.execute(delete(Notification).where(old).returning(Notification.id))).all()
        )
