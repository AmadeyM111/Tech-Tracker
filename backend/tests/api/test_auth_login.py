"""T13: POST /api/v1/auth/login (plan §4.6, FR-1, FR-5, FR-57, FR-58, FR-61, FR-73).

AC-4, AC-20 (код и тело при входе заблокированного), AC-30, AC-36, AC-116.
Заметка ревью T11: роут входа не пишет в сессию БД до ``service.login``.

Окружение — ``api_env`` / ``api_env_secure`` (conftest): настоящий ``create_app`` с запущенным
lifespan, сессии БД во внешней транзакции теста. Модуль схем ``app.api.v1.schemas.auth``
импортируется внутри теста (имена классов plan не фиксирует).
"""

import importlib
import logging
import re
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, SecretStr
from sqlalchemy import event

from tests.conftest import ApiEnv, parse_set_cookie
from tests.factories import get_table

LOGIN_URL = "/api/v1/auth/login"
SECRET = "Sup3r-secret-Pa55phrase-xyz"
WRONG = "Wr0ng-Pa55phrase-unique-qq"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43,}$")  # 32 байта в base64url (D-13)
USER_KEYS = {"id", "login", "role", "must_change_password"}


def _cmp(response: httpx.Response) -> tuple[int, Any, dict[str, str]]:
    headers = {k.lower(): v for k, v in response.headers.items() if k.lower() not in {"date"}}
    return response.status_code, response.json(), headers


# --- успех: cookie (AC-36, FR-58) ---------------------------------------------------------


async def test_ac36_login_success_sets_session_cookie_flags_without_secure_in_dev(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=SECRET)
    response = await api_env.login(user.login, SECRET)

    assert response.status_code == 200, response.text
    morsel = parse_set_cookie(response, "gt_session")
    assert morsel is not None, "нет Set-Cookie gt_session"
    assert TOKEN_RE.match(morsel.value)
    assert morsel["httponly"]
    assert str(morsel["samesite"]).lower() == "lax"
    assert morsel["path"] == "/"
    assert int(morsel["max-age"]) == 604800
    assert not morsel["secure"], "cookie_secure=False: Secure не ставится (AC-36)"
    assert not morsel["domain"]
    assert len(response.headers.get_list("set-cookie")) == 1


async def test_ac36_fr58_login_cookie_has_secure_when_cookie_secure_true(
    api_env_secure: ApiEnv,
) -> None:
    env = api_env_secure
    user = await env.new_user(role="user", password=SECRET)
    response = await env.login(user.login, SECRET)

    assert response.status_code == 200, response.text
    morsel = parse_set_cookie(response, "gt_session")
    assert morsel is not None
    assert morsel["secure"]
    assert morsel["httponly"]
    assert str(morsel["samesite"]).lower() == "lax"
    assert morsel["path"] == "/"
    assert int(morsel["max-age"]) == 604800


async def test_ac36_cookie_name_follows_settings_cookie_name(
    api_env_secure: ApiEnv,
) -> None:
    """Имя берётся из ``Settings.cookie_name`` (префикс ``__Host-`` допустим только с Secure)."""
    env = api_env_secure
    env.settings.cookie_name = "__Host-gt_session"
    user = await env.new_user(role="user", password=SECRET)
    response = await env.login(user.login, SECRET)

    assert response.status_code == 200, response.text
    morsel = parse_set_cookie(response, "__Host-gt_session")
    assert morsel is not None
    assert morsel["secure"] and morsel["path"] == "/" and not morsel["domain"]
    assert parse_set_cookie(response, "gt_session") is None
    # выданный токен действует
    token = env.token_from(response)
    assert token
    assert (await env.me(token)).status_code == 200


# --- успех: тело и серверное состояние ----------------------------------------------------


async def test_ac4_login_body_has_profile_and_no_token_or_hash(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="business_admin", password=SECRET)
    response = await api_env.login(user.login, SECRET)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"user"}
    assert set(body["user"]) == USER_KEYS
    assert body["user"] == {
        "id": str(user.id),
        "login": user.login,
        "role": "business_admin",
        "must_change_password": False,
    }
    token = api_env.token_from(response)
    assert token
    assert token not in response.text
    assert user.password_hash not in response.text
    assert "argon2" not in response.text.lower()


async def test_login_user_without_role_gets_role_null(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role=None, password=SECRET)
    response = await api_env.login(user.login, SECRET)
    assert response.status_code == 200
    assert response.json()["user"]["role"] is None


