"""Протокол MCP: список и вызов инструментов поверх Streamable HTTP (ADR-0018, PN-3, PN-12).

Сервер работает без состояния (``stateless=True``): каждый HTTP-запрос самостоятелен, субъект
берётся из контекста запроса (``context``). Вызов инструмента выполняется в своей транзакции:
ошибка домена откатывает все его записи. Имя токена попадает в журнал через ``client_name_scope``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import ValidationError

from app.api.mcp.context import current_request
from app.core.db import transaction
from app.core.errors import (
    AppError,
    Forbidden,
    NoRole,
    NotAuthenticated,
    NotFound,
    PasswordChangeRequired,
    Unprocessable,
)
from app.domain.access.roles import Actor
from app.domain.events.client_context import client_name_scope
from app.domain.tokens.service import ResolvedToken

logger = logging.getLogger(__name__)
SERVER_NAME = "gtrack"


def _gate(principal: ResolvedToken) -> AppError | None:
    """Гейты до инструментов (PN-3): одноразовый пароль, роль «без роли»."""
    if principal.must_change_password:
        return PasswordChangeRequired()
    if principal.role is None:
        return NoRole()
    return None


def _actor(principal: ResolvedToken) -> Actor:
    # session_id для токена — байты id строки api_token: сессионных эндпоинтов MCP не открывает.
    return Actor(
        user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        login=principal.login,
        role=principal.role,
        must_change_password=False,
        session_id=principal.token_id.bytes,
    )


def _error_result(exc: AppError) -> types.CallToolResult:
    payload = json.dumps({"detail": exc.detail, "code": exc.code}, ensure_ascii=False)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=payload)], isError=True
    )


async def _list_tools() -> list[types.Tool]:
    request = current_request()
    if request is None or _gate(request.principal) is not None:
        return []
    return [
        types.Tool(name=spec.name, description=spec.description, inputSchema=spec.input_schema)
        for spec in request.registry.visible_for(request.principal.role)
    ]


async def _call_tool(name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
    request = current_request()
    if request is None:
        return _error_result(NotAuthenticated())
    gated = _gate(request.principal)
    if gated is not None:
        return _error_result(gated)
    spec = request.registry.get(name)
    if spec is None:
        return _error_result(NotFound("Инструмент не найден", code="not_found"))
    if not request.registry.allowed(request.principal.role, spec):
        return _error_result(Forbidden())
    try:
        async with transaction(request.sessionmaker) as db:
            with client_name_scope(request.principal.name):
                payload = await spec.handler(db, _actor(request.principal), arguments or {})
    except AppError as exc:
        return _error_result(exc)
    except ValidationError:
        return _error_result(
            Unprocessable("Некорректные аргументы инструмента", code="validation_error")
        )
    except Exception as exc:  # непредвиденное: только тип в журнал, без значений и трассировки
        logger.error("mcp tool %s failed: %s", name, type(exc).__name__)
        return _error_result(AppError("Внутренняя ошибка", code="internal_error"))
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text", text=json.dumps(payload, ensure_ascii=False, default=str)
            )
        ],
        isError=False,
    )


def build_session_manager() -> StreamableHTTPSessionManager:
    server = Server(SERVER_NAME)
    server.list_tools()(_list_tools)  # type: ignore[no-untyped-call]  # декоратор SDK без типов
    server.call_tool()(_call_tool)
    return StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)


class McpRuntime:
    """Держит ``StreamableHTTPSessionManager`` запущенным на время жизни приложения.

    Группа задач SDK входит и выходит в одной задаче: ``run()`` открыт в фоновой задаче, которую
    ждёт вход в контекст и которую останавливает выход. Так не возникает ошибки «cancel scope
    вошёл в одной задаче, а вышел в другой», когда жизненный цикл ведёт внешний код.
    """

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._sessions = session_manager
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def _serve(self, started: asyncio.Event) -> None:
        async with self._sessions.run():
            started.set()
            await self._stop.wait()

    async def __aenter__(self) -> McpRuntime:
        started = asyncio.Event()
        self._task = asyncio.create_task(self._serve(started))
        ready = asyncio.create_task(started.wait())
        await asyncio.wait({ready, self._task}, return_when=asyncio.FIRST_COMPLETED)
        ready.cancel()
        if self._task.done():
            self._task.result()  # ошибка запуска поднимается сразу
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
