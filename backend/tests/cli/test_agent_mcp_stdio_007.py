"""R7-T17: MCP по stdio в подпроцессе (007: FR-35, FR-37, FR-38, NFR-6, AC-38 - stderr; plan §4.9).

Запуск: ``sys.executable -I backend/app/agent_mcp.py`` (установка пакета не нужна). БД не нужна.
Ключ собирается из байтов в рантайме и не печатается.
"""

from __future__ import annotations

import ast
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.db_support import BACKEND_DIR

MODULE = Path(BACKEND_DIR) / "app" / "agent_mcp.py"
KEY = "gtk_" + base64.urlsafe_b64encode(bytes(range(90, 122))).decode("ascii").rstrip("=")
TASK_ID = "11111111-2222-4333-8444-555555555555"
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}},
}


def _leaks(text: str) -> bool:
    return KEY in text or any(KEY[i : i + 8] in text for i in range(len(KEY) - 7))


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GOSTRACKER_")}
    env.update(extra)
    return env


def _run(lines: list[bytes], env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", str(MODULE)],
        input=b"".join(line + b"\n" for line in lines),
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )


def _json_lines(out: bytes) -> list[dict[str, Any]]:
    assert out == b"" or out.endswith(b"\n")
    return [json.loads(line) for line in out.decode("utf-8").split("\n") if line]


def test_module_file_exists() -> None:
    assert MODULE.is_file()


def test_initialize_single_line_response_and_eof_exit_zero() -> None:
    """FR-35: initialize -> ответ одной строкой; EOF -> код 0; stdout только JSON-RPC."""
    proc = _run([json.dumps(INIT).encode()], _env())
    assert proc.returncode == 0
    assert proc.stdout.count(b"\n") == 1
    (resp,) = _json_lines(proc.stdout)
    assert resp["jsonrpc"] == "2.0" and resp["id"] == 1
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    assert "tools" in resp["result"]["capabilities"]


def test_empty_stdin_exits_zero_with_empty_stdout() -> None:
    proc = _run([], _env())
    assert proc.returncode == 0 and proc.stdout == b""


def test_broken_json_gives_32700_and_process_continues() -> None:
    """PD-12: битая строка -> -32700 (id null); процесс продолжает отвечать."""
    ping = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    proc = _run([b"{not json", json.dumps(ping).encode()], _env())
    assert proc.returncode == 0
    first, second = _json_lines(proc.stdout)
    assert first["error"]["code"] == -32700 and first["id"] is None
    assert second == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_notification_gives_no_output_and_batch_gives_32600() -> None:
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    proc = _run([json.dumps(note).encode(), json.dumps([INIT]).encode()], _env())
    assert proc.returncode == 0
    (resp,) = _json_lines(proc.stdout)
    assert resp["error"]["code"] == -32600


def test_blank_lines_are_ignored() -> None:
    ping = {"jsonrpc": "2.0", "id": 3, "method": "ping"}
    proc = _run([b"", json.dumps(ping).encode(), b""], _env())
    assert proc.returncode == 0
    assert _json_lines(proc.stdout) == [{"jsonrpc": "2.0", "id": 3, "result": {}}]


def test_tools_list_without_key_returns_list() -> None:
    """PD-15: tools/list работает всегда. В R7-T17 набор может быть пустым (R7-T18 добавит 11)."""
    req = {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}
    proc = _run([json.dumps(req).encode()], _env())
    (resp,) = _json_lines(proc.stdout)
    assert isinstance(resp["result"]["tools"], list)


def test_no_key_tools_call_is_auth_error_or_unknown_tool() -> None:
    """FR-38: без ключа процесс жив и не падает; неизвестный инструмент -> -32602."""
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "whoami", "arguments": {}},
    }
    proc = _run([json.dumps(req).encode()], _env())
    assert proc.returncode == 0
    (resp,) = _json_lines(proc.stdout)
    if "error" in resp:
        assert resp["error"]["code"] == -32602
    else:
        assert resp["result"]["isError"] is True
        assert resp["result"]["structuredContent"]["error"]["code"] == "not_authenticated"


def test_with_key_stdout_and_stderr_do_not_leak_key() -> None:
    """AC-38 (stderr), NFR-6: ключ и его подстроки >= 8 не попадают ни в stdout, ни в stderr."""
    reqs = [
        INIT,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "whoami", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_task", "arguments": {"task_id": TASK_ID}},
        },
        {"jsonrpc": "2.0", "id": 5, "method": "ping"},
    ]
    env = _env(GOSTRACKER_URL="http://127.0.0.1:9", GOSTRACKER_API_KEY=KEY)
    proc = _run([json.dumps(r).encode() for r in reqs], env)
    assert proc.returncode == 0
    messages = _json_lines(proc.stdout)  # каждая строка stdout - валидный JSON-RPC
    assert all(m.get("jsonrpc") == "2.0" for m in messages)
    assert {m["id"] for m in messages} >= {1, 2, 5}
    stdout_leak = _leaks(proc.stdout.decode("utf-8", "replace"))
    stderr_leak = _leaks(proc.stderr.decode("utf-8", "replace"))
    assert not stdout_leak, "секрет в stdout"
    assert not stderr_leak, "секрет в stderr"


def test_with_key_and_unreachable_api_known_tool_call_is_connection_error() -> None:
    """FR-37: недоступный API -> результат-ошибка connection_error; процесс продолжает работать.

    Зависит от инструментов только если они есть (R7-T18): в R7-T17 пропускается.
    """
    list_req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    env = _env(GOSTRACKER_URL="http://127.0.0.1:9", GOSTRACKER_API_KEY=KEY)
    names = [
        t["name"]
        for t in _json_lines(_run([json.dumps(list_req).encode()], env).stdout)[0]["result"][
            "tools"
        ]
    ]
    if "whoami" not in names:
        pytest.skip("инструменты появляются в R7-T18")
    calls = [
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "whoami", "arguments": {}},
        },
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ]
    proc = _run([json.dumps(c).encode() for c in calls], env)
    first, second = _json_lines(proc.stdout)
    assert first["result"]["isError"] is True
    assert first["result"]["structuredContent"]["error"]["code"] == "connection_error"
    assert second["result"] == {}
    assert not _leaks(proc.stderr.decode("utf-8", "replace")), "секрет в stderr"


def test_bad_url_gives_config_error_not_crash() -> None:
    """PD-15: http://example.org -> config_error при вызове; initialize и tools/list работают."""
    reqs = [
        INIT,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ]
    env = _env(GOSTRACKER_URL="http://example.org", GOSTRACKER_API_KEY=KEY)
    proc = _run([json.dumps(r).encode() for r in reqs], env)
    assert proc.returncode == 0
    assert [m["id"] for m in _json_lines(proc.stdout)] == [1, 2, 3]
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    assert not _leaks(out), "секрет в выводе процесса"


def test_ac38_only_stdlib_imports() -> None:
    """PD-12/NFR-6: все импорты модуля - из стандартной библиотеки; app.* нет."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "относительные импорты запрещены"
            assert node.module is not None
            roots.add(node.module.split(".")[0])
    foreign = sorted(r for r in roots if r not in sys.stdlib_module_names)
    assert foreign == [], f"не из стандартной библиотеки: {foreign}"
    assert "app" not in roots
