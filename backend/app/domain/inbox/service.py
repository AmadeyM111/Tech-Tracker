"""Ingest внешних сообщений и список застрявшей работы (спека 034)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.clock import today_msk, utcnow
from app.core.errors import ErrorCode, Forbidden, NotFound, Unprocessable
from app.core.pagination import PageParams
from app.domain.access.policy import can_read_project_content
from app.domain.access.roles import Actor
from app.domain.comments.models import Comment
from app.domain.inbox.models import ExternalMessage
from app.domain.projects.models import Project, ProjectMember
from app.domain.tasks.context import load_task_context
from app.domain.tasks.models import Task, TaskStatus
from app.domain.tasks.service import TITLE_MAX, TaskCreateData, create_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

STALE_AFTER: Final = timedelta(hours=48)
SOURCE_TELEGRAM: Final = "telegram"
URL_MAX: Final = 2048


@dataclass(frozen=True)
class IngestResult:
    task_id: UUID
    comment_id: UUID | None
    source: str
    external_id: str
    url: str | None


@dataclass(frozen=True)
class StuckItem:
    id: UUID
    project_id: UUID
    title: str
    status: str
    last_activity_at: datetime
    due_date: Any
    overdue: bool
    blocked: bool | None
    open_dod: bool | None


def _invalid(message: str) -> Unprocessable:
    return Unprocessable(message, code=ErrorCode.validation_error)


def _title_from_text(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:TITLE_MAX]
    raise _invalid("Текст сообщения пуст")


def _clean_url(url: str | None) -> str | None:
    if url is None:
        return None
    value = url.strip()
    if not value:
        return None
    if len(value) > URL_MAX:
        raise _invalid("Ссылка: не более 2048 символов")
    if not (value.startswith("https://") or value.startswith("http://")):
        raise _invalid("Ссылка: http или https")
    return value


def _is_member_of(user_id: UUID) -> ColumnElement[bool]:
    return exists().where(ProjectMember.project_id == Project.id, ProjectMember.user_id == user_id)


async def _by_key(
    db: AsyncSession, workspace_id: UUID, source: str, external_id: str
) -> ExternalMessage | None:
    return (
        await db.execute(
            select(ExternalMessage).where(
                ExternalMessage.workspace_id == workspace_id,
                ExternalMessage.source == source,
                ExternalMessage.external_id == external_id,
            )
        )
    ).scalar_one_or_none()


async def _present(db: AsyncSession, actor: Actor, row: ExternalMessage) -> IngestResult:
    ctx = await load_task_context(db, actor, row.task_id)
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    return IngestResult(
        task_id=row.task_id,
        comment_id=row.comment_id,
        source=row.source,
        external_id=row.external_id,
        url=row.url,
    )


async def source_for_task(
    db: AsyncSession, workspace_id: UUID, task_id: UUID
) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(ExternalMessage.source, ExternalMessage.url).where(
                ExternalMessage.workspace_id == workspace_id,
                ExternalMessage.task_id == task_id,
                ExternalMessage.comment_id.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        return None, None
    return row.source, row.url


async def sources_for_comments(
    db: AsyncSession, workspace_id: UUID, comment_ids: list[UUID]
) -> dict[UUID, tuple[str | None, str | None]]:
    if not comment_ids:
        return {}
    rows = (
        await db.execute(
            select(ExternalMessage.comment_id, ExternalMessage.source, ExternalMessage.url).where(
                ExternalMessage.workspace_id == workspace_id,
                ExternalMessage.comment_id.in_(comment_ids),
            )
        )
    ).all()
    return {row.comment_id: (row.source, row.url) for row in rows if row.comment_id is not None}


async def ingest_message(
    db: AsyncSession,
    actor: Actor,
    *,
    project_id: UUID,
    source: str,
    external_id: str,
    text: str,
    task_id: UUID | None,
    url: str | None,
) -> IngestResult:
    """Создать задачу или комментарий; повтор ключа возвращает ту же сущность."""
    if source != SOURCE_TELEGRAM:
        raise _invalid("Источник: telegram")
    ext_id = external_id.strip()
    if not ext_id or len(ext_id) > 256:
        raise _invalid("Внешний идентификатор: от 1 до 256 символов")
    clean_url = _clean_url(url)
    existing = await _by_key(db, actor.workspace_id, source, ext_id)
    if existing is not None:
        return await _present(db, actor, existing)

    try:
        async with db.begin_nested():
            if task_id is None:
                title = _title_from_text(text)
                new_task_id = await create_task(
                    db,
                    actor,
                    project_id,
                    TaskCreateData(title=title, description=text, due_date=today_msk()),
                )
                new_comment_id: UUID | None = None
            else:
                from app.domain.comments import service as comments_service

                ctx = await load_task_context(db, actor, task_id, lock_project="share")
                if ctx.project.project_id != project_id:
                    raise NotFound("Задача не найдена")
                comment = await comments_service.create_comment(db, actor, task_id, text)
                new_task_id = task_id
                new_comment_id = comment.id
            row = ExternalMessage(
                workspace_id=actor.workspace_id,
                source=source,
                external_id=ext_id,
                url=clean_url,
                task_id=new_task_id,
                comment_id=new_comment_id,
            )
            db.add(row)
            await db.flush()
    except IntegrityError:
        raced = await _by_key(db, actor.workspace_id, source, ext_id)
        if raced is None:
            raise
        return await _present(db, actor, raced)
    return IngestResult(
        task_id=new_task_id,
        comment_id=new_comment_id,
        source=source,
        external_id=ext_id,
        url=clean_url,
    )


def _optional_flag(task: Task, column: str) -> bool | None:
    if column not in Task.__table__.c:
        return None
    value = getattr(task, column, None)
    if value is None:
        return None
    return bool(value)


async def list_stuck_work(
    db: AsyncSession, actor: Actor, params: PageParams
) -> tuple[list[StuckItem], bool]:
    """Не done в моих проектах, без движения 48 ч. Просрочка — отдельное поле."""
    cutoff = utcnow() - STALE_AFTER
    last_comment = (
        select(func.max(Comment.created_at))
        .where(
            Comment.task_id == Task.id,
            Comment.workspace_id == actor.workspace_id,
            Comment.deleted_at.is_(None),
        )
        .correlate(Task)
        .scalar_subquery()
    )
    last_activity = func.greatest(Task.updated_at, func.coalesce(last_comment, Task.updated_at))
    stmt = (
        select(Task, last_activity.label("last_activity_at"))
        .join(Project, Project.id == Task.project_id)
        .where(
            Task.workspace_id == actor.workspace_id,
            Task.deleted_at.is_(None),
            Task.status != TaskStatus.DONE.value,
            Project.workspace_id == actor.workspace_id,
            Project.deleted_at.is_(None),
            or_(_is_member_of(actor.user_id), Project.owner_id == actor.user_id),
            last_activity <= cutoff,
        )
        .order_by(last_activity, Task.id)
    )
    offset = (params.page - 1) * params.page_size
    fetched = list((await db.execute(stmt.limit(params.page_size + 1).offset(offset))).all())
    has_next = len(fetched) > params.page_size
    rows = fetched[: params.page_size]
    today = today_msk()
    items: list[StuckItem] = []
    for row in rows:
        task: Task = row.Task
        due = task.due_date
        items.append(
            StuckItem(
                id=task.id,
                project_id=task.project_id,
                title=task.title,
                status=task.status,
                last_activity_at=row.last_activity_at,
                due_date=due,
                overdue=due is not None and due < today,
                blocked=_optional_flag(task, "blocked"),
                open_dod=_optional_flag(task, "open_dod"),
            )
        )
    return items, has_next
