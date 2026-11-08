"""Учётные записи без роли: ``/api/v1/unassigned-accounts*``.

Spec 019, FR-13a, AC-26, AC-30; plan §4.4, RG-11.

Гейт — router-level ``require_capability(ONBOARD_ACCOUNTS)``: право только у БА. ТА, «Пользователь»
и «без роли» получают 403 для любого запроса и любого тела. Обработчики вызывают сервис
``app.domain.users.onboarding`` один раз на действие; транзакцию фиксирует ``DbSession``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.accounts import UnassignedAccountOut
from app.api.v1.schemas.admin import SetRoleRequest
from app.core.db import DbSession
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.users import onboarding

router = APIRouter(
    prefix="/unassigned-accounts",
    tags=["accounts"],
    dependencies=[Depends(require_capability(Capability.ONBOARD_ACCOUNTS))],
    responses=error_responses(401, 403),
)

CurrentActor = Annotated[Actor, Depends(get_active_actor)]


@router.get("", response_model=Page[UnassignedAccountOut], responses=error_responses(422))
async def list_unassigned_accounts(
    db: DbSession, actor: CurrentActor, params: Annotated[PageParams, Query()]
) -> Page[UnassignedAccountOut]:
    """Учётные записи пространства без роли: ``login ASC, id ASC``; email в ответе нет (AC-30)."""
    accounts, has_next = await onboarding.list_unassigned(db, actor, params)
    return Page[UnassignedAccountOut](
        items=[UnassignedAccountOut.model_validate(account) for account in accounts],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )


@router.put(
    "/{user_id}/role",
    status_code=204,
    response_class=Response,
    responses=error_responses(400, 404, 422),
)
async def assign_user_role(
    user_id: UUID, body: SetRoleRequest, db: DbSession, actor: CurrentActor
) -> Response:
    """Назначает роль «Пользователь» учётной записи без роли; иное значение и повтор — 403."""
    await onboarding.assign_user_role(db, actor, user_id, body.role)
    return Response(status_code=204)
