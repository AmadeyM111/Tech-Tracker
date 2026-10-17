"""Комментарии: ``/api/v1/tasks/{id}/comments``, ``/api/v1/comments/{id}`` (plan §11.4, D-65).

Гейт — router-level ``require_capability(BUSINESS_ACCESS)``: ТА и «без роли» получают 403.
Порядок ошибок: гейты -> 422 схемы -> 404 -> 403 -> 422 домена; права и очистку проверяет
домен ``app.domain.comments``. Транзакцию фиксирует ``DbSession``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.comments import Comment, CommentCreate, CommentUpdate
from app.core.db import DbSession
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.comments import service

router = APIRouter(
    tags=["comments"],
    dependencies=[Depends(require_capability(Capability.BUSINESS_ACCESS))],
    responses=error_responses(401, 403),
)

CurrentActor = Annotated[Actor, Depends(get_active_actor)]


@router.get(
    "/tasks/{task_id}/comments",
    response_model=Page[Comment],
    responses=error_responses(404, 422),
)
async def list_comments(
    task_id: UUID, db: DbSession, actor: CurrentActor, params: Annotated[PageParams, Query()]
) -> Page[Comment]:
    """Комментарии задачи по времени создания; удалённые — заглушкой без текста."""
    views, has_next = await service.list_comments(db, actor, task_id, params)
    return Page[Comment](
        items=[Comment.model_validate(v) for v in views],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )


@router.post(
    "/tasks/{task_id}/comments",
    status_code=201,
    response_model=Comment,
    responses=error_responses(400, 404, 422),
)
async def create_comment(
    task_id: UUID, body: CommentCreate, db: DbSession, actor: CurrentActor
) -> Comment:
    """Добавляет комментарий участника проекта; HTML очищается (FR-23)."""
    return Comment.model_validate(await service.create_comment(db, actor, task_id, body.body))


@router.patch(
    "/comments/{comment_id}",
    response_model=Comment,
    responses=error_responses(400, 404, 422),
)
async def edit_comment(
    comment_id: UUID, body: CommentUpdate, db: DbSession, actor: CurrentActor
) -> Comment:
    """Правит свой комментарий: новый текст и ``edited_at`` (AC-58)."""
    return Comment.model_validate(await service.edit_comment(db, actor, comment_id, body.body))


@router.delete(
    "/comments/{comment_id}",
    status_code=204,
    response_class=Response,
    responses=error_responses(404, 422),
)
async def delete_comment(comment_id: UUID, db: DbSession, actor: CurrentActor) -> Response:
    """Мягко удаляет комментарий; автор, владелец проекта или БА-участник (AC-58)."""
    await service.delete_comment(db, actor, comment_id)
    return Response(status_code=204)