async def test_login_with_one_time_password_flag_returns_must_change_password(
    api_env: ApiEnv,
) -> None:
    """FR-55: вход разрешён, клиент узнаёт о необходимости смены пароля из тела."""
    user = await api_env.new_user(role="user", password=SECRET, must_change_password=True)
    response = await api_env.login(user.login, SECRET)
    assert response.status_code == 200
    assert response.json()["user"]["must_change_password"] is True
    assert api_env.token_from(response)


async def test_login_creates_server_side_session_with_hashed_id(api_env: ApiEnv) -> None:
    """FR-58, D-13: в БД — HMAC токена, не сам токен; одна строка на вход."""
    user = await api_env.new_user(role="user", password=SECRET)
    assert await api_env.session_ids(user.id) == []
    response = await api_env.login(user.login, SECRET)
    token = api_env.token_from(response)
    assert token
    ids = await api_env.session_ids(user.id)
    assert ids == [api_env.token_id(token)]
    assert token.encode() not in ids


async def test_ac116_fr73_login_in_upper_case_succeeds(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", login="ivan.petrov", password=SECRET)
    for variant in ("IVAN.PETROV", "Ivan.Petrov", "ivan.petrov"):
        response = await api_env.login(variant, SECRET)
        assert response.status_code == 200, variant
        assert response.json()["user"]["login"] == "ivan.petrov"
        assert response.json()["user"]["id"] == str(user.id)


@pytest.mark.parametrize("variant", ["ivanov.petr", "IVANOV.PETR", "Ivanov.Petr", "iVaNoV.pEtR"])
async def test_ac126_login_in_any_case_returns_display_login_in_response_and_profile(
    api_env: ApiEnv, variant: str
) -> None:
    """FR-73a: логин в ответе входа и в ``GET /me`` — написание при создании, а не набранное."""
    env = api_env
    user = await env.new_user(role="business_admin", login="Ivanov.Petr", password=SECRET)

    response = await env.login(variant, SECRET)

    assert response.status_code == 200, response.text
    assert response.json()["user"]["login"] == "Ivanov.Petr"
    assert response.json()["user"]["id"] == str(user.id)
    token = env.token_from(response)
    assert token
    me = await env.me(token)
    assert me.status_code == 200, me.text
    assert me.json()["login"] == "Ivanov.Petr"
    assert me.json()["id"] == str(user.id)


async def test_ac126_wrong_password_with_lower_case_login_is_same_as_unknown_login(
    api_env: ApiEnv,
) -> None:
    env = api_env
    await env.new_user(role="business_admin", login="Ivanov.Petr", password=SECRET)

    wrong = await env.login("ivanov.petr", WRONG)
    unknown = await env.login("nobody.here", WRONG)

    assert wrong.status_code == 401
    assert _cmp(wrong) == _cmp(unknown)
    assert not wrong.headers.get_list("set-cookie")


async def test_ac126_user_key_and_display_are_stored_separately(api_env: ApiEnv) -> None:
    env = api_env
    user = await env.new_user(role="user", login="Ivanov.Petr", password=SECRET)
    row = await env.user_row(user.id)
    assert (row.login, row.login_display) == ("ivanov.petr", "Ivanov.Petr")


# --- отказы: одинаковый 401 (AC-4, AC-20, AC-30, FR-61) -----------------------------------


async def _failure_responses(env: ApiEnv) -> dict[str, httpx.Response]:
    good = await env.new_user(role="user", password=SECRET, login="kevin.good")
    blocked = await env.new_user(role="user", password=SECRET, login="blocked.user", blocked=True)
    orphan = await env.new_user(role="user", password=SECRET, login="no.member")
    member = get_table("workspace_member")
    await env.execute(member.delete().where(member.c.user_id == orphan.id))

    cases: dict[str, tuple[str, str]] = {
        "wrong_password": (good.login, WRONG),
        "unknown_login": ("nobody.here", WRONG),
        "unknown_login_valid_pw": ("nobody.here", SECRET),
        "blocked_correct_password": (blocked.login, SECRET),
        "no_membership_correct_password": (orphan.login, SECRET),
        "too_short_login": ("ab", SECRET),
        "cyrillic_login": ("иван", SECRET),
        "space_in_login": ("kevin good", SECRET),
        "leading_dot_login": (".kevin.good", SECRET),
        "too_long_login": ("a" * 65, SECRET),
        "kelvin_sign_login": ("Kevin.good", SECRET),
        "trailing_newline_login": ("kevin.good\n", SECRET),
    }
    out: dict[str, httpx.Response] = {}
    for name, (login, password) in cases.items():
        out[name] = await env.login(login, password)
    return out


async def test_ac4_ac20_ac30_fr61_all_login_failures_are_identical_401(api_env: ApiEnv) -> None:
    responses = await _failure_responses(api_env)
    reference = _cmp(responses["wrong_password"])
    assert reference[0] == 401
    assert reference[1]["code"] == "invalid_credentials"
    assert set(reference[1]) == {"detail", "code"}
    assert isinstance(reference[1]["detail"], str)

    for name, response in responses.items():
        assert _cmp(response) == reference, f"{name}: ответ отличается от неверного пароля"
        assert api_env.token_from(response) is None, f"{name}: поставлена cookie"
        assert not response.headers.get_list("set-cookie"), f"{name}: есть Set-Cookie"


async def test_ac20_blocked_user_with_correct_password_creates_no_session(
    api_env: ApiEnv,
) -> None:
    blocked = await api_env.new_user(role="user", password=SECRET, blocked=True)
    response = await api_env.login(blocked.login, SECRET)
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert await api_env.session_ids(blocked.id) == []


async def test_fr57_password_not_echoed_in_401(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=SECRET)
    for login, password in ((user.login, WRONG), ("nobody.here", WRONG), ("ab", WRONG)):
        response = await api_env.login(login, password)
        assert response.status_code == 401
        assert WRONG not in response.text
        assert all(WRONG not in v for v in response.headers.values())


async def test_login_wrong_password_does_not_create_session(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=SECRET)
    response = await api_env.login(user.login, WRONG)
    assert response.status_code == 401
    assert await api_env.session_ids(user.id) == []


# --- валидация тела: 422 без значений (FR-57) --------------------------------------------


def _assert_clean_422(response: httpx.Response, *secrets: str) -> None:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["detail"], list)
    for item in body["detail"]:
        assert "input" not in item
        assert "ctx" not in item
    for secret in secrets:
        assert secret not in response.text
    assert not response.headers.get_list("set-cookie")


