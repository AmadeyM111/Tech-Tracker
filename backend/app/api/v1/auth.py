"""Вход, выход и смена своего пароля (plan §4.6, FR-1, FR-5, FR-56, FR-58, FR-60, FR-61, D-13)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_actor
from app.api.v1.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    SessionUser,
)
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.db import DbSession
from app.core.security.passwords import PasswordHasher
from app.domain.access.roles import Actor, Role
from app.domain.auth import service
from app.domain.auth.provider import AuthProvider
from app.domain.auth.sessions import SessionStore

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, db: DbSession
) -> LoginResponse:
    """Вход по логину и паролю; любая причина отказа — один и тот же 401.

    До ``service.login`` обработчик не обращается к БД (ревью T11): иначе ``commit_durably``
    внутри сервиса зафиксировал бы эти записи досрочно. Cookie клиента не читается: токен
    всегда выдаёт сервер (защита от фиксации сессии).
    """
    state = request.app.state
    settings: Settings = state.settings
    provider: AuthProvider = state.auth_provider
    sessions: SessionStore = state.session_store

    result = await service.login(
        db,
        provider,
        sessions,
        login=body.login,
        password=body.password,
        now=utcnow(),
    )
    response.set_cookie(
        key=settings.cookie_name,
        value=result.token,
        max_age=int(settings.session_absolute_timeout.total_seconds()),
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return LoginResponse(
        user=SessionUser(
            id=result.user_id,
            login=result.login,
            role=None if result.role is None else Role(result.role),
            must_change_password=result.must_change_password,
        )
    )


@router.post("/logout", status_code=204, response_class=Response)
async def logout(
    request: Request,
    db: DbSession,
    _actor: Annotated[Actor, Depends(get_actor)],
) -> Response:
    """Завершает сессию на сервере и стирает cookie (FR-60).

    Доступен при одноразовом пароле и без роли: используется ``get_actor``, а не
    ``get_active_actor`` (plan §4.5, п.2–3). Повторный выход той же cookie — 401: сессии нет.
    """
    state = request.app.state
    settings: Settings = state.settings
    sessions: SessionStore = state.session_store

    token = request.cookies.get(settings.cookie_name)
    if token:  # get_actor уже убедился, что cookie есть
        await service.logout(db, sessions, token)

    response = Response(status_code=204)
    response.delete_cookie(
        key=settings.cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/password", status_code=204, response_class=Response)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    db: DbSession,
    actor: Annotated[Actor, Depends(get_actor)],
) -> Response:
    """Смена своего пароля (FR-56): 204 без тела.

    Доступна при одноразовом пароле и без роли: ``get_actor``, а не ``get_active_actor``
    (plan §4.5, п.2–3). Origin проверяется app-level зависимостью ``check_origin`` до
    обработчика, поэтому чужой Origin не засчитывается как неверный пароль. Файл пароля
    первого ТА сервис удаляет после COMMIT (``get_db`` фиксирует транзакцию до ответа).
    """
    state = request.app.state
    settings: Settings = state.settings
    hasher: PasswordHasher = state.password_hasher
    sessions: SessionStore = state.session_store

    await service.change_own_password(
        db,
        actor,
        hasher,
        sessions,
        settings,
        current=body.current_password,
        new=body.new_password,
        now=utcnow(),
    )
    return Response(status_code=204)
