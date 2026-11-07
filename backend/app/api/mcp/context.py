"""Контекст одного MCP-запроса: субъект по токену, реестр инструментов, фабрика сессий (PN-3).

Выставляется ASGI-адаптером ``endpoint`` до передачи запроса в протокольный слой и
сбрасывается после. Инструменты читают его через ``current_request``. Значения не пишутся в логи.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.mcp.registry import ToolRegistry
from app.domain.tokens.service import ResolvedToken


@dataclass(frozen=True)
class McpRequest:
    principal: ResolvedToken
    registry: ToolRegistry
    sessionmaker: async_sessionmaker[AsyncSession]


_request: ContextVar[McpRequest | None] = ContextVar("gtrack_mcp_request", default=None)


def set_request(request: McpRequest) -> Token[McpRequest | None]:
    return _request.set(request)


def reset_request(token: Token[McpRequest | None]) -> None:
    _request.reset(token)


def current_request() -> McpRequest | None:
    return _request.get()
