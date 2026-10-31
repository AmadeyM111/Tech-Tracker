"""R7-T18: 11 инструментов агента MCP и сквозные проверки (007: AC-42…AC-45, AC-38 — результаты и
логи инструментов; FR-35…FR-38; plan §4.9, PD-13, PD-14, PD-15).

Клиент — ``tests.mcp_support`` (``McpTestClient`` поверх ``McpServer`` и ``BridgeTransport`` к
ASGI-приложению теста), мир — ``make_world007``. Плюс регрессионные проверки по ревью R7-T17
(``reviews/R7-T17-1.md``): ключ недопустимого формата, длинный ``Retry-After``, системные прокси,
``GOSTRACKER_CA_FILE``, обходы проверки URL, stdio с недоступным API.

Секрет ключа в сообщения ``assert`` не попадает: проверки утечек дают булево до ``assert``.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import ssl
import subprocess
import sys
import threading
import tomllib
import uuid
from collections.abc import Iterator
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from app import agent_mcp
from app.agent_mcp import ApiResponse, McpServer, ToolSpec, UrllibTransport, build_server
from tests.agents007_support import (
    CLOCK,
    World007,
    domain_events,
    hide,
    make_key,
    make_world007,
    mutated_secret,
    project_task_count,
)
from tests.conftest import ApiEnv
from tests.db_support import BACKEND_DIR
from tests.mcp_support import (
    connect,
    connect_without_key,
    error_of,
    leaks,
    ok_body,
)

API = "/api/v1"
MODULE = Path(BACKEND_DIR) / "app" / "agent_mcp.py"
PYPROJECT = Path(BACKEND_DIR) / "pyproject.toml"

# plan §4.9, PD-13: ровно 11 инструментов, порядок таблицы
TOOL_NAMES = [
    "whoami",
    "list_projects",
    "list_my_tasks",
    "list_project_tasks",
    "get_task",
    "create_task",
    "create_subtask",
    "set_task_status",
    "update_task",
    "list_comments",
    "add_comment",
]

# plan §4.9: параметры (свойства схемы) и обязательные параметры
TOOL_PARAMS: dict[str, tuple[set[str], set[str]]] = {
    "whoami": (set(), set()),
    "list_projects": ({"page", "page_size"}, set()),
    "list_my_tasks": ({"page", "page_size"}, set()),
    "list_project_tasks": (
        {"project_id", "status", "assignee_id", "page", "page_size"},
        {"project_id"},
    ),
    "get_task": ({"task_id"}, {"task_id"}),
    "create_task": (
        {"project_id", "title", "description", "due_date", "priority", "assignee_id"},
        {"project_id", "title", "description", "due_date"},
    ),
    "create_subtask": (
        {"task_id", "title", "description", "due_date", "priority", "assignee_id"},
        {"task_id", "title"},
    ),
    "set_task_status": ({"task_id", "status"}, {"task_id", "status"}),
    "update_task": (
        {"task_id", "title", "description", "due_date", "priority", "assignee_id"},
        {"task_id"},
    ),
    "list_comments": ({"task_id", "page", "page_size"}, {"task_id"}),
    "add_comment": ({"task_id", "body"}, {"task_id", "body"}),
}

STATUSES = ["todo", "in_progress", "review", "done"]
PRIORITIES = ["low", "medium", "high"]
KEY_LIKE = ("key", "token", "secret", "auth", "bearer", "password", "ключ", "парол")

# Ключ для проверок без БД: собирается из байтов в рантайме, не печатается.
LOCAL_KEY = "gtk_" + base64.urlsafe_b64encode(bytes(range(130, 162))).decode("ascii").rstrip("=")


# --- помощники ---------------------------------------------------------------------------------


def _tools_without_key() -> list[dict[str, Any]]:
    """``tools/list`` у сервера без ключа (PD-15: список работает всегда)."""
    resp = McpServer(None).handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp is not None and "result" in resp
    return list(resp["result"]["tools"])


def _by_name(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {t["name"]: t for t in tools}


def _tool(name: str) -> dict[str, Any]:
    tools = _by_name(_tools_without_key())
    assert name in tools, f"нет инструмента {name}"
    return tools[name]


def _branches(prop: dict[str, Any]) -> list[dict[str, Any]]:
    """Сама схема свойства и ветки ``anyOf``/``oneOf`` (для полей «значение или null»)."""
    out = [prop]
    for key in ("anyOf", "oneOf"):
        for sub in prop.get(key) or []:
            if isinstance(sub, dict):
                out.append(sub)
    return out


def _enum_of(prop: dict[str, Any]) -> list[Any]:
    for branch in _branches(prop):
        if "enum" in branch:
            return [v for v in branch["enum"] if v is not None]
    raise AssertionError("у свойства нет перечисления")


def _has_type(prop: dict[str, Any]) -> bool:
    return any("type" in b or "enum" in b for b in _branches(prop))


def _texts(*parts: Any) -> str:
    return json.dumps(parts, ensure_ascii=False, default=str)


def _no_trace(result: dict[str, Any]) -> bool:
    text = _texts(result)
    return "Traceback" not in text and 'File "' not in text and "Exception" not in text


async def _ba1_get(env: ApiEnv, w: World007, url: str) -> Any:
    r = await env.client.get(url, headers=env.auth(w.cookie("ba1")))
    assert r.status_code == 200, (url, r.status_code)
    return r.json()


async def _event_count(env: ApiEnv, w: World007) -> int:
    return len(await domain_events(env, w.ws.id))


def _create_args(w: World007, **extra: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "project_id": str(w.P),
        "title": "Отчёт",
        "description": "Собрать метрики",
        "due_date": "2026-11-10",
    }
    args.update(extra)
    return args


# --- локальный HTTP-сервер (без БД): запись запросов ----------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.reply: tuple[int, dict[str, str], bytes] = (200, {}, b"{}")


def _start_http(rec: _Recorder) -> tuple[HTTPServer, threading.Thread]:
    class Handler(BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            rec.requests.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": raw,
                }
            )
            status, headers, payload = rec.reply
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PATCH = do_DELETE = do_CONNECT = _handle  # noqa: N815

        def log_message(self, *args: object) -> None:
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


@pytest.fixture
def http_server() -> Iterator[tuple[str, _Recorder]]:
    rec = _Recorder()
    httpd, thread = _start_http(rec)
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", rec
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture
def proxy_server() -> Iterator[tuple[str, _Recorder]]:
    rec = _Recorder()
    httpd, thread = _start_http(rec)
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", rec
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _call(server: McpServer, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )
    assert resp is not None
    return resp


# =============================================================================================
# AC-42 (FR-35, FR-36): набор и описания инструментов
# =============================================================================================


def test_007_ac42_exactly_eleven_tools_in_plan_order() -> None:
    """AC-42, PD-13: ровно 11 инструментов, имена и порядок — таблица plan §4.9."""
    names = [t["name"] for t in _tools_without_key()]
    assert names == TOOL_NAMES


async def test_007_ac42_tools_list_with_k_u_is_the_same(api_env: ApiEnv) -> None:
    """AC-42: клиент с K_u получает тот же список из 11 инструментов (PD-15: список не зависит
    от ключа)."""
    env = api_env
    w = await make_world007(env)
    client, transport = await connect(env, w.K_u.secret)
    tools = await client.list_tools()
    assert [t["name"] for t in tools] == TOOL_NAMES
    assert tools == _tools_without_key()
    assert transport.journal == [], "tools/list не должен обращаться к API"


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_007_ac42_schema_shape_and_params(name: str) -> None:
    """AC-42, FR-36: описание на русском; inputSchema — object, properties, required,
    additionalProperties: false; параметры и обязательные — по plan §4.9; у каждого — тип."""
    tool = _tool(name)
    description = tool.get("description")
    assert isinstance(description, str) and description.strip()
    assert any("а" <= ch.lower() <= "я" for ch in description), "описание не на русском"
    schema = tool.get("inputSchema")
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    assert isinstance(schema.get("properties"), dict)
    assert isinstance(schema.get("required"), list)
    assert schema.get("additionalProperties") is False
    props, required = TOOL_PARAMS[name]
    assert set(schema["properties"]) == props
    assert set(schema["required"]) == required
    for pname, prop in schema["properties"].items():
        assert isinstance(prop, dict) and _has_type(prop), f"{name}.{pname}: нет типа"


@pytest.mark.parametrize(
    ("name", "param"), [("list_project_tasks", "status"), ("set_task_status", "status")]
)
def test_007_ac42_status_enum_exactly_spec(name: str, param: str) -> None:
    """AC-42: перечисление статусов — ровно todo, in_progress, review, done."""
    prop = _tool(name)["inputSchema"]["properties"][param]
    assert _enum_of(prop) == STATUSES


@pytest.mark.parametrize("name", ["create_task", "create_subtask", "update_task"])
def test_007_ac42_priority_enum_exactly_spec(name: str) -> None:
    """AC-42: перечисление приоритетов — ровно low, medium, high."""
    prop = _tool(name)["inputSchema"]["properties"]["priority"]
    assert _enum_of(prop) == PRIORITIES


@pytest.mark.parametrize("name", ["create_task", "create_subtask", "update_task"])
def test_007_ac42_due_date_format_date_and_yyyy_mm_dd(name: str) -> None:
    """AC-42, FR-36: у срока ``format: date`` и «YYYY-MM-DD» в описании."""
    tool = _tool(name)
    prop = tool["inputSchema"]["properties"]["due_date"]
    string_branches = [b for b in _branches(prop) if b.get("format") == "date"]
    assert string_branches, "у due_date нет format: date"
    assert string_branches[0].get("type") == "string"
    described = " ".join(str(b.get("description", "")) for b in _branches(prop))
    assert "YYYY-MM-DD" in described


def test_007_ac42_create_task_description_names_required_fields_and_moscow() -> None:
    """AC-42, FR-36: описание create_task называет название, описание, срок и правило
    «не раньше сегодня по Europe/Moscow»."""
    text = _tool("create_task")["description"]
    low = text.lower()
    for word in ("назван", "описан", "срок"):
        assert word in low, word
    assert "Europe/Moscow" in text
    assert "сегодня" in low


def test_007_ac42_set_task_status_description_done_is_closing() -> None:
    """AC-42, FR-36: описание set_task_status говорит, что закрытие — это done."""
    text = _tool("set_task_status")["description"]
    assert "done" in text
    assert "закры" in text.lower()


def test_007_ac42_update_task_has_no_status() -> None:
    """PD-13: у update_task нет параметра status (смена статуса — set_task_status)."""
    props = _tool("update_task")["inputSchema"]["properties"]
    assert "status" not in props


def test_007_ac45_no_tool_has_key_parameter() -> None:
    """AC-45, FR-38: ни у одного инструмента нет параметра для ключа."""
    tools = _tools_without_key()
    assert [t["name"] for t in tools] == TOOL_NAMES
    for tool in tools:
        for pname in tool["inputSchema"]["properties"]:
            low = pname.lower()
            assert not any(word in low for word in KEY_LIKE), f"{tool['name']}.{pname}"


def test_007_fr35_console_script_declared() -> None:
    """PD-12: ``[project.scripts] gostracker-mcp = "app.agent_mcp:main"``."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    assert scripts.get("gostracker-mcp") == "app.agent_mcp:main"