async def test_fr57_missing_password_field_is_422_without_values(api_env: ApiEnv) -> None:
    response = await api_env.client.post(LOGIN_URL, json={"login": "kevin.good"})
    _assert_clean_422(response, "kevin.good")


async def test_fr57_missing_login_field_is_422_without_password_echo(api_env: ApiEnv) -> None:
    response = await api_env.client.post(LOGIN_URL, json={"password": SECRET})
    _assert_clean_422(response, SECRET)


async def test_fr57_empty_object_is_422(api_env: ApiEnv) -> None:
    _assert_clean_422(await api_env.client.post(LOGIN_URL, json={}))


async def test_fr57_wrong_field_types_422_without_echo(api_env: ApiEnv) -> None:
    response = await api_env.client.post(
        LOGIN_URL, json={"login": {"a": SECRET}, "password": [SECRET]}
    )
    _assert_clean_422(response, SECRET)


async def test_fr57_malformed_json_is_400_without_echo(api_env: ApiEnv) -> None:
    response = await api_env.client.post(
        LOGIN_URL,
        content=('{"login": "kevin.good", "password": "' + SECRET).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Некорректный JSON в теле запроса", "code": "bad_request"}
    assert SECRET not in response.text
    assert "kevin.good" not in response.text
    assert not response.headers.get_list("set-cookie")


async def test_non_json_content_type_is_rejected_and_logs_nobody_in(api_env: ApiEnv) -> None:
    """D-16: тела только JSON. Корректные данные в text/plain не должны привести ко входу."""
    user = await api_env.new_user(role="user", password=SECRET)
    response = await api_env.client.post(
        LOGIN_URL,
        content=f'{{"login": "{user.login}", "password": "{SECRET}"}}'.encode(),
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code in (415, 422), response.text
    assert SECRET not in response.text
    assert api_env.token_from(response) is None
    assert await api_env.session_ids(user.id) == []


async def test_form_encoded_body_is_not_accepted(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=SECRET)
    response = await api_env.client.post(LOGIN_URL, data={"login": user.login, "password": SECRET})
    assert response.status_code in (415, 422), response.text
    assert SECRET not in response.text
    assert api_env.token_from(response) is None


async def test_login_get_method_is_405(api_env: ApiEnv) -> None:
    response = await api_env.client.get(LOGIN_URL)
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"


# --- SecretStr в схеме (FR-57) ------------------------------------------------------------


def _login_schema() -> type[BaseModel]:
    module = importlib.import_module("app.api.v1.schemas.auth")
    candidates = [
        obj
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__ == module.__name__
        and {"login", "password"} <= set(obj.model_fields)
    ]
    assert len(candidates) == 1, f"ожидалась одна схема входа с login и password: {candidates}"
    return candidates[0]


def test_fr57_login_schema_password_is_secretstr_and_not_in_repr() -> None:
    schema = _login_schema()
    assert schema.model_fields["password"].annotation is SecretStr
    item = schema(login="kevin.good", password=SECRET)
    assert isinstance(item.password, SecretStr)
    assert item.password.get_secret_value() == SECRET
    for text in (repr(item), str(item), item.model_dump_json(), str(item.model_dump())):
        assert SECRET not in text


# --- fixation и повторный вход ------------------------------------------------------------


async def test_session_fixation_client_cookie_in_login_request_is_ignored(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=SECRET)
    planted = "attacker-chosen-token-0123456789abcdefghijklmnop"
    response = await api_env.login(user.login, SECRET, headers=api_env.auth(planted))

    assert response.status_code == 200
    token = api_env.token_from(response)
    assert token and token != planted
    # подставленный токен не стал сессией
    assert (await api_env.me(planted)).status_code == 401
    assert api_env.token_id(planted) not in await api_env.session_ids(user.id)
    assert (await api_env.me(token)).status_code == 200


async def test_login_with_existing_valid_session_cookie_issues_new_token_and_keeps_old(
    api_env: ApiEnv,
) -> None:
    """Plan молчит о повторном входе; AC-31 («вошёл в двух браузерах») предполагает несколько
    действующих сессий. Фиксируем: новый токен, старый действует до выхода/истечения."""
    user = await api_env.new_user(role="user", password=SECRET)
    first = await api_env.login_ok(user)
    second_response = await api_env.login(user.login, SECRET, headers=api_env.auth(first))
    second = api_env.token_from(second_response)
    assert second and second != first
    assert len(await api_env.session_ids(user.id)) == 2
    assert (await api_env.me(first)).status_code == 200
    assert (await api_env.me(second)).status_code == 200


async def test_each_login_issues_distinct_token(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=SECRET)
    tokens = {await api_env.login_ok(user) for _ in range(3)}
    assert len(tokens) == 3


# --- логи (FR-57) -------------------------------------------------------------------------


async def test_fr57_login_flow_does_not_log_password_or_token(
    api_env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    user = await api_env.new_user(role="user", password=SECRET)
    caplog.set_level(logging.DEBUG)
    bad = await api_env.login(user.login, WRONG)
    good = await api_env.login(user.login, SECRET)
    assert (bad.status_code, good.status_code) == (401, 200)
    token = api_env.token_from(good)
    assert token
    await api_env.me(token)

    dump = caplog.text + repr([vars(r) for r in caplog.records])
    for secret in (SECRET, WRONG, token):
        assert secret not in dump


# --- заметка ревью T11: до service.login нет записей в БД ----------------------------------


async def test_t11_review_login_route_writes_nothing_before_service_login(
    api_env: ApiEnv, db_engine: Any
) -> None:
    """Запросы вне входа (INSERT/UPDATE/DELETE) до первого обращения к провайдеру запрещены:
    иначе ``checkpoint``/``commit_durably`` зафиксирует их досрочно. Шпион — на
    ``app.state.auth_provider.authenticate`` (первый обращающийся к БД шаг ``service.login``)."""
    user = await api_env.new_user(role="user", password=SECRET)
    provider = api_env.app.state.auth_provider
    original = provider.authenticate

    statements: list[str] = []
    writes_before_provider: list[str] = []
    provider_called = False

    def on_execute(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    async def spy(*args: Any, **kwargs: Any) -> Any:
        nonlocal provider_called
        provider_called = True
        writes_before_provider.extend(
            s
            for s in statements
            if s.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}
        )
        return await original(*args, **kwargs)

    provider.authenticate = spy
    event.listen(db_engine.sync_engine, "before_cursor_execute", on_execute)
    try:
        response = await api_env.login(user.login, SECRET)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", on_execute)
        provider.authenticate = original

    assert response.status_code == 200
    assert provider_called, "роут входа не вызвал провайдер аутентификации"
    assert writes_before_provider == []
    # и сам вход всё же записал сессию после провайдера
    assert any(s.lstrip().upper().startswith("INSERT") for s in statements)
