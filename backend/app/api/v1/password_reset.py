"""Публичные маршруты сброса пароля по email (spec 007: FR-3, FR-5, FR-6, FR-9, NFR-2)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.api.openapi import error_response, error_responses
from app.api.v1.schemas.password_reset import (
    PasswordResetAccepted,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetStatus,
)
from app.core.clock import utcnow
from app.core.db import DbSession
from app.core.mail import deliver
from app.core.security.passwords import PasswordHasher
from app.domain.auth.password_reset import confirm_reset, request_reset
from app.domain.auth.sessions import SessionStore

router = APIRouter(prefix="/auth/password-reset", tags=["auth"])


@router.get("/status", response_model=PasswordResetStatus)
async def password_reset_status(request: Request) -> PasswordResetStatus:
    """Включён ли сброс пароля по email (настроен SMTP)."""
    return PasswordResetStatus(enabled=request.app.state.password_reset_policy is not None)


@router.post(
    "/request",
    response_model=PasswordResetAccepted,
    responses={
        **error_response(404, "Функция отключена (code: feature_disabled)"),
        **error_responses(400, 403, 422),
    },
)
async def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    db: DbSession,
    background: BackgroundTasks,
) -> PasswordResetAccepted:
    """Запрос письма со ссылкой сброса; ответ одинаков для любого адреса (FR-6).

    IP берётся из ``request.client`` (``X-Forwarded-For`` не читается). Письмо уходит
    фоновой задачей после ответа.
    """
    state = request.app.state
    message = await request_reset(
        db,
        state.password_reset_policy,
        email=body.email,
        client_ip=request.client.host if request.client else None,
        now=utcnow(),
    )
    if message is not None:
        background.add_task(deliver, state.mailer, message)
    return PasswordResetAccepted()


@router.post(
    "/confirm",
    status_code=204,
    response_class=Response,
    responses={
        **error_response(404, "Функция отключена (code: feature_disabled)"),
        **error_responses(400, 403, 422),
    },
)
async def confirm_password_reset(
    body: PasswordResetConfirm, request: Request, db: DbSession
) -> Response:
    """Смена пароля по токену из письма; успех — 204 без тела и без cookie (FR-11).

    Неверный, просроченный или использованный токен — 400 ``reset_token_invalid``.
    """
    state = request.app.state
    hasher: PasswordHasher = state.password_hasher
    sessions: SessionStore = state.session_store
    await confirm_reset(
        db,
        state.password_reset_policy,
        hasher,
        sessions,
        state.settings,
        token=body.token,
        new_password=body.new_password,
        now=utcnow(),
    )
    return Response(status_code=204)
