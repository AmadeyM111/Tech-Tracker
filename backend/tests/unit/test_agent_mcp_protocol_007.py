"""R7-T17: протокол MCP (007: FR-35, FR-37, FR-38; plan §4.9, PD-12, PD-14, PD-15).

``McpServer`` проверяется с поддельным ``Transport`` и тестовым ``ToolSpec``; БД и сеть не нужны.
Ключ в тестах собирается из байтов в рантайме и не печатается.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

import pytest

from app import agent_mcp
from app.agent_mcp import ApiResponse, McpServer, ToolSpec, TransportError

TASK_ID = "11111111-2222-4333-8444-555555555555"
KEY = "gtk_" + base64.urlsafe_b64encode(bytes(range(7, 39))).decode("ascii").rstrip("=")


class FakeTransport:
    """Поддельный транспорт: журнал вызовов и очередь ответов/исключений."""

    def __init__(self, *responses: ApiResponse | Exception) -> None:
        self.calls: list[
            tuple[str, str, Mapping[str, str] | None, Mapping[str, object] | None]
        ] = []
        self._queue = list(responses)

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> ApiResponse:
        self.calls.append((method, path, query, body))
        item = self._queue.pop(0) if self._queue else ApiResponse(200, {"ok": True}, None)
        if isinstance(item, Exception):
            raise item
        return item


GET_TOOL = ToolSpec(
    name="get_thing",
    description="Получить вещь",
    input_schema={
        "type": "object",
        "properties": {"task_id": {"type": "string"}, "page": {"type": "integer"}},
        "required": ["task_id"],
        "additionalProperties": False,
    },
    method="GET",
    path="/api/v1/tasks/{task_id}",
    path_params=("task_id",),
    query_params=("page",),
)
POST_TOOL = ToolSpec(
    name="make_thing",
    description="Создать вещь",
    input_schema={
        "type": "object",
        "properties": {"task_id": {"type": "string"}, "title": {"type": "string"}},
        "required": ["task_id", "title"],
        "additionalProperties": False,
    },
    method="POST",
    path="/api/v1/tasks/{task_id}/things",
    path_params=("task_id",),
    body_params=("title",),
)


def _server(transport: Any, **kw: Any) -> McpServer:
    return McpServer(transport, tools=(GET_TOOL, POST_TOOL), **kw)


def _rpc(method: str, params: object = None, id_: object = 1) -> dict[str, object]:
    msg: dict[str, object] = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _call(server: McpServer, name: str, arguments: object) -> dict[str, Any]:
    resp = server.handle(_rpc("tools/call", {"name": name, "arguments": arguments}))
    assert resp is not None and "result" in resp
    result = resp["result"]
    assert isinstance(result, dict)
    return result


def _error(result: dict[str, Any]) -> dict[str, Any]:
    assert result["isError"] is True
    err = result["structuredContent"]["error"]
    assert isinstance(err, dict)
    return err


def test_module_constants() -> None:
    """plan §4.9: версии протокола, имена переменных окружения, имена окружения."""
    assert agent_mcp.PROTOCOL_VERSIONS == ("2025-06-18", "2025-03-26", "2024-11-05")
    assert agent_mcp.SERVER_INFO["name"] == "gostracker"
    assert agent_mcp.ENV_URL == "GOSTRACKER_URL"
    assert agent_mcp.ENV_KEY == "GOSTRACKER_API_KEY"
    assert agent_mcp.ENV_CA == "GOSTRACKER_CA_FILE"


@pytest.mark.parametrize("version", ["2025-06-18", "2025-03-26", "2024-11-05"])
def test_initialize_echoes_supported_version(version: str) -> None:
    """FR-35/PD-12: поддержанная версия возвращается как есть; capabilities.tools есть."""
    resp = _server(FakeTransport()).handle(
        _rpc("initialize", {"protocolVersion": version, "capabilities": {}, "clientInfo": {}}, 7)
    )
    assert resp is not None
    assert resp["jsonrpc"] == "2.0" and resp["id"] == 7 and "error" not in resp
    result = resp["result"]
    assert isinstance(result, dict)
    assert result["protocolVersion"] == version
    assert isinstance(result["capabilities"], dict) and "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "gostracker"


@pytest.mark.parametrize("params", [{"protocolVersion": "1999-01-01"}, {}, None])
def test_initialize_unknown_version_falls_back_to_latest(params: object) -> None:
    """PD-12: иная версия -> 2025-06-18."""
    resp = _server(FakeTransport()).handle(_rpc("initialize", params))
    assert resp is not None
    assert resp["result"]["protocolVersion"] == "2025-06-18"  # type: ignore[index]


def test_ping_returns_empty_object() -> None:
    resp = _server(FakeTransport()).handle(_rpc("ping", None, "p-1"))
    assert resp == {"jsonrpc": "2.0", "id": "p-1", "result": {}}


@pytest.mark.parametrize(
    "message",
    [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}},
    ],
)
def test_notification_has_no_response(message: dict[str, object]) -> None:
    """PD-12: уведомления (без id) -> None."""
    transport = FakeTransport()
    assert _server(transport).handle(message) is None
    assert transport.calls == []


def test_unknown_method_is_minus_32601() -> None:
    resp = _server(FakeTransport()).handle(_rpc("resources/list", None, 5))
    assert resp is not None and resp["id"] == 5
    assert resp["error"]["code"] == -32601  # type: ignore[index]
    assert "result" not in resp


def test_batch_array_is_minus_32600() -> None:
    """PD-12: массив (batch) -> -32600."""
    resp = _server(FakeTransport()).handle([_rpc("ping")])
    assert resp is not None and resp["error"]["code"] == -32600  # type: ignore[index]
    assert resp["id"] is None


@pytest.mark.parametrize("message", ["text", 42, None, {"jsonrpc": "2.0", "id": 1}])
def test_invalid_request_is_minus_32600(message: object) -> None:
    resp = _server(FakeTransport()).handle(message)
    assert resp is not None and resp["error"]["code"] == -32600  # type: ignore[index]


def test_tools_list_returns_registered_tools() -> None:
    """FR-35: tools/list -> name, description, inputSchema; без ключа тоже."""
    for transport in (FakeTransport(), None):
        resp = McpServer(transport, tools=(GET_TOOL, POST_TOOL)).handle(_rpc("tools/list"))
        assert resp is not None
        tools = resp["result"]["tools"]  # type: ignore[index]
        assert [t["name"] for t in tools] == ["get_thing", "make_thing"]
        assert tools[0]["description"] == "Получить вещь"
        assert tools[0]["inputSchema"] == dict(GET_TOOL.input_schema)


def test_tools_list_works_with_config_error() -> None:
    resp = McpServer(None, config_error="bad url", tools=(GET_TOOL,)).handle(_rpc("tools/list"))
    assert resp is not None and len(resp["result"]["tools"]) == 1  # type: ignore[index]


def test_default_tools_registry_is_a_tuple() -> None:
    """В R7-T17 TOOLS = (); в R7-T18 станет 11. Здесь важно лишь, что это кортеж ToolSpec."""
    assert isinstance(agent_mcp.TOOLS, tuple)
    assert all(isinstance(t, ToolSpec) for t in agent_mcp.TOOLS)


def test_unknown_tool_is_minus_32602() -> None:
    transport = FakeTransport()
    resp = _server(transport).handle(_rpc("tools/call", {"name": "nope", "arguments": {}}, 9))
    assert resp is not None and resp["id"] == 9
    assert resp["error"]["code"] == -32602  # type: ignore[index]
    assert transport.calls == []


def test_tools_call_success_shape_and_request() -> None:
    """plan §4.9: успех -> content[text=JSON тела], structuredContent=тело, isError false."""
    body = {"id": TASK_ID, "title": "T"}
    transport = FakeTransport(ApiResponse(200, body, None))
    result = _call(_server(transport), "get_thing", {"task_id": TASK_ID, "page": 2})
    assert result["isError"] is False
    assert result["structuredContent"] == body
    assert result["content"][0]["type"] == "text"
    assert json.loads(result["content"][0]["text"]) == body
    assert len(transport.calls) == 1
    method, path, query, body = transport.calls[0]
    assert (method, path) == ("GET", f"/api/v1/tasks/{TASK_ID}")
    assert dict(query or {}) == {"page": "2"}
    assert not body


def test_tools_call_post_sends_body_without_path_params() -> None:
    transport = FakeTransport(ApiResponse(201, {"id": "x"}, None))
    result = _call(_server(transport), "make_thing", {"task_id": TASK_ID, "title": "Привет"})
    assert result["isError"] is False
    method, path, query, body = transport.calls[0]
    assert (method, path) == ("POST", f"/api/v1/tasks/{TASK_ID}/things")
    assert not query
    assert dict(body or {}) == {"title": "Привет"}


def test_api_422_becomes_error_result() -> None:
    """FR-37, AC-44: 422 -> isError, status, code, detail; без трассировки."""
    detail = [{"loc": ["body", "description"], "msg": "required", "type": "missing"}]
    transport = FakeTransport(
        ApiResponse(422, {"detail": detail, "code": "validation_error"}, None)
    )
    result = _call(_server(transport), "make_thing", {"task_id": TASK_ID, "title": "x"})
    err = _error(result)
    assert err["status"] == 422 and err["code"] == "validation_error"
    assert err["detail"] == detail
    assert err["retry_after_seconds"] is None
    text = json.dumps(result, ensure_ascii=False)
    assert "Traceback" not in text and 'File "' not in text


@pytest.mark.parametrize(
    ("status", "code", "retry"),
    [(429, "too_many_requests", 17), (503, "service_unavailable", 5)],
)
def test_429_and_503_carry_retry_after(status: int, code: str, retry: int) -> None:
    """FR-37: 429 и 503 -> retry_after_seconds из Retry-After."""
    transport = FakeTransport(ApiResponse(status, {"detail": "slow down", "code": code}, retry))
    err = _error(_call(_server(transport), "get_thing", {"task_id": TASK_ID}))
    assert err["status"] == status and err["code"] == code
    assert err["retry_after_seconds"] == retry
    assert err["detail"] == "slow down"


def test_transport_exception_is_error_result_and_next_call_works() -> None:
    """FR-37: исключение транспорта -> результат-ошибка без трассировки; соединение живо."""
    secret_text = "boom-internal-text"
    transport = FakeTransport(
        TransportError("connection_error", "Сервер недоступен"),
        RuntimeError(secret_text),
        ApiResponse(200, {"ok": 1}, None),
    )
    server = _server(transport)
    err = _error(_call(server, "get_thing", {"task_id": TASK_ID}))
    assert err["status"] is None and err["code"] == "connection_error"
    assert err["detail"] == "Сервер недоступен"
    # неожиданное исключение: результат-ошибка или -32603, но без его текста
    resp = server.handle(
        _rpc("tools/call", {"name": "get_thing", "arguments": {"task_id": TASK_ID}})
    )
    assert resp is not None
    assert secret_text not in json.dumps(resp, ensure_ascii=False)
    assert "Traceback" not in json.dumps(resp, ensure_ascii=False)
    ok = _call(server, "get_thing", {"task_id": TASK_ID})
    assert ok["isError"] is False and ok["structuredContent"] == {"ok": 1}


@pytest.mark.parametrize("code", ["redirect_not_allowed", "invalid_response"])
def test_transport_error_codes_are_passed_through(code: str) -> None:
    transport = FakeTransport(TransportError(code, "d"))
    err = _error(_call(_server(transport), "get_thing", {"task_id": TASK_ID}))
    assert err["code"] == code and err["status"] is None


def test_no_key_returns_401_without_transport() -> None:
    """FR-38/PD-15: transport=None -> 401 not_authenticated, сети нет."""
    server = McpServer(None, tools=(GET_TOOL,))
    err = _error(_call(server, "get_thing", {"task_id": TASK_ID}))
    assert err["status"] == 401 and err["code"] == "not_authenticated"
    assert isinstance(err["detail"], str) and err["detail"]


def test_config_error_returns_config_error_without_transport() -> None:
    """PD-15: неверный URL -> config_error, status null; ключ не в тексте."""
    server = McpServer(None, config_error="Неверный GOSTRACKER_URL", tools=(GET_TOOL,))
    result = _call(server, "get_thing", {"task_id": TASK_ID})
    err = _error(result)
    assert err["code"] == "config_error" and err["status"] is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"task_id": TASK_ID, "unknown": 1},
        {"task_id": "../admin/users"},
        {"task_id": "not-a-uuid"},
        {"title": "x"},
        {},
        ["task_id"],
        "text",
    ],
)
def test_invalid_arguments_do_not_reach_transport(arguments: object) -> None:
    """PD-14: неизвестный аргумент, не-UUID, не-объект -> invalid_arguments."""
    transport = FakeTransport()
    err = _error(_call(_server(transport), "get_thing", arguments))
    assert err["code"] == "invalid_arguments" and err["status"] is None
    assert transport.calls == []


def test_missing_arguments_treated_as_empty_object() -> None:
    """Без поля arguments обязательный параметр пути отсутствует -> invalid_arguments."""
    transport = FakeTransport()
    resp = _server(transport).handle(_rpc("tools/call", {"name": "get_thing"}))
    assert resp is not None
    err = _error(resp["result"])  # type: ignore[arg-type]
    assert err["code"] == "invalid_arguments" and transport.calls == []


def test_body_validation_is_left_to_api() -> None:
    """PD-14: обязательность тела локально не проверяется - запрос уходит в API."""
    transport = FakeTransport(ApiResponse(422, {"detail": "x", "code": "validation_error"}, None))
    err = _error(_call(_server(transport), "make_thing", {"task_id": TASK_ID}))
    assert err["code"] == "validation_error"
    assert len(transport.calls) == 1


def test_key_never_appears_in_results() -> None:
    """FR-38: ключ в ответах сервера не появляется (булево до assert, значение не печатается)."""
    server = McpServer(None, config_error=None, tools=(GET_TOOL,))
    outputs = [
        server.handle(_rpc("initialize", {"protocolVersion": "2025-06-18"})),
        server.handle(_rpc("tools/list")),
        _call(server, "get_thing", {"task_id": TASK_ID}),
        _call(server, "get_thing", {"task_id": "bad"}),
    ]
    text = json.dumps(outputs, ensure_ascii=False)
    leaked = KEY in text or any(KEY[i : i + 8] in text for i in range(len(KEY) - 7))
    assert not leaked, "секрет в ответах сервера"


def test_malformed_call_params_give_json_rpc_error() -> None:
    """Некорректные params у tools/call -> ошибка JSON-RPC (-32602 или -32600), сервер не падает."""
    server = _server(FakeTransport())
    for params in ([], "x", 1, {"name": 5}, {"name": None}):
        resp = server.handle(_rpc("tools/call", params))
        assert resp is not None and "error" in resp
        assert resp["error"]["code"] in (-32602, -32600)  # type: ignore[index]
