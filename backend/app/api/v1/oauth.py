"""OAuth 2.1 endpoint'ы: регистрация, согласие, token, revoke (spec 028 FR-4…FR-8, FR-13, FR-14).

Машинные endpoint (``register``, ``token``, ``revoke``) отвечают в формате OAuth
(``{error, error_description}``) обычным ответом, а не исключением: транзакция фиксируется,
поэтому счётчик лимита не откатывается. Согласие — под сессией пользователя (cookie).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api.deps import require_capability
from app.api.openapi import error_responses
from app.api.wellknown import require_base_url
from app.core.clock import utcnow
from app.core.db import DbSession
from app.core.errors import Unprocessable
from app.core.secrets import ensure_secret_key
from app.domain.access.roles import Actor, Capability
from app.domain.oauth import service

router = APIRouter(prefix="/oauth", tags=["oauth"])
_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
ConsentActor = Annotated[Actor, Depends(require_capability(Capability.BUSINESS_ACCESS))]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _oauth_error(exc: service.OauthError, extra: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": exc.error, "error_description": exc.description},
        status_code=exc.status,
        headers={**_HEADERS, **(extra or {})},
    )


def _too_many(retry_after: int, error: str) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": "Слишком много запросов"},
        status_code=429,
        headers={**_HEADERS, "Retry-After": str(retry_after)},
    )


def _allowed_hosts(request: Request) -> frozenset[str]:
    raw: str = request.app.state.settings.oauth_redirect_hosts
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


@router.post("/register", include_in_schema=False)
async def register(request: Request, db: DbSession) -> JSONResponse:
    """Динамическая регистрация публичного клиента (RFC 7591)."""
    require_base_url(request)
    key = ensure_secret_key(request.app.state.settings)
    wait = await service.hit_limit(
        db,
        key,
        "register_ip",
        _client_ip(request),
        limit=service.REGISTER_PER_HOUR,
        window=timedelta(hours=1),
    )
    if wait is not None:
        return _too_many(wait, "temporarily_unavailable")
    try:
        body = json.loads(await request.body() or b"{}")
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        return _oauth_error(service.OauthError("invalid_client_metadata", "Нужен JSON-объект"))
    try:
        client = await service.register_client(db, body, _allowed_hosts(request))
    except service.OauthError as exc:
        return _oauth_error(exc)
    return JSONResponse(
        {
            "client_id": client.client_id,
            "client_id_issued_at": int(client.created_at.timestamp()),
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": service.SCOPE,
        },
        status_code=201,
        headers=_HEADERS,
    )


async def _form(request: Request) -> dict[str, str]:
    return dict(
        parse_qsl((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
    )


@router.post("/token", include_in_schema=False)
async def token(request: Request, db: DbSession) -> JSONResponse:
    """Обмен кода и refresh-токена на токены (``application/x-www-form-urlencoded``)."""
    base = require_base_url(request)
    key = ensure_secret_key(request.app.state.settings)
    wait = await service.hit_limit(
        db,
        key,
        "token_ip",
        _client_ip(request),
        limit=service.TOKEN_PER_MINUTE,
        window=timedelta(minutes=1),
    )
    if wait is not None:
        return _too_many(wait, "slow_down")
    form = await _form(request)
    try:
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            result = await service.exchange_code(db, form, base)
        elif grant_type == "refresh_token":
            result = await service.exchange_refresh(db, form)
        else:
            raise service.OauthError("unsupported_grant_type", "Недопустимый grant_type")
    except service.OauthError as exc:
        return _oauth_error(exc)
    return JSONResponse(result, headers=_HEADERS)


@router.post("/revoke", include_in_schema=False)
async def revoke(request: Request, db: DbSession) -> JSONResponse:
    """RFC 7009: отзыв по токену; всегда 200."""
    require_base_url(request)
    raw = (await _form(request)).get("token", "")
    if raw:
        await service.revoke_by_token(db, raw)
    return JSONResponse({}, headers=_HEADERS)


class AuthorizeQuery(BaseModel):
    """Параметры запроса авторизации (RFC 6749 §4.1.1, RFC 7636, RFC 8707); проверяет сервис."""

    response_type: str | None = None
    client_id: str | None = None
    redirect_uri: str | None = None
    code_challenge: str | None = None
    code_challenge_method: str | None = None
    state: str | None = None
    scope: str | None = None
    resource: str | None = None


class ConsentContext(BaseModel):
    status: str  # "ok" | "redirect"
    client_name: str | None = None
    redirect_host: str | None = None
    redirect_uri: str | None = None
    login: str | None = None
    request_token: str | None = None
    redirect_to: str | None = None


@router.get(
    "/authorize/context",
    response_model=ConsentContext,
    responses=error_responses(401, 403, 422),
)
async def authorize_context(
    request: Request, db: DbSession, actor: ConsentActor, query: Annotated[AuthorizeQuery, Query()]
) -> ConsentContext:
    """Проверка запроса авторизации под сессией; подписанный контекст для решения."""
    base = require_base_url(request)
    given = query.model_dump()
    params = {k: v for k, v in given.items() if v is not None}
    try:
        req = await service.check_authorize_request(db, base, params)
    except service.AuthorizeError as exc:
        if not exc.redirect:
            raise Unprocessable(exc.description, code=_page_error_code(exc)) from exc
        return ConsentContext(
            status="redirect",
            redirect_to=service.redirect_with(
                params["redirect_uri"],
                base,
                {
                    "error": exc.error,
                    "error_description": exc.description,
                    "state": params.get("state"),
                },
            ),
        )
    key = ensure_secret_key(request.app.state.settings)
    return ConsentContext(
        status="ok",
        client_name=req.label,
        redirect_host=req.redirect_host,
        redirect_uri=req.redirect_uri,
        login=actor.login,
        request_token=service.sign_context(key, req, actor.user_id, utcnow()),
    )


def _page_error_code(exc: service.AuthorizeError) -> str:
    return "oauth_client_unknown" if exc.error == "invalid_client" else "oauth_request_invalid"


class ConsentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_token: str
    allow: bool


class ConsentResult(BaseModel):
    redirect_to: str


@router.post(
    "/authorize/decision",
    response_model=ConsentResult,
    responses=error_responses(400, 401, 403, 422),
)
async def authorize_decision(
    body: ConsentDecision, request: Request, db: DbSession, actor: ConsentActor
) -> ConsentResult:
    """«Разрешить» (грант, код, аудит) или «Отклонить»; ответ — адрес редиректа клиенту."""
    base = require_base_url(request)
    key = ensure_secret_key(request.app.state.settings)
    try:
        ctx: dict[str, Any] = service.verify_context(
            key, body.request_token, actor.user_id, utcnow()
        )
        if body.allow:
            return ConsentResult(redirect_to=await service.grant_consent(db, actor, base, ctx))
    except service.OauthError as exc:
        raise Unprocessable(exc.description, code="oauth_request_invalid") from exc
    return ConsentResult(
        redirect_to=service.redirect_with(
            ctx["r"], base, {"error": "access_denied", "state": ctx.get("s")}
        )
    )