def test_007_fr35_tools_constant_is_tuple_of_toolspec() -> None:
    """plan §4.9: ``TOOLS`` — кортеж из 11 ``ToolSpec`` в порядке таблицы."""
    assert isinstance(agent_mcp.TOOLS, tuple)
    assert all(isinstance(t, ToolSpec) for t in agent_mcp.TOOLS)
    assert [t.name for t in agent_mcp.TOOLS] == TOOL_NAMES


# =============================================================================================
# FR-35: каждый инструмент — ровно своя операция (журнал BridgeTransport)
# =============================================================================================


async def test_007_fr35_each_tool_calls_exactly_its_method_and_path(api_env: ApiEnv) -> None:
    """FR-35, plan §4.9: все 11 инструментов вызваны; каждый — одним запросом к своему методу и
    пути, с параметрами в query или теле по таблице; все вызовы успешны."""
    env = api_env
    w = await make_world007(env)
    client, transport = await connect(env, w.K_u.secret)

    steps: list[tuple[str, dict[str, Any]]] = [
        ("whoami", {}),
        ("list_projects", {"page": 1, "page_size": 10}),
        ("list_my_tasks", {"page": 1, "page_size": 10}),
        (
            "list_project_tasks",
            {"project_id": str(w.P), "status": "todo", "assignee_id": str(w.u1.id)},
        ),
        ("get_task", {"task_id": str(w.T1)}),
    ]
    for name, args in steps:
        ok_body(await client.call(name, args))

    created = ok_body(await client.call("create_task", _create_args(w, priority="high")))
    new_id = created["id"]
    sub = ok_body(await client.call("create_subtask", {"task_id": str(w.T1), "title": "Шаг 1"}))
    assert sub["id"]
    ok_body(await client.call("set_task_status", {"task_id": str(w.T1), "status": "in_progress"}))
    ok_body(await client.call("update_task", {"task_id": new_id, "title": "Отчёт v2"}))
    ok_body(await client.call("list_comments", {"task_id": str(w.T1), "page": 1, "page_size": 10}))
    ok_body(await client.call("add_comment", {"task_id": str(w.T1), "body": "Готово"}))

    assert transport.calls() == [
        ("GET", f"{API}/me"),
        ("GET", f"{API}/projects"),
        ("GET", f"{API}/me/tasks"),
        ("GET", f"{API}/projects/{w.P}/tasks"),
        ("GET", f"{API}/tasks/{w.T1}"),
        ("POST", f"{API}/projects/{w.P}/tasks"),
        ("POST", f"{API}/tasks/{w.T1}/subtasks"),
        ("PATCH", f"{API}/tasks/{w.T1}"),
        ("PATCH", f"{API}/tasks/{new_id}"),
        ("GET", f"{API}/tasks/{w.T1}/comments"),
        ("POST", f"{API}/tasks/{w.T1}/comments"),
    ]
    j = transport.journal
    # чтения: тела нет; параметры — в query
    for call in (j[0], j[1], j[2], j[3], j[4], j[9]):
        assert call.body is None, call.path
    assert not j[0].query and not j[4].query
    assert j[1].query == {"page": "1", "page_size": "10"}
    assert j[2].query == {"page": "1", "page_size": "10"}
    assert j[3].query == {"status": "todo", "assignee_id": str(w.u1.id)}
    assert j[9].query == {"page": "1", "page_size": "10"}
    # записи: параметры пути не дублируются в теле; set_task_status шлёт только status
    assert j[5].body == {
        "title": "Отчёт",
        "description": "Собрать метрики",
        "due_date": "2026-11-10",
        "priority": "high",
    }
    assert j[6].body == {"title": "Шаг 1"}
    assert j[7].body == {"status": "in_progress"}
    assert j[8].body == {"title": "Отчёт v2"}
    assert j[10].body == {"body": "Готово"}
    for call in j[5:9] + [j[10]]:
        assert not call.query, call.path
    assert [c.status for c in j] == [200, 200, 200, 200, 200, 201, 201, 200, 200, 200, 201]


