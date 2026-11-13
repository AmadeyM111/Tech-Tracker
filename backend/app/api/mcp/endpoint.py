"""ASGI-адаптер ``/mcp``: Origin, токен, контекст запроса (ADR-0018, PN-2, PN-7, FR-2, FR-9).

Токен читается только из ``Authorization: Bearer``; cookie здесь не принимается (PN-2).
Проверка токена — отдельная короткая транзакция, которая фиксирует ``last_used_at``. Ответы
об отказе — JSON ``{"detail","code"}``, как у REST.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

from app.api.deps import check_origin
from app.api.mcp.context import McpRequest, reset_request, set_request
from app.api.wellknown import oauth_base_url
from app.core.db import transaction
from app.core.errors import AppError, NotAuthenticated, OriginMismatch
from app.domain.oauth.service import ACCESS_PREFIX, resolve_access
from app.domain.tokens.service import ResolvedToken, resolve_token

Asgi = Callable[[Scope, Receive, Send], Awaitable[None]]


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def _reject(
    exc: AppError,
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    challenge: str | None = None,
) -> None:
    headers = {"WWW-Authenticate": challenge} if challenge else None
    response = JSONResponse(
        {"detail": exc.detail, "code": exc.code}, status_code=exc.status_code, headers=headers
    )
    await response(scope, receive, send)


def _challenge(base: str | None, *, invalid: bool) -> str | None:
    """RFC 9728 §5.1 / RFC 6750: где искать метаданные ресурса (spec 028 FR-3)."""
    if base is None:
        return None
    parts = [f'resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"', 'scope="mcp"']
    if invalid:
        parts.insert(0, 'error="invalid_token"')
    return "Bearer " + ", ".join(parts)


async def _principal(app, raw: str) -> ResolvedToken | None:  # type: ignore[no-untyped-def]
    """``gtrk_`` (ADR-0018) или ``gtat_`` (OAuth, спека 028 FR-10)."""
    async with transaction(app.state.sessionmaker) as db:
        if raw.startswith(ACCESS_PREFIX):
            base = oauth_base_url(app.state.settings)
            oauth = None if base is None else await resolve_access(db, raw, base)
            if oauth is None:
                return None
            return ResolvedToken(
                token_id=oauth.token_id,
                user_id=oauth.user_id,
                workspace_id=oauth.workspace_id,
                login=oauth.login,
                role=oauth.role,
                must_change_password=oauth.must_change_password,
                name=oauth.name,
            )
        return await resolve_token(db, raw)


class McpEndpoint:
    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._sessions = session_manager
        # Имя для интроспекции маршрутов (как у обычного endpoint); Starlette не вызывает его.
        self.__name__ = "mcp_endpoint"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        app = scope["app"]
        request = Request(scope, receive)
        try:
            await check_origin(request)
        except OriginMismatch as exc:
            await _reject(exc, scope, receive, send)
            return
        base = oauth_base_url(app.state.settings)
        raw = _bearer_token(request)
        if raw is None:
            await _reject(
                NotAuthenticated(), scope, receive, send, challenge=_challenge(base, invalid=False)
            )
            return
        principal = await _principal(app, raw)
        if principal is None:
            await _reject(
                NotAuthenticated(), scope, receive, send, challenge=_challenge(base, invalid=True)
            )
            return
        context = McpRequest(
            principal=principal,
            registry=app.state.mcp_registry,
            sessionmaker=app.state.sessionmaker,
        )
        token = set_request(context)
        try:
            await self._sessions.handle_request(scope, receive, send)
        finally:
            reset_request(token)
