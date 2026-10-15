"""Сервис комментариев (plan §11.4, §11.5, §10.2 п.2; D-28, D-55, D-56, D-60).

Не вызывает ``commit()``: транзакцию запроса фиксирует ``get_db``. Порядок проверок:
задача или комментарий (404) -> ``FOR SHARE`` проекта (§10.2 п.2) -> участие и права (403) ->
входные данные и очистка (422) -> запись. Права пересчитываются после блокировки проекта.
Правит комментарий только автор, оставаясь участником (``can_edit_comment``); удаляет —
``can_delete_comment``. События и упоминания не пишутся (D-55, SC-6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.clock import utcnow
from app.core.errors import ErrorCode, Forbidden, NotFound, Unprocessable
from app.core.pagination import PageParams, paginate
from app.domain.access.policy import (
    ProjectFacts,
    can_delete_comment,
    can_edit_comment,
    can_read_project_content,
)
from app.domain.access.roles import Actor
from app.domain.comments.models import Comment
from app.domain.comments.sanitize import strip_html
from app.domain.projects.models import Project
from app.domain.projects.queries import load_project_facts
from app.domain.tasks.context import load_task_context
from app.domain.tasks.models import Task
from app.domain.users.directory import UserRef, user_refs

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

BODY_MAX: Final = 10_000
_SURROGATES: Final = re.compile("[\ud800-\udfff]")


@dataclass(frozen=True)
class CommentPermissions:
    edit: bool
    delete: bool


@dataclass(frozen=True)
class CommentView:
    id: UUID
    task_id: UUID
    author: UserRef
    body: str | None
    is_deleted: bool
    created_at: datetime
    edited_at: datetime | None
    permissions: CommentPermissions


def _invalid(message: str) -> Unprocessable:
    return Unprocessable(message, code=ErrorCode.validation_error)


def _clean_body(body: str) -> str:
    """Очищенный текст; 422 для не строки, длины > 10 000, NUL, суррогатов и пустого результата."""
    if not isinstance(body, str):
        raise _invalid("Комментарий: текст")
    if len(body) > BODY_MAX:
        raise _invalid("Комментарий: не более 10000 символов")
    if "\x00" in body:
        raise _invalid("Текст не может содержать нулевой символ")
    if _SURROGATES.search(body):
        raise _invalid("Текст содержит недопустимые символы")
    cleaned = strip_html(body)
    if not cleaned.strip():
        raise _invalid("Комментарий не может быть пустым")
    return cleaned


def _permissions(actor: Actor, project: ProjectFacts, author_id: UUID) -> CommentPermissions:
    member = can_read_project_content(actor, project)
    return CommentPermissions(
        edit=member and can_edit_comment(actor, author_id),
        delete=can_delete_comment(actor, project, author_id),
    )


async def _view(
    db: AsyncSession, actor: Actor, project: ProjectFacts, comment: Comment
) -> CommentView:
    return (await _views(db, actor, project, [comment]))[0]


async def _views(
    db: AsyncSession, actor: Actor, project: ProjectFacts, comments: list[Comment]
) -> list[CommentView]:
    authors = [c.created_by for c in comments if c.created_by is not None]
    refs = await user_refs(db, actor.workspace_id, authors)
    views: list[CommentView] = []
    for c in comments:
        assert c.created_by is not None  # комментарии пишут только пользователи
        is_deleted = c.deleted_at is not None
        views.append(
            CommentView(
                id=c.id,
                task_id=c.task_id,
                author=refs.get(c.created_by) or UserRef(id=c.created_by, login=""),
                body=None if is_deleted else c.body,
                is_deleted=is_deleted,
                created_at=c.created_at,
                edited_at=None if is_deleted else c.edited_at,
                permissions=(
                    CommentPermissions(edit=False, delete=False)
                    if is_deleted
                    else _permissions(actor, project, c.created_by)
                ),
            )
        )
    return views


async def _live_comment(db: AsyncSession, actor: Actor, comment_id: UUID) -> Any:
    """Строка ``(project_id)`` неудалённого комментария неудалённой задачи; иначе ``None``."""
    return (
        await db.execute(
            select(Task.project_id)
            .join(Comment, Comment.task_id == Task.id)
            .join(Project, Project.id == Task.project_id)
            .where(
                Comment.id == comment_id,
                Comment.workspace_id == actor.workspace_id,
                Comment.deleted_at.is_(None),
                Task.workspace_id == actor.workspace_id,
                Task.deleted_at.is_(None),
                Project.workspace_id == actor.workspace_id,
                Project.deleted_at.is_(None),
            )
        )
    ).one_or_none()


async def _lock_live_comment(
    db: AsyncSession, actor: Actor, comment_id: UUID
) -> tuple[ProjectFacts, Comment]:
    """404 -> ``FOR SHARE`` проекта; после блокировки комментарий и факты читаются заново."""
    row = await _live_comment(db, actor, comment_id)
    if row is None:
        raise NotFound("Комментарий не найден")
    try:
        project = await load_project_facts(db, actor, row.project_id, lock="share")
    except NotFound:
        raise NotFound("Комментарий не найден") from None
    row = await _live_comment(db, actor, comment_id)
    if row is None or row.project_id != project.project_id:
        raise NotFound("Комментарий не найден")
    comment = (
        await db.execute(
            select(Comment)
            .where(
                Comment.id == comment_id,
                Comment.workspace_id == actor.workspace_id,
                Comment.deleted_at.is_(None),
            )
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if comment is None:
        raise NotFound("Комментарий не найден")
    return project, comment


async def _lock_task_rows(db: AsyncSession, task_id: UUID, parent_id: UUID | None) -> None:
    """``FOR SHARE`` на живых строках задачи: родитель, затем сама подзадача (§10.2 п.5).

    ``delete_task`` берёт строку задачи ``FOR NO KEY UPDATE``: параллельное удаление не оставит
    живой комментарий под удалённой задачей, а само ждёт незафиксированный комментарий.
    Удалённая задача или родитель — 404.
    """
    for row_id in (parent_id, task_id):
        if row_id is None:
            continue
        locked = (
            await db.execute(
                select(Task.id)
                .where(Task.id == row_id, Task.deleted_at.is_(None))
                .with_for_update(read=True)
            )
        ).first()
        if locked is None:
            raise NotFound("Задача не найдена")


async def create_comment(db: AsyncSession, actor: Actor, task_id: UUID, body: str) -> CommentView:
    """Новый комментарий участника проекта (AC-58, FR-23)."""
    ctx = await load_task_context(db, actor, task_id, lock_project="share")
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    await _lock_task_rows(db, task_id, ctx.task.parent_id)
    comment = Comment(
        workspace_id=actor.workspace_id,
        task_id=task_id,
        body=_clean_body(body),
        created_by=actor.user_id,
    )
    db.add(comment)
    await db.flush()
    return await _view(db, actor, ctx.project, comment)


async def edit_comment(db: AsyncSession, actor: Actor, comment_id: UUID, body: str) -> CommentView:
    """Правка своего комментария участником: новый текст и ``edited_at`` (AC-58)."""
    project, comment = await _lock_live_comment(db, actor, comment_id)
    assert comment.created_by is not None
    if not (
        can_read_project_content(actor, project) and can_edit_comment(actor, comment.created_by)
    ):
        raise Forbidden()
    comment.body = _clean_body(body)
    comment.edited_at = utcnow()
    await db.flush()
    return await _view(db, actor, project, comment)


async def delete_comment(db: AsyncSession, actor: Actor, comment_id: UUID) -> None:
    """Мягкое удаление со своим пакетом ``deleted_batch_id`` (AC-58, AC-103, D-56)."""
    project, comment = await _lock_live_comment(db, actor, comment_id)
    assert comment.created_by is not None
    if not can_delete_comment(actor, project, comment.created_by):
        raise Forbidden()
    comment.deleted_at = utcnow()
    comment.deleted_batch_id = uuid4()
    await db.flush()


async def list_comments(
    db: AsyncSession, actor: Actor, task_id: UUID, params: PageParams
) -> tuple[list[CommentView], bool]:
    """Комментарии задачи по ``created_at, id``; удалённые — заглушкой без текста."""
    ctx = await load_task_context(db, actor, task_id)
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    stmt = (
        select(Comment)
        .where(Comment.task_id == task_id, Comment.workspace_id == actor.workspace_id)
        .order_by(Comment.created_at, Comment.id)
    )
    rows, has_next = await paginate(db, stmt, params)
    return await _views(db, actor, ctx.project, rows), has_next
