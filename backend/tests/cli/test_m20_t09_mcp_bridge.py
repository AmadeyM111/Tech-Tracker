"""M20-T09: подкоманда ``gtrack mcp`` — stdio-мост к ``/mcp`` (ADR-0018, PN-8).

Проверяем: без токена — код 2 и понятное сообщение; адрес по умолчанию и ``GTRACK_URL``; клиентская
сессия к реальному приложению (через ASGI-транспорт) видит инструменты и вызывает их; неверный токен
не проходит. Работу stdio-процесса с настоящим агентом проверяет ручной критерий AC-9.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.cli.commands import mcp as bridge
from app.cli.main import main
from tests.conftest import ApiEnv

TOKENS = "/api/v1/me/tokens"
ENDPOINT = "http://testserver/mcp"


def test_m20_t09_missing_token_exits_2_with_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(bridge.TOKEN_ENV, raising=False)
    assert main(["mcp"]) == 2
    err = capsys.readouterr().err
    assert bridge.TOKEN_ENV in err
    assert "Доступ для агентов" in err


def test_m20_t09_blank_token_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(bridge.TOKEN_ENV, "   ")
    assert main(["mcp"]) == 2
    assert bridge.TOKEN_ENV in capsys.readouterr().err


def test_m20_t09_missing_ca_file_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv(bridge.TOKEN_ENV, "gtrk_x")
    monkeypatch.setenv(bridge.CA_ENV, str(tmp_path / "nope.pem"))
    assert main(["mcp"]) == 2
    assert bridge.CA_ENV in capsys.readouterr().err


def test_m20_t09_default_endpoint_uses_https_port() -> None:
    assert bridge.endpoint_from_env({"HTTPS_PORT": "8443"}) == "https://localhost:8443/mcp"
    assert bridge.endpoint_from_env({}) == "https://localhost:443/mcp"


def test_m20_t09_gtrack_url_overrides_and_trims_slash() -> None:
    env = {bridge.URL_ENV: "http://127.0.0.1:8000/"}
    assert bridge.endpoint_from_env(env) == "http://127.0.0.1:8000/mcp"


async def _agent_token(env: ApiEnv) -> str:
    user = await env.new_user(role="user")
    session = await env.login_ok(user)
    created = await env.client.post(TOKENS, json={"name": "bridge"}, headers=env.auth(session))
    assert created.status_code == 201, created.text
    return str(created.json()["token"])


def _asgi_client(env: ApiEnv, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app),
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_m20_t09_bridge_session_lists_and_calls_tools(api_env: ApiEnv) -> None:
    token = await _agent_token(api_env)
    async with (
        _asgi_client(api_env, token) as client,
        bridge.open_session(ENDPOINT, client) as session,
    ):
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert {"list_my_tasks", "create_task", "add_comment"} <= names

        result = await session.call_tool("list_my_tasks", {})
        assert result.isError is False


async def test_m20_t09_bad_token_does_not_open_session(api_env: ApiEnv) -> None:
    async with _asgi_client(api_env, "gtrk_" + "b" * 43) as client:
        with pytest.raises(Exception):  # noqa: B017 — тип ошибки SDK не важен, важен отказ
            async with bridge.open_session(ENDPOINT, client) as session:
                await session.list_tools()