async def test_007_fr35_update_task_null_assignee_and_due_date_pass_through(
    api_env: ApiEnv,
) -> None:
    """plan §4.9: update_task принимает ``null`` для due_date/assignee_id и передаёт его в тело
    как есть (правила — на стороне API, PD-14): ответ API — результат-ошибка, не -32602."""
    env = api_env
    w = await make_world007(env)
    client, transport = await connect(env, w.K_u.secret)
    created = ok_body(await client.call("create_task", _create_args(w)))
    result = await client.call("update_task", {"task_id": created["id"], "due_date": None})
    assert transport.journal[-1].method == "PATCH"
    assert transport.journal[-1].body == {"due_date": None}
    err = error_of(result)
    assert err["status"] == transport.journal[-1].status
    assert 400 <= err["status"] < 500


# =============================================================================================
# AC-43 (FR-35, FR-29): сквозной сценарий через MCP
# =============================================================================================


async def test_007_ac43_five_calls_succeed_and_result_is_visible_to_ba1(api_env: ApiEnv) -> None:
    """AC-43: создать задачу в P, in_progress, review, комментарий «Результат: …», done —
    каждый вызов успешен; у ba1 задача done, автор и исполнитель agent.u, комментарий agent.u;
    события — по AC-35 (автор agent.u, идентификатор ключа K_u)."""
    env = api_env
    w = await make_world007(env)
    client, transport = await connect(env, w.K_u.secret)
    before = await _event_count(env, w)

    created = ok_body(await client.call("create_task", _create_args(w, title="Сквозная")))
    tid = created["id"]
    for status in ("in_progress", "review"):
        ok_body(await client.call("set_task_status", {"task_id": tid, "status": status}))
    comment = ok_body(
        await client.call("add_comment", {"task_id": tid, "body": "Результат: отчёт готов"})
    )
    ok_body(await client.call("set_task_status", {"task_id": tid, "status": "done"}))
    assert len(transport.journal) == 5

    card = await _ba1_get(env, w, f"{API}/tasks/{tid}")
    assert card["status"] == "done"
    assert card["author"]["id"] == str(w.agent_u.id)
    assert card["assignee"]["id"] == str(w.agent_u.id)
    comments = await _ba1_get(env, w, f"{API}/tasks/{tid}/comments")
    (item,) = [c for c in comments["items"] if c["id"] == comment["id"]]
    assert item["body"] == "Результат: отчёт готов"
    assert item["author"]["id"] == str(w.agent_u.id)

    written = (await domain_events(env, w.ws.id))[before:]
    assert [e.action for e in written] == [
        "task.created",
        "task.updated",
        "task.updated",
        "comment.created",
        "task.updated",
    ]
    assert [e.entity_id for e in written] == [
        uuid.UUID(tid),
        uuid.UUID(tid),
        uuid.UUID(tid),
        uuid.UUID(comment["id"]),
        uuid.UUID(tid),
    ]
    for e in written:
        assert e.actor_id == w.agent_u.id, e.action
        assert e.api_key_id == w.K_u.id, e.action
    assert [e.changes for e in written if e.action == "task.updated"] == [
        [{"field": "status", "old": "todo", "new": "in_progress"}],
        [{"field": "status", "old": "in_progress", "new": "review"}],
        [{"field": "status", "old": "review", "new": "done"}],
    ]
    leaked = leaks(w.K_u.secret, repr([tuple(e) for e in written]))
    assert not leaked, "секрет ключа в событиях"


# =============================================================================================
# AC-44 (FR-37): ошибки инструментов
# =============================================================================================


