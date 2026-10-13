"""T13: выход, профиль, поведение сессии (plan §4.5-§4.6, D-13, D-14).

AC-20 (блокировка завершает сессию), AC-32, AC-33 (сроки), AC-34 (выход), AC-79 (фоновые
запросы), FR-55/FR-66 (гейты для /me), FR-60, FR-62, FR-67.

Вход выполняется по HTTP (``api_env.login_ok``), время двигает ``api_env.clock``.
Временные роуты — ``add_api_route`` на приложение теста (как в test_deps_gates), чтобы
проверить фон для изменяющего метода.
"""

from datetime import timedelta
from email.utils import parsedate_to_datetime
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends

from tests.conftest import FIXED_NOW, ApiEnv, parse_set_cookie
from tests.factories import get_table

PW = "Sup3r-secret-Pa55phrase-xyz"
BG = {"X-GT-Background": "1"}

# Явная матрица BR-1 (значения Capability — имя члена в нижнем регистре, tasks.md T12).
EXPECTED_CAPABILITIES: dict[str, list[str]] = {
    "tech_admin": ["assign_roles", "manage_accounts", "view_audit"],
    "business_admin": [
        "business_access",
        "crm_read",
        "crm_write",
        "labels_manage",
        "pipeline_manage",
        "project_create",
        "task_assign_others",
    ],
    "mixed": [
        "assign_roles",
        "business_access",
        "crm_read",
        "crm_write",
        "labels_manage",
        "manage_accounts",
        "pipeline_manage",
        "project_create",
        "project_manage_any",
        "task_assign_others",
        "view_audit",
    ],
    "user": ["business_access"],
}


def _code(response: httpx.Response) -> str:
    body = response.json()
    assert isinstance(body, dict)
    return str(body["code"])


async def _last_activity(env: ApiEnv, token: str) -> Any:
    from sqlalchemy import select

    table = get_table("user_session")
    async with env.sessionmaker() as session:
        return (
            await session.execute(
                select(table.c.last_activity_at).where(table.c.id == env.token_id(token))
            )
        ).scalar_one_or_none()


# --- GET /me -------------------------------------------------------------------------------


@pytest.mark.parametrize("role", list(EXPECTED_CAPABILITIES))
async def test_me_returns_profile_and_sorted_capabilities_for_each_role(
    api_env: ApiEnv, role: str
) -> None:
    user = await api_env.new_user(role=role, password=PW)
    token = await api_env.login_ok(user)

    response = await api_env.me(token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"id", "login", "role", "must_change_password", "capabilities"}
    assert body["id"] == str(user.id)
    assert body["login"] == user.login
    assert body["role"] == role
    assert body["must_change_password"] is False
    assert body["capabilities"] == EXPECTED_CAPABILITIES[role]
    assert body["capabilities"] == sorted(body["capabilities"])
    # ни токена, ни хеша
    assert token not in response.text
    assert user.password_hash not in response.text


async def test_me_without_cookie_is_401_not_authenticated(api_env: ApiEnv) -> None:
    response = await api_env.client.get("/api/v1/me")
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


async def test_fr66_me_without_role_is_403_no_role(api_env: ApiEnv) -> None:
    """Plan §4.6: ``GET /me`` — «активный (п.1–3)», гейт «без роли» применяется (FR-66, AC-75)."""
    user = await api_env.new_user(role=None, password=PW)
    token = await api_env.login_ok(user)
    response = await api_env.me(token)
    assert response.status_code == 403
    assert _code(response) == "no_role"


async def test_fr55_me_with_one_time_password_is_403_password_change_required(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=PW, must_change_password=True)
    token = await api_env.login_ok(user)
    response = await api_env.me(token)
    assert response.status_code == 403
    assert _code(response) == "password_change_required"


