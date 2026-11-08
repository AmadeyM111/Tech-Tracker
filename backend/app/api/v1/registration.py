"""Публичные маршруты самостоятельной регистрации (spec 019: FR-3..FR-9, NFR-1; plan §4.4).

Роутер: схема → один вызов домена (``domain/auth/registration.py``) → схема ответа. Запросов к
БД и ``commit()`` здесь нет; транзакцию фиксирует ``DbSession``. Письмо уходит фоновой задачей
после ответа, IP клиента берётся из ``request.client`` (``X-Forwarded-For`` не читается).
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.api.openapi import error_response, error_responses
from app.api.v1.schemas.registration import (
    RegistrationAccepted,
    RegistrationConfirm,
    RegistrationRequest,
)
from app.core.clock import utcnow
from app.core.db import DbSession
from app.core.mail import deliver
from app.domain.auth import registration as registration_domain

router = APIRouter(prefix="/auth/registration", tags=["auth"])

_FEATURE_DISABLED = "Функция отключена или пространство не единственное (code: feature_disabled)"
_RATE_LIMITED = "Слишком много запросов с этого IP-адреса или по этой ссылке (code: rate_limited)"


@router.post(
    "/request",
    response_model=RegistrationAccepted,
    responses={
        **error_response(404, _FEATURE_DISABLED),
        **error_response(429, _RATE_LIMITED),
        **error_responses(400, 403, 422),
    },
)
async def request_registration(
    body: RegistrationRequest,
    request: Request,
    db: DbSession,
    background: BackgroundTasks,
) -> RegistrationAccepted:
    """Заявка на регистрацию; ответ одинаков, занят адрес или свободен (FR-4).

    Ошибки формы (адрес, имя, фамилия, логин, пароль) и лимит IP отвечают кодами из каталога.
    Письмо со ссылкой уходит только на свободный адрес и только после ответа.
    """
    state = request.app.state
    form = registration_domain.RegistrationForm(
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        login=body.login,
        password=body.password,
    )
    message = await registration_domain.request_registration(
        db,
        state.registration_policy,
        state.password_hasher,
        form=form,
        client_ip=request.client.host if request.client else None,
        now=utcnow(),
    )
    if message is not None:
        background.add_task(deliver, state.mailer, message)
    return RegistrationAccepted()


@router.post(
    "/confirm",
    status_code=204,
    response_class=Response,
    responses={
        **error_response(404, _FEATURE_DISABLED),
        **error_response(409, "Логин занят учётной записью (code: login_taken)"),
        **error_response(429, _RATE_LIMITED),
        **error_responses(400, 403, 422),
    },
)
async def confirm_registration(
    body: RegistrationConfirm,
    request: Request,
    db: DbSession,
) -> Response:
    """Подтверждение регистрации по ссылке; успех — 204 без тела и без cookie (AC-16).

    Неверная, просроченная или использованная ссылка и занятый адрес — 400
    ``registration_token_invalid``. Занятый логин — 409 ``login_taken``. Сессия не создаётся:
    вход отдельным действием.
    """
    state = request.app.state
    await registration_domain.confirm_registration(
        db,
        state.registration_policy,
        token=body.token,
        client_ip=request.client.host if request.client else None,
        now=utcnow(),
    )
    return Response(status_code=204)
