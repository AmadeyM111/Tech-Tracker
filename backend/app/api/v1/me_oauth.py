"""Облачные клиенты пользователя: список и отзыв (spec 028 FR-11)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.api.deps import get_active_actor
from app.api.openapi import error_responses
from app.core.db import DbSession
from app.domain.access.roles import Actor
from app.domain.oauth import service

router = APIRouter(prefix="/me/oauth-grants", tags=["me"], responses=error_responses(401, 403))
CurrentActor = Annotated[Actor, Depends(get_active_actor)]


class OauthGrantItem(BaseModel):
    id: UUID
    client_name: str
    redirect_host: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


@router.get("", response_model=list[OauthGrantItem])
async def list_grants(db: DbSession, actor: CurrentActor) -> list[OauthGrantItem]:
    return [
        OauthGrantItem(
            id=g.id,
            client_name=g.client_name,
            redirect_host=g.redirect_host,
            created_at=g.created_at,
            last_used_at=g.last_used_at,
            revoked_at=g.revoked_at,
        )
        for g in await service.list_grants(db, actor)
    ]


@router.delete(
    "/{grant_id}", status_code=204, response_class=Response, responses=error_responses(404, 422)
)
async def revoke_grant(grant_id: UUID, db: DbSession, actor: CurrentActor) -> Response:
    """Отключает облачный клиент: все его токены сразу недействительны; повтор — 204."""
    await service.revoke_grant(db, actor, grant_id)
    return Response(status_code=204)
