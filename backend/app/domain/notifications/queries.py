"""Список, счётчик и прочтение уведомлений (spec 012 FR-5…FR-7; plan PN-3, PN-4).

Видимость (PN-3): получатель — актор; за 30 дней; задача и проект не удалены; комментарий (если
есть) не удалён; получатель сейчас участник проекта. Убрали из проекта — уведомления скрыты, вернули
— снова видны. Чужие и скрытые уведомления отметить прочитанными нельзя (тихо игнорируются).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, update

from app.core.errors import Forbidden
from app.core.pagination import PageParams, paginate
from app.domain.access.roles import Actor, Capability
from app.domain.comments.models import Comment
from app.domain.notifications.models import Notification, NotificationKind
from app.domain.projects.models import Project, ProjectMember
from app.domain.tasks.models import Task
from app.domain.tasks.queries import TaskProjectRef
from app.domain.users.directory import UserRef, user_refs

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

WINDOW: Final = timedelta(days=30)


@dataclass(frozen=True)
class TaskRef:
    id: UUID
    title: str


@dataclass(frozen=True)
class NotificationView:
    id: UUID
    kind: NotificationKind
    task: TaskRef
    project: TaskProjectRef
    actor: UserRef | None
    created_at: datetime
    read: bool


def _require(actor: Actor) -> None:
    if not actor.can(Capability.BUSINESS_ACCESS):
        raise Forbidden()


def _visible(actor: Actor, now: datetime) -> list[Any]:
    """Условия видимости; запрос обязан JOIN-ить ``Task`` и ``Project``."""
    member = or_(
        Project.owner_id == actor.user_id,
        exists().where(
            ProjectMember.project_id == Project.id, ProjectMember.user_id == actor.user_id
        ),
    )
    live_comment = or_(
        Notification.comment_id.is_(None),
        exists().where(Comment.id == Notification.comment_id, Comment.deleted_at.is_(None)),
    )
    return [
        Notification.recipient_id == actor.user_id,
        Notification.workspace_id == actor.workspace_id,
        Notification.created_at >= now - WINDOW,
        Task.deleted_at.is_(None),
        Project.deleted_at.is_(None),
        member,
        live_comment,
    ]


def _joined(stmt: Any) -> Any:
    return stmt.join(Task, Task.id == Notification.task_id).join(
        Project, Project.id == Notification.project_id
    )


async def unread_count(db: AsyncSession, actor: Actor, *, now: datetime) -> int:
    """Число непрочитанных видимых уведомлений (значок, FR-5)."""
    _require(actor)
    stmt = _joined(select(func.count()).select_from(Notification)).where(
        *_visible(actor, now), Notification.read_at.is_(None)
    )
    return int((await db.execute(stmt)).scalar_one())


async def list_notifications(
    db: AsyncSession, actor: Actor, params: PageParams, *, now: datetime
) -> tuple[list[NotificationView], bool]:
    """Видимые уведомления за 30 дней, новые сверху."""
    _require(actor)
    stmt = (
        _joined(select(Notification))
        .where(*_visible(actor, now))
        .order_by(Notification.created_at.desc(), Notification.id.desc())
    )
    rows, has_next = await paginate(db, stmt, params)
    if not rows:
        return [], has_next
    tasks = {
        r.id: r.title
        for r in await db.execute(
            select(Task.id, Task.title).where(Task.id.in_({n.task_id for n in rows}))
        )
    }
    projects = {
        r.id: r.name
        for r in await db.execute(
            select(Project.id, Project.name).where(Project.id.in_({n.project_id for n in rows}))
        )
    }
    refs = await user_refs(
        db, actor.workspace_id, [n.actor_id for n in rows if n.actor_id is not None]
    )
    return [
        NotificationView(
            id=n.id,
            kind=NotificationKind(n.kind),
            task=TaskRef(id=n.task_id, title=tasks[n.task_id]),
            project=TaskProjectRef(id=n.project_id, name=projects[n.project_id]),
            actor=None if n.actor_id is None else refs.get(n.actor_id),
            created_at=n.created_at,
            read=n.read_at is not None,
        )
        for n in rows
    ], has_next


async def mark_read(
    db: AsyncSession, actor: Actor, ids: list[UUID] | None, *, now: datetime
) -> int:
    """Отмечает прочитанными выбранные (``ids``) или все видимые; возвращает число строк."""
    _require(actor)
    visible = _joined(select(Notification.id)).where(
        *_visible(actor, now), Notification.read_at.is_(None)
    )
    if ids is not None:
        visible = visible.where(Notification.id.in_(ids))
    result = await db.execute(
        update(Notification)
        .where(and_(Notification.id.in_(visible.scalar_subquery()), Notification.read_at.is_(None)))
        .values(read_at=now)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
