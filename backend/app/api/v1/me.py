"""Профиль текущего пользователя (plan §4.6, FR-66, FR-67)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_active_actor
from app.api.v1.schemas.auth import MeResponse
from app.domain.access.roles import Actor, Capability

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
async def me(actor: Annotated[Actor, Depends(get_active_actor)]) -> MeResponse:
    """Профиль и отсортированный список возможностей активного пользователя.

    Роль и флаги читаются из БД на каждый запрос (FR-67). ``get_active_actor`` гарантирует
    назначенную роль и ``must_change_password = false``.
    """
    assert actor.role is not None  # гейт «без роли» уже отработал
    capabilities = sorted((cap for cap in Capability if actor.can(cap)), key=lambda c: c.value)
    return MeResponse(
        id=actor.user_id,
        login=actor.login,
        role=actor.role,
        must_change_password=actor.must_change_password,
        capabilities=capabilities,
    )
