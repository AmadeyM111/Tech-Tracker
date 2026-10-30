"""Учётные записи агентов: ``/api/v1/admin/agents`` (007 FR-1, FR-2, AC-1…AC-3; plan §4.5, PD-4).

Гейт раздела — router-level ``require_capability(MANAGE_ACCOUNTS)``: БА, Пользователь и «без
роли» получают 403 для любого тела. Обработчик только вызывает
``app.domain.users.service.create_agent``; транзакцию фиксирует ``DbSession``. Пароля у агента
нет, в ответе (как и в логах) пароля и хеша нет.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.admin import AdminUser, CreateAgentRequest
from app.core.db import DbSession
from app.core.security.passwords import PasswordHasher
from app.domain.access.roles import Actor, Capability
from app.domain.users import service

router = APIRouter(
    prefix="/admin/agents",
    tags=["admin-agents"],
    dependencies=[Depends(require_capability(Capability.MANAGE_ACCOUNTS))],
    responses=error_responses(401, 403),
)

# ``get_active_actor`` общий с гейтом раздела (кэш зависимостей запроса): ``get_actor`` один.
CurrentActor = Annotated[Actor, Depends(get_active_actor)]


@router.post("", status_code=201, response_model=AdminUser, responses=error_responses(400, 422))
async def create_agent(
    body: CreateAgentRequest, request: Request, db: DbSession, actor: CurrentActor
) -> AdminUser:
    """Создаёт учётную запись агента с указанной ролью или без неё (FR-1, FR-2)."""
    hasher: PasswordHasher = request.app.state.password_hasher
    account = await service.create_agent(db, actor, hasher, login=body.login, role=body.role)
    # is_agent берётся из результата сервиса, а не из ORM-атрибута (plan §4.1)
    return AdminUser.model_validate(account)
