"""Токены агентов: ``/api/v1/me/tokens`` (ADR-0018, PN-2, PN-5, FR-1, FR-3).

Гейт — ``get_active_actor`` (cookie-сессия). ``Authorization: Bearer`` здесь не принимается:
без cookie запрос получает 401, поэтому токен не выпускает и не отзывает токены (PN-2).
Логика — в ``app.domain.tokens.service``; маршрут только вызывает её и отдаёт схему.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_active_actor
from app.api.openapi import error_responses
from app.api.v1.schemas.tokens import TokenCreate, TokenCreated, TokenItem
from app.core.clock import utcnow
from app.core.db import DbSession
from app.domain.access.roles import Actor
from app.domain.tokens import service
from app.domain.tokens.service import TokenView

router = APIRouter(prefix="/me/tokens", tags=["tokens"], responses=error_responses(401, 403))

CurrentActor = Annotated[Actor, Depends(get_active_actor)]


def _item(view: TokenView) -> TokenItem:
    return TokenItem(
        id=view.id,
        name=view.name,
        created_at=view.created_at,
        expires_at=view.expires_at,
        last_used_at=view.last_used_at,
        revoked_at=view.revoked_at,
        active=_is_active(view),
    )


def _is_active(view: TokenView) -> bool:
    return view.revoked_at is None and view.expires_at > utcnow()


@router.get("", response_model=list[TokenItem])
async def list_my_tokens(db: DbSession, actor: CurrentActor) -> list[TokenItem]:
    """Токены текущего пользователя, новые первыми; значения токенов не возвращаются."""
    return [_item(view) for view in await service.list_tokens(db, actor)]


@router.post(
    "",
    status_code=201,
    response_model=TokenCreated,
    responses=error_responses(400, 409, 422),
)
async def create_my_token(body: TokenCreate, db: DbSession, actor: CurrentActor) -> TokenCreated:
    """Выдаёт токен агента. Значение ``token`` в ответе — единственный раз (AC-1)."""
    created = await service.create_token(db, actor, body.name)
    item = _item(created.view)
    return TokenCreated(**item.model_dump(), token=created.token)


@router.delete(
    "/{token_id}",
    status_code=204,
    response_class=Response,
    responses=error_responses(404, 422),
)
async def revoke_my_token(token_id: UUID, db: DbSession, actor: CurrentActor) -> Response:
    """Отзывает свой токен (AC-3). Повторный отзыв — 204."""
    await service.revoke_token(db, actor, token_id)
    return Response(status_code=204)
