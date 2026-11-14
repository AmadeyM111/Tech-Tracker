"""Внешний вход (spec 029, FR-12…FR-21; ADR-0026): Яндекс ID, VK ID (флаг выкл.), Google.

Провайдеры заменены ``httpx.MockTransport``; PKCE проверяется по ``code_challenge`` из адреса
авторизации. Отказ входа через провайдера всегда одинаков (``login_failed``): существование
учётки не раскрывается (FR-2, FR-17).
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import text

from app.domain.auth.external_providers import enabled_providers
from tests.conftest import RESET_SETTINGS, ApiEnv, _open_api_env
from tests.factories import make_workspace

PW = "Correct-Horse-Battery-9"
CB = "/api/v1/auth/external"


class FakeProviders:
    """Подменяет ответы провайдеров; ``profiles`` — ``code`` -> ответ профиля."""

    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.challenges: dict[str, str] = {}  # code -> ожидаемый code_challenge
        self.fail = False
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.host}{request.url.path}")
        if self.fail:
            return httpx.Response(500, json={})
        body = parse_qs(request.content.decode()) if request.content else {}
        host, path = request.url.host, request.url.path
        if path in ("/token", "/oauth2/auth"):
            code = body["code"][0]
            verifier = body["code_verifier"][0]
            digest = hashlib.sha256(verifier.encode()).digest()
            challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            if self.challenges.get(code) != challenge or code not in self.profiles:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": f"tok-{code}"})
        auth = request.headers.get("authorization", "")
        token = auth.split(" ", 1)[1] if " " in auth else (body.get("access_token") or [""])[0]
        profile = self.profiles.get(token.removeprefix("tok-"))
        if profile is None:
            return httpx.Response(401, json={})
        if host == "login.yandex.ru":
            return httpx.Response(200, json=profile)
        return httpx.Response(200, json=profile if host != "id.vk.ru" else {"user": profile})


@pytest.fixture
def fake() -> FakeProviders:
    return FakeProviders()


@pytest_asyncio.fixture
async def ext_env(
    settings: Any, fixed_clock: Any, db_sessionmaker: Any, fake: FakeProviders
) -> AsyncIterator[ApiEnv]:
    from app.main import create_app

    cfg = settings.model_copy(
        update={
            **RESET_SETTINGS,
            "yandex_login": True,
            "yandex_client_id": "yandex-client",
            "yandex_client_secret": SecretStr("yandex-secret"),
            "google_login": True,
            "google_client_id": "google-client",
            "google_client_secret": SecretStr("google-secret"),
            "vk_login": False,
            "vk_client_id": "54898092",
        }
    )
    application = create_app(cfg, clock=fixed_clock)
    async for env in _open_api_env(
        application, cfg, fixed_clock, db_sessionmaker, "https://tracker.example.test"
    ):
        env.app.state.external_http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        yield env


async def _start(env: ApiEnv, provider: str, **query: str) -> tuple[str, dict[str, list[str]]]:
    response = await env.client.get(f"{CB}/{provider}/start", params=query)
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    return location, parse_qs(urlsplit(location).query)


async def _callback(
    env: ApiEnv, provider: str, params: dict[str, str], token: str | None = None
) -> httpx.Response:
    headers = env.auth(token) if token else None
    return await env.client.get(f"{CB}/{provider}/callback", params=params, headers=headers)


async def _login_via(
    env: ApiEnv,
    fake: FakeProviders,
    provider: str,
    code: str,
    profile: dict[str, Any],
    *,
    remember: bool = False,
    token: str | None = None,
    start_params: dict[str, str] | None = None,
) -> httpx.Response:
    query = {"remember": "true"} if remember else {}
    _, q = await _start(env, provider, **query)
    fake.profiles[code] = profile
    fake.challenges[code] = q["code_challenge"][0]
    return await _callback(env, provider, {"state": q["state"][0], "code": code}, token)


def _error(response: httpx.Response) -> str | None:
    assert response.status_code == 302, response.text
    query = parse_qs(urlsplit(response.headers["location"]).query)
    return query.get("external_error", [None])[0]


YANDEX_NEW = {"id": "ya-1001", "default_email": "Ivan.Petrov@Example.ru", "login": "ivanp"}


async def _workspace(env: ApiEnv) -> Any:
    async with env.sessionmaker() as s:
        ws = await make_workspace(s)
        await s.commit()
    return ws


async def _rows(env: ApiEnv, sql: str, **params: Any) -> list[Any]:
    async with env.sessionmaker() as s:
        return list((await s.execute(text(sql), params)).all())


async def test_029_providers_list_shows_only_enabled(ext_env: ApiEnv) -> None:
    response = await ext_env.client.get(f"{CB}/providers")
    assert response.status_code == 200
    assert {p["name"] for p in response.json()} == {"yandex", "google"}


def test_029_flag_without_client_id_does_not_enable(settings: Any) -> None:
    only_flag = settings.model_copy(update={"yandex_login": True, "yandex_client_id": None})
    assert enabled_providers(only_flag) == {}
    only_id = settings.model_copy(update={"yandex_login": False, "yandex_client_id": "x"})
    assert enabled_providers(only_id) == {}


async def test_029_start_uses_pkce_state_and_exact_redirect(ext_env: ApiEnv) -> None:
    location, q = await _start(ext_env, "yandex")
    assert location.startswith("https://oauth.yandex.ru/authorize?")
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["yandex-client"]
    assert q["code_challenge_method"] == ["S256"]
    assert len(q["state"][0]) >= 32 and len(q["code_challenge"][0]) == 43
    assert q["redirect_uri"] == [
        "https://tracker.example.test/api/v1/auth/external/yandex/callback"
    ]
    assert q["scope"] == ["login:email"]
    google, gq = await _start(ext_env, "google")
    assert google.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert gq["scope"] == ["openid email"]


async def test_029_disabled_provider_is_unavailable(ext_env: ApiEnv) -> None:
    response = await ext_env.client.get(f"{CB}/vk/start")
    assert response.status_code == 302
    assert response.headers["location"] == "/login?external_error=provider_unavailable&provider=vk"


async def test_029_first_login_creates_user_without_password(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    await _workspace(ext_env)
    response = await _login_via(ext_env, fake, "yandex", "c1", YANDEX_NEW)
    assert response.status_code == 302 and response.headers["location"] == "/"
    token = ext_env.token_from(response)
    assert token
    me = await ext_env.me(token)
    assert me.status_code == 200
    assert me.json()["role"] == "user"
    assert me.json()["login"] == "ivanpetrov"  # локальная часть email, правила 019
    user = (
        await _rows(
            ext_env,
            "SELECT password_hash, email, self_registered FROM app_user WHERE login = 'ivanpetrov'",
        )
    )[0]
    assert user.password_hash is None and user.self_registered is True
    assert user.email is None  # Яндекс адрес не подтверждает: в app_user не пишем
    ident = (
        await _rows(
            ext_env,
            "SELECT provider, provider_subject, email_at_link, email_verified_by_provider "
            "FROM external_identity",
        )
    )[0]
    assert tuple(ident) == ("yandex", "ya-1001", "ivan.petrov@example.ru", False)
    method = await _rows(ext_env, "SELECT auth_method, remember FROM user_session")
    assert tuple(method[0]) == ("yandex", False)


async def test_029_second_login_reuses_account(ext_env: ApiEnv, fake: FakeProviders) -> None:
    await _workspace(ext_env)
    await _login_via(ext_env, fake, "yandex", "c1", YANDEX_NEW)
    again = await _login_via(ext_env, fake, "yandex", "c2", YANDEX_NEW)
    assert ext_env.token_from(again)
    assert (await _rows(ext_env, "SELECT count(*) FROM app_user"))[0][0] == 1
    assert (await _rows(ext_env, "SELECT count(*) FROM external_identity"))[0][0] == 1


async def test_029_yandex_email_of_existing_user_is_neutral_failure(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    """AC-7, FR-16, FR-17: автопривязки нет; ответ не отличается от других отказов."""
    ws = await _workspace(ext_env)
    await ext_env.new_user(role="user", workspace=ws, email="ivan.petrov@example.ru")
    response = await _login_via(ext_env, fake, "yandex", "c1", YANDEX_NEW)
    assert _error(response) == "login_failed"
    assert ext_env.token_from(response) is None
    assert (await _rows(ext_env, "SELECT count(*) FROM external_identity"))[0][0] == 0


async def test_029_google_verified_email_links_existing_user(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    ws = await _workspace(ext_env)
    user = await ext_env.new_user(role="user", workspace=ws, email="anna@example.ru")
    profile = {"sub": "g-1", "email": "Anna@Example.ru", "email_verified": True}
    response = await _login_via(ext_env, fake, "google", "g1", profile)
    token = ext_env.token_from(response)
    assert token
    assert (await ext_env.me(token)).json()["login"] == user.login
    rows = await _rows(ext_env, "SELECT user_id, email_verified_by_provider FROM external_identity")
    assert rows[0].user_id == user.id and rows[0].email_verified_by_provider is True


async def test_029_google_unverified_email_does_not_link(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    ws = await _workspace(ext_env)
    await ext_env.new_user(role="user", workspace=ws, email="anna@example.ru")
    profile = {"sub": "g-1", "email": "anna@example.ru", "email_verified": False}
    response = await _login_via(ext_env, fake, "google", "g1", profile)
    assert _error(response) == "login_failed"


async def test_029_google_verified_new_user_stores_email(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    await _workspace(ext_env)
    profile = {"sub": "g-9", "email": "new.person@example.ru", "email_verified": True}
    response = await _login_via(ext_env, fake, "google", "g1", profile)
    assert ext_env.token_from(response)
    email = (await _rows(ext_env, "SELECT email FROM app_user"))[0][0]
    assert email == "new.person@example.ru"


async def test_029_registration_closed_gives_the_same_failure(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    """Q-3: без самостоятельной регистрации (019) учётка не создаётся; текст отказа тот же."""
    await _workspace(ext_env)
    ext_env.app.state.registration_policy = None
    response = await _login_via(ext_env, fake, "yandex", "c1", YANDEX_NEW)
    assert _error(response) == "login_failed"
    assert (await _rows(ext_env, "SELECT count(*) FROM app_user"))[0][0] == 0


async def test_029_blocked_user_cannot_log_in_via_provider(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    """AC-9, FR-20."""
    await _workspace(ext_env)
    await _login_via(ext_env, fake, "yandex", "c1", YANDEX_NEW)
    await ext_env.execute(text("UPDATE app_user SET is_blocked = true"))
    response = await _login_via(ext_env, fake, "yandex", "c2", YANDEX_NEW)
    assert _error(response) == "login_failed"
    assert ext_env.token_from(response) is None


async def test_029_state_is_validated_and_one_time(ext_env: ApiEnv, fake: FakeProviders) -> None:
    """AC-10, FR-13."""
    await _workspace(ext_env)
    _, q = await _start(ext_env, "yandex")
    fake.profiles["c1"] = YANDEX_NEW
    fake.challenges["c1"] = q["code_challenge"][0]
    bad = await _callback(ext_env, "yandex", {"state": "x" * 43, "code": "c1"})
    assert _error(bad) == "state_invalid"
    no_state = await _callback(ext_env, "yandex", {"code": "c1"})
    assert _error(no_state) == "state_invalid"
    other_provider = await _callback(ext_env, "google", {"state": q["state"][0], "code": "c1"})
    assert _error(other_provider) == "state_invalid"  # state сгорел при первом обращении
    reused = await _callback(ext_env, "yandex", {"state": q["state"][0], "code": "c1"})
    assert _error(reused) == "state_invalid"
    assert (await _rows(ext_env, "SELECT count(*) FROM app_user"))[0][0] == 0


async def test_029_expired_state_is_rejected(ext_env: ApiEnv, fake: FakeProviders) -> None:
    await _workspace(ext_env)
    _, q = await _start(ext_env, "yandex")
    ext_env.clock.advance(timedelta(minutes=11))
    fake.profiles["c1"] = YANDEX_NEW
    fake.challenges["c1"] = q["code_challenge"][0]
    response = await _callback(ext_env, "yandex", {"state": q["state"][0], "code": "c1"})
    assert _error(response) == "state_invalid"


async def test_029_wrong_pkce_verifier_fails_at_provider(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    await _workspace(ext_env)
    _, q = await _start(ext_env, "yandex")
    fake.profiles["c1"] = YANDEX_NEW
    fake.challenges["c1"] = "someone-elses-challenge"
    response = await _callback(ext_env, "yandex", {"state": q["state"][0], "code": "c1"})
    assert _error(response) == "provider_unavailable"


async def test_029_provider_denial_and_outage(ext_env: ApiEnv, fake: FakeProviders) -> None:
    await _workspace(ext_env)
    _, q = await _start(ext_env, "yandex")
    denied = await _callback(ext_env, "yandex", {"state": q["state"][0], "error": "access_denied"})
    assert _error(denied) == "cancelled"
    fake.fail = True
    down = await _login_via(ext_env, fake, "yandex", "c1", YANDEX_NEW)
    assert _error(down) == "provider_unavailable"


async def test_029_remember_flag_extends_session(ext_env: ApiEnv, fake: FakeProviders) -> None:
    await _workspace(ext_env)
    response = await _login_via(ext_env, fake, "yandex", "c1", YANDEX_NEW, remember=True)
    assert "Max-Age=2592000" in response.headers["set-cookie"]
    row = (await _rows(ext_env, "SELECT remember, auth_method FROM user_session"))[0]
    assert tuple(row) == (True, "yandex")


async def test_029_provider_tokens_and_secrets_are_not_stored(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    """FR-21: в БД нет провайдерских токенов; секреты клиента не попадают в запрос к браузеру."""
    await _workspace(ext_env)
    location, _ = await _start(ext_env, "yandex")
    assert "yandex-secret" not in location
    await _login_via(ext_env, fake, "yandex", "c1", YANDEX_NEW)
    dump = str(await _rows(ext_env, "SELECT * FROM external_identity")) + str(
        await _rows(ext_env, "SELECT * FROM oauth_login_state")
    )
    assert "tok-" not in dump and "yandex-secret" not in dump


async def test_029_password_login_is_impossible_without_password(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    await _workspace(ext_env)
    await _login_via(ext_env, fake, "yandex", "c1", YANDEX_NEW)
    nobody = await ext_env.login("nobody.here", PW)
    answer = await ext_env.login("ivanpetrov", PW)
    assert answer.status_code == 401 and answer.text == nobody.text


# --- привязка и отвязка ---------------------------------------------------------------------


async def test_029_link_requires_same_session_and_confirms(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    ws = await _workspace(ext_env)
    user = await ext_env.new_user(role="user", workspace=ws, password=PW)
    other = await ext_env.new_user(role="user", workspace=ws, password=PW)
    token = await ext_env.login_ok(user)
    other_token = await ext_env.login_ok(other)

    anonymous = await ext_env.client.post("/api/v1/me/login-methods/yandex/link")
    assert anonymous.status_code == 401

    started = await ext_env.client.post(
        "/api/v1/me/login-methods/yandex/link", headers=ext_env.auth(token)
    )
    assert started.status_code == 200, started.text
    q = parse_qs(urlsplit(started.json()["url"]).query)
    fake.profiles["c1"] = YANDEX_NEW
    fake.challenges["c1"] = q["code_challenge"][0]
    params = {"state": q["state"][0], "code": "c1"}

    no_session = await _callback(ext_env, "yandex", params)  # сгорает state
    assert _error(no_session) == "state_invalid"

    started = await ext_env.client.post(
        "/api/v1/me/login-methods/yandex/link", headers=ext_env.auth(token)
    )
    q = parse_qs(urlsplit(started.json()["url"]).query)
    fake.challenges["c1"] = q["code_challenge"][0]
    params = {"state": q["state"][0], "code": "c1"}
    foreign = await _callback(ext_env, "yandex", params, other_token)
    assert _error(foreign) == "state_invalid"

    started = await ext_env.client.post(
        "/api/v1/me/login-methods/yandex/link", headers=ext_env.auth(token)
    )
    q = parse_qs(urlsplit(started.json()["url"]).query)
    fake.challenges["c1"] = q["code_challenge"][0]
    ok = await _callback(ext_env, "yandex", {"state": q["state"][0], "code": "c1"}, token)
    assert ok.status_code == 302 and ok.headers["location"] == "/profile?external=linked"

    methods = (
        await ext_env.client.get("/api/v1/me/login-methods", headers=ext_env.auth(token))
    ).json()
    assert methods["has_password"] is True
    assert [m["provider"] for m in methods["linked"]] == ["yandex"]
    assert methods["available"] == ["google"]
    actions = await _rows(ext_env, "SELECT action FROM domain_event WHERE action LIKE 'user.ext%'")
    assert [a[0] for a in actions] == ["user.external_linked"]
    # теперь вход через Яндекс даёт ту же учётку
    login = await _login_via(ext_env, fake, "yandex", "c2", YANDEX_NEW)
    assert (await ext_env.me(ext_env.token_from(login) or "")).json()["login"] == user.login


async def test_029_identity_linked_elsewhere_is_rejected(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    ws = await _workspace(ext_env)
    first = await ext_env.new_user(role="user", workspace=ws, password=PW)
    second = await ext_env.new_user(role="user", workspace=ws, password=PW)
    for user, code, expected in ((first, "c1", None), (second, "c2", "already_linked")):
        token = await ext_env.login_ok(user)
        started = await ext_env.client.post(
            "/api/v1/me/login-methods/yandex/link", headers=ext_env.auth(token)
        )
        q = parse_qs(urlsplit(started.json()["url"]).query)
        fake.profiles[code] = YANDEX_NEW
        fake.challenges[code] = q["code_challenge"][0]
        done = await _callback(ext_env, "yandex", {"state": q["state"][0], "code": code}, token)
        assert _error(done) == expected


async def test_029_link_of_disabled_provider_is_404(ext_env: ApiEnv) -> None:
    ws = await _workspace(ext_env)
    user = await ext_env.new_user(role="user", workspace=ws, password=PW)
    token = await ext_env.login_ok(user)
    response = await ext_env.client.post(
        "/api/v1/me/login-methods/vk/link", headers=ext_env.auth(token)
    )
    assert response.status_code == 404
    assert response.json()["code"] == "feature_disabled"


async def _identity_session(ext_env: ApiEnv, fake: FakeProviders) -> tuple[str, str]:
    """Пользователь без пароля с одной привязкой Яндекса: ``(токен, id привязки)``."""
    await _workspace(ext_env)
    response = await _login_via(ext_env, fake, "yandex", "c1", YANDEX_NEW)
    token = ext_env.token_from(response) or ""
    methods = (
        await ext_env.client.get("/api/v1/me/login-methods", headers=ext_env.auth(token))
    ).json()
    assert methods["has_password"] is False
    assert methods["linked"][0]["can_unlink"] is False
    return token, methods["linked"][0]["id"]


async def test_029_cannot_unlink_the_last_method(ext_env: ApiEnv, fake: FakeProviders) -> None:
    """AC-8, FR-19."""
    token, identity = await _identity_session(ext_env, fake)
    response = await ext_env.client.delete(
        f"/api/v1/me/login-methods/{identity}", headers=ext_env.auth(token)
    )
    assert response.status_code == 422
    assert response.json()["code"] == "last_login_method"


async def test_029_set_password_then_unlink(ext_env: ApiEnv, fake: FakeProviders) -> None:
    """Q-6: пароль можно задать позже; после этого отвязка разрешена, а повторное задание — нет."""
    token, identity = await _identity_session(ext_env, fake)
    weak = await ext_env.client.post(
        "/api/v1/me/login-methods/password",
        json={"new_password": "short"},
        headers=ext_env.auth(token),
    )
    assert weak.status_code == 422
    done = await ext_env.client.post(
        "/api/v1/me/login-methods/password",
        json={"new_password": PW},
        headers=ext_env.auth(token),
    )
    assert done.status_code == 204, done.text
    again = await ext_env.client.post(
        "/api/v1/me/login-methods/password",
        json={"new_password": PW},
        headers=ext_env.auth(token),
    )
    assert again.status_code == 422 and again.json()["code"] == "password_already_set"
    assert (await ext_env.login("ivanpetrov", PW)).status_code == 200
    removed = await ext_env.client.delete(
        f"/api/v1/me/login-methods/{identity}", headers=ext_env.auth(token)
    )
    assert removed.status_code == 204
    gone = await ext_env.client.delete(
        f"/api/v1/me/login-methods/{identity}", headers=ext_env.auth(token)
    )
    assert gone.status_code == 404
    actions = await _rows(ext_env, "SELECT action FROM domain_event WHERE action LIKE 'user.ext%'")
    assert [a[0] for a in actions] == ["user.external_unlinked"]


async def test_029_unlink_with_two_providers_and_foreign_identity(
    ext_env: ApiEnv, fake: FakeProviders
) -> None:
    ws = await _workspace(ext_env)
    first = await ext_env.new_user(role="user", workspace=ws, password=PW)
    stranger = await ext_env.new_user(role="user", workspace=ws, password=PW)
    token = await ext_env.login_ok(first)
    stranger_token = await ext_env.login_ok(stranger)
    ids = []
    for provider, code, profile in (
        ("yandex", "c1", YANDEX_NEW),
        ("google", "c2", {"sub": "g-1", "email": "z@example.ru", "email_verified": False}),
    ):
        started = await ext_env.client.post(
            f"/api/v1/me/login-methods/{provider}/link", headers=ext_env.auth(token)
        )
        q = parse_qs(urlsplit(started.json()["url"]).query)
        fake.profiles[code] = profile
        fake.challenges[code] = q["code_challenge"][0]
        await _callback(ext_env, provider, {"state": q["state"][0], "code": code}, token)
    methods = (
        await ext_env.client.get("/api/v1/me/login-methods", headers=ext_env.auth(token))
    ).json()
    ids = [m["id"] for m in methods["linked"]]
    assert len(ids) == 2 and methods["available"] == []
    foreign = await ext_env.client.delete(
        f"/api/v1/me/login-methods/{ids[0]}", headers=ext_env.auth(stranger_token)
    )
    assert foreign.status_code == 404
    mine = await ext_env.client.delete(
        f"/api/v1/me/login-methods/{ids[0]}", headers=ext_env.auth(token)
    )
    assert mine.status_code == 204


@pytest.mark.parametrize("provider", ["yandex", "google"])
async def test_029_callback_rate_limit(ext_env: ApiEnv, provider: str) -> None:
    for _ in range(60):
        await ext_env.client.get(f"{CB}/{provider}/callback", params={"state": "x"})
    limited = await ext_env.client.get(f"{CB}/{provider}/callback", params={"state": "x"})
    assert _error(limited) == "provider_unavailable"
