"""Учётные записи агентов и их ключи: ``/api/v1/admin/agents`` (007 FR-1, FR-2, FR-5…FR-10,
AC-1…AC-3, AC-6…AC-12; plan §4.5, §4.6, PD-4, PD-6).

Гейт раздела — router-level ``require_capability(MANAGE_ACCOUNTS)``: БА, Пользователь и «без
роли» получают 403 для любого тела. Обработчики только вызывают сервисы
``app.domain.users.service`` и ``app.domain.api_keys.service``; транзакцию фиксирует
``DbSession``. Пароля у агента нет, в ответе (как и в логах) пароля и хеша нет.

Секрет ключа есть только в ответе выпуска (FR-6): ``IssuedApiKeyResponse`` собирается явно из
``issued.key`` и ``issued.secret``, ответ не кэшируется (``Cache-Control: no-store``), тело ответа
не логируется. Отзыв — ``POST …/revoke`` (ключ не удаляется, PD-6).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.admin import (
    AdminUser,
    ApiKeyInfo,
    CreateAgentRequest,
    IssueApiKeyRequest,
    IssuedApiKeyResponse,
)
from app.core.db import DbSession
from app.core.pagination import Page, PageParams
from app.core.security.passwords import PasswordHasher
from app.domain.access.roles import Actor, Capability
from app.domain.api_keys import service as api_keys
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


@router.get(
    "/{user_id}/api-keys",
    name="list_api_keys",
    response_model=Page[ApiKeyInfo],
    responses=error_responses(404, 422),
)
async def list_api_keys(
    user_id: UUID, db: DbSession, actor: CurrentActor, params: Annotated[PageParams, Query()]
) -> Page[ApiKeyInfo]:
    """Ключи агента: ``created_at DESC, id DESC``; у не агента — пустая страница (FR-7)."""
    keys, has_next = await api_keys.list_api_keys(db, actor, user_id, params)
    return Page[ApiKeyInfo](
        items=[ApiKeyInfo.model_validate(key) for key in keys],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )


@router.post(
    "/{user_id}/api-keys",
    name="issue_api_key",
    status_code=201,
    response_model=IssuedApiKeyResponse,
    responses=error_responses(400, 404, 422),
)
async def issue_api_key(
    user_id: UUID,
    body: IssueApiKeyRequest,
    response: Response,
    db: DbSession,
    actor: CurrentActor,
) -> IssuedApiKeyResponse:
    """Выпускает ключ агенту; секрет возвращается один раз и не кэшируется (FR-5, FR-6, FR-9)."""
    issued = await api_keys.issue_api_key(
        db, actor, user_id, name=body.name, ttl_days=body.expires_in_days
    )
    response.headers["Cache-Control"] = "no-store"
    # явная сборка: в ответ попадают только представление ключа и секрет (FR-6)
    return IssuedApiKeyResponse(key=ApiKeyInfo.model_validate(issued.key), secret=issued.secret)


@router.post(
    "/{user_id}/api-keys/{key_id}/revoke",
    name="revoke_api_key",
    status_code=204,
    response_class=Response,
    responses=error_responses(404, 422),
)
async def revoke_api_key(
    user_id: UUID, key_id: UUID, db: DbSession, actor: CurrentActor
) -> Response:
    """Отзывает ключ; повтор и отзыв истёкшего — 204 без изменений (FR-8)."""
    await api_keys.revoke_api_key(db, actor, user_id, key_id)
    return Response(status_code=204)
