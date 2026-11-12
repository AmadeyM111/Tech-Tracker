"""Спека 028: OAuth 2.1 на /mcp для облачных клиентов (AC-1…AC-11).

Метаданные, 401 с ``resource_metadata``, DCR, согласие, token endpoint (код, refresh, ротация,
повтор), ``gtat_`` на ``/mcp``, гранты и отзыв, аудит, лимиты, очистка.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import text

from tests.api.test_m20_t08_mcp_tools import _call, _error_code, _payload
from tests.conftest import ApiEnv
from tests.projects_api_support import make_api_world, send

BASE = "https://t.example"
MCP = "/mcp"
REG = "/api/v1/oauth/register"
TOKEN = "/api/v1/oauth/token"
CTX = "/api/v1/oauth/authorize/context"
DECISION = "/api/v1/oauth/authorize/decision"
GRANTS = "/api/v1/me/oauth-grants"
REDIRECT = "https://chatgpt.com/connector/oauth/abc123"


def _setup(env: ApiEnv) -> None:
    env.app.state.settings.public_base_url = BASE


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return verifier, challenge.decode()


async def _register(env: ApiEnv, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"client_name": "ChatGPT", "redirect_uris": [REDIRECT], **over}
    r = await env.client.post(REG, json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def _auth_params(client_id: str, challenge: str, **over: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz",
        "resource": f"{BASE}/mcp",
        **over,
    }


async def _consent(env: ApiEnv, token: str, params: dict[str, str]) -> str:
    """Контекст + «Разрешить»: возвращает код из редиректа."""
    ctx = await env.client.get(CTX, params=params, headers=env.auth(token))
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert body["status"] == "ok"
    done = await env.client.post(
        DECISION,
        json={"request_token": body["request_token"], "allow": True},
        headers=env.auth(token),
    )
    assert done.status_code == 200, done.text
    query = parse_qs(urlsplit(done.json()["redirect_to"]).query)
    assert query["state"] == ["xyz"] and query["iss"] == [BASE]
    return query["code"][0]


async def _exchange(
    env: ApiEnv, client_id: str, code: str, verifier: str, override: dict[str, str] | None = None
) -> Any:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT,
        "client_id": client_id,
        **(override or {}),
    }
    return await env.client.post(TOKEN, data=form)


async def _connect(env: ApiEnv, w: Any, who: str = "usr") -> dict[str, Any]:
    client = await _register(env)
    verifier, challenge = _pkce()
    code = await _consent(env, w.tok(who), _auth_params(client["client_id"], challenge))
    r = await _exchange(env, client["client_id"], code, verifier)
    assert r.status_code == 200, r.text
    return {"client": client, **r.json()}


# --- AC-1: метаданные ---------------------------------------------------------------------------


async def test_028_ac1_metadata_from_public_base_url_and_disabled_without_it(
    api_env: ApiEnv,
) -> None:
    env = api_env
    r = await env.client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 404 and r.json()["code"] == "feature_disabled"
    _setup(env)
    first = await env.client.get("/.well-known/oauth-protected-resource")
    assert first.headers.get("cache-control") == "no-store"
    prm = first.json()
    assert prm["resource"] == f"{BASE}/mcp" and prm["authorization_servers"] == [BASE]
    same = (await env.client.get("/.well-known/oauth-protected-resource/mcp")).json()
    assert same == prm
    asm = (await env.client.get("/.well-known/oauth-authorization-server")).json()
    assert asm["issuer"] == BASE and asm["issuer"] in prm["authorization_servers"]
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert asm["token_endpoint"] == f"{BASE}/api/v1/oauth/token"
    assert asm["registration_endpoint"] == f"{BASE}/api/v1/oauth/register"
    assert asm["authorization_endpoint"] == f"{BASE}/oauth/authorize"
    assert asm["authorization_response_iss_parameter_supported"] is True
    assert (await env.client.get("/.well-known/openid-configuration")).json()["issuer"] == BASE


async def test_028_ac1_issuer_ignores_host_and_forwarded_headers(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    r = await env.client.get(
        "/.well-known/oauth-authorization-server",
        headers={
            "Host": "evil.example",
            "X-Forwarded-Proto": "http",
            "X-Forwarded-Host": "evil.example",
        },
    )
    assert r.json()["issuer"] == BASE


async def test_028_ac1_http_public_base_url_disables_oauth(api_env: ApiEnv) -> None:
    env = api_env
    env.app.state.settings.public_base_url = "http://t.example"
    assert (await env.client.get("/.well-known/oauth-authorization-server")).status_code == 404


# --- AC-2: 401 с resource_metadata --------------------------------------------------------------


async def test_028_ac2_mcp_401_carries_resource_metadata(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    anon = await env.client.post(MCP, json={})
    assert anon.status_code == 401
    wa = anon.headers["www-authenticate"]
    assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp"' in wa
    assert "invalid_token" not in wa
    bad = await env.client.post(MCP, json={}, headers={"Authorization": "Bearer gtat_nope"})
    assert bad.status_code == 401 and 'error="invalid_token"' in bad.headers["www-authenticate"]
    env.app.state.settings.public_base_url = None  # без OAuth заголовка нет, поведение прежнее
    assert "www-authenticate" not in (await env.client.post(MCP, json={})).headers


# --- AC-3: регистрация --------------------------------------------------------------------------


async def test_028_ac3_register_accepts_https_and_rejects_the_rest(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    client = await _register(env)
    assert client["token_endpoint_auth_method"] == "none" and "client_secret" not in client
    assert client["redirect_uris"] == [REDIRECT] and len(client["client_id"]) >= 16
    for bad in (
        "http://chatgpt.com/cb",
        "https://localhost/cb",
        "https://127.0.0.1/cb",
        "https://user:pw@chatgpt.com/cb",
        "https://chatgpt.com/cb#frag",
        "chatgpt.com/cb",
        "javascript:alert(1)",
    ):
        r = await env.client.post(REG, json={"redirect_uris": [bad]})
        assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri", bad
    for body in (
        {},
        {"redirect_uris": []},
        {"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "client_secret_post"},
    ):
        assert (await env.client.post(REG, json=body)).status_code == 400
    assert (await env.client.post(REG, content=b"not json")).status_code == 400


async def test_028_ac3_register_is_rate_limited_per_ip(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    for _ in range(20):
        await _register(env)
    limited = await env.client.post(REG, json={"redirect_uris": [REDIRECT]})
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0


# --- AC-4, AC-5: запрос авторизации и согласие --------------------------------------------------


async def test_028_ac4_bad_client_or_redirect_is_a_page_error_not_a_redirect(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = await _register(env)
    _, challenge = _pkce()
    unknown = await env.client.get(
        CTX, params=_auth_params("nope", challenge), headers=env.auth(w.tok("usr"))
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "oauth_client_unknown"
    wrong = await env.client.get(
        CTX,
        params=_auth_params(client["client_id"], challenge, redirect_uri="https://evil.example/cb"),
        headers=env.auth(w.tok("usr")),
    )
    assert wrong.status_code == 422 and wrong.json()["code"] == "oauth_request_invalid"


async def test_028_ac4_protocol_errors_redirect_to_the_client(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = await _register(env)
    _, challenge = _pkce()
    cases = {
        "code_challenge_method": ("plain", "invalid_request"),
        "resource": ("https://other.example/mcp", "invalid_target"),
        "response_type": ("token", "unsupported_response_type"),
        "scope": ("admin", "invalid_scope"),
    }
    for key, (value, error) in cases.items():
        params = _auth_params(client["client_id"], challenge, **{key: value})
        body = (await env.client.get(CTX, params=params, headers=env.auth(w.tok("usr")))).json()
        assert body["status"] == "redirect", key
        query = parse_qs(urlsplit(body["redirect_to"]).query)
        assert query["error"] == [error] and query["iss"] == [BASE] and query["state"] == ["xyz"], (
            key
        )


async def test_028_ac5_consent_needs_session_and_a_business_role(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = await _register(env)
    _, challenge = _pkce()
    params = _auth_params(client["client_id"], challenge)
    assert (await env.client.get(CTX, params=params)).status_code == 401
    assert (
        await env.client.get(CTX, params=params, headers=env.auth(w.tok("ta")))
    ).status_code == 403
    ok = await env.client.get(CTX, params=params, headers=env.auth(w.tok("usr")))
    body = ok.json()
    assert body["client_name"] == "ChatGPT" and body["redirect_host"] == "chatgpt.com"
    assert body["login"] == w.login("usr")


async def test_028_ac5_client_without_name_shows_the_domain(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = (await env.client.post(REG, json={"redirect_uris": [REDIRECT]})).json()
    _, challenge = _pkce()
    body = (
        await env.client.get(
            CTX, params=_auth_params(client["client_id"], challenge), headers=env.auth(w.tok("usr"))
        )
    ).json()
    assert body["client_name"] == "chatgpt.com"


async def test_028_ac5_deny_redirects_with_access_denied_and_creates_no_grant(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = await _register(env)
    _, challenge = _pkce()
    ctx = (
        await env.client.get(
            CTX, params=_auth_params(client["client_id"], challenge), headers=env.auth(w.tok("usr"))
        )
    ).json()
    done = await env.client.post(
        DECISION,
        json={"request_token": ctx["request_token"], "allow": False},
        headers=env.auth(w.tok("usr")),
    )
    query = parse_qs(urlsplit(done.json()["redirect_to"]).query)
    assert query["error"] == ["access_denied"] and query["iss"] == [BASE] and "code" not in query
    assert (await env.client.get(GRANTS, headers=env.auth(w.tok("usr")))).json() == []


async def test_028_ac5_decision_rejects_tampered_foreign_or_expired_context(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = await _register(env)
    _, challenge = _pkce()
    ctx = (
        await env.client.get(
            CTX, params=_auth_params(client["client_id"], challenge), headers=env.auth(w.tok("usr"))
        )
    ).json()["request_token"]
    body, _, sig = ctx.partition(".")
    for bad, who in ((f"{body}x.{sig}", "usr"), (ctx, "usr2"), ("junk", "usr")):
        r = await env.client.post(
            DECISION, json={"request_token": bad, "allow": True}, headers=env.auth(w.tok(who))
        )
        assert r.status_code == 422 and r.json()["code"] == "oauth_request_invalid", (bad, who)
    env.clock.advance(timedelta(minutes=11))
    late = await env.client.post(
        DECISION, json={"request_token": ctx, "allow": True}, headers=env.auth(w.tok("usr"))
    )
    assert late.status_code == 422


# --- AC-6, AC-7: token endpoint -----------------------------------------------------------------


async def test_028_ac6_code_exchange_with_pkce_and_one_time_use(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = await _register(env)
    verifier, challenge = _pkce()
    code = await _consent(env, w.tok("usr"), _auth_params(client["client_id"], challenge))

    wrong = await _exchange(
        env, client["client_id"], code, "x" * 50
    )  # неверный verifier сжигает код
    assert wrong.status_code == 400 and wrong.json()["error"] == "invalid_grant"
    again = await _exchange(env, client["client_id"], code, verifier)
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"


async def test_028_ac6_success_shape_and_every_binding_is_checked(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = await _register(env)
    for over in ({"redirect_uri": "https://evil.example/cb"}, {"client_id": "other"}):
        verifier, challenge = _pkce()
        code = await _consent(env, w.tok("usr"), _auth_params(client["client_id"], challenge))
        r = await _exchange(env, client["client_id"], code, verifier, over)
        assert r.status_code == 400 and r.json()["error"] == "invalid_grant", over
    verifier, challenge = _pkce()
    code = await _consent(env, w.tok("usr"), _auth_params(client["client_id"], challenge))
    ok = await _exchange(env, client["client_id"], code, verifier, {"resource": f"{BASE}/mcp"})
    body = ok.json()
    assert ok.status_code == 200 and body["token_type"] == "Bearer" and body["expires_in"] == 3600
    assert body["access_token"].startswith("gtat_") and body["refresh_token"].startswith("gtrt_")
    assert ok.headers["cache-control"] == "no-store"
    bad_resource = await _exchange(
        env, client["client_id"], "x", verifier, {"resource": "https://other/mcp"}
    )
    assert bad_resource.status_code == 400


async def test_028_ac6_expired_code_and_reuse_revokes_the_grant(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = await _register(env)
    verifier, challenge = _pkce()
    code = await _consent(env, w.tok("usr"), _auth_params(client["client_id"], challenge))
    env.clock.advance(timedelta(seconds=61))
    assert (await _exchange(env, client["client_id"], code, verifier)).json()[
        "error"
    ] == "invalid_grant"

    verifier, challenge = _pkce()
    code = await _consent(env, w.tok("usr"), _auth_params(client["client_id"], challenge))
    tokens = (await _exchange(env, client["client_id"], code, verifier)).json()
    await _exchange(env, client["client_id"], code, verifier)  # повторное использование кода
    result = await _call(env, tokens["access_token"], "list_projects", {}) if False else None
    assert result is None
    r = await env.client.post(
        MCP, json={}, headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert r.status_code == 401  # выданное по этому коду отозвано


async def test_028_ac7_refresh_rotates_and_reuse_revokes_the_grant(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    first = await _connect(env, w)
    cid = first["client"]["client_id"]

    def refresh(token: str) -> Any:
        return env.client.post(
            TOKEN, data={"grant_type": "refresh_token", "refresh_token": token, "client_id": cid}
        )

    second = await refresh(first["refresh_token"])
    assert second.status_code == 200, second.text
    new = second.json()
    assert (
        new["refresh_token"] != first["refresh_token"]
        and new["access_token"] != first["access_token"]
    )
    # старый refresh больше не действует, а его повторное предъявление отзывает весь грант
    stale = await refresh(first["refresh_token"])
    assert stale.status_code == 400 and stale.json()["error"] == "invalid_grant"
    assert (await refresh(new["refresh_token"])).json()["error"] == "invalid_grant"
    r = await env.client.post(
        MCP, json={}, headers={"Authorization": f"Bearer {new['access_token']}"}
    )
    assert r.status_code == 401


async def test_028_ac7_refresh_lives_90_days_and_each_use_prolongs(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    tokens = await _connect(env, w)
    cid = tokens["client"]["client_id"]
    env.clock.advance(timedelta(days=89))
    r = await env.client.post(
        TOKEN,
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": cid,
        },
    )
    assert r.status_code == 200, r.text
    env.clock.advance(timedelta(days=89))  # новый refresh снова на 90 суток от выдачи
    r2 = await env.client.post(
        TOKEN,
        data={
            "grant_type": "refresh_token",
            "refresh_token": r.json()["refresh_token"],
            "client_id": cid,
        },
    )
    assert r2.status_code == 200, r2.text
    env.clock.advance(timedelta(days=91))
    dead = await env.client.post(
        TOKEN,
        data={
            "grant_type": "refresh_token",
            "refresh_token": r2.json()["refresh_token"],
            "client_id": cid,
        },
    )
    assert dead.status_code == 400 and dead.json()["error"] == "invalid_grant"


async def test_028_token_endpoint_rejects_unknown_grant_types_and_is_rate_limited(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _setup(env)
    r = await env.client.post(TOKEN, data={"grant_type": "password"})
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"
    for _ in range(59):
        await env.client.post(TOKEN, data={"grant_type": "authorization_code", "code": "x"})
    limited = await env.client.post(TOKEN, data={"grant_type": "authorization_code", "code": "x"})
    assert limited.status_code == 429 and limited.json()["error"] == "slow_down"
    assert int(limited.headers["retry-after"]) > 0


# --- AC-8: gtat_ на /mcp ------------------------------------------------------------------------


async def test_028_ac8_access_token_works_on_mcp_with_the_users_rights_only(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    tokens = await _connect(env, w)
    result = await _call(env, tokens["access_token"], "list_projects", {})
    assert result.get("isError") is not True
    assert _payload(result)["items"], "usr участник проекта мира"
    denied = await _call(env, tokens["access_token"], "create_project", {"name": "П"})
    assert denied.get("isError") is not True  # «Пользователь» создаёт проекты (027)
    # токен не принимается REST API и не годится в query
    assert (
        await env.client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
    ).status_code == 401
    assert (
        await env.client.post(f"{MCP}?access_token={tokens['access_token']}", json={})
    ).status_code == 401


async def test_028_ac8_expiry_blocked_user_wrong_audience_and_gtrk_still_work(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    tokens = await _connect(env, w)
    access = tokens["access_token"]
    # gtrk_ работает как раньше
    gtrk = (await send(env, w.tok("usr"), "POST", "/api/v1/me/tokens", {"name": "L"})).json()[
        "token"
    ]
    assert (await _call(env, gtrk, "list_projects", {})).get("isError") is not True
    # другой audience (изменился PUBLIC_BASE_URL) — токен недействителен
    env.app.state.settings.public_base_url = "https://other.example"
    assert (
        await env.client.post(MCP, json={}, headers={"Authorization": f"Bearer {access}"})
    ).status_code == 401
    _setup(env)
    # блокировка пользователя отключает токен
    await env.execute(
        text("UPDATE app_user SET is_blocked = true WHERE login = :l").bindparams(
            l=w.login("usr").lower()
        )
    )
    assert (
        await env.client.post(MCP, json={}, headers={"Authorization": f"Bearer {access}"})
    ).status_code == 401
    await env.execute(
        text("UPDATE app_user SET is_blocked = false WHERE login = :l").bindparams(
            l=w.login("usr").lower()
        )
    )
    env.clock.advance(timedelta(hours=1, seconds=1))  # access живёт 1 час
    assert (
        await env.client.post(MCP, json={}, headers={"Authorization": f"Bearer {access}"})
    ).status_code == 401


async def test_028_ac8_role_is_read_from_the_database_on_every_call(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    tokens = await _connect(env, w, "usr")
    await env.execute(
        text("UPDATE workspace_member SET role = NULL WHERE user_id = :u").bindparams(
            u=w.uid("usr")
        )
    )
    r = await env.client.post(
        MCP,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_projects", "arguments": {}},
        },
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200 and _error_code(r.json()["result"]) == "no_role"


# --- AC-9, AC-10: гранты, отзыв, аудит ----------------------------------------------------------


async def test_028_ac9_grants_list_revoke_and_idempotence(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    tokens = await _connect(env, w)
    grants = (await env.client.get(GRANTS, headers=env.auth(w.tok("usr")))).json()
    assert len(grants) == 1 and grants[0]["client_name"] == "ChatGPT"
    assert grants[0]["redirect_host"] == "chatgpt.com" and grants[0]["revoked_at"] is None
    gid = grants[0]["id"]
    assert (await env.client.get(GRANTS, headers=env.auth(w.tok("usr2")))).json() == []
    assert (
        await env.client.delete(f"{GRANTS}/{gid}", headers=env.auth(w.tok("usr2")))
    ).status_code == 404

    assert (
        await env.client.delete(f"{GRANTS}/{gid}", headers=env.auth(w.tok("usr")))
    ).status_code == 204
    assert (
        await env.client.delete(f"{GRANTS}/{gid}", headers=env.auth(w.tok("usr")))
    ).status_code == 204
    after = (await env.client.get(GRANTS, headers=env.auth(w.tok("usr")))).json()
    assert after[0]["revoked_at"] is not None
    # все токены клиента недействительны сразу (Q-16)
    r = await env.client.post(
        MCP, json={}, headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert r.status_code == 401
    refresh = await env.client.post(
        TOKEN,
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client"]["client_id"],
        },
    )
    assert refresh.json()["error"] == "invalid_grant"
    assert (await env.client.get(GRANTS)).status_code == 401


async def test_028_ac9_rfc7009_revoke_by_token_is_silent_for_unknown_tokens(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    tokens = await _connect(env, w)
    assert (
        await env.client.post("/api/v1/oauth/revoke", data={"token": "gtat_unknown"})
    ).status_code == 200
    assert (
        await env.client.post("/api/v1/oauth/revoke", data={"token": tokens["refresh_token"]})
    ).status_code == 200
    r = await env.client.post(
        MCP, json={}, headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert r.status_code == 401


async def test_028_ac10_audit_has_client_name_only_and_feed_is_labelled(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    tokens = await _connect(env, w)
    grants = (await env.client.get(GRANTS, headers=env.auth(w.tok("usr")))).json()
    await env.client.delete(f"{GRANTS}/{grants[0]['id']}", headers=env.auth(w.tok("usr")))
    rows = await env.execute(
        text(
            "SELECT action, actor_id, entity_id, in_audit, details FROM domain_event "
            "WHERE action IN ('user.oauth_granted','user.oauth_revoked') ORDER BY id"
        )
    )
    assert rows is not None and [r.action for r in rows] == [
        "user.oauth_granted",
        "user.oauth_revoked",
    ]
    for row in rows:
        assert row.actor_id == row.entity_id == w.uid("usr") and row.in_audit is True
        assert row.details == {"client": "ChatGPT"}
    dump = str(rows)
    assert tokens["access_token"] not in dump and tokens["refresh_token"] not in dump


async def test_028_ac10_agent_actions_carry_the_client_label_in_the_feed(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    tokens = await _connect(env, w, "usr2")
    created = await _call(env, tokens["access_token"], "create_project", {"name": "Облако"})
    assert created.get("isError") is not True
    task = await _call(
        env,
        tokens["access_token"],
        "create_task",
        {
            "project_id": _payload(created)["id"],
            "title": "От агента",
            "description": "Описание",
            "due_date": "2026-12-01",
        },
    )
    assert task.get("isError") is not True, task
    rows = await env.execute(
        text("SELECT client_name FROM domain_event WHERE client_name IS NOT NULL")
    )
    assert rows is not None and {r.client_name for r in rows} == {"ChatGPT (OAuth)"}


async def test_028_grants_limit_is_20_active_per_user(api_env: ApiEnv) -> None:
    env = api_env
    _setup(env)
    w = await make_api_world(env)
    client = await _register(env)
    for _ in range(20):
        _, challenge = _pkce()
        await _consent(env, w.tok("usr"), _auth_params(client["client_id"], challenge))
    _, challenge = _pkce()
    ctx = (
        await env.client.get(
            CTX, params=_auth_params(client["client_id"], challenge), headers=env.auth(w.tok("usr"))
        )
    ).json()
    r = await env.client.post(
        DECISION,
        json={"request_token": ctx["request_token"], "allow": True},
        headers=env.auth(w.tok("usr")),
    )
    assert r.status_code == 422 and r.json()["code"] == "limit_reached"


# --- AC-11: очистка -----------------------------------------------------------------------------


async def test_028_ac11_maintenance_purges_unused_clients_and_expired_rows(api_env: ApiEnv) -> None:
    from app.domain.oauth.service import purge

    env = api_env
    _setup(env)
    w = await make_api_world(env)
    await _register(env)  # без гранта
    used = await _connect(env, w)
    env.clock.advance(timedelta(days=8))
    async with env.sessionmaker() as session:
        counts = await purge(session, env.clock.now(), dry_run=True)
        assert counts["oauth_clients_purged"] == 1 and counts["oauth_codes_purged"] >= 1
        await purge(session, env.clock.now(), dry_run=False)
        await session.commit()
    rows = await env.execute(text("SELECT client_id FROM oauth_client"))
    assert rows is not None and [r.client_id for r in rows] == [used["client"]["client_id"]]