async def test_007_ac44_create_without_description_is_422_then_whoami_works(
    api_env: ApiEnv,
) -> None:
    """AC-44: создание без описания -> isError, 422, validation_error, detail, без трассировки;
    сразу после — whoami в том же подключении успешен (agent.u)."""
    env = api_env
    w = await make_world007(env)
    client, _transport = await connect(env, w.K_u.secret)
    tasks_before = await project_task_count(env, w.P)

    args = _create_args(w)
    del args["description"]
    result = await client.call("create_task", args)
    err = error_of(result)
    assert err["status"] == 422
    assert err["code"] == "validation_error"
    assert err["detail"], "пустой detail"
    assert isinstance(err["detail"], (str, list))
    assert _no_trace(result), "трассировка в результате"
    assert result["content"] and result["content"][0]["type"] == "text"
    assert json.loads(result["content"][0]["text"])["error"]["code"] == "validation_error"
    assert await project_task_count(env, w.P) == tasks_before

    me = ok_body(await client.call("whoami"))
    assert me["login"] == "agent.u"
    assert me["id"] == str(w.agent_u.id)
    assert me["is_agent"] is True


async def test_007_ac44_rate_limit_gives_too_many_requests_with_retry(api_env: ApiEnv) -> None:
    """AC-44, FR-33: 120 вызовов whoami в минуту успешны; 121-й — результат-ошибка 429
    too_many_requests с retry_after_seconds (часы стоят: 60); подключение живо."""
    env = api_env
    w = await make_world007(env)
    client, transport = await connect(env, w.K_u.secret)
    for i in range(120):
        result = await client.call("whoami")
        assert result.get("isError") is False, f"вызов {i + 1}"
    result = await client.call("whoami")
    err = error_of(result)
    assert err["status"] == 429
    assert err["code"] == "too_many_requests"
    assert err["retry_after_seconds"] == 60
    assert _no_trace(result)
    assert len(transport.journal) == 121

    env.clock.set(CLOCK + timedelta(seconds=60))
    assert (await client.call("whoami")).get("isError") is False


async def test_007_ac44_invalid_arguments_do_not_reach_api(api_env: ApiEnv) -> None:
    """PD-14: неизвестный параметр и не-UUID в пути -> invalid_arguments без запроса к API;
    подключение продолжает работать."""
    env = api_env
    w = await make_world007(env)
    client, transport = await connect(env, w.K_u.secret)
    bad_path = await client.call("get_task", {"task_id": "../admin/users"})
    assert error_of(bad_path)["code"] == "invalid_arguments"
    unknown = await client.call("whoami", {"api_key": "x"})
    assert error_of(unknown)["code"] == "invalid_arguments"
    status_in_update = await client.call("update_task", {"task_id": str(w.T3), "status": "done"})
    assert error_of(status_in_update)["code"] == "invalid_arguments"
    assert transport.journal == []
    ok_body(await client.call("whoami"))


# =============================================================================================
# AC-45 (FR-38): без ключа, отозванный, искажённый; утечки
# =============================================================================================


def _assert_auth_error(result: dict[str, Any]) -> None:
    err = error_of(result)
    assert err["status"] == 401, err["status"]
    assert err["code"] == "not_authenticated", err["code"]


async def test_007_ac45_without_key_create_task_is_auth_error(api_env: ApiEnv) -> None:
    """AC-45: подключение без ключа -> create_task: 401 not_authenticated, задача не создана."""
    env = api_env
    w = await make_world007(env)
    before = await project_task_count(env, w.P)
    client = await connect_without_key()
    _assert_auth_error(await client.call("create_task", _create_args(w)))
    assert await project_task_count(env, w.P) == before
    # и через конфигурацию процесса без GOSTRACKER_API_KEY
    server = build_server({"GOSTRACKER_URL": "http://127.0.0.1:9"})
    resp = _call(server, "create_task", _create_args(w))
    assert "result" in resp, resp.get("error")
    _assert_auth_error(resp["result"])


async def test_007_ac45_revoked_key_create_task_is_auth_error(api_env: ApiEnv) -> None:
    """AC-45: отозванный ключ -> 401 not_authenticated от API, задача не создана."""
    env = api_env
    w = await make_world007(env)
    revoked = hide(
        await make_key(
            env,
            w.agent_u,
            created_by=w.ta1,
            name="revoked",
            created_at=CLOCK - timedelta(days=1),
            revoked_at=CLOCK - timedelta(hours=1),
        )
    )
    before = await project_task_count(env, w.P)
    client, transport = await connect(env, revoked.secret)
    _assert_auth_error(await client.call("create_task", _create_args(w)))
    assert transport.calls() == [("POST", f"{API}/projects/{w.P}/tasks")]
    assert transport.journal[0].status == 401
    assert await project_task_count(env, w.P) == before


async def test_007_ac45_mutated_key_create_task_is_auth_error(api_env: ApiEnv) -> None:
    """AC-45: ключ с изменённым символом -> 401 not_authenticated, задача не создана."""
    env = api_env
    w = await make_world007(env)
    before = await project_task_count(env, w.P)
    client, transport = await connect(env, mutated_secret(w.K_u.secret))
    _assert_auth_error(await client.call("create_task", _create_args(w)))
    assert transport.journal[0].status == 401
    assert await project_task_count(env, w.P) == before


@pytest.mark.parametrize(
    "bad_key",
    [
        pytest.param("gtk_AAAA BBBB", id="space-inside"),
        pytest.param("gtk_AAAA\r\nX-Injected: 1", id="crlf-inside"),
        pytest.param("gtk_AAAA\tBBBB", id="tab-inside"),
        pytest.param("gtk_ключключ", id="non-ascii"),
        pytest.param("gtk_AAAA\x00BBBB", id="nul"),
    ],
)
def test_007_ac45_invalid_key_format_is_401_without_network(
    http_server: tuple[str, _Recorder], bad_key: str
) -> None:
    """Ревью R7-T17 п.1, FR-38: ключ недопустимого формата -> вызов даёт 401 not_authenticated
    (не config_error), запросов в сеть нет; tools/list работает."""
    url, rec = http_server
    server = build_server({"GOSTRACKER_URL": url, "GOSTRACKER_API_KEY": bad_key})
    listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed is not None and [t["name"] for t in listed["result"]["tools"]] == TOOL_NAMES
    resp = _call(server, "whoami")
    assert "result" in resp, resp.get("error")
    _assert_auth_error(resp["result"])
    assert rec.requests == [], "запрос ушёл в сеть"


