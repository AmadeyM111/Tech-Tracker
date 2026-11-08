"""Вложения: ``/api/v1/tasks/{task_id}/attachments`` и ``/api/v1/attachments/{id}`` (spec 011).

Гейт — router-level ``require_capability(BUSINESS_ACCESS)``: ТА и «без роли» получают 403.
Загрузка — сырое тело запроса (``Content-Type`` клиента не используется), имя — ``?name=``
(plan PA-1). ``Content-Length`` больше лимита — 413 до чтения тела. Отдача — с ``nosniff``,
CSP ``sandbox``; ``inline`` только для картинок (FR-6).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.attachments import AttachmentOut
from app.core.config import Settings
from app.core.db import DbSession
from app.core.errors import PayloadTooLarge
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.attachments import queries, service

router = APIRouter(
    tags=["attachments"],
    dependencies=[Depends(require_capability(Capability.BUSINESS_ACCESS))],
    responses=error_responses(401, 403, 404, 422),
)

CurrentActor = Annotated[Actor, Depends(get_active_actor)]
SAFE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox; default-src 'none'",
    "Cache-Control": "private, no-cache",
}


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.get("/tasks/{task_id}/attachments", response_model=Page[AttachmentOut])
async def list_attachments(
    task_id: UUID, db: DbSession, actor: CurrentActor, params: Annotated[PageParams, Query()]
) -> Page[AttachmentOut]:
    """Живые вложения задачи, старые сверху (FR-9); формат списка — как у всех (ADR-0012)."""
    items, has_next = await queries.list_attachments(db, actor, task_id, params)
    return Page[AttachmentOut](
        items=[AttachmentOut.model_validate(i) for i in items],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )


@router.post(
    "/tasks/{task_id}/attachments",
    status_code=201,
    response_model=AttachmentOut,
    responses=error_responses(409, 413, 507),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_attachment(
    task_id: UUID,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
    name: Annotated[str, Query(min_length=1, max_length=1024)],
) -> AttachmentOut:
    """Прикрепляет файл: тело запроса — содержимое файла (FR-1…FR-5, FR-10)."""
    settings = _settings(request)
    declared = request.headers.get("content-length")
    if (
        declared is not None
        and declared.isdigit()
        and int(declared) > settings.attachment_max_bytes
    ):
        raise PayloadTooLarge(f"Файл больше {settings.attachment_max_bytes} байт")
    view = await service.add_attachment(
        db, actor, settings, task_id, name=name, chunks=request.stream()
    )
    return AttachmentOut.model_validate(view)


@router.get(
    "/attachments/{attachment_id}/content",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download_attachment(
    attachment_id: UUID, request: Request, db: DbSession, actor: CurrentActor
) -> FileResponse:
    """Файл вложения после проверки прав (FR-6)."""
    view, path = await queries.open_attachment(db, actor, _settings(request), attachment_id)
    return FileResponse(
        path,
        media_type=view.content_type,
        filename=view.name,
        content_disposition_type="inline" if view.inline else "attachment",
        headers=SAFE_HEADERS,
    )


@router.delete("/attachments/{attachment_id}", status_code=204, response_class=Response)
async def delete_attachment(attachment_id: UUID, db: DbSession, actor: CurrentActor) -> Response:
    """Мягкое удаление: автор вложения или полная правка задачи (FR-7)."""
    await service.delete_attachment(db, actor, attachment_id)
    return Response(status_code=204)
