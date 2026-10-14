"""Учётные записи и роли: ``/api/v1/admin/users*`` (plan §4.6, §4.5, FR-4, FR-5, FR-5a, FR-12,
FR-62, FR-65, FR-69, FR-73, D-15, D-34).

Гейт раздела — router-level ``require_capability(MANAGE_ACCOUNTS)`` (``PUT …/role`` —
дополнительно ``ASSIGN_ROLES``): зависимости выполняются раньше разбора пути и тела, поэтому
БА, Пользователь и «без роли» получают 403 для любого ``user_id`` и любого тела (FR-45a).
Обработчики только вызывают сервис ``app.domain.users.service`` один раз на действие; транзакцию
фиксирует ``DbSession``. Одноразовые пароли в ответах не возвращаются (D-15).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import get_active_actor, require_capability
from app.api.v1.schemas.admin import (
    AdminUser,
    CreateUserRequest,
    ResetPasswordRequest,
    SetRoleRequest,
)
from app.core.db import DbSession
from app.core.pagination import Page, PageParams
from app.core.security.passwords import PasswordHasher
from app.domain.access.roles import Actor, Capability
from app.domain.auth.sessions import SessionStore
from app.domain.users import service

router = APIRouter(
    prefix="/admin/users",
    tags=["admin-users"],
    dependencies=[Depends(require_capability(Capability.MANAGE_ACCOUNTS))],
)

# ``get_active_actor`` общий с гейтом раздела (кэш зависимостей запроса): ``get_actor`` один.
CurrentActor = Annotated[Actor, Depends(get_active_actor)]


@router.get("", response_model=Page[AdminUser])
async def list_users(
    db: DbSession, actor: CurrentActor, params: Annotated[PageParams, Query()]
) -> Page[AdminUser]:
    """Страница учётных записей пространства: ``login ASC, id ASC`` (D-34)."""
    accounts, has_next = await service.list_accounts(db, actor, params)
    return Page[AdminUser](
        items=[AdminUser.model_validate(account) for account in accounts],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )


@router.post("", status_code=201, response_model=AdminUser)
async def create_user(
    body: CreateUserRequest, request: Request, db: DbSession, actor: CurrentActor
) -> AdminUser:
    """Создаёт пользователя без роли с одноразовым паролем из запроса (FR-4, D-15)."""
    hasher: PasswordHasher = request.app.state.password_hasher
    account = await service.create_user(
        db, actor, hasher, login=body.login, one_time_password=body.one_time_password
    )
    return AdminUser.model_validate(account)


@router.get("/{user_id}", response_model=AdminUser)
async def get_user(user_id: UUID, db: DbSession, actor: CurrentActor) -> AdminUser:
    """Учётная запись; чужое пространство и неизвестный id — 404 (FR-13)."""
    return AdminUser.model_validate(await service.get_account(db, actor, user_id))


@router.post("/{user_id}/block", status_code=204, response_class=Response)
async def block_user(
    user_id: UUID, request: Request, db: DbSession, actor: CurrentActor
) -> Response:
    """Блокирует пользователя и завершает его сессии (FR-5); повтор — без ошибки."""
    sessions: SessionStore = request.app.state.session_store
    await service.block_user(db, actor, sessions, user_id)
    return Response(status_code=204)


@router.post("/{user_id}/unblock", status_code=204, response_class=Response)
async def unblock_user(user_id: UUID, db: DbSession, actor: CurrentActor) -> Response:
    """Снимает блокировку (FR-5a); прежние сессии не восстанавливаются."""
    await service.unblock_user(db, actor, user_id)
    return Response(status_code=204)


@router.post("/{user_id}/reset-password", status_code=204, response_class=Response)
async def reset_password(
    user_id: UUID,
    body: ResetPasswordRequest,
    request: Request,
    db: DbSession,
    actor: CurrentActor,
) -> Response:
    """Задаёт новый одноразовый пароль из запроса, завершает сессии (FR-65, D-15)."""
    hasher: PasswordHasher = request.app.state.password_hasher
    sessions: SessionStore = request.app.state.session_store
    await service.reset_password(
        db, actor, hasher, sessions, user_id, one_time_password=body.one_time_password
    )
    return Response(status_code=204)


@router.post("/{user_id}/revoke-sessions", status_code=204, response_class=Response)
async def revoke_sessions(
    user_id: UUID, request: Request, db: DbSession, actor: CurrentActor
) -> Response:
    """Завершает все сессии пользователя; вход остаётся возможным (FR-62)."""
    sessions: SessionStore = request.app.state.session_store
    await service.revoke_sessions(db, actor, sessions, user_id)
    return Response(status_code=204)


@router.put(
    "/{user_id}/role",
    response_model=AdminUser,
    dependencies=[Depends(require_capability(Capability.ASSIGN_ROLES))],
)
async def set_role(
    user_id: UUID, body: SetRoleRequest, db: DbSession, actor: CurrentActor
) -> AdminUser:
    """Назначает, меняет или снимает роль (FR-12); сессии и пароль не затрагиваются."""
    account = await service.set_role(db, actor, user_id, body.role)
    return AdminUser.model_validate(account)