def test_007_ac45_invalid_key_format_is_rejected_by_transport() -> None:
    """Ревью R7-T17 п.3: ключ с ``\\r\\n``/пробелом внутри не принимается транспортом (инъекция
    заголовков невозможна); текст ошибки без ключа."""
    for bad in (LOCAL_KEY[:10] + "\r\nX-Evil: 1", LOCAL_KEY[:10] + " " + LOCAL_KEY[10:]):
        with pytest.raises(ValueError) as info:
            UrllibTransport("http://127.0.0.1:9", bad)
        leaked = leaks(LOCAL_KEY, str(info.value))
        assert not leaked, "секрет в тексте ошибки"


async def test_007_ac45_ac38_key_absent_from_descriptions_schemas_results_and_logs(
    api_env: ApiEnv,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-45, AC-38: с K_u ни описание, ни схема, ни результат ни одного вызова (успехи и
    отказы 403/404/422/invalid_arguments) не содержат K_u и его подстрок >= 8; перехваченные
    логи модуля (stderr) и приложения — тоже. В stderr — имя инструмента и HTTP-статус."""
    env = api_env
    w = await make_world007(env)
    secret = w.K_u.secret
    with caplog.at_level(logging.DEBUG):
        client, _transport = await connect(env, secret)
        tools = await client.list_tools()
        assert [t["name"] for t in tools] == TOOL_NAMES
        created = ok_body(await client.call("create_task", _create_args(w)))
        calls: list[tuple[str, dict[str, Any]]] = [
            ("whoami", {}),
            ("list_projects", {}),
            ("list_my_tasks", {}),
            ("list_project_tasks", {"project_id": str(w.P)}),
            ("list_project_tasks", {"project_id": str(w.P2)}),  # 403
            ("get_task", {"task_id": str(w.T1)}),
            ("get_task", {"task_id": str(uuid.uuid4())}),  # 404
            ("create_subtask", {"task_id": created["id"], "title": "Шаг"}),
            ("set_task_status", {"task_id": created["id"], "status": "review"}),
            ("update_task", {"task_id": created["id"], "description": "   "}),  # 422
            ("list_comments", {"task_id": str(w.T1)}),
            ("add_comment", {"task_id": str(w.T1), "body": "Результат: ок"}),
            ("whoami", {"key": "x"}),  # invalid_arguments
        ]
        for name, args in calls:
            await client.call(name, args)
    captured = capsys.readouterr()
    everything = client.transcript() + _texts(tools)
    leak_results = leaks(secret, everything)
    leak_logs = leaks(secret, captured.err + captured.out + caplog.text)
    assert not leak_results, "секрет в описаниях, схемах или результатах инструментов"
    assert not leak_logs, "секрет в логах"
    assert "whoami" in captured.err and "200" in captured.err
    assert "403" in captured.err and "422" in captured.err


# =============================================================================================
# Ревью R7-T17 п.2: Retry-After из очень длинной строки
# =============================================================================================

_GET_TOOL = ToolSpec(
    name="whoami_probe",
    description="Проба",
    input_schema={
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    method="GET",
    path="/api/v1/me",
)


def test_007_fr37_huge_retry_after_is_not_an_exception(http_server: tuple[str, _Recorder]) -> None:
    """Ревью R7-T17 п.2: ``Retry-After`` из 5000 цифр (больше лимита int в 4300 цифр) ->
    транспорт возвращает ответ 429, а не исключение."""
    url, rec = http_server
    rec.reply = (
        429,
        {"Retry-After": "9" * 5000},
        b'{"detail": "later", "code": "too_many_requests"}',
    )
    resp = UrllibTransport(url, LOCAL_KEY).request("GET", "/api/v1/me")
    assert isinstance(resp, ApiResponse)
    assert resp.status == 429
    assert resp.retry_after is None or (isinstance(resp.retry_after, int) and resp.retry_after >= 0)


def test_007_fr37_huge_retry_after_gives_tool_error_not_32603(
    http_server: tuple[str, _Recorder],
) -> None:
    """Ревью R7-T17 п.2, FR-37: тот же ответ через McpServer -> результат-ошибка 429
    too_many_requests (не JSON-RPC -32603); следующий вызов работает."""
    url, rec = http_server
    rec.reply = (
        429,
        {"Retry-After": "9" * 5000},
        b'{"detail": "later", "code": "too_many_requests"}',
    )
    server = McpServer(UrllibTransport(url, LOCAL_KEY), tools=(_GET_TOOL,))
    resp = _call(server, "whoami_probe")
    assert "result" in resp, resp.get("error")
    err = error_of(resp["result"])
    assert (err["status"], err["code"]) == (429, "too_many_requests")
    rec.reply = (200, {}, b'{"login": "agent.u"}')
    again = _call(server, "whoami_probe")
    assert again["result"]["isError"] is False


# =============================================================================================
# Ревью R7-T17 п.3: прокси, GOSTRACKER_CA_FILE, обходы URL
# =============================================================================================


def test_007_nfr3_system_proxies_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
    http_server: tuple[str, _Recorder],
    proxy_server: tuple[str, _Recorder],
) -> None:
    """Ревью R7-T17 п.3, PD-15: заданные в окружении прокси (без no_proxy) не используются —
    запрос с ключом идёт прямо на GOSTRACKER_URL, прокси не получает ничего."""
    url, rec = http_server
    proxy_url, proxy_rec = proxy_server
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    for name in (
        "http_proxy",
        "HTTP_PROXY",
        "https_proxy",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ):
        monkeypatch.setenv(name, proxy_url)
    rec.reply = (200, {}, b'{"ok": true}')
    resp = UrllibTransport(url, LOCAL_KEY).request("GET", "/api/v1/me")
    assert resp.status == 200
    assert len(rec.requests) == 1
    assert proxy_rec.requests == [], "запрос ушёл через прокси"


@pytest.fixture(scope="module")
def tls_cert(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Самоподписанный сертификат для 127.0.0.1 (openssl); без openssl — пропуск."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("нет openssl")
    d = tmp_path_factory.mktemp("tls")
    cert, key = d / "tls.crt", d / "tls.key"
    proc = subprocess.run(
        [
            openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
            "-keyout", str(key), "-out", str(cert), "-subj", "/CN=127.0.0.1",
            "-addext", "subjectAltName=IP:127.0.0.1",
        ],
        capture_output=True,
        timeout=60,
        check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        pytest.skip("openssl не создал сертификат")
    return cert, key


@pytest.fixture
def https_server(tls_cert: tuple[Path, Path]) -> Iterator[tuple[str, _Recorder]]:
    rec = _Recorder()
    httpd, thread = _start_http(rec)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(tls_cert[0]), str(tls_cert[1]))
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    try:
        yield f"https://127.0.0.1:{httpd.server_address[1]}", rec
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_007_nfr3_ca_file_trusts_self_signed_and_default_verifies(
    https_server: tuple[str, _Recorder], tls_cert: tuple[Path, Path]
) -> None:
    """PD-15: с GOSTRACKER_CA_FILE самоподписанный сертификат принимается; без него и с чужим
    набором CA — connection_error (проверка сертификата включена), запрос с ключом не принят."""
    url, rec = https_server
    rec.reply = (200, {}, b'{"ok": true}')
    ok = UrllibTransport(url, LOCAL_KEY, cafile=str(tls_cert[0]), timeout=5).request(
        "GET", "/api/v1/me"
    )
    assert ok.status == 200 and len(rec.requests) == 1

    import certifi

    for cafile in (None, certifi.where()):
        with pytest.raises(agent_mcp.TransportError) as info:
            UrllibTransport(url, LOCAL_KEY, cafile=cafile, timeout=5).request("GET", "/api/v1/me")
        assert info.value.code == "connection_error"
    assert len(rec.requests) == 1, "запрос прошёл без проверки сертификата"


def _bad_ca_files(tmp_path: Path) -> list[str]:
    garbage = tmp_path / "garbage.crt"
    garbage.write_text("not a certificate", encoding="utf-8")
    empty = tmp_path / "empty.crt"
    empty.write_bytes(b"")
    return [str(tmp_path / "missing.crt"), str(tmp_path), str(garbage), str(empty)]


def test_007_nfr3_unreadable_ca_file_is_value_error_without_key(tmp_path: Path) -> None:
    """Ревью R7-T17 п.3: отсутствующий/каталог/мусор/пустой GOSTRACKER_CA_FILE -> ValueError
    транспорта без ключа в тексте (не откат к проверке без CA)."""
    for cafile in _bad_ca_files(tmp_path):
        with pytest.raises(ValueError) as info:
            UrllibTransport("https://127.0.0.1:9", LOCAL_KEY, cafile=cafile)
        leaked = leaks(LOCAL_KEY, str(info.value) + repr(info.value))
        assert not leaked, "секрет в тексте ошибки"


def test_007_nfr3_unreadable_ca_file_is_config_error(
    tmp_path: Path, http_server: tuple[str, _Recorder]
) -> None:
    """Ревью R7-T17 п.1/п.3, PD-15: нечитаемый GOSTRACKER_CA_FILE -> вызов whoami даёт
    config_error (status null), без сети и без ключа в результате."""
    for cafile in _bad_ca_files(tmp_path):
        server = build_server(
            {
                "GOSTRACKER_URL": "https://127.0.0.1:9",
                "GOSTRACKER_API_KEY": LOCAL_KEY,
                "GOSTRACKER_CA_FILE": cafile,
            }
        )
        resp = _call(server, "whoami")
        assert "result" in resp, resp.get("error")
        err = error_of(resp["result"])
        assert err["code"] == "config_error" and err["status"] is None
        leaked = leaks(LOCAL_KEY, _texts(resp))
        assert not leaked, "секрет в результате"


BYPASS_URLS = [
    "http://127.0.0.1@evil.com",
    "http://127.0.0.1:80@evil.com",
    "http://user:pass@127.0.0.1:8000",
    "http://localhost.evil.com",
    "http://localhost.evil.com:8000",
    "http://127.0.0.1.evil.com",
    "http://0.0.0.0",
    "http://0.0.0.0:8000",
    "http://[::ffff:127.0.0.1]",
    "http://[::ffff:127.0.0.1]:8000",
    "http://127.0.0.2",
    "http://2130706433",
    "http://0x7f000001",
    "http://127.1",
    "http://evil.com#@127.0.0.1",
    "http://evil.com?@127.0.0.1",
    "http://127.0.0.1:8000\\@evil.com",
    "http://ｌｏｃａｌｈｏｓｔ",
]


@pytest.mark.parametrize("bad_url", BYPASS_URLS)
def test_007_nfr3_url_bypass_attempts_are_rejected(bad_url: str) -> None:
    """Ревью R7-T17 п.3, PD-15: обходы проверки «http только для loopback» отвергаются
    транспортом (ValueError без ключа)."""
    with pytest.raises(ValueError) as info:
        UrllibTransport(bad_url, LOCAL_KEY)
    leaked = leaks(LOCAL_KEY, str(info.value))
    assert not leaked, "секрет в тексте ошибки"


@pytest.mark.parametrize("bad_url", ["http://127.0.0.1@evil.com", "http://0.0.0.0:8000"])
def test_007_nfr3_url_bypass_gives_config_error_on_call(bad_url: str) -> None:
    """PD-15: неверный URL при корректном ключе -> вызов whoami даёт config_error."""
    server = build_server({"GOSTRACKER_URL": bad_url, "GOSTRACKER_API_KEY": LOCAL_KEY})
    resp = _call(server, "whoami")
    assert "result" in resp, resp.get("error")
    assert error_of(resp["result"])["code"] == "config_error"


# =============================================================================================
# Ревью R7-T17 п.4: stdio с инструментами (подпроцесс)
# =============================================================================================


def _proc_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GOSTRACKER_")}
    env.update(extra)
    return env


def _run_stdio(messages: list[dict[str, Any]], env: dict[str, str]) -> Any:
    return subprocess.run(
        [sys.executable, "-I", str(MODULE)],
        input=b"".join(json.dumps(m).encode() + b"\n" for m in messages),
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )


def _stdout_messages(out: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in out.decode("utf-8").split("\n") if line]


def test_007_ac38_stdio_unreachable_api_is_connection_error_without_leak() -> None:
    """Ревью R7-T17 п.4, FR-37, AC-38: с ключом и недоступным API whoami -> результат-ошибка
    connection_error; процесс продолжает (ping); stdout/stderr без ключа и подстрок >= 8."""
    env = _proc_env(GOSTRACKER_URL="http://127.0.0.1:9", GOSTRACKER_API_KEY=LOCAL_KEY)
    msgs = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "whoami", "arguments": {}},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ]
    proc = _run_stdio(msgs, env)
    assert proc.returncode == 0
    first, second = _stdout_messages(proc.stdout)
    assert "result" in first, first.get("error")
    err = error_of(first["result"])
    assert err["code"] == "connection_error" and err["status"] is None
    assert second == {"jsonrpc": "2.0", "id": 2, "result": {}}
    leak_out = leaks(LOCAL_KEY, proc.stdout.decode("utf-8", "replace"))
    leak_err = leaks(LOCAL_KEY, proc.stderr.decode("utf-8", "replace"))
    assert not leak_out, "секрет в stdout"
    assert not leak_err, "секрет в stderr"
    assert "whoami" in proc.stderr.decode("utf-8", "replace")


def test_007_ac45_stdio_invalid_key_format_is_auth_error() -> None:
    """Ревью R7-T17 п.1, FR-38: ключ недопустимого формата в окружении процесса -> whoami даёт
    401 not_authenticated (не config_error); stdout/stderr без ключа."""
    bad = LOCAL_KEY[:12] + " " + LOCAL_KEY[12:]
    env = _proc_env(GOSTRACKER_URL="http://127.0.0.1:9", GOSTRACKER_API_KEY=bad)
    msgs = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "whoami", "arguments": {}},
        },
    ]
    proc = _run_stdio(msgs, env)
    assert proc.returncode == 0
    (first,) = _stdout_messages(proc.stdout)
    assert "result" in first, first.get("error")
    _assert_auth_error(first["result"])
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    leaked = leaks(LOCAL_KEY, out)
    assert not leaked, "секрет в выводе процесса"


def test_007_ac38_stdio_tools_list_has_eleven_tools() -> None:
    """FR-35: процесс по stdio без ключа отдаёт 11 инструментов."""
    proc = _run_stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}], _proc_env())
    (resp,) = _stdout_messages(proc.stdout)
    assert [t["name"] for t in resp["result"]["tools"]] == TOOL_NAMES


async def test_007_ac45_client_helper_survives_unknown_tool(api_env: ApiEnv) -> None:
    """FR-37: неизвестный инструмент -> JSON-RPC -32602; следующий вызов в том же подключении
    работает (подключение не обрывается)."""
    env = api_env
    w = await make_world007(env)
    client, _transport = await connect(env, w.K_u.secret)
    resp = await client.rpc("tools/call", {"name": "delete_task", "arguments": {}})
    assert resp["error"]["code"] == -32602
    ok_body(await client.call("whoami"))


# =============================================================================================
# Ревью R7-T18-1: обязательные параметры тела, точное тело, пробы пути, изоляция схем
# =============================================================================================


class _RecordingTransport:
    """Транспорт без сети: журнал (метод, путь, query, тело); ответ — 200 ``{}``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any, Any]] = []

    def request(
        self, method: str, path: str, *, query: Any = None, body: Any = None
    ) -> ApiResponse:
        self.calls.append((method, path, query, body))
        return ApiResponse(200, {}, None)


