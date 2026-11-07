"""M20-T06: ``/api/v1/me/tokens`` — выдача, список, отзыв (ADR-0018, PN-2, AC-1, AC-3).

Все маршруты — только cookie-сессия: ``Authorization: Bearer`` без cookie даёт 401 (PN-2).
"""

from __future__ import annotations

from tests.conftest import ApiEnv

TOKENS = "/api/v1/me/tokens"


async def _user_cookie(env: ApiEnv, role: str | None = "user") -> tuple[str, str]:
    user = await env.new_user(role=role)
    session = await env.login_ok(user)
    return session, str(user.id)


async def test_ac1_create_returns_token_once_and_list_hides_it(api_env: ApiEnv) -> None:
    env = api_env
    session, _ = await _user_cookie(env)

    created = await env.client.post(TOKENS, json={"name": "Claude Code"}, headers=env.auth(session))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["token"].startswith("gtrk_")
    assert body["name"] == "Claude Code"
    assert body["active"] is True
    assert body["revoked_at"] is None

    listed = await env.client.get(TOKENS, headers=env.auth(session))
    assert listed.status_code == 200, listed.text
    items = listed.json()
    assert [i["id"] for i in items] == [body["id"]]
    assert "token" not in items[0]
    assert body["token"] not in listed.text


async def test_ac3_revoke_marks_token_inactive_and_repeat_is_204(api_env: ApiEnv) -> None:
    env = api_env
    session, _ = await _user_cookie(env)
    token_id = (
        await env.client.post(TOKENS, json={"name": "agent"}, headers=env.auth(session))
    ).json()["id"]

    first = await env.client.delete(f"{TOKENS}/{token_id}", headers=env.auth(session))
    assert first.status_code == 204, first.text
    again = await env.client.delete(f"{TOKENS}/{token_id}", headers=env.auth(session))
    assert again.status_code == 204, again.text

    item = (await env.client.get(TOKENS, headers=env.auth(session))).json()[0]
    assert item["revoked_at"] is not None
    assert item["active"] is False


async def test_revoke_unknown_token_is_404(api_env: ApiEnv) -> None:
    env = api_env
    session, _ = await _user_cookie(env)
    response = await env.client.delete(
        f"{TOKENS}/00000000-0000-4000-8000-000000000001", headers=env.auth(session)
    )
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"


async def test_no_cookie_and_bearer_header_is_401(api_env: ApiEnv) -> None:
    env = api_env
    session, _ = await _user_cookie(env)
    token = (
        await env.client.post(TOKENS, json={"name": "agent"}, headers=env.auth(session))
    ).json()["token"]

    bearer_only = {"Authorization": f"Bearer {token}"}
    assert (await env.client.get(TOKENS, headers=bearer_only)).status_code == 401
    assert (
        await env.client.post(TOKENS, json={"name": "x"}, headers=bearer_only)
    ).status_code == 401


async def test_user_without_role_is_forbidden(api_env: ApiEnv) -> None:
    env = api_env
    session, _ = await _user_cookie(env, role=None)
    response = await env.client.get(TOKENS, headers=env.auth(session))
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "no_role"


async def test_name_validation_is_422(api_env: ApiEnv) -> None:
    env = api_env
    session, _ = await _user_cookie(env)
    for name in ["", "   ", "x" * 65]:
        response = await env.client.post(TOKENS, json={"name": name}, headers=env.auth(session))
        assert response.status_code == 422, (name, response.text)


async def test_eleventh_active_token_is_409(api_env: ApiEnv) -> None:
    env = api_env
    session, _ = await _user_cookie(env)
    for i in range(10):
        ok = await env.client.post(TOKENS, json={"name": f"a{i}"}, headers=env.auth(session))
        assert ok.status_code == 201, ok.text
    limit = await env.client.post(TOKENS, json={"name": "a10"}, headers=env.auth(session))
    assert limit.status_code == 409, limit.text
    assert limit.json()["code"] == "token_limit_reached"
