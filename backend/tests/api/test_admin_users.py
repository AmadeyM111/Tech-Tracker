"""T17: API учётных записей ``/api/v1/admin/users*`` (plan §4.6, §4.5, D-15, D-34).

AC-2, AC-3, AC-20, AC-22 (страница), AC-39, AC-44, AC-45, AC-113, AC-116, AC-121 (создание без
роли); FR-4, FR-5, FR-5a, FR-42, FR-45a, FR-55, FR-57, FR-62, FR-65, FR-73.
Заметки ревью: T15 (стабильный порядок страниц), T16 (порядок проверок create_user).

Контракт plan §4.6 (принят как есть, см. отчёт об неоднозначностях):
- ``GET /admin/users`` -> ``Page[...]`` ``{items, page, page_size, has_next}``, элемент
  ``{id, login, role, is_blocked, must_change_password, created_at}``;
- ``POST /admin/users`` ``{login, one_time_password}`` -> 201 элемент, роль ``null``;
- ``POST /{id}/block|unblock|revoke-sessions`` -> 204 без тела;
- ``POST /{id}/reset-password`` ``{one_time_password}`` -> 204 без тела.
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from tests.admin_support import (
    ADMIN_USERS,
    ADMIN_VIEW_FIELDS,
    OTP,
    OTP_FIELD,
    PW,
    admin_in_new_workspace,
    code_of,
    events,
    member_role,
    new_workspace,
    seed,
)
from tests.conftest import FIXED_NOW, ApiEnv
from tests.factories import PLACEHOLDER_HASH

LOGIN_URL = "/api/v1/auth/login"


def _common_entry(minimum: int = 12) -> str:
    from app.core.security.common_passwords import is_common_password
    from tests.db_support import BACKEND_DIR

    path = BACKEND_DIR / "app" / "core" / "security" / "data" / "common-passwords-10k.txt"
    entries = path.read_text(encoding="utf-8").split("\n")[:-1]
    entry = next(e for e in entries if len(e) >= minimum and e != PW and e.isascii())
    assert is_common_password(entry)
    return entry


async def _create(env: ApiEnv, token: str, login: str, password: str = OTP) -> httpx.Response:
    return await env.client.post(
        ADMIN_USERS, json={"login": login, OTP_FIELD: password}, headers=env.auth(token)
    )


async def _list_all(env: ApiEnv, token: str, page_size: int = 100) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        r = await env.client.get(
            ADMIN_USERS, params={"page": page, "page_size": page_size}, headers=env.auth(token)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        items += body["items"]
        if not body["has_next"]:
            return items
        page += 1


# --- список ----------------------------------------------------------------------------------


async def test_ac2_list_returns_workspace_users_with_documented_fields(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    ivan, _ = await seed(env, ws, "user", login="ivan.petrov")
    blocked, _ = await seed(env, ws, "business_admin", blocked=True)
    fresh, _ = await seed(env, ws, None, must_change_password=True)
    await seed(env, await new_workspace(env), "user")  # чужое пространство

    response = await env.client.get(ADMIN_USERS, headers=env.auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "page", "page_size", "has_next"}
    assert (body["page"], body["page_size"], body["has_next"]) == (1, 50, False)
    by_id = {item["id"]: item for item in body["items"]}
    assert set(by_id) == {str(u.id) for u in (admin, ivan, blocked, fresh)}
    for item in body["items"]:
        assert set(item) == ADMIN_VIEW_FIELDS  # ни пароля, ни хеша, ни счётчиков входа
        uuid.UUID(item["id"])
    assert by_id[str(ivan.id)]["login"] == "ivan.petrov"
    assert by_id[str(ivan.id)]["role"] == "user"
    assert by_id[str(admin.id)]["role"] == "tech_admin"
    assert by_id[str(blocked.id)]["is_blocked"] is True
    assert by_id[str(fresh.id)]["role"] is None
    assert by_id[str(fresh.id)]["must_change_password"] is True
    assert by_id[str(ivan.id)]["must_change_password"] is False
    assert "$argon2" not in response.text


async def test_ac22_list_default_page_size_is_50_and_has_next(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    for _ in range(51):  # вместе с администратором 52
        await seed(env, ws, "user", sessions=0)

    first = (await env.client.get(ADMIN_USERS, headers=env.auth(token))).json()
    second = (await env.client.get(ADMIN_USERS, params={"page": 2}, headers=env.auth(token))).json()

    assert (first["page"], first["page_size"], len(first["items"]), first["has_next"]) == (
        1,
        50,
        50,
        True,
    )
    assert (second["page"], len(second["items"]), second["has_next"]) == (2, 2, False)
    ids = [i["id"] for i in first["items"] + second["items"]]
    assert len(set(ids)) == 52
    assert str(admin.id) in ids


@pytest.mark.parametrize(
    "params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"page": "x"}]
)
async def test_ac22_list_invalid_page_params_are_422(
    api_env: ApiEnv, params: dict[str, Any]
) -> None:
    _, _, token = await admin_in_new_workspace(api_env)
    response = await api_env.client.get(ADMIN_USERS, params=params, headers=api_env.auth(token))
    assert response.status_code == 422, response.text


async def test_t15_list_pages_are_stable_for_users_with_equal_created_at(
    api_env: ApiEnv,
) -> None:
    """Заметка ревью T15: ключ сортировки одинаков (FixedClock) -> тай-брейкер по id."""
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    for _ in range(6):
        await seed(env, ws, "user", sessions=0)

    one_by_one = [i["id"] for i in await _list_all(env, token, page_size=1)]
    pairs = [i["id"] for i in await _list_all(env, token, page_size=2)]
    whole = [i["id"] for i in await _list_all(env, token, page_size=100)]
    again = [i["id"] for i in await _list_all(env, token, page_size=100)]

    assert len(whole) == 7 and len(set(whole)) == 7
    assert one_by_one == whole
    assert pairs == whole
    assert again == whole
    created = {i["created_at"] for i in await _list_all(env, token)}
    assert len(created) == 1, "в тесте у всех created_at должен совпадать (FixedClock)"


# --- карточка --------------------------------------------------------------------------------


async def test_ac2_get_user_returns_admin_view(api_env: ApiEnv) -> None:
    """002/AC-3: цель с ролью ``business_admin`` (прежде ``mixed``)."""
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "business_admin", must_change_password=True)

    response = await env.client.get(f"{ADMIN_USERS}/{target.id}", headers=env.auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == ADMIN_VIEW_FIELDS
    assert body["id"] == str(target.id)
    assert body["login"] == target.login
    assert body["role"] == "business_admin"
    assert body["is_blocked"] is False
    assert body["must_change_password"] is True


async def test_ac2_get_unknown_user_is_404_not_found(api_env: ApiEnv) -> None:
    _, admin, token = await admin_in_new_workspace(api_env)
    own = await api_env.client.get(f"{ADMIN_USERS}/{admin.id}", headers=api_env.auth(token))
    assert own.status_code == 200, own.text
    response = await api_env.client.get(
        f"{ADMIN_USERS}/{uuid.uuid4()}", headers=api_env.auth(token)
    )
    assert response.status_code == 404
    assert code_of(response) == "not_found"


# --- создание (AC-113, AC-116, AC-121) --------------------------------------------------------


async def test_ac113_ac121_create_user_201_without_role_and_without_password_in_response(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)

    response = await _create(env, token, "ivan.petrov", OTP)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == ADMIN_VIEW_FIELDS
    assert body["login"] == "ivan.petrov"
    assert body["role"] is None  # AC-121: после создания роли нет
    assert body["is_blocked"] is False
    assert body["must_change_password"] is True
    assert OTP not in response.text
    assert "$argon2" not in response.text
    assert "password" not in {k.lower() for k in body}
    assert await member_role(env, uuid.UUID(body["id"])) is None
    # ровно одно событие создания (AC-121, AC-114), автор — актор
    created = [e for e in await events(env, entity_id=uuid.UUID(body["id"]))]
    assert [e.action for e in created] == ["user.created"]
    assert created[0].actor_id == admin.id
    # пользователь виден в списке и в карточке
    got = await env.client.get(f"{ADMIN_USERS}/{body['id']}", headers=env.auth(token))
    assert got.json() == body
    assert ws.id  # пространство актора


async def test_ac113_created_user_logs_in_with_one_time_password_and_must_change_it(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    assert (await _create(env, token, "ivan.petrov", OTP)).status_code == 201

    login = await env.login("ivan.petrov", OTP)

    assert login.status_code == 200, login.text
    user = login.json()["user"]
    assert user["must_change_password"] is True
    assert user["role"] is None
    new_token = env.token_from(login)
    assert new_token
    me = await env.me(new_token)
    assert me.status_code == 403
    assert code_of(me) == "password_change_required"


async def test_ac116_login_with_capitals_keeps_case_in_response_login_works_in_any_case(
    api_env: ApiEnv,
) -> None:
    """FR-73a: ответ несёт написание при создании; вход и уникальность — без учёта регистра."""
    env = api_env
    _, _, token = await admin_in_new_workspace(env)

    response = await _create(env, token, "Ivan.Petrov")

    assert response.status_code == 201, response.text
    assert response.json()["login"] == "Ivan.Petrov"
    assert (await env.login("IVAN.PETROV", OTP)).status_code == 200
    assert (await env.login("ivan.petrov", OTP)).json()["user"]["login"] == "Ivan.Petrov"


async def _item(env: ApiEnv, token: str, user_id: str) -> dict[str, Any]:
    r = await env.client.get(f"{ADMIN_USERS}/{user_id}", headers=env.auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict)
    return body


async def _logins_in_list(env: ApiEnv, token: str) -> dict[str, str]:
    return {i["id"]: i["login"] for i in await _list_all(env, token)}


@pytest.mark.parametrize("login", ["Ivanov.Petr", "QA-Team_1"])
async def test_ac125_create_returns_login_as_typed_in_response_list_and_card(
    api_env: ApiEnv, login: str
) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)

    response = await _create(env, token, login)

    assert response.status_code == 201, response.text
    created = response.json()
    assert set(created) == ADMIN_VIEW_FIELDS
    assert created["login"] == login
    assert (await _item(env, token, created["id"]))["login"] == login
    assert (await _logins_in_list(env, token))[created["id"]] == login
    row = await env.user_row(uuid.UUID(created["id"]))
    assert (row.login, row.login_display) == (login.lower(), login)


async def test_ac125_login_unchanged_by_block_unblock_reset_and_role_changes(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    created = (await _create(env, token, "Ivanov.Petr")).json()
    uid = created["id"]
    base = f"{ADMIN_USERS}/{uid}"
    auth = env.auth(token)

    async def assert_same() -> None:
        assert (await _item(env, token, uid))["login"] == "Ivanov.Petr"
        assert (await _logins_in_list(env, token))[uid] == "Ivanov.Petr"

    assert (await env.client.post(f"{base}/block", headers=auth)).status_code == 204
    await assert_same()
    assert (await env.client.post(f"{base}/unblock", headers=auth)).status_code == 204
    await assert_same()
    reset = await env.client.post(
        f"{base}/reset-password", json={OTP_FIELD: OTP + "-2"}, headers=auth
    )
    assert reset.status_code == 204, reset.text
    await assert_same()
    for role in ("user", "business_admin", None):
        r = await env.client.put(f"{base}/role", json={"role": role}, headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["login"] == "Ivanov.Petr"
        await assert_same()


@pytest.mark.parametrize("attempt", ["ivanov.PETR", "ivanov.petr", "IVANOV.PETR", "Ivanov.Petr"])
async def test_ac128_case_variant_of_existing_login_is_422_login_taken(
    api_env: ApiEnv, attempt: str
) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    first = (await _create(env, token, "Ivanov.Petr")).json()
    before_ids = set(await _logins_in_list(env, token))
    before_events = len(await events(env))

    response = await _create(env, token, attempt)

    assert response.status_code == 422, response.text
    assert code_of(response) == "login_taken"
    assert set(await _logins_in_list(env, token)) == before_ids
    assert len(await events(env)) == before_events
    assert (await _item(env, token, first["id"]))["login"] == "Ivanov.Petr"


@pytest.mark.parametrize(
    "login",
    ["Ivanov.Пётр", "\u212aivan", ".Ivan", "Iv", "A" * 65],
    ids=["cyrillic", "kelvin", "leading-dot", "2-chars", "65-chars"],
)
async def test_ac128_invalid_mixed_case_login_is_422_login_invalid(
    api_env: ApiEnv, login: str
) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    before = set(await _logins_in_list(env, token))

    response = await _create(env, token, login)

    assert response.status_code == 422, response.text
    assert code_of(response) == "login_invalid"
    assert set(await _logins_in_list(env, token)) == before


async def test_ac128_login_taken_across_workspaces_for_case_variant(api_env: ApiEnv) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    await seed(env, await new_workspace(env), "user", login="Ivanov.Petr")

    response = await _create(env, token, "ivanov.petr")

    assert response.status_code == 422
    assert code_of(response) == "login_taken"


@pytest.mark.committed
@pytest.mark.parametrize("same_workspace", [True, False], ids=["one-workspace", "two-workspaces"])
async def test_ac128_parallel_create_of_case_variants_has_one_winner(
    committed_api_env: ApiEnv, same_workspace: bool
) -> None:
    env = committed_api_env
    ws1 = await new_workspace(env)
    _, (t1,) = await seed(env, ws1, "tech_admin")
    ws2 = ws1 if same_workspace else await new_workspace(env)
    _, (t2,) = await seed(env, ws2, "tech_admin")

    first, second = await asyncio.gather(
        _create(env, t1, "Ivanov.Petr"), _create(env, t2, "ivanov.petr")
    )

    assert sorted([first.status_code, second.status_code]) == [201, 422], (
        first.text,
        second.text,
    )
    loser = first if first.status_code == 422 else second
    winner = second if loser is first else first
    assert code_of(loser) == "login_taken"
    found = await env.execute(
        text("SELECT login, login_display FROM app_user WHERE login = 'ivanov.petr'")
    )
    assert found is not None and len(found) == 1
    assert found[0].login_display == winner.json()["login"]
    created_events = await env.execute(
        text(
            "SELECT count(*) FROM domain_event WHERE action = 'user.created' AND entity_id = :e"
        ).bindparams(e=uuid.UUID(winner.json()["id"]))
    )
    assert created_events is not None and created_events[0][0] == 1


async def test_oi129_account_list_is_ordered_by_normalized_login_ignoring_case(
    api_env: ApiEnv,
) -> None:
    """OI-129 а): ``anna, Boris, ivan, Kirill`` (без пунктуации: порядок не зависит от БД)."""
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    for login in ("Kirill", "ivan", "Boris", "anna"):
        await seed(env, ws, "user", login=login)

    items = await _list_all(env, token)

    logins = [i["login"] for i in items]
    assert [x for x in logins if x in {"anna", "Boris", "ivan", "Kirill"}] == [
        "anna",
        "Boris",
        "ivan",
        "Kirill",
    ]
    assert [x.lower() for x in logins] == sorted(x.lower() for x in logins)


@pytest.mark.parametrize(
    "login",
    [
        "ab",
        ".ivan",
        "ivan petrov",
        "иван",
        "a" * 65,
        "Kelvin",  # знак Кельвина: lower() даёт ASCII «k»
        "",
        "ivan@petrov",
    ],
    ids=["short", "leading-dot", "space", "cyrillic", "65-chars", "kelvin", "empty", "at-sign"],
)
async def test_ac116_invalid_login_is_422_login_invalid_and_user_not_created(
    api_env: ApiEnv, login: str
) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    before = len(await _list_all(env, token))

    response = await _create(env, token, login)

    assert response.status_code == 422, response.text
    assert code_of(response) == "login_invalid"
    assert len(await _list_all(env, token)) == before


async def test_ac116_64_chars_login_is_accepted(api_env: ApiEnv) -> None:
    _, _, token = await admin_in_new_workspace(api_env)
    response = await _create(api_env, token, "a" * 64)
    assert response.status_code == 201, response.text


async def test_ac116_taken_login_is_422_login_taken_case_insensitive(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await seed(env, ws, "user", login="ivan.petrov")

    response = await _create(env, token, "Ivan.Petrov")

    assert response.status_code == 422, response.text
    assert code_of(response) == "login_taken"


async def test_ac116_login_taken_in_another_workspace_is_also_taken(api_env: ApiEnv) -> None:
    """Логин глобально уникален (``UNIQUE(login)``, plan §4.3)."""
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    await seed(env, await new_workspace(env), "user", login="ivan.petrov")

    response = await _create(env, token, "ivan.petrov")

    assert response.status_code == 422
    assert code_of(response) == "login_taken"


async def test_ac113_password_of_11_chars_is_422_password_too_short_user_not_created(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    short = "zq9-lk3-px7"
    assert len(short) == 11

    response = await _create(env, token, "ivan.petrov", short)

    assert response.status_code == 422, response.text
    assert code_of(response) == "password_too_short"
    assert short not in response.text
    assert (await env.login("ivan.petrov", short)).status_code == 401
    assert [i["login"] for i in await _list_all(env, token) if i["login"] == "ivan.petrov"] == []


async def test_ac113_password_of_12_chars_is_accepted(api_env: ApiEnv) -> None:
    _, _, token = await admin_in_new_workspace(api_env)
    response = await _create(api_env, token, "ivan.petrov", "zq9-lk3-px7k")
    assert response.status_code == 201, response.text


async def test_ac113_common_password_is_422_password_too_common(api_env: ApiEnv) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    common = _common_entry()

    response = await _create(env, token, "ivan.petrov", common)

    assert response.status_code == 422, response.text
    assert code_of(response) == "password_too_common"
    assert [i for i in await _list_all(env, token) if i["login"] == "ivan.petrov"] == []


async def test_t16_review_create_checks_login_before_taken_before_password(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await seed(env, ws, "user", login="ivan.petrov")
    short = "zq9-lk3-px7"

    invalid = await _create(env, token, ".ivan", short)
    taken = await _create(env, token, "ivan.petrov", short)

    assert code_of(invalid) == "login_invalid"
    assert code_of(taken) == "login_taken"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"login": "ivan.petrov"},
        {OTP_FIELD: OTP},
        {"login": 5, OTP_FIELD: OTP},
        {"login": "ivan.petrov", OTP_FIELD: 12345678901234},
        {"login": "ivan.petrov", OTP_FIELD: OTP, "role": "tech_admin"},
    ],
    ids=["empty", "no-password", "no-login", "login-int", "password-int", "extra-field-role"],
)
async def test_ac116_malformed_create_body_is_422_validation_error(
    api_env: ApiEnv, body: dict[str, Any]
) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    response = await env.client.post(ADMIN_USERS, json=body, headers=env.auth(token))
    assert response.status_code == 422, response.text
    assert OTP not in response.text


async def test_ac121_create_does_not_accept_role_in_body(api_env: ApiEnv) -> None:
    """FR-4, OI-117: роль назначается отдельным действием; поле ``role`` в создании — 422."""
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    response = await env.client.post(
        ADMIN_USERS,
        json={"login": "ivan.petrov", OTP_FIELD: OTP, "role": "user"},
        headers=env.auth(token),
    )
    assert response.status_code == 422
    assert [i for i in await _list_all(env, token) if i["login"] == "ivan.petrov"] == []


# --- блокировка (FR-5, AC-20, AC-44) ----------------------------------------------------------


async def test_ac20_block_returns_204_and_terminates_target_sessions(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    target, tokens = await seed(env, ws, "user", sessions=2)
    other, (other_token,) = await seed(env, ws, "user")
    assert (await env.me(tokens[0])).status_code == 200

    response = await env.client.post(f"{ADMIN_USERS}/{target.id}/block", headers=env.auth(token))

    assert response.status_code == 204, response.text
    assert response.content == b""
    for t in tokens:
        me = await env.me(t)
        assert me.status_code == 401
        assert code_of(me) == "not_authenticated"
    assert await env.session_ids(target.id) == []
    assert (await env.me(other_token)).status_code == 200  # чужие сессии целы
    got = await env.client.get(f"{ADMIN_USERS}/{target.id}", headers=env.auth(token))
    assert got.json()["is_blocked"] is True
    assert [e.action for e in await events(env, entity_id=target.id)] == ["user.blocked"]
    assert (await events(env, entity_id=target.id))[0].actor_id == admin.id
    assert other.id


async def test_ac20_blocked_user_cannot_log_in(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user", password=PW)
    await env.client.post(f"{ADMIN_USERS}/{target.id}/block", headers=env.auth(token))

    response = await env.login(target.login, PW)

    assert response.status_code == 401
    assert code_of(response) == "invalid_credentials"


async def test_ac20_block_is_idempotent_204_without_second_event(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")
    url = f"{ADMIN_USERS}/{target.id}/block"

    first = await env.client.post(url, headers=env.auth(token))
    second = await env.client.post(url, headers=env.auth(token))

    assert (first.status_code, second.status_code) == (204, 204)
    assert [e.action for e in await events(env, entity_id=target.id)] == ["user.blocked"]


async def test_ac44_unblock_returns_204_login_works_sessions_not_restored(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, (old_token,) = await seed(env, ws, "user", password=PW)
    await env.client.post(f"{ADMIN_USERS}/{target.id}/block", headers=env.auth(token))

    response = await env.client.post(f"{ADMIN_USERS}/{target.id}/unblock", headers=env.auth(token))

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert (await env.me(old_token)).status_code == 401  # AC-44: прежняя сессия не вернулась
    login = await env.login(target.login, PW)
    assert login.status_code == 200
    new_token = env.token_from(login)
    assert new_token
    assert (await env.me(new_token)).status_code == 200
    got = await env.client.get(f"{ADMIN_USERS}/{target.id}", headers=env.auth(token))
    assert got.json()["is_blocked"] is False
    assert [e.action for e in await events(env, entity_id=target.id)] == [
        "user.blocked",
        "user.unblocked",
    ]


async def test_fr5a_unblock_resets_failed_login_counter_and_lock(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user", password=PW, blocked=True)
    await env.execute(
        text(
            "UPDATE app_user SET failed_login_count = 3, login_locked_until = :t WHERE id = :u"
        ).bindparams(t=FIXED_NOW + timedelta(minutes=10), u=target.id)
    )

    response = await env.client.post(f"{ADMIN_USERS}/{target.id}/unblock", headers=env.auth(token))

    assert response.status_code == 204
    row = await env.user_row(target.id)
    assert row.failed_login_count == 0
    assert row.login_locked_until is None
    assert (await env.login(target.login, PW)).status_code == 200


async def test_ac44_unblock_active_user_is_idempotent_204_without_event(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")

    response = await env.client.post(f"{ADMIN_USERS}/{target.id}/unblock", headers=env.auth(token))

    assert response.status_code == 204
    assert await events(env, entity_id=target.id) == []


# --- сброс пароля (FR-65, AC-45, AC-113) ------------------------------------------------------


async def test_ac45_reset_password_204_old_password_rejected_new_requires_change(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, tokens = await seed(env, ws, "business_admin", password=PW, sessions=2)
    new = "Fresh-0ne-Time-Pa55-xq"

    response = await env.client.post(
        f"{ADMIN_USERS}/{target.id}/reset-password",
        json={OTP_FIELD: new},
        headers=env.auth(token),
    )

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert (await env.login(target.login, PW)).status_code == 401  # прежний пароль не подходит
    for t in tokens:
        assert (await env.me(t)).status_code == 401  # сессии завершены
    login = await env.login(target.login, new)
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True
    assert login.json()["user"]["role"] == "business_admin"  # роль не тронута
    token_new = env.token_from(login)
    assert token_new
    me = await env.me(token_new)
    assert me.status_code == 403
    assert code_of(me) == "password_change_required"
    assert [e.action for e in await events(env, entity_id=target.id)] == ["user.password_reset"]


async def test_ac113_reset_password_resets_failed_login_counter_and_lock(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user", password=PW)
    await env.execute(
        text(
            "UPDATE app_user SET failed_login_count = 4, login_locked_until = :t WHERE id = :u"
        ).bindparams(t=FIXED_NOW + timedelta(minutes=10), u=target.id)
    )

    response = await env.client.post(
        f"{ADMIN_USERS}/{target.id}/reset-password",
        json={OTP_FIELD: OTP},
        headers=env.auth(token),
    )

    assert response.status_code == 204
    row = await env.user_row(target.id)
    assert (row.failed_login_count, row.login_locked_until) == (0, None)
    assert (await env.login(target.login, OTP)).status_code == 200


@pytest.mark.parametrize(
    ("password", "code"),
    [("zq9-lk3-px7", "password_too_short"), (_common_entry(), "password_too_common")],
    ids=["11-chars", "common"],
)
async def test_ac113_reset_with_bad_password_is_422_and_nothing_changes(
    api_env: ApiEnv, password: str, code: str
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, (old_token,) = await seed(env, ws, "user", password=PW)

    response = await env.client.post(
        f"{ADMIN_USERS}/{target.id}/reset-password",
        json={OTP_FIELD: password},
        headers=env.auth(token),
    )

    assert response.status_code == 422, response.text
    assert code_of(response) == code
    assert password not in response.text
    assert (await env.me(old_token)).status_code == 200  # сессия цела
    assert (await env.login(target.login, PW)).status_code == 200  # пароль прежний
    assert await events(env, entity_id=target.id) == []


async def test_ac113_reset_password_repeat_is_allowed(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")
    url = f"{ADMIN_USERS}/{target.id}/reset-password"

    first = await env.client.post(url, json={OTP_FIELD: OTP}, headers=env.auth(token))
    second = await env.client.post(
        url, json={OTP_FIELD: "Second-0ne-Time-Pa55-xq"}, headers=env.auth(token)
    )

    assert (first.status_code, second.status_code) == (204, 204)
    assert (await env.login(target.login, "Second-0ne-Time-Pa55-xq")).status_code == 200


# --- завершение сессий (FR-62, AC-39) ---------------------------------------------------------


async def test_ac39_revoke_sessions_204_login_still_possible(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, tokens = await seed(env, ws, "user", password=PW, sessions=3)

    response = await env.client.post(
        f"{ADMIN_USERS}/{target.id}/revoke-sessions", headers=env.auth(token)
    )

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert await env.session_ids(target.id) == []
    for t in tokens:
        assert (await env.me(t)).status_code == 401
    login = await env.login(target.login, PW)  # AC-39: вход возможен
    assert login.status_code == 200
    got = await env.client.get(f"{ADMIN_USERS}/{target.id}", headers=env.auth(token))
    assert got.json()["is_blocked"] is False
    assert [e.action for e in await events(env, entity_id=target.id)] == ["user.sessions_revoked"]


async def test_ac39_revoke_sessions_with_no_sessions_is_204(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user", sessions=0)
    url = f"{ADMIN_USERS}/{target.id}/revoke-sessions"

    first = await env.client.post(url, headers=env.auth(token))
    second = await env.client.post(url, headers=env.auth(token))

    assert (first.status_code, second.status_code) == (204, 204)


async def test_ac39_admin_can_revoke_own_sessions_and_then_gets_401(api_env: ApiEnv) -> None:
    env = api_env
    _, admin, token = await admin_in_new_workspace(env)
    await seed(env, await new_workspace(env), "tech_admin")  # шум

    response = await env.client.post(
        f"{ADMIN_USERS}/{admin.id}/revoke-sessions", headers=env.auth(token)
    )

    assert response.status_code == 204
    assert (await env.me(token)).status_code == 401


# --- 404 для несуществующих целей, 422 по формату id ------------------------------------------


@pytest.mark.parametrize("action", ["get", "block", "unblock", "revoke", "reset", "role_user"])
async def test_ac21_unknown_user_id_is_404_on_every_endpoint(api_env: ApiEnv, action: str) -> None:
    from tests.admin_support import admin_call

    env = api_env
    _, admin, token = await admin_in_new_workspace(env)
    own = await admin_call(env, token, "get", admin.id)  # раздел существует и доступен
    assert own.status_code == 200, own.text
    response = await admin_call(env, token, action, uuid.uuid4())
    assert response.status_code == 404, response.text
    assert code_of(response) == "not_found"


# --- пароли не утекают (D-15, FR-57, AC-113) --------------------------------------------------


async def test_ac113_passwords_and_hashes_are_not_in_responses_or_logs(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    api_env: ApiEnv,
) -> None:
    from app.core.logging import configure_logging

    env = api_env
    configure_logging("DEBUG")
    capsys.readouterr()
    caplog.set_level(logging.DEBUG)
    secrets = [
        "Create-Leak-Pa55phrase-1101",
        "Reset-Leak-Pa55phrase-2202",
        "zq9-lk3-px7",  # 11 символов
        "Taken-Leak-Pa55phrase-3303",
    ]
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user", password=PW)
    responses: list[httpx.Response] = []

    responses.append(await _create(env, token, "leak.one", secrets[0]))
    responses.append(await _create(env, token, "leak.one", secrets[3]))  # login_taken
    responses.append(await _create(env, token, "leak.two", secrets[2]))  # too_short
    responses.append(
        await env.client.post(
            f"{ADMIN_USERS}/{target.id}/reset-password",
            json={OTP_FIELD: secrets[1]},
            headers=env.auth(token),
        )
    )
    responses.append(await env.client.get(ADMIN_USERS, headers=env.auth(token)))
    responses.append(await env.client.get(f"{ADMIN_USERS}/{target.id}", headers=env.auth(token)))
    assert [r.status_code for r in responses] == [201, 422, 422, 204, 200, 200]
    hashes = [PLACEHOLDER_HASH]
    created_hash = await env.execute(
        text("SELECT password_hash FROM app_user WHERE login = 'leak.one'")
    )
    assert created_hash
    hashes.append(created_hash[0][0])

    for response in responses:
        haystacks = [response.text, str(sorted(response.headers.items()))]
        for secret in secrets:
            for haystack in haystacks:
                assert secret not in haystack
        for value in hashes:
            assert value not in response.text

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines, "access-лог пуст: проверка бессмысленна"
    for line in lines:
        json.loads(line)
    assert ADMIN_USERS in out
    log_haystacks = [out, caplog.text]
    for record in caplog.records:
        log_haystacks += [record.getMessage(), repr(record.args), str(record.exc_text)]
    for secret in secrets:
        for haystack in log_haystacks:
            assert secret not in haystack, f"пароль попал в лог: {secret[:10]}..."

    # события журнала: ни пароля, ни хеша в details (FR-57)
    dumped = json.dumps(
        [(str(e.action), e.details) for e in await events(env)], default=str, ensure_ascii=False
    )
    for secret in secrets:
        assert secret not in dumped
    assert "$argon2" not in dumped


# --- гейты: доступ, 401, 403, origin (plan §4.5; FR-42, FR-45a; AC-26 в части БА/П) -------------


def _endpoints(target: Any) -> list[tuple[str, str, str, Any]]:
    """(имя, метод, путь, тело) всех эндпоинтов раздела для цели ``target``."""
    base = f"{ADMIN_USERS}/{target}"
    return [
        ("list", "GET", ADMIN_USERS, None),
        ("create", "POST", ADMIN_USERS, {"login": "gate.check", OTP_FIELD: OTP}),
        ("get", "GET", base, None),
        ("block", "POST", f"{base}/block", None),
        ("unblock", "POST", f"{base}/unblock", None),
        ("reset", "POST", f"{base}/reset-password", {OTP_FIELD: OTP}),
        ("revoke", "POST", f"{base}/revoke-sessions", None),
        ("role", "PUT", f"{base}/role", {"role": "user"}),  # 002/AC-5: 403 не зависит от тела
    ]


async def _fire(
    env: ApiEnv, method: str, path: str, body: Any, headers: dict[str, str]
) -> httpx.Response:
    kwargs: dict[str, Any] = {} if body is None else {"json": body}
    return await env.client.request(method, path, headers=headers, **kwargs)


async def _assert_target_untouched(env: ApiEnv, target_id: uuid.UUID, sessions: int) -> None:
    row = await env.user_row(target_id)
    assert row.is_blocked is False
    assert row.must_change_password is False
    assert await member_role(env, target_id) == "user"
    assert len(await env.session_ids(target_id)) == sessions


async def test_fr7_without_cookie_every_admin_endpoint_is_401(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")
    for name, method, path, body in _endpoints(target.id):
        response = await _fire(env, method, path, body, {})
        assert (response.status_code, code_of(response)) == (401, "not_authenticated"), name


@pytest.mark.parametrize("role", ["business_admin", "user"])
async def test_ac26_fr42_business_admin_and_user_get_403_on_every_admin_endpoint(
    api_env: ApiEnv, role: str
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    actor, (token,) = await seed(env, ws, role)
    target, _ = await seed(env, ws, "user", sessions=1)
    foreign, _ = await seed(env, await new_workspace(env), "user")

    for target_id in (target.id, uuid.uuid4(), foreign.id):  # FR-45a: 403 для ЛЮБОГО id
        for name, method, path, body in _endpoints(target_id):
            response = await _fire(env, method, path, body, env.auth(token))
            assert response.status_code == 403, (name, target_id, response.text)
            assert code_of(response) == "forbidden", name
    await _assert_target_untouched(env, target.id, 1)
    _, (checker,) = await seed(env, ws, "tech_admin")
    assert [r for r in await _list_all(env, checker) if r["login"] == "gate.check"] == []


@pytest.mark.parametrize("role", ["business_admin", "user"])
async def test_fr45a_403_precedes_validation_and_404_for_business_admin_and_user(
    api_env: ApiEnv, role: str
) -> None:
    """Гейт раньше разбора пути и тела: не-UUID в пути и пустое тело дают 403, не 422/404."""
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, (token,) = await seed(env, ws, role)
    base = f"{ADMIN_USERS}/not-a-uuid"
    cases = [
        ("GET", base, None),
        ("POST", f"{base}/block", None),
        ("POST", f"{base}/reset-password", {}),
        ("PUT", f"{base}/role", {"role": "nonsense"}),
        ("POST", ADMIN_USERS, {}),
    ]
    for method, path, body in cases:
        response = await _fire(env, method, path, body, env.auth(token))
        assert response.status_code == 403, (method, path, response.text)


async def test_fr66_user_without_role_gets_403_no_role_on_every_admin_endpoint(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, (token,) = await seed(env, ws, None)
    target, _ = await seed(env, ws, "user")
    for name, method, path, body in _endpoints(target.id):
        response = await _fire(env, method, path, body, env.auth(token))
        assert (response.status_code, code_of(response)) == (403, "no_role"), name
    await _assert_target_untouched(env, target.id, 1)


async def test_fr55_one_time_password_admin_gets_403_password_change_required(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, (token,) = await seed(env, ws, "tech_admin", must_change_password=True)
    target, _ = await seed(env, ws, "user")
    for name, method, path, body in _endpoints(target.id):
        response = await _fire(env, method, path, body, env.auth(token))
        assert (response.status_code, code_of(response)) == (
            403,
            "password_change_required",
        ), name
    await _assert_target_untouched(env, target.id, 1)


async def test_d16_foreign_origin_on_unsafe_admin_requests_is_403_origin_mismatch(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")
    headers = {**env.auth(token), "Origin": "http://evil.example"}
    for name, method, path, body in _endpoints(target.id):
        if method == "GET":
            continue
        response = await _fire(env, method, path, body, headers)
        assert (response.status_code, code_of(response)) == (403, "origin_mismatch"), name
    await _assert_target_untouched(env, target.id, 1)
    assert [i for i in await _list_all(env, token) if i["login"] == "gate.check"] == []


# Удалён ``test_fr42_mixed_role_has_access_to_admin_section``: СМ больше не администратор учётных
# записей (002/FR-3). Заменитель: ``test_002_ac3_*`` в api/test_tech_admins_002.py.


async def test_fr12_not_allowed_methods_on_admin_users_are_405(api_env: ApiEnv) -> None:
    """Удаления учётных записей в R1 нет: DELETE/PATCH не заведены."""
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")
    for method in ("DELETE", "PATCH"):
        response = await env.client.request(
            method, f"{ADMIN_USERS}/{target.id}", headers=env.auth(token)
        )
        assert response.status_code == 405, (method, response.text)
    assert await member_role(env, target.id) == "user"


# --- OpenAPI ---------------------------------------------------------------------------------


def _admin_operations(env: ApiEnv) -> dict[tuple[str, str], dict[str, Any]]:
    schema = env.app.openapi()
    ops: dict[tuple[str, str], dict[str, Any]] = {}
    for path, item in schema["paths"].items():
        if path.startswith("/api/v1/admin/users"):
            for method, op in item.items():
                ops[(method.upper(), path)] = op
    return ops


def _collect_refs(node: Any, schemas: dict[str, Any], seen: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            name = ref.rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                _collect_refs(schemas[name], schemas, seen)
        for value in node.values():
            _collect_refs(value, schemas, seen)
    elif isinstance(node, list):
        for value in node:
            _collect_refs(value, schemas, seen)


async def test_t17_openapi_declares_all_admin_user_operations(api_env: ApiEnv) -> None:
    ops = _admin_operations(api_env)
    expected = {
        ("GET", "/api/v1/admin/users"),
        ("POST", "/api/v1/admin/users"),
        ("GET", "/api/v1/admin/users/{user_id}"),
        ("POST", "/api/v1/admin/users/{user_id}/block"),
        ("POST", "/api/v1/admin/users/{user_id}/unblock"),
        ("POST", "/api/v1/admin/users/{user_id}/reset-password"),
        ("POST", "/api/v1/admin/users/{user_id}/revoke-sessions"),
        ("PUT", "/api/v1/admin/users/{user_id}/role"),
    }
    normalized = {(m, re.sub(r"\{[^}]+\}", "{user_id}", p)) for (m, p) in ops}
    assert normalized == expected


async def test_t17_operation_id_equals_function_name_and_is_unique(api_env: ApiEnv) -> None:
    from tests.api.test_route_guards import _iter_routes

    ops = _admin_operations(api_env)
    assert len(ops) == 8
    ids = [op["operationId"] for op in ops.values()]
    assert len(ids) == len(set(ids))
    by_path: dict[tuple[str, str], str] = {}
    for route in _iter_routes(api_env.app.routes):
        if route.path.startswith("/api/v1/admin/users"):
            for method in set(route.methods) - {"HEAD", "OPTIONS"}:
                by_path[(method, route.path)] = route.endpoint.__name__
    assert set(by_path) == set(ops)
    for key, op in ops.items():
        assert op["operationId"] == by_path[key], key


async def test_d15_t17_openapi_responses_have_no_password_fields(api_env: ApiEnv) -> None:
    schema = api_env.app.openapi()
    schemas = schema["components"]["schemas"]
    operations = _admin_operations(api_env)
    assert len(operations) == 8
    for key, op in operations.items():
        seen: set[str] = set()
        _collect_refs(op.get("responses", {}), schemas, seen)
        for name in seen:
            if name.startswith(("HTTPValidationError", "ValidationError")):
                continue
            props = set(schemas[name].get("properties", {}))
            forbidden = {
                "password",
                "one_time_password",
                "password_hash",
                "hashed_password",
                "hash",
            }
            assert not (props & forbidden), (key, name)


async def test_d15_t17_openapi_request_password_is_write_only_secret(api_env: ApiEnv) -> None:
    schema = api_env.app.openapi()
    schemas = schema["components"]["schemas"]
    found = 0
    for (method, path), op in _admin_operations(api_env).items():
        body = op.get("requestBody")
        if not body:
            continue
        seen: set[str] = set()
        _collect_refs(body, schemas, seen)
        for name in seen:
            prop = schemas[name].get("properties", {}).get(OTP_FIELD)
            if prop is None:
                continue
            found += 1
            assert prop.get("format") == "password" or prop.get("writeOnly") is True, (
                method,
                path,
                prop,
            )
    assert found == 2, "ожидалось тело создания и сброса пароля с полем одноразового пароля"


async def test_d34_t17_list_response_is_page_of_one_named_item_schema(api_env: ApiEnv) -> None:
    schema = api_env.app.openapi()
    schemas = schema["components"]["schemas"]
    op = _admin_operations(api_env)[("GET", "/api/v1/admin/users")]
    ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    page = schemas[ref.rsplit("/", 1)[-1]]
    assert set(page["properties"]) == {"items", "page", "page_size", "has_next"}
    item_ref = page["properties"]["items"]["items"]["$ref"]
    item = schemas[item_ref.rsplit("/", 1)[-1]]
    assert set(item["properties"]) == ADMIN_VIEW_FIELDS
    # то же представление отдают карточка и создание: одна схема, без коллизий имён
    get_ref = _admin_operations(api_env)[("GET", "/api/v1/admin/users/{user_id}")]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]["$ref"]
    assert get_ref == item_ref
    for name in schemas:
        assert "__" not in name and "." not in name, f"коллизия имён схем: {name}"
