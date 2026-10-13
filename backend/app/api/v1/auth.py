"""Вход и выход (plan §4.6, FR-1, FR-5, FR-58, FR-60, FR-61, D-13)."""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_actor
from app.api.v1.schemas.auth import LoginRequest, LoginResponse, SessionUser
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.db import DbSession
from app.domain.access.roles import Actor, Role
from app.domain.auth import service
from app.domain.auth.provider import AuthProvider
from app.domain.auth.sessions import SessionStore

router = APIRouter(prefix="/auth", tags=["auth"])

# plan §4.6: Max-Age = 7 суток (абсолютный срок сессии по умолчанию)
SESSION_COOKIE_MAX_AGE: Final = 7 * 24 * 60 * 60


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
        max_age=SESSION_COOKIE_MAX_AGE,
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