async def test_007_ac28_set_task_status_without_status_is_422_not_false_success(
    api_env: ApiEnv,
) -> None:
    """Ревью R7-T18-1 (блокирующее), FR-25, AC-28, FR-37: set_task_status без ``status`` ->
    тело ровно ``{"status": null}`` -> результат-ошибка 422 validation_error; статус T1 не
    изменился, новых событий нет (не «ложный успех» на ``PATCH {}``)."""
    env = api_env
    w = await make_world007(env)
    client, transport = await connect(env, w.K_u.secret)
    before_events = await _event_count(env, w)

    result = await client.call("set_task_status", {"task_id": str(w.T1)})
    assert transport.calls() == [("PATCH", f"{API}/tasks/{w.T1}")]
    assert transport.journal[0].body == {"status": None}
    err = error_of(result)
    assert (err["status"], err["code"]) == (422, "validation_error")
    assert _no_trace(result)

    card = await _ba1_get(env, w, f"{API}/tasks/{w.T1}")
    assert card["status"] == "todo"
    assert await _event_count(env, w) == before_events


async def test_007_ac44_create_task_without_description_sends_null_and_is_422(
    api_env: ApiEnv,
) -> None:
    """Ревью R7-T18-1 (блокирующее), AC-44: create_task без ``description`` -> в теле
    ``description: null`` (обязательный параметр тела), 422 validation_error, задач и
    событий не прибавилось."""
    env = api_env
    w = await make_world007(env)
    client, transport = await connect(env, w.K_u.secret)
    tasks_before = await project_task_count(env, w.P)
    events_before = await _event_count(env, w)

    args = _create_args(w)
    del args["description"]
    result = await client.call("create_task", args)
    assert transport.journal[0].body == {
        "title": "Отчёт",
        "description": None,
        "due_date": "2026-11-10",
    }
    err = error_of(result)
    assert (err["status"], err["code"]) == (422, "validation_error")
    assert await project_task_count(env, w.P) == tasks_before
    assert await _event_count(env, w) == events_before


