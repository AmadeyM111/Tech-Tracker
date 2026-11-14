"""Спека 021: согласие на обработку ПДн (AC-1…AC-7; контракт — specs/021-pdn-consent-form §4)."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import Settings
from app.domain.legal import documents
from app.main import _check_legal_ready, create_app
from tests.admin_support import code_of, events, new_workspace, seed
from tests.conftest import RESET_SETTINGS, ApiEnv, _open_api_env
from tests.mail_support import RecordingMailer

REQUEST = "/api/v1/auth/registration/request"
CONFIRM = "/api/v1/auth/registration/confirm"
ACCEPT = "/api/v1/me/pdn-consent"
PW = "Zq7-registration-pw"
LINK_PREFIX = "https://tracker.example.test/register/confirm#token="


@pytest_asyncio.fixture
async def pdn_env(
    settings: Settings, fixed_clock: Any, db_sessionmaker: Any
) -> AsyncIterator[ApiEnv]:
    """Функция согласия включена (с заглушками реквизитов: env=test это допускает)."""
    enabled = settings.model_copy(update={**RESET_SETTINGS, "pdn_consent_enabled": True})
    application = create_app(enabled, clock=fixed_clock)
    async for env in _open_api_env(
        application, enabled, fixed_clock, db_sessionmaker, "http://testserver"
    ):
        application.state.mailer = RecordingMailer()
        await new_workspace(env)
        yield env


def _body(email: str, **extra: Any) -> dict[str, Any]:
    return {
        "email": email,
        "first_name": "Анна",
        "last_name": "Петрова",
        "password": PW,
        **extra,
    }


def _ok() -> dict[str, Any]:
    return {"pdn_consent": True, "pdn_consent_version": documents.current_version()}


async def _rows(env: ApiEnv, sql: str, **params: Any) -> list[Any]:
    rows = await env.execute(text(sql).bindparams(**params))
    assert rows is not None
    return list(rows)


# --- FR-1, FR-2: тексты и реквизиты как данные ------------------------------------------


def test_fr1_versions_are_one_date_for_both_documents() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", documents.current_version())
    assert documents.load("privacy").version == documents.load("consent").version


def test_fr1_texts_have_no_consultant_header_and_no_unresolved_slots() -> None:
    for kind in documents.KINDS:
        joined = " ".join(p for s in documents.load(kind).sections for p in s.paragraphs)
        for banned in (
            "Внимание!",
            "15 000 000",
            "+7-951",
            "WhatsApp",
            "распространяется безвозмездно",
        ):
            assert banned not in joined, (kind, banned)
        assert "{" not in joined and "}" not in joined, kind


def test_fr1_contact_email_and_provider_transfer_are_in_the_texts() -> None:
    privacy = " ".join(p for s in documents.load("privacy").sections for p in s.paragraphs)
    assert documents.requisites()["contact_email"] == "support@leggent.ru"
    assert "support@leggent.ru" in privacy
    assert "Вход через провайдера — это передача данных провайдеру" in privacy


def test_fr9_requisites_are_filled_and_the_postal_address_is_optional() -> None:
    req = documents.requisites()
    assert req["operator_name"].startswith("Индивидуальный предприниматель")
    assert (req["operator_ogrn"], req["operator_inn"]) == ("324774600650295", "771975146252")
    assert "operator_address" not in req  # ИП работает онлайн: почтового адреса нет
    assert documents.unfilled_placeholders() == []
    assert req["postal_part"] == "" and req["postal_part_dot"] == ""
    joined = " ".join(
        p for k in documents.KINDS for s in documents.load(k).sections for p in s.paragraphs
    )
    assert "ЕГРИП по ИНН 771975146252" in joined
    assert "Адрес для обращений: электронная почта support@leggent.ru" in joined
    assert "почтовый адрес" not in joined.lower()


def _patched_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **requisites: str) -> None:
    """Копия документов с изменёнными реквизитами; кэши загрузчика сбрасываются до и после."""
    target = tmp_path / "documents"
    shutil.copytree(documents.DOCUMENTS_DIR, target)
    raw = json.loads((target / "requisites.json").read_text(encoding="utf-8"))
    raw.update(requisites)
    (target / "requisites.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(documents, "DOCUMENTS_DIR", target)
    documents.requisites.cache_clear()
    documents.load.cache_clear()
    documents.current_version.cache_clear()


@pytest.fixture
def clean_legal_caches() -> Iterator[None]:
    yield
    documents.requisites.cache_clear()
    documents.load.cache_clear()
    documents.current_version.cache_clear()


def test_fr9_postal_address_is_shown_when_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_legal_caches: None
) -> None:
    _patched_documents(
        tmp_path, monkeypatch, operator_postal_address="г. Москва, ул. Примерная, д. 1"
    )
    joined = " ".join(p for sec in documents.load("privacy").sections for p in sec.paragraphs)
    assert "почтовый адрес: г. Москва, ул. Примерная, д. 1" in joined
    assert "Почтовый адрес: г. Москва, ул. Примерная, д. 1." in joined


# --- FR-9, AC-6: гейт реквизитов -------------------------------------------------------


def test_ac6_production_with_placeholders_refuses_to_start(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_legal_caches: None,
) -> None:
    prod = settings.model_copy(update={"env": "production", "pdn_consent_enabled": True})
    _check_legal_ready(prod)  # реквизиты заполнены: запуск разрешён
    _patched_documents(tmp_path, monkeypatch, operator_ogrn=documents.PLACEHOLDER)
    with pytest.raises(RuntimeError, match=r"\[ЗАПОЛНИТЬ\]"):
        _check_legal_ready(prod)


def test_ac6_disabled_flag_or_test_env_does_not_check(settings: Settings) -> None:
    _check_legal_ready(settings.model_copy(update={"env": "production"}))
    _check_legal_ready(settings.model_copy(update={"pdn_consent_enabled": True}))  # env=test


def test_ac6_check_script_exit_code_follows_placeholders() -> None:
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "check_legal_requisites.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script)], capture_output=True, text=True, check=False
    )
    assert (result.returncode == 1) == bool(documents.unfilled_placeholders())


# --- AC-4: публичные тексты -------------------------------------------------------------


async def test_ac4_public_texts_without_cookie(pdn_env: ApiEnv) -> None:
    status = await pdn_env.client.get("/api/v1/legal")
    assert status.json() == {"enabled": True, "version": documents.current_version()}
    for kind in ("privacy", "consent"):
        response = await pdn_env.client.get(f"/api/v1/legal/{kind}")
        assert response.status_code == 200
        body = response.json()
        assert body["kind"] == kind
        assert body["version"] == body["effective_date"] == documents.current_version()
        assert body["sections"] and "Внимание!" not in response.text
    assert (await pdn_env.client.get("/api/v1/legal/other")).status_code == 422


async def test_ac5_disabled_texts_are_404_and_status_says_so(api_env: ApiEnv) -> None:
    status = await api_env.client.get("/api/v1/legal")
    assert status.json()["enabled"] is False
    response = await api_env.client.get("/api/v1/legal/privacy")
    assert response.status_code == 404
    assert code_of(response) == "feature_disabled"


# --- AC-1, AC-2, AC-7: регистрация -------------------------------------------------------


async def test_ac1_registration_without_consent_is_422_and_nothing_stored(pdn_env: ApiEnv) -> None:
    for extra in ({}, {"pdn_consent": False, "pdn_consent_version": documents.current_version()}):
        response = await pdn_env.client.post(REQUEST, json=_body("a@example.test", **extra))
        assert response.status_code == 422
        assert code_of(response) == "pdn_consent_required"
    assert not pdn_env.app.state.mailer.sent
    assert await _rows(pdn_env, "SELECT 1 FROM registration_request") == []


async def test_ac1_stale_or_missing_version_is_422_mismatch(pdn_env: ApiEnv) -> None:
    for version in ("2000-01-01", None):
        response = await pdn_env.client.post(
            REQUEST, json=_body("a@example.test", pdn_consent=True, pdn_consent_version=version)
        )
        assert response.status_code == 422
        assert code_of(response) == "pdn_consent_version_mismatch"


async def test_ac1_consent_is_checked_before_the_rest_of_the_form(pdn_env: ApiEnv) -> None:
    response = await pdn_env.client.post(REQUEST, json=_body("not-an-email"))
    assert code_of(response) == "pdn_consent_required"


async def test_ac2_confirm_copies_version_to_account_and_writes_event(pdn_env: ApiEnv) -> None:
    address = "anna@example.test"
    response = await pdn_env.client.post(REQUEST, json=_body(address, **_ok()))
    assert response.status_code == 200
    pending = await _rows(
        pdn_env, "SELECT pdn_consent_version, pdn_consent_at FROM registration_request"
    )
    assert pending[0][0] == documents.current_version() and pending[0][1] is not None
    token = pdn_env.app.state.mailer.sent[-1].body.split(LINK_PREFIX, 1)[1].split()[0]
    assert (await pdn_env.client.post(CONFIRM, json={"token": token})).status_code == 200
    user = await _rows(
        pdn_env,
        "SELECT id, pdn_consent_version, pdn_consented_at FROM app_user WHERE email = :e",
        e=address,
    )
    assert user[0][1] == documents.current_version() and user[0][2] is not None
    given = [
        e
        for e in await events(pdn_env, entity_id=user[0][0])
        if e.action == "user.pdn_consent_given"
    ]
    assert len(given) == 1
    assert given[0].details == {"version": documents.current_version()}  # AC-7: только версия
    assert given[0].actor_id == user[0][0]


async def test_ac5_disabled_registration_ignores_consent(
    reset_api_env: ApiEnv,
) -> None:
    await new_workspace(reset_api_env)
    response = await reset_api_env.client.post(REQUEST, json=_body("b@example.test"))
    assert response.status_code == 200


# --- AC-3: гейт и экран подтверждения -----------------------------------------------------


async def _user_with_session(env: ApiEnv, **kwargs: Any) -> tuple[Any, str]:
    ws = await new_workspace(env)
    user, (token,) = await seed(env, ws, "user", **kwargs)
    return user, token


async def test_ac3_user_without_consent_is_blocked_everywhere_but_logout_and_accept(
    pdn_env: ApiEnv,
) -> None:
    user, token = await _user_with_session(pdn_env)
    for url in ("/api/v1/me", "/api/v1/projects", "/api/v1/me/tokens"):
        response = await pdn_env.client.get(url, headers=pdn_env.auth(token))
        assert response.status_code == 403, url
        assert code_of(response) == "pdn_consent_pending"
    accepted = await pdn_env.client.post(ACCEPT, json=_ok(), headers=pdn_env.auth(token))
    assert accepted.status_code == 204
    assert (await pdn_env.me(token)).status_code == 200
    row = await pdn_env.user_row(user.id)
    assert row.pdn_consent_version == documents.current_version()
    assert row.pdn_consented_at is not None
    given = [
        e for e in await events(pdn_env, entity_id=user.id) if e.action == "user.pdn_consent_given"
    ]
    assert len(given) == 1 and given[0].details == {"version": documents.current_version()}


async def test_ac3_logout_is_available_without_consent(pdn_env: ApiEnv) -> None:
    _user, token = await _user_with_session(pdn_env)
    response = await pdn_env.client.post("/api/v1/auth/logout", headers=pdn_env.auth(token))
    assert response.status_code == 204


async def test_ac3_accept_rejects_unchecked_and_stale_version(pdn_env: ApiEnv) -> None:
    _user, token = await _user_with_session(pdn_env)
    headers = pdn_env.auth(token)
    unchecked = await pdn_env.client.post(
        ACCEPT,
        json={"pdn_consent": False, "pdn_consent_version": documents.current_version()},
        headers=headers,
    )
    assert (unchecked.status_code, code_of(unchecked)) == (422, "pdn_consent_required")
    stale = await pdn_env.client.post(
        ACCEPT, json={"pdn_consent": True, "pdn_consent_version": "2000-01-01"}, headers=headers
    )
    assert (stale.status_code, code_of(stale)) == (422, "pdn_consent_version_mismatch")
    assert (await pdn_env.me(token)).status_code == 403


async def test_ac3_accept_needs_a_session(pdn_env: ApiEnv) -> None:
    response = await pdn_env.client.post(ACCEPT, json=_ok())
    assert response.status_code == 401


async def test_fr6_new_version_asks_again(pdn_env: ApiEnv) -> None:
    user, token = await _user_with_session(pdn_env)
    await pdn_env.execute(
        text(
            "UPDATE app_user SET pdn_consent_version = '2000-01-01', pdn_consented_at = now() "
            "WHERE id = :i"
        ).bindparams(i=user.id)
    )
    response = await pdn_env.me(token)
    assert (response.status_code, code_of(response)) == (403, "pdn_consent_pending")


async def test_ac5_disabled_flag_gives_no_gate_for_existing_users(api_env: ApiEnv) -> None:
    ws = await new_workspace(api_env)
    _user, (token,) = await seed(api_env, ws, "user")
    assert (await api_env.me(token)).status_code == 200


async def test_forced_password_change_comes_before_consent(pdn_env: ApiEnv) -> None:
    ws = await new_workspace(pdn_env)
    _user, (token,) = await seed(pdn_env, ws, "user", must_change_password=True)
    response = await pdn_env.me(token)
    assert code_of(response) == "password_change_required"
