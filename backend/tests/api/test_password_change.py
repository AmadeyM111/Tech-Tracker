"""T14: POST /api/v1/auth/password (plan §4.6; FR-52, FR-53, FR-55, FR-56, FR-57, FR-61, FR-66).

AC-23 (файл пароля первого ТА удаляется ПОСЛЕ COMMIT), AC-27, AC-28, AC-29, AC-31, AC-75,
AC-113 (часть), AC-115. Решения оркестратора (tasks.md T14, «Уточнения»):

1. неверный ``current_password`` считается тем же счётчиком и порогом, что вход (FR-61):
   5 подряд -> ``login_locked_until = now + 15 мин`` и текущая сессия завершена; ответ на
   неверный current всегда 422 ``invalid_current_password``; успешная смена сбрасывает счётчик;
2. файл пароля первого ТА удаляется после успешного COMMIT; сбой COMMIT оставляет файл; сбой
   удаления не меняет результат (204);
3. ``max_length`` 1024 у полей пароля и логина (422 без эха); суррогат в пароле -> 422, не 500.

FR-65 (сброс пароля администратором): эндпоинта сброса в R1.0 ещё нет (T16) — здесь проверяется
только то, что одноразовый пароль (``must_change_password = true``) требует смены.

Счётчик и блокировка проверяются на реальных фиксациях (``committed_api_env``): отказ — это
исключение, ``get_db`` откатывает транзакцию запроса, а счётчик обязан её пережить.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from tests.conftest import FIXED_NOW, ApiEnv

PW = "Sup3r-secret-Pa55phrase-xyz"
NEW = "Br4nd-new-Pa55phrase-uvw"
NEW2 = "Sec0nd-new-Pa55phrase-rst"
WRONG = "Wr0ng-Pa55phrase-unique-qq"
BAD = "Wr0ng-L0gin-Pa55phrase-zz"
PASSWORD_URL = "/api/v1/auth/password"
LOGOUT_URL = "/api/v1/auth/logout"
INITIAL_FILE = "initial-admin-password.txt"
SHORT_11 = "zq9-lk3-px7"
LOCK = timedelta(minutes=15)


def _code(response: httpx.Response) -> str:
    body = response.json()
    assert isinstance(body, dict)
    return str(body["code"])


async def _change(
    env: ApiEnv,
    token: str,
    current: str,
    new: str,
    *,
    client: httpx.AsyncClient | None = None,
    **headers: str,
) -> httpx.Response:
    return await (client or env.client).post(
        PASSWORD_URL,
        json={"current_password": current, "new_password": new},
        headers=env.auth(token, **headers),
    )


async def _active(env: ApiEnv, **kwargs: Any) -> tuple[Any, str]:
    kwargs.setdefault("role", "user")
    kwargs.setdefault("password", PW)
    user = await env.new_user(**kwargs)
    return user, await env.login_ok(user)


def _same_failure(response: httpx.Response, reference: httpx.Response) -> bool:
    return (
        response.status_code == reference.status_code
        and response.json() == reference.json()
        and not response.headers.get_list("set-cookie")
        and {k: v for k, v in response.headers.items() if k != "date"}
        == {k: v for k, v in reference.headers.items() if k != "date"}
    )


@asynccontextmanager
async def _quiet_client(env: ApiEnv) -> AsyncIterator[httpx.AsyncClient]:
    """Клиент, не пробрасывающий необработанные исключения приложения (нужен ответ 500)."""
    transport = httpx.ASGITransport(app=env.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=env.base_url) as client:
        yield client


def _initial_file(env: ApiEnv, login: str, password: str = "irrelevant-pass-1") -> Path:
    directory = env.settings.secrets_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / INITIAL_FILE
    path.write_text(f"login={login}\npassword={password}\n", encoding="utf-8")
    return path


# --- успех (AC-29, AC-31, FR-56) ------------------------------------------------------------


async def test_ac29_change_password_returns_204_and_clears_must_change_flag(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user, token = await _active(env, must_change_password=True)
    before = await env.user_row(user.id)
    assert before.must_change_password is True

    response = await _change(env, token, PW, NEW)

    assert response.status_code == 204, response.text
    assert response.content == b""
    after = await env.user_row(user.id)
    assert after.must_change_password is False
    assert after.password_hash != before.password_hash
    assert after.password_hash.startswith("$argon2id$")
    assert NEW not in after.password_hash
    me = await env.me(token)
    assert me.status_code == 200
    assert me.json()["must_change_password"] is False


async def test_ac29_old_password_no_longer_logs_in_and_new_one_does(api_env: ApiEnv) -> None:
    env = api_env
    user, token = await _active(env)
    assert (await _change(env, token, PW, NEW)).status_code == 204

    old = await env.login(user.login, PW)
    assert old.status_code == 401
    assert _code(old) == "invalid_credentials"
    assert env.token_from(old) is None
    new = await env.login(user.login, NEW)
    assert new.status_code == 200
    assert env.token_from(new)


async def test_ac29_password_changed_at_is_current_time(api_env: ApiEnv) -> None:
    env = api_env
    user, token = await _active(env)
    env.clock.advance(timedelta(minutes=5))

    assert (await _change(env, token, PW, NEW)).status_code == 204

    assert (await env.user_row(user.id)).password_changed_at == FIXED_NOW + timedelta(minutes=5)


async def test_ac31_other_sessions_are_removed_current_one_stays(api_env: ApiEnv) -> None:
    """Два «браузера» одного пользователя; чужие сессии не затрагиваются."""
    env = api_env
    user = await env.new_user(role="user", password=PW)
    browser_a = await env.login_ok(user)
    browser_b = await env.login_ok(user)
    other, other_token = await _active(env)
    assert len(await env.session_ids(user.id)) == 2

    response = await _change(env, browser_a, PW, NEW)

    assert response.status_code == 204
    assert (await env.me(browser_a)).status_code == 200
    gone = await env.me(browser_b)
    assert (gone.status_code, _code(gone)) == (401, "not_authenticated")
    assert await env.session_ids(user.id) == [env.token_id(browser_a)]
    assert (await env.me(other_token)).status_code == 200
    assert len(await env.session_ids(other.id)) == 1


# --- четыре кода 422 (AC-27, AC-28, AC-115, FR-52, FR-53, FR-56, FR-57) ---------------------


@pytest.mark.parametrize(
    ("current", "new", "code"),
    [
        (WRONG, NEW, "invalid_current_password"),
        (PW, PW, "password_reused"),
        (PW, SHORT_11, "password_too_short"),
    ],
)
async def test_fr56_rejected_change_gives_422_code_and_changes_nothing(
    api_env: ApiEnv, current: str, new: str, code: str
) -> None:
    env = api_env
    user, token = await _active(env, must_change_password=True)
    other = await env.login_ok(user)
    before = await env.user_row(user.id)

    response = await _change(env, token, current, new)

    assert response.status_code == 422, response.text
    assert _code(response) == code
    for secret in (current, new):
        assert secret not in response.text
    after = await env.user_row(user.id)
    assert after.password_hash == before.password_hash
    assert after.must_change_password is True
    assert after.password_changed_at == before.password_changed_at
    assert len(await env.session_ids(user.id)) == 2
    assert (await env.client.get("/api/v1/me", headers=env.auth(other))).status_code in (200, 403)


def _common_entry(minimum: int = 12) -> str:
    from app.core.security.common_passwords import is_common_password
    from tests.db_support import BACKEND_DIR

    path = BACKEND_DIR / "app" / "core" / "security" / "data" / "common-passwords-10k.txt"
    entries = path.read_text(encoding="utf-8").split("\n")[:-1]
    entry = next(e for e in entries if len(e) >= minimum and e != PW and e.isascii())
    assert is_common_password(entry)
    return entry


async def test_ac28_common_password_of_12_plus_chars_is_422_password_too_common(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user, token = await _active(env)
    common = _common_entry()
    before = (await env.user_row(user.id)).password_hash

    response = await _change(env, token, PW, common)

    assert (response.status_code, _code(response)) == (422, "password_too_common")
    assert common not in response.text
    assert (await env.user_row(user.id)).password_hash == before


async def test_ac27_boundary_eleven_chars_rejected_twelve_accepted(api_env: ApiEnv) -> None:
    env = api_env
    user, token = await _active(env)
    short = await _change(env, token, PW, SHORT_11)
    assert (short.status_code, _code(short)) == (422, "password_too_short")
    assert (await _change(env, token, PW, SHORT_11 + "w")).status_code == 204


async def test_ac27_short_and_common_password_reports_too_short(api_env: ApiEnv) -> None:
    """Порядок проверок: длина раньше списка частых (ревью T08)."""
    from app.core.security.common_passwords import is_common_password
    from tests.db_support import BACKEND_DIR

    path = BACKEND_DIR / "app" / "core" / "security" / "data" / "common-passwords-10k.txt"
    entries = path.read_text(encoding="utf-8").split("\n")[:-1]
    short_common = next(e for e in entries if 4 <= len(e) < 12 and e.isascii())
    assert is_common_password(short_common)
    env = api_env
    _, token = await _active(env)

    response = await _change(env, token, PW, short_common)

    assert (response.status_code, _code(response)) == (422, "password_too_short")


async def test_ac115_common_password_with_changed_letter_case_is_accepted(
    api_env: ApiEnv,
) -> None:
    from app.core.security.common_passwords import is_common_password
    from tests.db_support import BACKEND_DIR

    path = BACKEND_DIR / "app" / "core" / "security" / "data" / "common-passwords-10k.txt"
    variant = None
    for entry in path.read_text(encoding="utf-8").split("\n")[:-1]:
        if len(entry) < 12 or not entry.isascii():
            continue
        idx = next((i for i, ch in enumerate(entry) if ch.islower()), None)
        if idx is None:
            continue
        candidate = entry[:idx] + entry[idx].upper() + entry[idx + 1 :]
        if candidate != PW and not is_common_password(candidate):
            variant = candidate
            break
    assert variant is not None
    env = api_env
    user, token = await _active(env)

    response = await _change(env, token, PW, variant)

    assert response.status_code == 204, response.text
    assert (await env.login(user.login, variant)).status_code == 200


async def test_fr56_current_password_is_checked_before_policy_and_reuse(api_env: ApiEnv) -> None:
    env = api_env
    _, token = await _active(env)
    response = await _change(env, token, WRONG, "short")
    assert (response.status_code, _code(response)) == (422, "invalid_current_password")
    response = await _change(env, token, WRONG, WRONG)
    assert (response.status_code, _code(response)) == (422, "invalid_current_password")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"current_password": PW},
        {"new_password": NEW},
        {"current_password": PW, "new_password": 12345678901234},
        {"current_password": None, "new_password": NEW},
    ],
)
async def test_fr56_malformed_body_is_422_validation_error(
    api_env: ApiEnv, payload: dict[str, Any]
) -> None:
    env = api_env
    _, token = await _active(env)
    response = await env.client.post(PASSWORD_URL, json=payload, headers=env.auth(token))
    assert (response.status_code, _code(response)) == (422, "validation_error")
    assert PW not in response.text
    assert NEW not in response.text


async def test_fr7_password_endpoint_requires_authentication(api_env: ApiEnv) -> None:
    env = api_env
    body = {"current_password": PW, "new_password": NEW}
    response = await env.client.post(PASSWORD_URL, json=body)
    assert (response.status_code, _code(response)) == (401, "not_authenticated")
    response = await env.client.post(
        PASSWORD_URL, json=body, headers=env.auth("not-a-real-token-0123456789abcdef")
    )
    assert (response.status_code, _code(response)) == (401, "not_authenticated")


# --- одноразовый пароль (AC-29, AC-113, FR-55) ----------------------------------------------


async def test_ac113_one_time_password_login_reports_must_change_and_blocks_other_requests(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user = await env.new_user(role="user", password=PW, must_change_password=True)
    login = await env.login(user.login, PW)
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True
    token = env.token_from(login)
    assert token

    me = await env.me(token)
    assert (me.status_code, _code(me)) == (403, "password_change_required")
    # фоновый опрос (D-14) гейт не обходит
    probe = await env.me(token, **{"X-GT-Background": "1"})
    assert (probe.status_code, _code(probe)) == (403, "password_change_required")


async def test_ac29_one_time_password_flow_change_unblocks_the_same_session(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user = await env.new_user(role="business_admin", password=PW, must_change_password=True)
    token = await env.login_ok(user)

    assert (await _change(env, token, PW, NEW)).status_code == 204

    me = await env.me(token)
    assert me.status_code == 200
    body = me.json()
    assert body["must_change_password"] is False
    assert body["role"] == "business_admin"
    # повторный вход паролем, выданным ранее, невозможен; одноразовый пароль израсходован
    assert (await env.login(user.login, PW)).status_code == 401


async def test_ac113_logout_is_allowed_with_one_time_password_and_old_session_gets_401(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user = await env.new_user(role="user", password=PW, must_change_password=True)
    token = await env.login_ok(user)

    out = await env.client.post(LOGOUT_URL, headers=env.auth(token))

    assert out.status_code == 204
    me = await env.me(token)
    assert (me.status_code, _code(me)) == (401, "not_authenticated")
    again = await _change(env, token, PW, NEW)
    assert (again.status_code, _code(again)) == (401, "not_authenticated")
    assert (await env.user_row(user.id)).must_change_password is True
    assert await env.session_ids(user.id) == []


async def test_fr55_failed_change_keeps_one_time_password_requirement(api_env: ApiEnv) -> None:
    env = api_env
    user = await env.new_user(role="user", password=PW, must_change_password=True)
    token = await env.login_ok(user)

    assert (await _change(env, token, PW, SHORT_11)).status_code == 422
    assert (await _change(env, token, WRONG, NEW)).status_code == 422

    me = await env.me(token)
    assert (me.status_code, _code(me)) == (403, "password_change_required")


# --- пользователь без роли (AC-75, FR-66) ---------------------------------------------------


async def test_ac75_user_without_role_can_login_change_password_and_logout(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user = await env.new_user(role=None, password=PW)
    login = await env.login(user.login, PW)
    assert login.status_code == 200
    assert login.json()["user"]["role"] is None
    token = env.token_from(login)
    assert token

    me = await env.me(token)
    assert (me.status_code, _code(me)) == (403, "no_role")

    assert (await _change(env, token, PW, NEW)).status_code == 204
    me = await env.me(token)
    assert (me.status_code, _code(me)) == (403, "no_role")  # смена пароля роли не даёт
    assert (await env.login(user.login, NEW)).status_code == 200

    out = await env.client.post(LOGOUT_URL, headers=env.auth(token))
    assert out.status_code == 204
    me = await env.me(token)
    assert me.status_code == 401


async def test_fr66_user_without_role_gets_403_no_role_on_other_routes(api_env: ApiEnv) -> None:
    env = api_env
    _, token = await _active(env, role=None)
    # обход всех маршрутов: test_route_guards.py; здесь существующий защищённый маршрут
    for extra in ({}, {"X-GT-Background": "1"}):
        response = await env.me(token, **extra)
        assert (response.status_code, _code(response)) == (403, "no_role")


async def test_fr55_fr66_one_time_password_gate_precedes_no_role_and_then_no_role_remains(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user = await env.new_user(role=None, password=PW, must_change_password=True)
    token = await env.login_ok(user)
    me = await env.me(token)
    assert (me.status_code, _code(me)) == (403, "password_change_required")

    assert (await _change(env, token, PW, NEW)).status_code == 204

    me = await env.me(token)
    assert (me.status_code, _code(me)) == (403, "no_role")


# --- max_length и суррогаты (ревью T08, T13; FR-57) -----------------------------------------


@pytest.mark.parametrize("field", ["current_password", "new_password"])
async def test_t13_review_password_change_fields_are_limited_to_1024_chars(
    api_env: ApiEnv, field: str
) -> None:
    env = api_env
    user, token = await _active(env)
    long_value = "Lng-" + "x" * 1021 + "!"  # 1026 символов
    assert len(long_value) > 1024
    payload = {"current_password": PW, "new_password": NEW}
    payload[field] = long_value
    before = (await env.user_row(user.id)).password_hash

    response = await env.client.post(PASSWORD_URL, json=payload, headers=env.auth(token))

    assert (response.status_code, _code(response)) == (422, "validation_error")
    assert long_value not in response.text
    assert "Lng-" not in response.text
    assert (await env.user_row(user.id)).password_hash == before
    assert (await env.me(token)).status_code == 200


async def test_t13_review_new_password_of_exactly_1024_chars_is_accepted(api_env: ApiEnv) -> None:
    env = api_env
    user, token = await _active(env)
    value = ("Aa1-" * 300)[:1024]
    assert len(value) == 1024
    response = await _change(env, token, PW, value)
    assert response.status_code == 204, response.text
    assert (await env.login(user.login, value)).status_code == 200


async def test_t13_review_login_and_password_fields_of_login_are_limited_to_1024_chars(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user = await env.new_user(role="user", password=PW)
    long_password = "LoginLng-" + "y" * 1020
    response = await env.client.post(
        "/api/v1/auth/login", json={"login": user.login, "password": long_password}
    )
    assert (response.status_code, _code(response)) == (422, "validation_error")
    assert "LoginLng-" not in response.text

    long_login = "a" * 1025
    response = await env.client.post(
        "/api/v1/auth/login", json={"login": long_login, "password": PW}
    )
    assert (response.status_code, _code(response)) == (422, "validation_error")
    assert long_login not in response.text
    assert PW not in response.text
    assert (await env.user_row(user.id)).failed_login_count == 0


async def test_t08_review_new_password_with_lone_surrogate_is_422_not_500(
    api_env: ApiEnv,
) -> None:
    """Одиночный суррогат в JSON (``\\ud800``): 422 без пароля в ответе; пароль не сменён."""
    env = api_env
    user, token = await _active(env)
    before = (await env.user_row(user.id)).password_hash
    raw = (
        '{"current_password": ' + json.dumps(PW) + ', "new_password": "SurLeak-\\ud800"}'
    ).encode()
    async with _quiet_client(env) as client:
        response = await client.post(
            PASSWORD_URL,
            content=raw,
            headers={**env.auth(token), "Content-Type": "application/json"},
        )

    assert response.status_code == 422, response.text
    assert _code(response) == "validation_error"
    assert "SurLeak" not in response.text
    assert PW not in response.text
    assert (await env.user_row(user.id)).password_hash == before
    assert (await env.me(token)).status_code == 200


async def test_t08_review_current_password_with_lone_surrogate_is_422_not_500(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _, token = await _active(env)
    raw = (
        '{"current_password": "SurCur-\\ud800", "new_password": ' + json.dumps(NEW) + "}"
    ).encode()
    async with _quiet_client(env) as client:
        response = await client.post(
            PASSWORD_URL,
            content=raw,
            headers={**env.auth(token), "Content-Type": "application/json"},
        )
    assert response.status_code == 422, response.text
    assert _code(response) in {"invalid_current_password", "validation_error"}
    assert "SurCur" not in response.text
    assert NEW not in response.text


async def test_t08_review_login_password_with_lone_surrogate_is_not_500(api_env: ApiEnv) -> None:
    env = api_env
    user = await env.new_user(role="user", password=PW)
    raw = ('{"login": ' + json.dumps(user.login) + ', "password": "SurLogin-\\ud800"}').encode()
    async with _quiet_client(env) as client:
        response = await client.post(
            "/api/v1/auth/login", content=raw, headers={"Content-Type": "application/json"}
        )
    assert response.status_code in (401, 422), response.text
    assert "SurLogin" not in response.text
    assert env.token_from(response) is None


# --- Origin (D-16) --------------------------------------------------------------------------


async def test_d16_foreign_origin_on_password_change_is_403_before_processing(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user, token = await _active(env)
    before = await env.user_row(user.id)

    for current in (PW, WRONG):  # неверный current при чужом Origin не засчитывается
        response = await _change(env, token, current, NEW, Origin="http://evil.example")
        assert (response.status_code, _code(response)) == (403, "origin_mismatch")

    after = await env.user_row(user.id)
    assert after.password_hash == before.password_hash
    assert after.failed_login_count == 0
    assert (await env.me(token)).status_code == 200


async def test_d16_same_origin_password_change_passes(api_env: ApiEnv) -> None:
    env = api_env
    _, token = await _active(env)
    response = await _change(env, token, PW, NEW, Origin="http://testserver")
    assert response.status_code == 204


# --- перебор current_password (tasks.md T14, «Уточнения» п.1; FR-61) ------------------------


async def test_fr61_four_wrong_current_passwords_then_correct_one_succeeds_and_resets_counter(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    user, token = await _active(env)
    for expected in (1, 2, 3, 4):
        response = await _change(env, token, WRONG, NEW)
        assert (response.status_code, _code(response)) == (422, "invalid_current_password")
        row = await env.user_row(user.id)
        assert row.failed_login_count == expected  # переживает откат запроса
        assert row.login_locked_until is None
        assert (await env.me(token)).status_code == 200

    assert (await _change(env, token, PW, NEW)).status_code == 204

    row = await env.user_row(user.id)
    assert row.failed_login_count == 0
    assert row.login_locked_until is None
    # счётчик начат заново: снова 4 неверных current не блокируют
    for _ in range(4):
        assert (await _change(env, token, WRONG, NEW2)).status_code == 422
    assert (await env.me(token)).status_code == 200
    assert (await _change(env, token, NEW, NEW2)).status_code == 204


async def test_fr61_five_wrong_current_passwords_lock_login_and_end_current_session(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    user, token = await _active(env)
    await env.login_ok(user)  # второй «браузер»: его судьба при блокировке не фиксируется
    reference = await env.login("ghost.user", BAD)  # обычный отказ входа
    assert reference.status_code == 401
    responses = [await _change(env, token, WRONG, NEW) for _ in range(5)]

    # на пороге тот же ответ, что и раньше
    assert {(r.status_code, _code(r)) for r in responses} == {(422, "invalid_current_password")}
    assert responses[4].json() == responses[0].json()
    row = await env.user_row(user.id)
    assert row.login_locked_until == FIXED_NOW + LOCK
    after = await env.me(token)
    assert (after.status_code, _code(after)) == (401, "not_authenticated")
    assert env.token_id(token) not in await env.session_ids(user.id)

    locked = await env.login(user.login, PW)
    assert locked.status_code == 401
    assert env.token_from(locked) is None
    assert _same_failure(locked, reference)

    env.clock.advance(timedelta(minutes=14, seconds=59))
    still = await env.login(user.login, PW)
    assert still.status_code == 401
    assert _same_failure(still, reference)

    env.clock.advance(timedelta(seconds=1))
    response = await env.login(user.login, PW)
    assert response.status_code == 200, response.text
    assert env.token_from(response)


async def test_fr61_wrong_logins_and_wrong_current_passwords_share_one_counter(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    user, token = await _active(env)
    for _ in range(3):
        assert (await env.login(user.login, BAD)).status_code == 401
    assert (await env.user_row(user.id)).failed_login_count == 3

    first = await _change(env, token, WRONG, NEW)
    assert (first.status_code, _code(first)) == (422, "invalid_current_password")
    assert (await env.user_row(user.id)).failed_login_count == 4
    assert (await env.me(token)).status_code == 200

    fifth = await _change(env, token, WRONG, NEW)
    assert (fifth.status_code, _code(fifth)) == (422, "invalid_current_password")

    assert (await env.user_row(user.id)).login_locked_until == FIXED_NOW + LOCK
    assert (await env.me(token)).status_code == 401
    assert (await env.login(user.login, PW)).status_code == 401


async def test_fr61_wrong_current_failures_do_not_lock_other_users(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    user, token = await _active(env)
    bystander, bystander_token = await _active(env)
    for _ in range(5):
        await _change(env, token, WRONG, NEW)
    assert (await env.user_row(user.id)).login_locked_until is not None
    assert (await env.user_row(bystander.id)).login_locked_until is None
    assert (await env.me(bystander_token)).status_code == 200
    assert (await env.login(bystander.login, PW)).status_code == 200


async def test_fr61_parallel_wrong_current_passwords_do_not_exceed_threshold_of_checks(
    committed_api_env: ApiEnv,
) -> None:
    """20 параллельных неверных current: не более 5 реальных проверок, блокировка зафиксирована."""
    env = committed_api_env
    user, token = await _active(env)
    hasher = env.app.state.password_hasher
    calls = 0
    original = hasher.verify

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    hasher.verify = counting
    try:
        responses = await asyncio.gather(*[_change(env, token, WRONG, NEW) for _ in range(20)])
    finally:
        hasher.verify = original

    assert calls <= env.settings.login_max_failures, calls
    for response in responses:
        assert response.status_code in (422, 401), response.text
        if response.status_code == 422:
            assert _code(response) == "invalid_current_password"
        assert NEW not in response.text
    row = await env.user_row(user.id)
    assert row.login_locked_until is not None, "блокировка не зафиксирована"
    gone = await env.me(token)
    assert gone.status_code == 401
    assert (await env.login(user.login, PW)).status_code == 401
    assert row.password_hash == user.password_hash


# --- файл пароля первого ТА (AC-23, FR-6; «Уточнения» п.2) ----------------------------------


async def test_ac23_first_admin_password_file_is_removed_after_successful_change(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user = await env.new_user(
        login="admin", role="tech_admin", password=PW, must_change_password=True
    )
    path = _initial_file(env, "admin", PW)
    token = await env.login_ok(user)
    assert path.exists()

    response = await _change(env, token, PW, NEW)

    assert response.status_code == 204
    assert not path.exists()
    assert (await env.me(token)).status_code == 200


async def test_ac23_file_is_removed_only_after_commit_not_before(api_env: ApiEnv) -> None:
    """Файл ещё на месте в момент каждой фиксации транзакции запроса и удалён к ответу."""
    env = api_env
    user = await env.new_user(
        login="admin", role="tech_admin", password=PW, must_change_password=True
    )
    path = _initial_file(env, "admin", PW)
    token = await env.login_ok(user)
    seen: list[bool] = []

    def before_commit(_session: Session) -> None:
        seen.append(path.exists())

    event.listen(Session, "before_commit", before_commit)
    try:
        response = await _change(env, token, PW, NEW)
    finally:
        event.remove(Session, "before_commit", before_commit)

    assert response.status_code == 204
    assert seen, "COMMIT транзакции запроса не наблюдался"
    assert all(seen), "файл удалён до COMMIT"
    assert not path.exists()


async def test_ac23_commit_failure_returns_500_keeps_old_password_and_password_file(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    user = await env.new_user(
        login="admin", role="tech_admin", password=PW, must_change_password=True
    )
    path = _initial_file(env, "admin", PW)
    token = await env.login_ok(user)
    # сбой фиксации: отложенный триггер срабатывает при COMMIT, если сменился хеш пароля
    await env.execute(
        text(
            "CREATE FUNCTION t14_fail_commit() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 't14 commit failure'; END $$"
        )
    )
    await env.execute(
        text(
            "CREATE CONSTRAINT TRIGGER t14_fail_commit AFTER UPDATE OF password_hash ON app_user "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "WHEN (OLD.password_hash IS DISTINCT FROM NEW.password_hash) "
            "EXECUTE FUNCTION t14_fail_commit()"
        )
    )
    before = await env.user_row(user.id)

    async with _quiet_client(env) as client:
        response = await _change(env, token, PW, NEW, client=client)

    assert response.status_code == 500, response.text
    assert response.json()["code"] == "internal_error"
    assert PW not in response.text
    assert NEW not in response.text
    assert path.exists(), "файл удалён, хотя пароль не сменён"
    assert "password=" in path.read_text(encoding="utf-8")
    after = await env.user_row(user.id)
    assert after.password_hash == before.password_hash
    assert after.must_change_password is True
    assert (await env.me(token)).status_code == 403  # сессия жива, смена по-прежнему нужна
    assert (await env.login(user.login, PW)).status_code == 200


async def test_ac23_file_removal_failure_does_not_undo_password_change(api_env: ApiEnv) -> None:
    env = api_env
    user = await env.new_user(
        login="admin", role="tech_admin", password=PW, must_change_password=True
    )
    token = await env.login_ok(user)
    env.settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    (env.settings.secrets_dir / INITIAL_FILE).mkdir()  # вместо файла — каталог

    response = await _change(env, token, PW, NEW)

    assert response.status_code == 204, response.text
    assert (await env.user_row(user.id)).must_change_password is False
    assert (await env.login(user.login, NEW)).status_code == 200


async def test_ac23_change_by_another_user_keeps_password_file_of_first_admin(
    api_env: ApiEnv,
) -> None:
    env = api_env
    path = _initial_file(env, "admin", PW)
    user, token = await _active(env, login="second.admin", role="tech_admin")
    assert user.login == "second.admin"

    response = await _change(env, token, PW, NEW)

    assert response.status_code == 204
    assert path.exists()
    assert path.read_text(encoding="utf-8") == f"login=admin\npassword={PW}\n"


async def test_ac23_rejected_change_keeps_password_file(api_env: ApiEnv) -> None:
    env = api_env
    user = await env.new_user(
        login="admin", role="tech_admin", password=PW, must_change_password=True
    )
    path = _initial_file(env, "admin", PW)
    token = await env.login_ok(user)
    assert (await _change(env, token, WRONG, NEW)).status_code == 422
    assert (await _change(env, token, PW, SHORT_11)).status_code == 422
    assert path.exists()
