"""Спека 032: 120 ``tools/call`` в минуту и read-only токен / OAuth ``mcp:read``."""

from __future__ import annotations

from typing import Any

from app.api.mcp.rate_limit import TokenRateLimiter
from tests.api.test_028_oauth import _auth_params, _consent, _exchange, _pkce, _register, _setup
from tests.api.test_m20_t07_mcp_core import PROTOCOL, _list_names, _rpc
from tests.api.test_m20_t08_mcp_tools import _agent_token, _call, _error_code, _payload
from tests.conftest import ApiEnv
from tests.projects_api_support import make_api_world, send

TOKENS = "/api/v1/me/tokens"
WRITE_TOOLS = frozenset(
    {"create_task", "create_subtask", "update_task", "create_project", "add_comment"}
)


async def _issue(env: ApiEnv, *, read_only: bool = False, role: str = "user") -> str:
    user = await env.new_user(role=role)
    session = await env.login_ok(user)
    created = await env.client.post(
        TOKENS, json={"name": "agent", "read_only": read_only}, headers=env.auth(session)
    )
    assert created.status_code == 201, created.text
    assert created.json()["read_only"] is read_only
    return str(created.json()["token"])


async def test_032_ac6_create_token_persists_read_only(api_env: ApiEnv) -> None:
    env = api_env
    user = await env.new_user(role="user")
    session = await env.login_ok(user)
    created = await env.client.post(
        TOKENS, json={"name": "наблюдатель", "read_only": True}, headers=env.auth(session)
    )
    assert created.status_code == 201, created.text
    assert created.json()["read_only"] is True
    listed = (await env.client.get(TOKENS, headers=env.auth(session))).json()
    assert listed[0]["read_only"] is True
    default = await env.client.post(TOKENS, json={"name": "полный"}, headers=env.auth(session))
    assert default.status_code == 201, default.text
    assert default.json()["read_only"] is False


async def test_032_ac1_tools_call_over_limit_is_429(api_env: ApiEnv) -> None:
    env = api_env
    env.app.state.mcp_limiter = TokenRateLimiter(limit=2, window=60.0)
    token = await _issue(env)
    first = await _rpc(env, token, "tools/call", {"name": "list_my_tasks", "arguments": {}})
    second = await _rpc(env, token, "tools/call", {"name": "list_my_tasks", "arguments": {}})
    third = await _rpc(env, token, "tools/call", {"name": "list_my_tasks", "arguments": {}})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert third.status_code == 429, third.text
    assert third.json()["code"] == "rate_limited"
    assert int(third.headers["retry-after"]) >= 1


async def test_032_ac2_initialize_and_tools_list_do_not_count(api_env: ApiEnv) -> None:
    env = api_env
    env.app.state.mcp_limiter = TokenRateLimiter(limit=1, window=60.0)
    token = await _issue(env)
    listed = await _rpc(env, token, "tools/list")
    init = await _rpc(
        env,
        token,
        "initialize",
        {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    )
    call = await _rpc(env, token, "tools/call", {"name": "list_my_tasks", "arguments": {}})
    blocked = await _rpc(env, token, "tools/call", {"name": "list_my_tasks", "arguments": {}})
    assert listed.status_code == 200, listed.text
    assert init.status_code == 200, init.text
    assert call.status_code == 200, call.text
    assert blocked.status_code == 429, blocked.text


async def test_032_ac3_read_only_hides_write_tools(api_env: ApiEnv) -> None:
    env = api_env
    token = await _issue(env, read_only=True, role="business_admin")
    names = set(await _list_names(env, token))
    assert "list_my_tasks" in names
    assert names.isdisjoint(WRITE_TOOLS)


async def test_032_ac4_read_only_create_task_is_forbidden(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token_read_only(env, w, "ba")
    result = await _call(
        env,
        token,
        "create_task",
        {
            "project_id": str(w.project_id),
            "title": "Нельзя",
            "description": "Описание",
            "due_date": "2026-12-01",
            "assignee_id": str(w.uid("usr")),
        },
    )
    assert _error_code(result) == "forbidden"


async def test_032_ac5_legacy_token_still_writes(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    result = await _call(
        env,
        token,
        "create_task",
        {
            "project_id": str(w.project_id),
            "title": "Из агента",
            "description": "Описание",
            "due_date": "2026-12-01",
            "assignee_id": str(w.uid("usr")),
        },
    )
    assert result.get("isError") in (False, None), result
    assert _payload(result)["title"] == "Из агента"


async def test_032_oauth_mcp_read_is_read_only(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = await _register(env)
    verifier, challenge = _pkce()
    params = _auth_params(client["client_id"], challenge, scope="mcp:read")
    code = await _consent(env, w.tok("ba"), params)
    tokens = await _exchange(env, client["client_id"], code, verifier)
    assert tokens.status_code == 200, tokens.text
    granted = set(tokens.json()["scope"].split())
    assert "mcp:read" in granted and "mcp" not in granted
    access = tokens.json()["access_token"]
    names = set(await _list_names(env, access))
    assert "list_projects" in names
    assert names.isdisjoint(WRITE_TOOLS)
    denied = await _call(env, access, "create_project", {"name": "Нет"})
    assert _error_code(denied) == "forbidden"


async def _agent_token_read_only(env: ApiEnv, w: Any, who: str) -> str:
    response = await send(env, w.tok(who), "POST", TOKENS, {"name": "ro", "read_only": True})
    assert response.status_code == 201, response.text
    assert response.json()["read_only"] is True
    return str(response.json()["token"])
