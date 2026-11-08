"""Загрузка и удаление вложений (spec 011 FR-1…FR-10; plan PA-1…PA-7).

Порядок загрузки: задача и права (404 → 403) → место на диске (507) → блокировка задачи и лимит
(409) → потоковая запись (413/422) → тип (422) → публикация файла → строка и событие ленты.
Если после публикации файла что-то падает, файл удаляется; сбой ``COMMIT`` оставляет сироту,
её удаляет ``gtrack maintenance``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import Forbidden, NotFound, PayloadTooLarge, TooManyAttachments
from app.domain.access.policy import can_edit_task_fully, can_read_project_content
from app.domain.access.roles import Actor
from app.domain.attachments import storage
from app.domain.attachments.models import Attachment
from app.domain.attachments.queries import AttachmentView, view_of
from app.domain.attachments.types import FileKind, clean_name, content_type_for, detect_kind
from app.domain.events.catalog import EventAction
from app.domain.events.writer import record_event
from app.domain.tasks.context import load_task_context
from app.domain.tasks.models import Task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _lock_task(db: AsyncSession, task_id: UUID) -> None:
    """``FOR NO KEY UPDATE`` на живой задаче: загрузки в одну задачу идут по очереди, иначе
    параллельные запросы обходят лимит FR-3 (ревью 011, п. 1); удаление задачи ждёт загрузку."""
    locked = (
        await db.execute(
            select(Task.id)
            .where(Task.id == task_id, Task.deleted_at.is_(None))
            .with_for_update(key_share=True)
        )
    ).first()
    if locked is None:
        raise NotFound("Задача не найдена")


async def _live_count(db: AsyncSession, actor: Actor, task_id: UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).where(
                    Attachment.task_id == task_id,
                    Attachment.workspace_id == actor.workspace_id,
                    Attachment.deleted_at.is_(None),
                )
            )
        ).scalar_one()
    )


def _detect(name: str, staged: storage.StagedFile) -> tuple[FileKind, str]:
    kind = detect_kind(name, staged.head, staged.path)
    return kind, content_type_for(kind, staged.path)


async def add_attachment(
    db: AsyncSession,
    actor: Actor,
    settings: Settings,
    task_id: UUID,
    *,
    name: str,
    chunks: AsyncIterator[bytes],
    declared_size: int | None = None,
) -> AttachmentView:
    """Прикрепляет файл к задаче (FR-1…FR-5, FR-8, FR-10).

    Тело читается до блокировок (медленный клиент не держит блокировку задачи); тип проверяется
    в потоке (не блокирует цикл событий); лимит и запись — под блокировкой задачи.
    """
    ctx = await load_task_context(db, actor, task_id)
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    if declared_size is not None and declared_size > settings.attachment_max_bytes:
        raise PayloadTooLarge(f"Файл больше {settings.attachment_max_bytes} байт")
    original = clean_name(name)
    root = settings.attachments_dir
    storage.check_free_space(root, settings.attachments_min_free_mb)
    staged = await storage.stage(root, chunks, max_bytes=settings.attachment_max_bytes)
    try:
        kind, content_type = await asyncio.to_thread(_detect, original, staged)
        ctx = await load_task_context(db, actor, task_id, lock_project="share")
        if not can_read_project_content(actor, ctx.project):
            raise Forbidden()
        await _lock_task(db, task_id)
        if await _live_count(db, actor, task_id) >= settings.attachments_per_task:
            raise TooManyAttachments()
        stored = storage.publish(root, staged)
    except BaseException:
        storage.discard(staged.path)
        raise
    try:
        row = Attachment(
            workspace_id=actor.workspace_id,
            task_id=task_id,
            project_id=ctx.project.project_id,
            created_by=actor.user_id,
            original_name=original,
            kind=kind,
            content_type=content_type,
            size_bytes=staged.size,
            sha256=staged.sha256,
            storage_key=staged.key,
        )
        db.add(row)
        await db.flush()
        await record_event(
            db,
            workspace_id=actor.workspace_id,
            actor_id=actor.user_id,
            action=EventAction.ATTACHMENT_CREATED,
            entity_id=row.id,
            project_id=ctx.project.project_id,
        )
        return await view_of(db, actor, row, ctx.project, ctx.task)
    except BaseException:
        storage.discard(stored)
        raise


async def delete_attachment(db: AsyncSession, actor: Actor, attachment_id: UUID) -> None:
    """Мягкое удаление: автор вложения или полная правка задачи (FR-7, Q-5)."""
    row = (
        await db.execute(
            select(Attachment).where(
                Attachment.id == attachment_id,
                Attachment.workspace_id == actor.workspace_id,
                Attachment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Вложение не найдено")
    try:
        ctx = await load_task_context(db, actor, row.task_id, lock_project="share")
    except NotFound:
        raise NotFound("Вложение не найдено") from None
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    if not (row.created_by == actor.user_id or can_edit_task_fully(actor, ctx.project, ctx.task)):
        raise Forbidden()
    locked = (
        await db.execute(
            select(Attachment)
            .where(Attachment.id == attachment_id, Attachment.deleted_at.is_(None))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if locked is None:
        raise NotFound("Вложение не найдено")
    locked.deleted_at = utcnow()
    locked.deleted_batch_id = uuid4()
    await db.flush()
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.ATTACHMENT_DELETED,
        entity_id=locked.id,
        project_id=ctx.project.project_id,
    )
