"""Профиль текущего пользователя (plan §4.6, FR-66, FR-67)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_active_actor
from app.api.openapi import error_responses
from app.api.v1.schemas.admin import SetNameRequest
from app.api.v1.schemas.auth import MeResponse
from app.core.db import DbSession
from app.core.errors import NoRole
from app.domain.access.roles import Actor, Capability
from app.domain.users import profile

router = APIRouter(tags=["me"])


def _capabilities(actor: Actor) -> list[Capability]:
    return sorted((cap for cap in Capability if actor.can(cap)), key=lambda c: c.value)


def _me_response(
    actor: Actor, capabilities: list[Capability], own: profile.OwnProfile
) -> MeResponse:
    if actor.role is None:
        raise NoRole()
    return MeResponse(
        id=actor.user_id,
        login=actor.login,
        role=actor.role,
        must_change_password=actor.must_change_password,
        capabilities=capabilities,
        first_name=own.first_name,
        last_name=own.last_name,
    )


@router.get("/me", response_model=MeResponse, responses=error_responses(401, 403))
async def me(actor: Annotated[Actor, Depends(get_active_actor)], db: DbSession) -> MeResponse:
    """Профиль и отсортированный список возможностей активного пользователя.

    Роль и флаги читаются из БД на каждый запрос (FR-67). ``get_active_actor`` гарантирует
    назначенную роль и ``must_change_password = false``.
    """
    if actor.role is None:  # гейт «без роли» уже отработал; защита от прямого вызова
        raise NoRole()
    capabilities = _capabilities(actor)
    own = await profile.get_own_profile(db, actor)
    return _me_response(actor, capabilities, own)


@router.put("/me/name", response_model=MeResponse, responses=error_responses(400, 401, 403, 422))
async def set_own_name(
    body: SetNameRequest, actor: Annotated[Actor, Depends(get_active_actor)], db: DbSession
) -> MeResponse:
    """Меняет собственные имя и фамилию (FR-3c); доступно любой роли с сессией."""
    own = await profile.set_own_name(db, actor, body.first_name, body.last_name)
    return _me_response(actor, _capabilities(actor), own)
