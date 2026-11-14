"""Упрощённый вход, этап (а) (spec 029, FR-1…FR-5): вход по email или логину; «Запомнить меня».

Ответ при отказе одинаковый для неизвестного email, неизвестного логина, неверного пароля и
значения вне шаблона (без раскрытия существования учётки). Срок сессии: без флажка — как раньше
(8 ч простоя, 7 дней абсолютно); с флажком — 30 дней простоя и абсолютно.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.domain.auth.models import UserSession
from app.domain.system.maintenance import purge_expired_sessions
from tests.conftest import ApiEnv

PW = "Correct-Horse-Battery-9"
T0 = datetime(2026, 11, 14, 9, 0, 0, tzinfo=UTC)
LOGIN_PATH = "/api/v1/auth/login"
WEEK = 7 * 24 * 3600
THIRTY_DAYS = 30 * 24 * 3600


async def _post(env: ApiEnv, body: dict[str, Any]) -> Any:
    return await env.client.post(LOGIN_PATH, json=body)


async def test_029a_login_by_login_still_works(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    response = await _post(api_env, {"login": user.login, "password": PW})
    assert response.status_code == 200, response.text


async def test_029a_login_by_email_in_any_case(api_env: ApiEnv) -> None:
    email = "ivanov.petr@example.ru"
    await api_env.new_user(role="user", password=PW, email=email)
    for value in (email, email.upper()):
        response = await _post(api_env, {"login": value, "password": PW})
        assert response.status_code == 200, (value, response.text)


async def test_029a_unknown_email_unknown_login_and_wrong_password_look_identical(
    api_env: ApiEnv,
) -> None:
    email = "ivanov.petr@example.ru"
    user = await api_env.new_user(role="user", password=PW, email=email)
    answers = [
        await _post(api_env, {"login": "nobody.here@example.ru", "password": PW}),
        await _post(api_env, {"login": "nobody.here", "password": PW}),
        await _post(api_env, {"login": user.login, "password": "Wrong-Password-123"}),
        await _post(api_env, {"login": email, "password": "Wrong-Password-123"}),
    ]
    assert {a.status_code for a in answers} == {401}
    assert len({a.text for a in answers}) == 1, [a.text for a in answers]


async def test_029a_malformed_identifiers_get_the_same_answer(api_env: ApiEnv) -> None:
    await api_env.new_user(role="user", password=PW)
    unknown = await _post(api_env, {"login": "nobody.here@example.ru", "password": PW})
    for value in ("@example.ru", "a@", "bad@@example.ru", "почта@example.ru", "x" * 300 + "@x.ru"):
        response = await _post(api_env, {"login": value, "password": PW})
        assert response.status_code == 401, (value, response.text)
        assert response.text == unknown.text, value


async def test_029a_remember_flag_sets_thirty_day_cookie_and_session_row(api_env: ApiEnv) -> None:
    api_env.clock.set(T0)
    user = await api_env.new_user(role="user", password=PW)

    plain = await _post(api_env, {"login": user.login, "password": PW})
    assert plain.status_code == 200
    plain_token = api_env.token_from(plain)
    assert plain_token is not None
    assert f"Max-Age={WEEK}" in plain.headers["set-cookie"]

    remembered = await _post(api_env, {"login": user.login, "password": PW, "remember": True})
    assert remembered.status_code == 200
    token = api_env.token_from(remembered)
    assert token is not None
    assert f"Max-Age={THIRTY_DAYS}" in remembered.headers["set-cookie"]

    async with api_env.sessionmaker() as db:
        row = (
            await db.execute(select(UserSession).where(UserSession.id == api_env.token_id(token)))
        ).scalar_one()
        plain_row = (
            await db.execute(
                select(UserSession).where(UserSession.id == api_env.token_id(plain_token))
            )
        ).scalar_one()
    assert row.remember is True and row.auth_method == "password"
    assert row.absolute_expires_at == T0 + timedelta(days=30)
    assert plain_row.remember is False
    assert plain_row.absolute_expires_at == T0 + timedelta(days=7)


async def test_029a_default_session_expires_after_eight_hours_idle(api_env: ApiEnv) -> None:
    api_env.clock.set(T0)
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    api_env.clock.set(T0 + timedelta(hours=8))
    assert (await api_env.me(token)).status_code == 401


async def test_029a_remember_session_survives_eight_hours_idle(api_env: ApiEnv) -> None:
    api_env.clock.set(T0)
    user = await api_env.new_user(role="user", password=PW)
    response = await _post(api_env, {"login": user.login, "password": PW, "remember": True})
    token = api_env.token_from(response)
    assert token is not None
    api_env.clock.set(T0 + timedelta(hours=9))
    assert (await api_env.me(token)).status_code == 200
    # простой по «Запомнить меня» — 30 дней: после 31 дня без активности сессии уже нет
    api_env.clock.set(T0 + timedelta(hours=9) + timedelta(days=31))
    assert (await api_env.me(token)).status_code == 401


async def test_029a_cleanup_keeps_remembered_sessions_inside_their_window(
    api_env: ApiEnv,
) -> None:
    api_env.clock.set(T0)
    user = await api_env.new_user(role="user", password=PW)
    plain = await api_env.login_ok(user)
    remembered_response = await _post(
        api_env, {"login": user.login, "password": PW, "remember": True}
    )
    remembered = api_env.token_from(remembered_response)
    assert remembered is not None
    now = T0 + timedelta(hours=9)
    deleted = await purge_expired_sessions(
        api_env.sessionmaker,
        now=now,
        idle_timeout=api_env.settings.session_idle_timeout,
        remember_idle_timeout=api_env.settings.session_remember_timeout,
    )
    assert deleted == 1  # только сессия без «Запомнить меня» (простой больше 8 ч)
    api_env.clock.set(now)
    assert (await api_env.me(remembered)).status_code == 200
    assert plain is not None


async def test_029a_lock_counts_failures_by_email_and_by_login_together(api_env: ApiEnv) -> None:
    """FR-3: пять неверных паролей по email блокируют учётку и для входа по логину."""
    email = "lock.test@example.ru"
    user = await api_env.new_user(role="user", password=PW, email=email)
    for _ in range(5):
        assert (
            await _post(api_env, {"login": email, "password": "Wrong-Password-123"})
        ).status_code == 401
    locked = await _post(api_env, {"login": user.login, "password": PW})
    assert locked.status_code == 401, locked.text
