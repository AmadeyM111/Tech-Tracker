"""M20-T07: ядро MCP-сервера ``/mcp`` (ADR-0018, PN-2, PN-3, PN-7, PN-11, PN-12).

Покрытие: AC-2 (401 без токена или с неверным), AC-6 (``tools/list`` по роли), AC-10 (чужой Origin
→ 403), FR-5 (вызов недоступного → ``forbidden``), PN-3 (блокировка, одноразовый пароль, без роли),
PN-12 (ошибки в формате ``{"detail","code"}``, без утечки текста непредвиденной ошибки),
NFR-1 (токен не попадает в журнал).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from sqlalchemy import update

from app.api.mcp.context import current_request
from app.api.mcp.registry import ToolRegistry, ToolSpec
from app.core.errors import NotFound
from app.domain.access.roles import Capability
from app.domain.events.client_context import current_client_name
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember
from tests.conftest import ApiEnv

MCP = "/mcp"
TOKENS = "/api/v1/me/tokens"
PROTOCOL = "2025-06-18"


async def _issue_token(
    env: ApiEnv, role: str | None = "user", name: str = "agent"
) -> tuple[str, Any]:
    user = await env.new_user(role=role)
    session = await env.login_ok(user)
    created = await env.client.post(TOKENS, json={"name": name}, headers=env.auth(session))
    assert created.status_code == 201, created.text
    return created.json()["token"], user


def _headers(token: str, **extra: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL,
        **extra,
    }


async def _rpc(env: ApiEnv, token: str, method: str, params: dict[str, Any] | None = None) -> Any:
    return await env.client.post(
        MCP,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers=_headers(token),
    )


async def _list_names(env: ApiEnv, token: str) -> list[str]:
    response = await _rpc(env, token, "tools/list")
    assert response.status_code == 200, response.text
    return sorted(tool["name"] for tool in response.json()["result"]["tools"])


async def _call(
    env: ApiEnv, token: str, name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = await _rpc(env, token, "tools/call", {"name": name, "arguments": arguments or {}})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    return json.loads(result["content"][0]["text"])


async def _probe_registry(env: ApiEnv) -> None:
    async def whoami(db: Any, actor: Any, args: dict[str, Any]) -> dict[str, Any]:
        return {"login": actor.login, "client": current_client_name(), "role": str(actor.role)}

    async def create_probe(db: Any, actor: Any, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    async def boom(db: Any, actor: Any, args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("секретное-значение-в-тексте-ошибки")

    async def missing(db: Any, actor: Any, args: dict[str, Any]) -> dict[str, Any]:
        raise NotFound()

    env.app.state.mcp_registry = ToolRegistry(
        [
            ToolSpec("whoami", "кто я", {"type": "object"}, Capability.BUSINESS_ACCESS, whoami),
            ToolSpec(
                "create_probe",
                "создать",
                {"type": "object"},
                Capability.PROJECT_CREATE,
                create_probe,
            ),
            ToolSpec("boom", "падает", {"type": "object"}, Capability.BUSINESS_ACCESS, boom),
            ToolSpec("missing", "нет", {"type": "object"}, Capability.BUSINESS_ACCESS, missing),
        ]
    )


async def test_ac2_request_without_token_is_401(api_env: ApiEnv) -> None:
    response = await api_env.client.post(
        MCP, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}, headers=_headers("")
    )
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "not_authenticated"


async def test_ac2_invalid_token_is_401(api_env: ApiEnv) -> None:
    response = await _rpc(api_env, "gtrk_" + "a" * 43, "tools/list")
    assert response.status_code == 401, response.text
    assert response.json() == {
        "detail": response.json()["detail"],
        "code": "not_authenticated",
    }


async def test_session_cookie_is_not_accepted_on_mcp(api_env: ApiEnv) -> None:
    env = api_env
    user = await env.new_user(role="user")
    session = await env.login_ok(user)
    response = await env.client.post(
        MCP,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={
            **env.auth(session),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL,
        },
    )
    assert response.status_code == 401, response.text


async def test_ac10_foreign_origin_is_403(api_env: ApiEnv) -> None:
    token, _ = await _issue_token(api_env)
    response = await api_env.client.post(
        MCP,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers=_headers(token, Origin="https://evil.example"),
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "origin_mismatch"


async def test_initialize_with_valid_token(api_env: ApiEnv) -> None:
    token, _ = await _issue_token(api_env)
    response = await _rpc(
        api_env,
        token,
        "initialize",
        {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["serverInfo"]["name"] == "gtrack"


async def test_ac6_tools_list_depends_on_role(api_env: ApiEnv) -> None:
    await _probe_registry(api_env)
    user_token, _ = await _issue_token(api_env, role="user")
    ba_token, _ = await _issue_token(api_env, role="business_admin")
    ta_token, _ = await _issue_token(api_env, role="tech_admin")

    # спека 027, этап 1: «Пользователь» получает PROJECT_CREATE, инструмент create_probe ему виден
    assert await _list_names(api_env, user_token) == ["boom", "create_probe", "missing", "whoami"]
    assert await _list_names(api_env, ba_token) == ["boom", "create_probe", "missing", "whoami"]
    assert await _list_names(api_env, ta_token) == []


async def test_forbidden_tool_call_returns_forbidden(api_env: ApiEnv) -> None:
    await _probe_registry(api_env)
    token, _ = await _issue_token(api_env, role="tech_admin")  # у ТА нет PROJECT_CREATE
    result = await _call(api_env, token, "create_probe")
    assert result["isError"] is True
    assert _payload(result)["code"] == "forbidden"


async def test_allowed_call_runs_as_token_owner_with_client_name(api_env: ApiEnv) -> None:
    await _probe_registry(api_env)
    token, user = await _issue_token(api_env, role="user", name="Claude Code на ноутбуке")
    result = await _call(api_env, token, "whoami")
    assert result.get("isError") in (False, None)
    payload = _payload(result)
    assert payload["login"] == user.login
    assert payload["client"] == "Claude Code на ноутбуке"


async def test_unknown_tool_is_not_found(api_env: ApiEnv) -> None:
    await _probe_registry(api_env)
    token, _ = await _issue_token(api_env, role="user")
    result = await _call(api_env, token, "no_such_tool")
    assert result["isError"] is True
    assert _payload(result)["code"] == "not_found"


async def test_app_error_from_handler_keeps_its_code(api_env: ApiEnv) -> None:
    await _probe_registry(api_env)
    token, _ = await _issue_token(api_env, role="user")
    result = await _call(api_env, token, "missing")
    assert _payload(result)["code"] == "not_found"


async def test_unexpected_error_hides_detail(api_env: ApiEnv) -> None:
    await _probe_registry(api_env)
    token, _ = await _issue_token(api_env, role="user")
    result = await _call(api_env, token, "boom")
    assert result["isError"] is True
    payload = _payload(result)
    assert payload["code"] == "internal_error"
    assert "секретное-значение" not in result["content"][0]["text"]


async def test_must_change_password_blocks_tools(api_env: ApiEnv) -> None:
    await _probe_registry(api_env)
    token, user = await _issue_token(api_env, role="user")
    await api_env.execute(
        update(AppUser).where(AppUser.id == user.id).values(must_change_password=True)
    )
    assert await _list_names(api_env, token) == []
    assert _payload(await _call(api_env, token, "whoami"))["code"] == "password_change_required"


async def test_user_without_role_is_blocked(api_env: ApiEnv) -> None:
    await _probe_registry(api_env)
    token, user = await _issue_token(api_env, role="user")
    await api_env.execute(
        update(WorkspaceMember).where(WorkspaceMember.user_id == user.id).values(role=None)
    )
    assert await _list_names(api_env, token) == []
    assert _payload(await _call(api_env, token, "whoami"))["code"] == "no_role"


async def test_blocked_user_token_is_401(api_env: ApiEnv) -> None:
    token, user = await _issue_token(api_env, role="user")
    await api_env.execute(update(AppUser).where(AppUser.id == user.id).values(is_blocked=True))
    response = await _rpc(api_env, token, "tools/list")
    assert response.status_code == 401, response.text


async def test_token_value_is_not_logged(api_env: ApiEnv, caplog: pytest.LogCaptureFixture) -> None:
    await _probe_registry(api_env)
    token, _ = await _issue_token(api_env, role="user")
    with caplog.at_level(logging.DEBUG):
        await _call(api_env, token, "whoami")
        await _call(api_env, token, "boom")
    assert token not in caplog.text


async def test_request_context_is_reset_after_call(api_env: ApiEnv) -> None:
    await _probe_registry(api_env)
    token, _ = await _issue_token(api_env, role="user")
    await _call(api_env, token, "whoami")
    assert current_request() is None
