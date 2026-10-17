"""Справочник пользователей: ``GET /api/v1/users`` (plan §10.3, FR-13, FR-45a, D-24).

Гейт — router-level ``require_capability(BUSINESS_ACCESS)``: ТА и «без роли» получают 403.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.common import DirectoryQuery, DirectoryUser
from app.core.db import DbSession
from app.core.pagination import Page
from app.domain.access.roles import Actor, Capability
from app.domain.users import directory

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_capability(Capability.BUSINESS_ACCESS))],
    responses=error_responses(401, 403),
)

CurrentActor = Annotated[Actor, Depends(get_active_actor)]


@router.get("", response_model=Page[DirectoryUser], responses=error_responses(422))
async def list_directory(
    db: DbSession, actor: CurrentActor, params: Annotated[DirectoryQuery, Query()]
) -> Page[DirectoryUser]:
    """Незаблокированные пользователи пространства с ролью БА/П; ``q`` — подстрока логина."""
    users, has_next = await directory.list_directory(db, actor, params, q=params.q)
    return Page[DirectoryUser](
        items=[DirectoryUser.model_validate(user) for user in users],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )
