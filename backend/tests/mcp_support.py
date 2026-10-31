"""Тестовый MCP-клиент для инструментов агента (007: NFR-4; plan §5, R7-T18).

Не тест-модуль. ``BridgeTransport`` реализует ``app.agent_mcp.Transport``: запрос уходит в
ASGI-приложение теста (``env.client`` поверх ``httpx.ASGITransport``) через
``asyncio.run_coroutine_threadsafe`` на цикле теста; ``McpServer`` вызывается из
``asyncio.to_thread``, поэтому цикл свободен и обслуживает запрос. Каждый запрос пишется в
журнал (метод, путь, query, тело, статус ответа). ``McpTestClient`` шлёт ``initialize``,
``notifications/initialized``, ``tools/list`` и ``tools/call`` как JSON-RPC-сообщения в
``McpServer.handle``.

Секрет ключа хранится только в закрытом атрибуте транспорта и не попадает в ``repr``,
журнал и сообщения ``assert``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.agent_mcp import ApiResponse, McpServer, TransportError

if TYPE_CHECKING:
    from tests.conftest import ApiEnv

PROTOCOL_VERSION = "2025-06-18"


def leaks(secret: str, text: str) -> bool:
    """Секрет или любая его подстрока длиной от 8 символов есть в ``text`` (AC-38, AC-45).

    Возвращает булево: значение секрета в сообщения ``assert`` не попадает."""
    if not secret:
        return False
    return secret in text or any(secret[i : i + 8] in text for i in range(len(secret) - 7))


@dataclass(frozen=True)
class BridgeCall:
    """Запись журнала ``BridgeTransport``: что инструмент отправил в API и что получил."""

    method: str
    path: str
    query: dict[str, str] | None
    body: dict[str, Any] | None
    status: int


class BridgeTransport:
    """``Transport`` (plan §4.9) поверх ASGI-приложения теста; ``secret=None`` — без заголовка
    ``Authorization`` (проверка 401 со стороны API)."""

    def __init__(self, env: ApiEnv, loop: asyncio.AbstractEventLoop, secret: str | None) -> None:
        self._env = env
        self._loop = loop
        self.__secret = secret
        self.journal: list[BridgeCall] = []

    def __repr__(self) -> str:
        return f"BridgeTransport(calls={len(self.journal)})"

    async def _send(
        self,
        method: str,
        path: str,
        query: Mapping[str, str] | None,
        body: Mapping[str, object] | None,
    ) -> Any:
        headers: dict[str, str] = {}
        if self.__secret is not None:
            headers["Authorization"] = "Bearer " + self.__secret
        kwargs: dict[str, Any] = {"headers": headers}
        if query is not None:
            kwargs["params"] = dict(query)
        if body is not None:
            kwargs["json"] = dict(body)
        return await self._env.client.request(method, path, **kwargs)

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> ApiResponse:
        future = asyncio.run_coroutine_threadsafe(self._send(method, path, query, body), self._loop)
        response = future.result(timeout=60)
        self.journal.append(
            BridgeCall(
                method=method,
                path=path,
                query=dict(query) if query is not None else None,
                body=dict(body) if body is not None else None,
                status=response.status_code,
            )
        )
        parsed: object = None
        if response.content.strip():
            try:
                parsed = response.json()
            except ValueError:
                if response.status_code < 400:
                    raise TransportError("invalid_response", "Ответ API не является JSON") from None
                parsed = None
        raw_retry = response.headers.get("retry-after")
        retry_after = int(raw_retry) if raw_retry and raw_retry.strip().isdigit() else None
        return ApiResponse(response.status_code, parsed, retry_after)

    def calls(self) -> list[tuple[str, str]]:
        """Журнал как пары (метод, путь)."""
        return [(c.method, c.path) for c in self.journal]


class McpTestClient:
    """Клиент MCP поверх ``McpServer.handle`` (JSON-RPC 2.0). Все ответы сервера копятся в
    ``responses`` — для проверок «ни один результат не содержит ключа» (AC-45)."""

    def __init__(self, server: McpServer) -> None:
        self.server = server
        self.responses: list[dict[str, Any]] = []
        self._next_id = 0

    async def _handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        # Сообщение проходит через JSON, как по stdio: сервер получает только JSON-типы.
        wire = json.loads(json.dumps(message, ensure_ascii=False))
        response = await asyncio.to_thread(self.server.handle, wire)
        if response is not None:
            response = json.loads(json.dumps(response, ensure_ascii=False))
            self.responses.append(response)
        return response

    async def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        response = await self._handle(message)
        assert response is not None, f"нет ответа на {method}"
        assert response.get("id") == self._next_id, f"чужой id в ответе на {method}"
        return response

    async def notify(self, method: str) -> None:
        response = await self._handle({"jsonrpc": "2.0", "method": method})
        assert response is None, f"ответ на уведомление {method}"

    async def initialize(self) -> dict[str, Any]:
        response = await self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-test-client", "version": "0"},
            },
        )
        assert "result" in response, f"initialize: {response.get('error')}"
        await self.notify("notifications/initialized")
        return dict(response["result"])

    async def list_tools(self) -> list[dict[str, Any]]:
        response = await self.rpc("tools/list")
        assert "result" in response, f"tools/list: {response.get('error')}"
        return list(response["result"]["tools"])

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """``CallToolResult`` инструмента; ошибка JSON-RPC (например, -32602 «неизвестный
        инструмент») — провал теста с кодом ошибки."""
        params: dict[str, Any] = {"name": name, "arguments": arguments or {}}
        response = await self.rpc("tools/call", params)
        error = response.get("error")
        assert "result" in response, f"tools/call {name}: ошибка JSON-RPC {error}"
        return dict(response["result"])

    def transcript(self) -> str:
        """Все ответы сервера одной строкой (для проверок утечек)."""
        return json.dumps(self.responses, ensure_ascii=False)


async def connect(env: ApiEnv, secret: str | None) -> tuple[McpTestClient, BridgeTransport]:
    """Клиент, подключённый к инструментам агента (``TOOLS``) с ключом ``secret``; после
    ``initialize``. Вызывать из async-теста (нужен текущий цикл)."""
    transport = BridgeTransport(env, asyncio.get_running_loop(), secret)
    client = McpTestClient(McpServer(transport))
    await client.initialize()
    return client, transport


async def connect_without_key() -> McpTestClient:
    """Подключение без ключа: ``McpServer(None)`` (FR-38, PD-15)."""
    client = McpTestClient(McpServer(None))
    await client.initialize()
    return client


def error_of(result: dict[str, Any]) -> dict[str, Any]:
    """``structuredContent.error`` результата-ошибки (plan §4.9)."""
    assert result.get("isError") is True, "ожидался результат-ошибка"
    structured = result.get("structuredContent")
    assert isinstance(structured, dict) and isinstance(structured.get("error"), dict)
    return dict(structured["error"])


def ok_body(result: dict[str, Any]) -> Any:
    """``structuredContent`` успешного результата; при ошибке — провал с кодом и статусом."""
    if result.get("isError") is not False:
        err = (result.get("structuredContent") or {}).get("error") or {}
        raise AssertionError(f"инструмент вернул ошибку: {err.get('status')} {err.get('code')}")
    return result.get("structuredContent")
