"""R8-T04: имя и фамилия в Admin API (spec 019: FR-3a..FR-3c; AC-22, AC-33, AC-35; RG-17)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from tests.admin_support import (
    ADMIN_USERS,
    ADMIN_VIEW_FIELDS,
    OTP,
    OTP_FIELD,
    admin_in_new_workspace,
    code_of,
    events,
    seed,
)

if TYPE_CHECKING:
    import httpx

    from tests.conftest import ApiEnv

VALID = {"first_name": "Иван", "last_name": "Петров"}


async def _post(env: ApiEnv, token: str, **over: Any) -> httpx.Response:
    body: dict[str, Any] = {"login": "ivan.petrov", **VALID, OTP_FIELD: OTP, **over}
    body = {k: v for k, v in body.items() if v is not ...}
    return await env.client.post(ADMIN_USERS, json=body, headers=env.auth(token))


async def _db_names(env: ApiEnv, user_id: uuid.UUID) -> tuple[Any, Any, Any]:
    rows = await env.execute(
        text(
            "SELECT first_name, last_name, self_registered FROM app_user WHERE id = :u"
        ).bindparams(u=user_id)
    )
    assert rows
    return tuple(rows[0])  # type: ignore[return-value]


async def _count_users(env: ApiEnv, login: str) -> int:
    rows = await env.execute(
        text("SELECT count(*) FROM app_user WHERE login = :l").bindparams(l=login)
    )
    assert rows
    return int(rows[0][0])


async def test_019_ac33_create_with_names_returns_201_and_stores_them(api_env: ApiEnv) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)

    response = await _post(env, token, first_name="  Иван ", last_name=" Петров-Сидоров ")

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == ADMIN_VIEW_FIELDS
    assert (body["first_name"], body["last_name"]) == ("Иван", "Петров-Сидоров")
    assert body["self_registered"] is False
    assert body["must_change_password"] is True
    assert await _db_names(env, uuid.UUID(body["id"])) == ("Иван", "Петров-Сидоров", False)
    got = await env.client.get(f"{ADMIN_USERS}/{body['id']}", headers=env.auth(token))
    assert got.json() == body


async def test_019_ac33_user_created_event_has_no_name_values(api_env: ApiEnv) -> None:
    env = api_env
    _, admin, token = await admin_in_new_workspace(env)
    body = (await _post(env, token, first_name="Уникум", last_name="Неповторимов")).json()

    rows = await events(env, entity_id=uuid.UUID(body["id"]))

    assert [e.action for e in rows] == ["user.created"]
    assert rows[0].actor_id == admin.id
    blob = repr([tuple(r) for r in rows])
    assert "Уникум" not in blob
    assert "Неповторимов" not in blob


@pytest.mark.parametrize("bad", ["", "   ", "я" * 101, "Ан\nна", "Ан\x00на"])
@pytest.mark.parametrize(
    ("field", "code"), [("first_name", "first_name_invalid"), ("last_name", "last_name_invalid")]
)
async def test_019_ac33_invalid_name_is_422_with_field_code_and_no_user(
    api_env: ApiEnv, field: str, code: str, bad: str
) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)

    response = await _post(env, token, **{field: bad})

    assert response.status_code == 422, response.text
    assert code_of(response) == code
    assert await _count_users(env, "ivan.petrov") == 0


@pytest.mark.parametrize("field", ["first_name", "last_name"])
async def test_019_ac33_missing_name_field_is_422_and_no_user(api_env: ApiEnv, field: str) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)

    response = await _post(env, token, **{field: ...})

    assert response.status_code == 422, response.text
    assert await _count_users(env, "ivan.petrov") == 0


async def test_019_ac33_name_check_order_first_before_last_before_password(
    api_env: ApiEnv,
) -> None:
    """RG-17: login_invalid -> login_taken -> first -> last -> email -> пароль."""
    env = api_env
    _, _, token = await admin_in_new_workspace(env)

    both = await _post(env, token, first_name="", last_name="", **{OTP_FIELD: "short"})
    assert code_of(both) == "first_name_invalid"
    last = await _post(env, token, last_name="", **{OTP_FIELD: "short"})
    assert code_of(last) == "last_name_invalid"
    bad_login = await _post(env, token, login="Плохой логин", first_name="")
    assert code_of(bad_login) == "login_invalid"


async def test_019_ac35_ta_sets_names_via_put_name(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")

    response = await env.client.put(
        f"{ADMIN_USERS}/{target.id}/name",
        json={"first_name": " Анна ", "last_name": "Орлова"},
        headers=env.auth(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == ADMIN_VIEW_FIELDS
    assert (body["first_name"], body["last_name"]) == ("Анна", "Орлова")
    assert await _db_names(env, target.id) == ("Анна", "Орлова", False)
    rows = await events(env, entity_id=target.id)
    assert [e.action for e in rows] == ["user.name_changed"]
    assert "Орлова" not in repr([tuple(r) for r in rows])


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"first_name": "", "last_name": "Орлова"}, "first_name_invalid"),
        ({"first_name": "Анна", "last_name": "   "}, "last_name_invalid"),
        ({"first_name": "Анна", "last_name": "я" * 101}, "last_name_invalid"),
    ],
)
async def test_019_ac35_put_name_invalid_is_422(
    api_env: ApiEnv, payload: dict[str, str], code: str
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")

    response = await env.client.put(
        f"{ADMIN_USERS}/{target.id}/name", json=payload, headers=env.auth(token)
    )

    assert response.status_code == 422, response.text
    assert code_of(response) == code
    assert await _db_names(env, target.id) == (None, None, False)


async def test_019_ac35_put_name_rejects_extra_fields(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")

    response = await env.client.put(
        f"{ADMIN_USERS}/{target.id}/name",
        json={**VALID, "role": "tech_admin"},
        headers=env.auth(token),
    )

    assert response.status_code == 422, response.text
    assert await _db_names(env, target.id) == (None, None, False)


async def test_019_ac35_put_name_unknown_or_foreign_user_is_404(api_env: ApiEnv) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    other_ws, _, _ = await admin_in_new_workspace(env)
    foreign, _ = await seed(env, other_ws, "user")

    for uid in (uuid.uuid4(), foreign.id):
        response = await env.client.put(
            f"{ADMIN_USERS}/{uid}/name", json=VALID, headers=env.auth(token)
        )
        assert response.status_code == 404, response.text
        assert code_of(response) == "not_found"
    assert await _db_names(env, foreign.id) == (None, None, False)


@pytest.mark.parametrize("role", ["business_admin", "user"])
async def test_019_ac35_put_name_forbidden_for_non_tech_admin(api_env: ApiEnv, role: str) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    actor, (token,) = await seed(env, ws, role)
    target, _ = await seed(env, ws, "user")

    response = await env.client.put(
        f"{ADMIN_USERS}/{target.id}/name", json=VALID, headers=env.auth(token)
    )

    assert response.status_code == 403, response.text
    assert actor.id != target.id
    assert await _db_names(env, target.id) == (None, None, False)


async def test_019_ac22_list_items_carry_names_and_self_registered(api_env: ApiEnv) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    created = (await _post(env, token)).json()

    page = await env.client.get(ADMIN_USERS, headers=env.auth(token))

    assert page.status_code == 200, page.text
    item = next(i for i in page.json()["items"] if i["id"] == created["id"])
    assert set(item) == ADMIN_VIEW_FIELDS
    assert (item["first_name"], item["last_name"], item["self_registered"]) == (
        "Иван",
        "Петров",
        False,
    )
