"""Спека 021, FR-4 / AC-8: согласие при входе через провайдера (Яндекс ID, Google)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import text

from app.domain.legal import documents
from tests.admin_support import code_of
from tests.api.test_029_external_login import (  # noqa: F401  (фикстуры ext_env, fake)
    CB,
    YANDEX_NEW,
    FakeProviders,
    _callback,
    _error,
    _rows,
    _workspace,
    ext_env,
    fake,
)
from tests.conftest import ApiEnv


def _enable(env: ApiEnv) -> None:
    env.app.state.settings.pdn_consent_enabled = True


def _with_consent() -> dict[str, str]:
    return {"consent": "true", "consent_version": documents.current_version()}


async def _login(env: ApiEnv, providers: FakeProviders, code: str, **query: str) -> Any:
    start = await env.client.get(f"{CB}/yandex/start", params=query)
    assert start.status_code == 302
    q = parse_qs(urlsplit(start.headers["location"]).query)
    if "code_challenge" not in q:  # отказ до перехода к провайдеру
        return start
    providers.profiles[code] = YANDEX_NEW
    providers.challenges[code] = q["code_challenge"][0]
    return await _callback(env, "yandex", {"state": q["state"][0], "code": code})


async def test_ac8_start_without_consent_is_refused_before_the_provider(
    ext_env: ApiEnv,  # noqa: F811
) -> None:
    _enable(ext_env)
    for query in ({}, {"consent": "true"}, {"consent": "true", "consent_version": "2000-01-01"}):
        response = await ext_env.client.get(f"{CB}/yandex/start", params=query)
        assert response.status_code == 302
        assert (
            response.headers["location"]
            == "/login?external_error=pdn_consent_required&provider=yandex"
        )
    assert (await _rows(ext_env, "SELECT count(*) FROM oauth_login_state"))[0][0] == 0


async def test_ac8_new_user_is_created_with_the_consent_and_enters(
    ext_env: ApiEnv,  # noqa: F811
    fake: FakeProviders,  # noqa: F811
) -> None:
    _enable(ext_env)
    await _workspace(ext_env)
    response = await _login(ext_env, fake, "c1", **_with_consent())
    token = ext_env.token_from(response)
    assert token
    assert (await ext_env.me(token)).status_code == 200  # согласие уже есть: гейт не срабатывает
    user = (
        await _rows(
            ext_env,
            "SELECT id, pdn_consent_version, pdn_consented_at FROM app_user "
            "WHERE login = 'ivanpetrov'",
        )
    )[0]
    assert user.pdn_consent_version == documents.current_version()
    assert user.pdn_consented_at is not None
    events = await _rows(
        ext_env,
        "SELECT details FROM domain_event "
        "WHERE entity_id = :i AND action = 'user.pdn_consent_given'",
        i=user.id,
    )
    assert [e.details for e in events] == [{"version": documents.current_version()}]


async def test_ac8_state_started_before_the_flag_gives_an_account_with_the_screen(
    ext_env: ApiEnv,  # noqa: F811
    fake: FakeProviders,  # noqa: F811
) -> None:
    await _workspace(ext_env)
    start = await ext_env.client.get(f"{CB}/yandex/start")  # функция ещё выключена
    q = parse_qs(urlsplit(start.headers["location"]).query)
    fake.profiles["c1"] = YANDEX_NEW
    fake.challenges["c1"] = q["code_challenge"][0]
    _enable(ext_env)
    response = await _callback(ext_env, "yandex", {"state": q["state"][0], "code": "c1"})
    token = ext_env.token_from(response)
    assert token
    me = await ext_env.me(token)
    assert (me.status_code, code_of(me)) == (403, "pdn_consent_pending")
    assert _error(response) is None
    row = (await _rows(ext_env, "SELECT pdn_consent_version FROM app_user"))[0]
    assert row.pdn_consent_version is None


async def test_ac8_disabled_function_ignores_consent_params(
    ext_env: ApiEnv,  # noqa: F811
    fake: FakeProviders,  # noqa: F811
) -> None:
    await _workspace(ext_env)
    response = await _login(ext_env, fake, "c1")
    assert ext_env.token_from(response)
    row = (await _rows(ext_env, text("SELECT pdn_consent_version FROM app_user").text))[0]
    assert row.pdn_consent_version is None
