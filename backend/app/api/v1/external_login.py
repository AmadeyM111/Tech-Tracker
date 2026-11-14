"""Вход через внешних провайдеров и «Способы входа» в профиле (spec 029 FR-12…FR-21; ADR-0026).

Публичные маршруты ``/auth/external/{provider}/start`` и ``.../callback`` — навигация браузера:
результат всегда редирект (на ``/``, ``/profile`` или ``/login?external_error=<код>``), чтобы
пользователь не увидел JSON. Любой отказ входа одинаков (``login_failed``), существование учётки
не раскрывается. Провайдер выключен флагом или без Client ID — ``provider_unavailable``.
Привязка и отвязка — только из открытой сессии (``/me/login-methods``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, SecretStr

from app.api.deps import get_active_actor
from app.api.openapi import error_response, error_responses
from app.api.wellknown import oauth_base_url
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.db import DbSession
from app.core.errors import FeatureDisabled
from app.core.secrets import ensure_secret_key
from app.domain.access.roles import Actor
from app.domain.auth import external
from app.domain.auth.external_providers import enabled_providers
from app.domain.auth.sessions import SessionStore
from app.domain.oauth.service import hit_limit

router = APIRouter(prefix="/auth/external", tags=["auth"])
me_router = APIRouter(prefix="/me/login-methods", tags=["me"], responses=error_responses(401, 403))
CurrentActor = Annotated[Actor, Depends(get_active_actor)]
Provider = Literal["yandex", "vk", "google"]
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_LIMIT = 60
_WINDOW = timedelta(minutes=10)


def _redirect(path: str, **params: str) -> RedirectResponse:
    target = f"{path}?{urlencode(params)}" if params else path
    return RedirectResponse(target, status_code=302, headers=_NO_STORE)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


async def _throttled(request: Request, db: DbSession) -> bool:
    key = ensure_secret_key(request.app.state.settings)
    wait = await hit_limit(
        db, key, "external_ip", _client_ip(request), limit=_LIMIT, window=_WINDOW
    )
    return wait is not None


class ProviderItem(BaseModel):
    name: Provider


@router.get("/providers", response_model=list[ProviderItem])
async def list_providers(request: Request) -> list[ProviderItem]:
    """Включённые провайдеры для кнопок на экране входа (публично, без ключей)."""
    settings: Settings = request.app.state.settings
    if oauth_base_url(settings) is None:
        return []
    return [ProviderItem(name=name) for name in enabled_providers(settings)]


@router.get(
    "/{provider}/start",
    status_code=302,
    response_class=RedirectResponse,
    responses=error_responses(422),
)
async def start_login(
    provider: Provider, request: Request, db: DbSession, remember: bool = False
) -> RedirectResponse:
    """Начало входа: редирект к провайдеру (PKCE S256, одноразовый ``state``)."""
    settings: Settings = request.app.state.settings
    base = oauth_base_url(settings)
    cfg = enabled_providers(settings).get(provider)
    if base is None or cfg is None or await _throttled(request, db):
        return _redirect("/login", external_error="provider_unavailable")
    url = await external.start(
        db, cfg, base_url=base, purpose="login", user_id=None, remember=remember, now=utcnow()
    )
    return RedirectResponse(url, status_code=302, headers=_NO_STORE)


@router.get(
    "/{provider}/callback",
    status_code=302,
    response_class=RedirectResponse,
    responses=error_responses(422),
)
async def callback(
    provider: Provider,
    request: Request,
    db: DbSession,
    state: Annotated[str | None, Query(max_length=1024)] = None,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
    device_id: Annotated[str | None, Query(max_length=256)] = None,
) -> RedirectResponse:
    """Обратный вызов провайдера: вход, привязка или отказ; всё — редиректом."""
    app_state = request.app.state
    settings: Settings = app_state.settings
    sessions: SessionStore = app_state.session_store
    base = oauth_base_url(settings)
    if base is None or await _throttled(request, db):
        return _redirect("/login", external_error="provider_unavailable")
    now = utcnow()
    cookie = request.cookies.get(settings.cookie_name)
    record = await sessions.resolve(db, cookie, now=now, background=True) if cookie else None
    outcome = await external.complete(
        db,
        app_state.external_http,
        enabled_providers(settings),
        sessions,
        external.CallbackRequest(
            provider=provider,
            state=state,
            code=code,
            device_id=device_id,
            provider_error=error,
            session_user_id=None if record is None else record.user_id,
        ),
        base_url=base,
        registration_open=app_state.registration_policy is not None,
        now=now,
    )
    page = "/profile" if outcome.purpose == "link" else "/login"
    if outcome.error is not None:
        return _redirect(page, external_error=outcome.error)
    if outcome.purpose == "link":
        return _redirect("/profile", external="linked")
    assert outcome.token is not None
    response = _redirect("/")
    response.set_cookie(
        key=settings.cookie_name,
        value=outcome.token,
        max_age=int(
            (
                settings.session_remember_timeout
                if outcome.remember
                else settings.session_absolute_timeout
            ).total_seconds()
        ),
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


# --- «Способы входа» в профиле ---------------------------------------------------------------


class LinkedIdentity(BaseModel):
    id: UUID
    provider: Provider
    linked_at: datetime
    last_used_at: datetime | None
    can_unlink: bool


class LoginMethods(BaseModel):
    has_password: bool
    linked: list[LinkedIdentity]
    available: list[Provider]  # включённые провайдеры, которые ещё не привязаны


class LinkStart(BaseModel):
    url: str


class SetPasswordRequest(BaseModel):
    new_password: SecretStr


@me_router.get("", response_model=LoginMethods)
async def list_login_methods(request: Request, db: DbSession, actor: CurrentActor) -> LoginMethods:
    has_password, items = await external.list_identities(db, actor.user_id)
    linked_names = {i.provider for i in items}
    enabled = enabled_providers(request.app.state.settings)
    return LoginMethods(
        has_password=has_password,
        linked=[
            LinkedIdentity(
                id=i.id,
                provider=i.provider,
                linked_at=i.linked_at,
                last_used_at=i.last_used_at,
                can_unlink=i.can_unlink,
            )
            for i in items
        ],
        available=[n for n in enabled if n not in linked_names],
    )


@me_router.post(
    "/{provider}/link",
    response_model=LinkStart,
    responses={
        **error_response(404, "Провайдер выключен (code: feature_disabled)"),
        **error_responses(422),
    },
)
async def start_link(
    provider: Provider, request: Request, db: DbSession, actor: CurrentActor
) -> LinkStart:
    """Начало привязки (FR-18): адрес авторизации; сессия сохраняется до ``callback``."""
    settings: Settings = request.app.state.settings
    base = oauth_base_url(settings)
    cfg = enabled_providers(settings).get(provider)
    if base is None or cfg is None:
        raise FeatureDisabled()
    url = await external.start(
        db, cfg, base_url=base, purpose="link", user_id=actor.user_id, remember=False, now=utcnow()
    )
    return LinkStart(url=url)


@me_router.delete(
    "/{identity_id}",
    status_code=204,
    response_class=Response,
    responses={
        **error_response(422, "Последний способ входа (code: last_login_method)"),
        **error_responses(404),
    },
)
async def unlink_login_method(identity_id: UUID, db: DbSession, actor: CurrentActor) -> Response:
    """Отвязка (FR-19): запрещена, если это последний способ входа."""
    await external.unlink(db, actor.user_id, identity_id, utcnow())
    return Response(status_code=204)


@me_router.post(
    "/password",
    status_code=204,
    response_class=Response,
    responses={
        **error_responses(400),
        **error_response(422, "Пароль уже задан или не проходит политику (code из каталога)"),
    },
)
async def set_password(
    body: SetPasswordRequest, request: Request, db: DbSession, actor: CurrentActor
) -> Response:
    """Q-6: задаёт пароль учётной записи без пароля; остальные сессии завершаются."""
    state = request.app.state
    await external.set_initial_password(
        db,
        state.password_hasher,
        state.session_store,
        actor.user_id,
        actor.session_id,
        body.new_password,
        utcnow(),
    )
    return Response(status_code=204)
