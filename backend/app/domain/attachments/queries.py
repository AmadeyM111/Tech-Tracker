"""Чтение вложений: список задачи и файл для скачивания (spec 011 FR-1, FR-6, FR-9).

Права — как у содержимого проекта (404 → 403). Удалённое вложение, вложение удалённой задачи или
проекта — 404. Путь файла строится только из ключа хранения.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import Forbidden, NotFound
from app.domain.access.policy import (
    ProjectFacts,
    TaskFacts,
    can_edit_task_fully,
    can_read_project_content,
)
from app.domain.access.roles import Actor
from app.domain.attachments.models import Attachment
from app.domain.attachments.storage import final_path
from app.domain.attachments.types import INLINE, FileKind
from app.domain.tasks.context import load_task_context
from app.domain.users.directory import UserRef, user_refs

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AttachmentView:
    id: UUID
    task_id: UUID
    name: str
    kind: FileKind
    content_type: str
    size_bytes: int
    created_at: datetime
    author: UserRef | None
    inline: bool
    can_delete: bool


def _view(
    row: Attachment,
    author: UserRef | None,
    actor: Actor,
    project: ProjectFacts,
    task: TaskFacts,
) -> AttachmentView:
    kind = FileKind(row.kind)
    return AttachmentView(
        id=row.id,
        task_id=row.task_id,
        name=row.original_name,
        kind=kind,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
        author=author,
        inline=kind in INLINE,
        can_delete=row.created_by == actor.user_id or can_edit_task_fully(actor, project, task),
    )


async def view_of(
    db: AsyncSession, actor: Actor, row: Attachment, project: ProjectFacts, task: TaskFacts
) -> AttachmentView:
    refs = await user_refs(db, actor.workspace_id, [row.created_by] if row.created_by else [])
    author = None if row.created_by is None else refs.get(row.created_by)
    return _view(row, author, actor, project, task)


async def list_attachments(db: AsyncSession, actor: Actor, task_id: UUID) -> list[AttachmentView]:
    """Живые вложения задачи, старые сверху (FR-9)."""
    ctx = await load_task_context(db, actor, task_id)
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    rows = list(
        (
            await db.execute(
                select(Attachment)
                .where(
                    Attachment.task_id == task_id,
                    Attachment.workspace_id == actor.workspace_id,
                    Attachment.deleted_at.is_(None),
                )
                .order_by(Attachment.created_at, Attachment.id)
            )
        ).scalars()
    )
    refs = await user_refs(
        db, actor.workspace_id, [r.created_by for r in rows if r.created_by is not None]
    )
    return [
        _view(
            r,
            None if r.created_by is None else refs.get(r.created_by),
            actor,
            ctx.project,
            ctx.task,
        )
        for r in rows
    ]


async def open_attachment(
    db: AsyncSession, actor: Actor, settings: Settings, attachment_id: UUID
) -> tuple[AttachmentView, Path]:
    """Вложение и путь к файлу для отдачи (FR-6); файла нет на диске — 404."""
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
        ctx = await load_task_context(db, actor, row.task_id)
    except NotFound:
        raise NotFound("Вложение не найдено") from None
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    path = final_path(settings.attachments_dir, row.storage_key)
    if not path.is_file():
        raise NotFound("Файл вложения не найден")
    return await view_of(db, actor, row, ctx.project, ctx.task), path
