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
from app.core.db import transaction
from app.core.errors import AppError, NotAuthenticated, OriginMismatch
from app.domain.tokens.service import resolve_token

Asgi = Callable[[Scope, Receive, Send], Awaitable[None]]


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def _reject(exc: AppError, scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status_code)
    await response(scope, receive, send)


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
        raw = _bearer_token(request)
        if raw is None:
            await _reject(NotAuthenticated(), scope, receive, send)
            return
        async with transaction(app.state.sessionmaker) as db:
            principal = await resolve_token(db, raw)
        if principal is None:
            await _reject(NotAuthenticated(), scope, receive, send)
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