async def test_007_fr37_add_comment_without_body_sends_null_and_is_422(api_env: ApiEnv) -> None:
    """Ревью R7-T18-1 (блокирующее), FR-27, FR-37: add_comment без ``body`` -> тело
    ``{"body": null}`` -> 422 validation_error; комментариев и событий не прибавилось."""
    from tests.agents007_support import task_comment_count

    env = api_env
    w = await make_world007(env)
    client, transport = await connect(env, w.K_u.secret)
    comments_before = await task_comment_count(env, w.T1)
    events_before = await _event_count(env, w)

    result = await client.call("add_comment", {"task_id": str(w.T1)})
    assert transport.journal[0].body == {"body": None}
    err = error_of(result)
    assert (err["status"], err["code"]) == (422, "validation_error")
    assert await task_comment_count(env, w.T1) == comments_before
    assert await _event_count(env, w) == events_before


async def test_007_fr35_create_task_body_has_no_implicit_fields(api_env: ApiEnv) -> None:
    """Ревью R7-T18-1 (желательное 2), PD-14: create_task без ``priority``/``assignee_id`` ->
    тело ровно {title, description, due_date}; значения по умолчанию ставит API (medium,
    исполнитель — сам агент)."""
    env = api_env
    w = await make_world007(env)
    client, transport = await connect(env, w.K_u.secret)
    created = ok_body(await client.call("create_task", _create_args(w)))
    assert transport.journal[0].body == {
        "title": "Отчёт",
        "description": "Собрать метрики",
        "due_date": "2026-11-10",
    }
    assert not transport.journal[0].query
    assert created["priority"] == "medium"
    assert created["assignee"]["id"] == str(w.agent_u.id)