async def test_fr67_me_reflects_role_change_without_relogin(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    assert (await api_env.me(token)).json()["capabilities"] == ["business_access"]

    member = get_table("workspace_member")
    await api_env.execute(member.update().where(member.c.user_id == user.id).values(role="mixed"))

    body = (await api_env.me(token)).json()
    assert body["role"] == "mixed"
    assert body["capabilities"] == EXPECTED_CAPABILITIES["mixed"]


# --- logout (AC-34, FR-60) -----------------------------------------------------------------


async def test_ac34_fr60_logout_deletes_session_and_token_stops_working(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    assert (await api_env.me(token)).status_code == 200
    assert len(await api_env.session_ids(user.id)) == 1

    response = await api_env.client.post("/api/v1/auth/logout", headers=api_env.auth(token))

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert await api_env.session_ids(user.id) == []  # FR-60: удалена на сервере
    after = await api_env.me(token)
    assert after.status_code == 401
    assert _code(after) == "not_authenticated"


async def test_logout_clears_cookie(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    response = await api_env.client.post("/api/v1/auth/logout", headers=api_env.auth(token))

    morsel = parse_set_cookie(response, "gt_session")
    assert morsel is not None, "logout не сбросил cookie"
    assert morsel.value == ""
    assert morsel["path"] == "/"
    expires = morsel["expires"]
    expired = bool(expires) and parsedate_to_datetime(expires) < FIXED_NOW
    assert morsel["max-age"] == "0" or expired, (morsel["max-age"], expires)


async def test_logout_cookie_clearing_carries_same_flags_when_secure(
    api_env_secure: ApiEnv,
) -> None:
    env = api_env_secure
    user = await env.new_user(role="user", password=PW)
    token = await env.login_ok(user)
    response = await env.client.post("/api/v1/auth/logout", headers=env.auth(token))
    morsel = parse_set_cookie(response, "gt_session")
    assert morsel is not None
    assert morsel["path"] == "/"
    assert morsel["secure"]
    assert morsel["httponly"]
    assert str(morsel["samesite"]).lower() == "lax"


async def test_logout_only_ends_own_session(api_env: ApiEnv) -> None:
    """AC-31 (два браузера): выход в одном не затрагивает вторую сессию того же пользователя."""
    user = await api_env.new_user(role="user", password=PW)
    first = await api_env.login_ok(user)
    second = await api_env.login_ok(user)
    await api_env.client.post("/api/v1/auth/logout", headers=api_env.auth(first))
    assert (await api_env.me(first)).status_code == 401
    assert (await api_env.me(second)).status_code == 200
    assert len(await api_env.session_ids(user.id)) == 1


async def test_logout_twice_is_safe(api_env: ApiEnv) -> None:
    """Повтор выхода: plan — «аутентифицирован» (401 для уже завершённой сессии); допустим
    и идемпотентный 204. Главное — не 5xx и сессия не воскресает."""
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    first = await api_env.client.post("/api/v1/auth/logout", headers=api_env.auth(token))
    second = await api_env.client.post("/api/v1/auth/logout", headers=api_env.auth(token))
    assert first.status_code == 204
    assert second.status_code in (204, 401)
    if second.status_code == 401:
        assert _code(second) == "not_authenticated"
    assert (await api_env.me(token)).status_code == 401


async def test_logout_without_cookie_is_401(api_env: ApiEnv) -> None:
    response = await api_env.client.post("/api/v1/auth/logout")
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


async def test_ac75_logout_allowed_with_one_time_password(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW, must_change_password=True)
    token = await api_env.login_ok(user)
    response = await api_env.client.post("/api/v1/auth/logout", headers=api_env.auth(token))
    assert response.status_code == 204
    assert (await api_env.me(token)).status_code == 401
    assert await api_env.session_ids(user.id) == []


async def test_ac75_logout_allowed_without_role(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role=None, password=PW)
    token = await api_env.login_ok(user)
    response = await api_env.client.post("/api/v1/auth/logout", headers=api_env.auth(token))
    assert response.status_code == 204
    assert await api_env.session_ids(user.id) == []


# --- блокировка завершает сессию (AC-20, FR-62) ---------------------------------------------


async def test_ac20_blocking_user_makes_next_request_401(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    assert (await api_env.me(token)).status_code == 200

    table = get_table("app_user")
    await api_env.execute(
        table.update().where(table.c.id == user.id).values(is_blocked=True, blocked_at=FIXED_NOW)
    )

    response = await api_env.me(token)
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"
    # заблокированный не может войти заново (тот же ответ, что и на неверный пароль)
    relogin = await api_env.login(user.login, PW)
    assert relogin.status_code == 401
    assert _code(relogin) == "invalid_credentials"


async def test_fr62_deleting_sessions_makes_token_401(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    table = get_table("user_session")
    await api_env.execute(table.delete().where(table.c.user_id == user.id))
    assert (await api_env.me(token)).status_code == 401


# --- сроки сессии (AC-32, AC-33, AC-79, FR-59) -----------------------------------------------


async def test_ac32_session_idle_for_8_hours_is_401(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    api_env.clock.advance(timedelta(hours=8))
    response = await api_env.me(token)
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


async def test_ac32_session_idle_just_under_8_hours_is_valid(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    api_env.clock.advance(timedelta(hours=7, minutes=59))
    assert (await api_env.me(token)).status_code == 200


async def test_ac32_regular_requests_extend_idle_timeout(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    for _ in range(3):
        api_env.clock.advance(timedelta(hours=7))
        assert (await api_env.me(token)).status_code == 200
    assert await _last_activity(api_env, token) == FIXED_NOW + timedelta(hours=21)


async def test_ac33_absolute_lifetime_7_days_even_with_continuous_activity(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    # непрерывное использование: запрос каждые 7 часов, последний ровно за 7 ч до границы
    for _ in range(23):
        api_env.clock.advance(timedelta(hours=7))
        assert (await api_env.me(token)).status_code == 200, "сессия истекла раньше 7 суток"
    api_env.clock.advance(timedelta(hours=6, minutes=59))  # 6 сут 23 ч 59 мин с входа
    assert (await api_env.me(token)).status_code == 200
    api_env.clock.advance(timedelta(minutes=1))  # ровно 7 суток с входа
    response = await api_env.me(token)
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


async def test_ac33_session_older_than_7_days_but_active_a_minute_ago_is_401(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    table = get_table("user_session")
    await api_env.execute(
        table.update()
        .where(table.c.user_id == user.id)
        .values(last_activity_at=FIXED_NOW + timedelta(days=7) - timedelta(minutes=1))
    )
    api_env.clock.advance(timedelta(days=7, seconds=1))
    assert (await api_env.me(token)).status_code == 401


async def test_ac79_background_polling_does_not_extend_idle_timeout(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)

    for step in (timedelta(hours=4), timedelta(hours=3, minutes=59)):  # всего 7 ч 59 мин
        api_env.clock.advance(step)
        response = await api_env.me(token, **BG)
        assert response.status_code == 200
    assert await _last_activity(api_env, token) == FIXED_NOW  # фон не продлил

    # обычный запрос после 7 ч 59 мин фона проходит и продлевает
    assert (await api_env.me(token)).status_code == 200
    assert await _last_activity(api_env, token) == FIXED_NOW + timedelta(hours=7, minutes=59)


async def test_ac79_background_polling_then_regular_request_after_8h01_is_401(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    for step in (timedelta(hours=4), timedelta(hours=4, minutes=1)):  # всего 8 ч 01 мин
        api_env.clock.advance(step)
        last = await api_env.me(token, **BG)
    # последний фоновый запрос уже после 8 ч без обычной активности
    assert last.status_code == 401
    assert (await api_env.me(token)).status_code == 401


async def test_ac79_regular_request_between_polls_restarts_idle_timer(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    api_env.clock.advance(timedelta(hours=5))
    assert (await api_env.me(token)).status_code == 200  # обычный: продлевает
    api_env.clock.advance(timedelta(hours=5))
    assert (await api_env.me(token, **BG)).status_code == 200  # 5 ч с обычного
    api_env.clock.advance(timedelta(hours=2, minutes=59))
    assert (await api_env.me(token, **BG)).status_code == 200  # 7 ч 59 мин с обычного
    api_env.clock.advance(timedelta(minutes=2))
    assert (await api_env.me(token, **BG)).status_code == 401  # 8 ч 01 мин


async def test_d14_background_header_value_other_than_1_is_regular_request(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    api_env.clock.advance(timedelta(hours=5))
    assert (await api_env.me(token, **{"X-GT-Background": "0"})).status_code == 200
    assert await _last_activity(api_env, token) == FIXED_NOW + timedelta(hours=5)


async def test_d14_background_header_is_ignored_for_mutating_methods(api_env: ApiEnv) -> None:
    from app.api.deps import get_actor
    from app.domain.access.roles import Actor

    async def touch(actor: Annotated[Actor, Depends(get_actor)]) -> Any:
        return {"ok": True}

    api_env.app.add_api_route("/_t/touch", touch, methods=["POST"])
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)

    api_env.clock.advance(timedelta(hours=5))
    response = await api_env.client.post("/_t/touch", headers=api_env.auth(token, **BG))
    assert response.status_code == 200
    assert await _last_activity(api_env, token) == FIXED_NOW + timedelta(hours=5)
