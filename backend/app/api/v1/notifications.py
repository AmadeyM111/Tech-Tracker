"""Уведомления: ``/api/v1/me/notifications*`` (spec 012 FR-5…FR-7).

Гейт — router-level ``require_capability(BUSINESS_ACCESS)``: ТА уведомлений не получает (403).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.notifications import (
    MarkRead,
    NotificationOut,
    NotificationPage,
    UnreadCount,
)
from app.core.clock import utcnow
from app.core.db import DbSession
from app.core.pagination import PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.notifications import queries

router = APIRouter(
    prefix="/me/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_capability(Capability.BUSINESS_ACCESS))],
    responses=error_responses(401, 403, 422),
)

CurrentActor = Annotated[Actor, Depends(get_active_actor)]


@router.get("", response_model=NotificationPage)
async def list_notifications(
    db: DbSession, actor: CurrentActor, params: Annotated[PageParams, Query()]
) -> NotificationPage:
    """Уведомления за 30 дней, новые сверху, и число непрочитанных (FR-5)."""
    now = utcnow()
    items, has_next = await queries.list_notifications(db, actor, params, now=now)
    return NotificationPage(
        items=[NotificationOut.model_validate(i) for i in items],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
        unread=await queries.unread_count(db, actor, now=now),
    )


@router.get("/unread", response_model=UnreadCount)
async def get_unread(db: DbSession, actor: CurrentActor) -> UnreadCount:
    """Только счётчик — для значка в меню (опрос 15 с, NFR-1)."""
    return UnreadCount(unread=await queries.unread_count(db, actor, now=utcnow()))


@router.post("/read", status_code=204, response_class=Response, responses=error_responses(400))
async def mark_read(body: MarkRead, db: DbSession, actor: CurrentActor) -> Response:
    """Прочитано: выбранные или все; чужие и скрытые id игнорируются (FR-5)."""
    await queries.mark_read(db, actor, None if body.all else body.ids, now=utcnow())
    return Response(status_code=204)