_SOME_UUID = "11111111-2222-4333-8444-555555555555"

# инструмент -> (параметр пути, остальные допустимые аргументы)
PATH_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "list_project_tasks": ("project_id", {}),
    "get_task": ("task_id", {}),
    "create_task": (
        "project_id",
        {"title": "x", "description": "d", "due_date": "2026-11-10"},
    ),
    "create_subtask": ("task_id", {"title": "x"}),
    "set_task_status": ("task_id", {"status": "done"}),
    "update_task": ("task_id", {"title": "x"}),
    "list_comments": ("task_id", {}),
    "add_comment": ("task_id", {"body": "x"}),
}

BAD_PATH_VALUES = [
    pytest.param("../admin/users", id="dotdot-admin"),
    pytest.param("..", id="dotdot"),
    pytest.param("%2e%2e", id="pct-dotdot"),
    pytest.param(f"{_SOME_UUID}?x=1", id="uuid-query"),
    pytest.param(f"{_SOME_UUID}#f", id="uuid-fragment"),
    pytest.param(f"{_SOME_UUID}\x00", id="uuid-nul"),
    pytest.param(f"{_SOME_UUID}\\", id="uuid-backslash"),
    pytest.param("\\", id="backslash"),
    pytest.param(f"{_SOME_UUID}/../../admin", id="uuid-traversal"),
    pytest.param(f" {_SOME_UUID}", id="leading-space"),
]


@pytest.mark.parametrize("tool_name", list(PATH_TOOLS))
@pytest.mark.parametrize("bad", BAD_PATH_VALUES)
def test_007_pd14_bad_path_param_never_reaches_transport(tool_name: str, bad: str) -> None:
    """Ревью R7-T18-1 (желательное 3), PD-14: во всех инструментах с параметром пути
    недопустимое значение -> invalid_arguments (status null), транспорт не вызван; корректный
    UUID с теми же аргументами доходит ровно одним запросом."""
    param, rest = PATH_TOOLS[tool_name]
    transport = _RecordingTransport()
    server = McpServer(transport)
    resp = _call(server, tool_name, {param: bad, **rest})
    assert "result" in resp, resp.get("error")
    err = error_of(resp["result"])
    assert (err["code"], err["status"]) == ("invalid_arguments", None)
    assert transport.calls == []

    ok = _call(server, tool_name, {param: _SOME_UUID, **rest})
    assert ok["result"]["isError"] is False
    assert len(transport.calls) == 1
    assert _SOME_UUID in transport.calls[0][1]


@pytest.fixture
def _restore_tool_schemas() -> Iterator[None]:
    """Снимок схем ``TOOLS`` до теста; после — восстановление на месте (если тест их испортил,
    остальные тесты не страдают)."""
    import copy

    saved = [copy.deepcopy(dict(t.input_schema)) for t in agent_mcp.TOOLS]
    try:
        yield
    finally:
        for tool, schema in zip(agent_mcp.TOOLS, saved, strict=True):
            current = tool.input_schema
            if isinstance(current, dict) and current != schema:
                current.clear()
                current.update(copy.deepcopy(schema))


def test_007_fr38_tools_list_result_mutation_does_not_leak_into_shared_tools(
    _restore_tool_schemas: None,
) -> None:
    """Ревью R7-T18-1 (желательное 1): изменение ответа tools/list (в том же процессе, без
    JSON) не меняет глобальный TOOLS: второй McpServer отдаёт прежний список, локальная
    проверка аргументов прежняя (``api_key`` отвергается, транспорт не вызван)."""
    before = json.loads(json.dumps(_tools_without_key(), ensure_ascii=False))

    first = McpServer(None).handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert first is not None
    tools = {t["name"]: t for t in first["result"]["tools"]}
    for tool in tools.values():
        tool["description"] += " ИЗМЕНЕНО"
        tool["inputSchema"]["properties"]["api_key"] = {"type": "string"}
        tool["inputSchema"]["required"].append("api_key")
    tools["set_task_status"]["inputSchema"]["properties"]["status"]["enum"].append("closed")
    tools["create_task"]["inputSchema"]["properties"]["priority"]["enum"].clear()
    tools["get_task"]["inputSchema"]["properties"]["task_id"]["description"] = "ИЗМЕНЕНО"

    after = json.loads(json.dumps(_tools_without_key(), ensure_ascii=False))
    assert after == before, "ответ tools/list разделяет объекты со схемами TOOLS"

    transport = _RecordingTransport()
    resp = _call(McpServer(transport), "whoami", {"api_key": "x"})
    assert error_of(resp["result"])["code"] == "invalid_arguments"
    assert transport.calls == []


def test_007_pd14_only_schema_properties_are_accepted() -> None:
    """Ревью R7-T18-1 (желательное 4), PD-14: допустимые имена аргументов — только
    ``properties`` схемы; имя из ``body_params``/``query_params`` вне схемы отвергается
    (invalid_arguments) без обращения к транспорту."""
    spec = ToolSpec(
        name="probe_tool",
        description="Проба",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string"}, "title": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
        method="POST",
        path="/api/v1/tasks/{task_id}/things",
        path_params=("task_id",),
        query_params=("hidden_query",),
        body_params=("title", "hidden_body"),
    )
    transport = _RecordingTransport()
    server = McpServer(transport, tools=(spec,))
    for extra in ({"hidden_body": "x"}, {"hidden_query": "1"}):
        resp = _call(server, "probe_tool", {"task_id": _SOME_UUID, **extra})
        assert error_of(resp["result"])["code"] == "invalid_arguments", extra
    assert transport.calls == []
    ok = _call(server, "probe_tool", {"task_id": _SOME_UUID, "title": "t"})
    assert ok["result"]["isError"] is False
    assert transport.calls[0][3] == {"title": "t"}
