"""R8-T05: свой профиль, ``GET /me`` с именами и ``PUT /me/name`` (spec 019: FR-3c; AC-34)."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from tests.admin_support import ADMIN_USERS, admin_in_new_workspace, code_of, events, seed

if TYPE_CHECKING:
    from tests.conftest import ApiEnv

ME = "/api/v1/me"
ME_NAME = "/api/v1/me/name"
VALID = {"first_name": "Иван", "last_name": "Петров"}
ROLES = ["tech_admin", "business_admin", "user"]


async def _db_names(env: ApiEnv, user_id: uuid.UUID) -> tuple[Any, Any]:
    rows = await env.execute(
        text("SELECT first_name, last_name FROM app_user WHERE id = :u").bindparams(u=user_id)
    )
    assert rows
    return tuple(rows[0])  # type: ignore[return-value]


@pytest.mark.parametrize("role", ROLES)
async def test_019_ac34_get_me_has_null_names_by_default(api_env: ApiEnv, role: str) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, (token,) = await seed(env, ws, role)

    response = await env.client.get(ME, headers=env.auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] is None
    assert body["last_name"] is None


@pytest.mark.parametrize("role", ROLES)
async def test_019_ac34_any_role_sets_own_name_and_get_me_returns_it(
    api_env: ApiEnv, role: str
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    user, (token,) = await seed(env, ws, role)

    response = await env.client.put(
        ME_NAME,
        json={"first_name": "  Иван ", "last_name": " Петров-Сидоров "},
        headers=env.auth(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["first_name"], body["last_name"]) == ("Иван", "Петров-Сидоров")
    assert body["id"] == str(user.id)
    assert body["role"] == role
    assert await _db_names(env, user.id) == ("Иван", "Петров-Сидоров")
    got = await env.client.get(ME, headers=env.auth(token))
    assert got.json() == body


async def test_019_ac34_put_me_name_changes_only_own_names(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    me, (token,) = await seed(env, ws, "business_admin")
    other, _ = await seed(env, ws, "user")

    response = await env.client.put(ME_NAME, json=VALID, headers=env.auth(token))

    assert response.status_code == 200, response.text
    assert await _db_names(env, me.id) == ("Иван", "Петров")
    assert await _db_names(env, other.id) == (None, None)


@pytest.mark.parametrize("bad", ["", "   ", "я" * 200, "Ан\nна", "Ан\x00на"])
@pytest.mark.parametrize(
    ("field", "code"), [("first_name", "first_name_invalid"), ("last_name", "last_name_invalid")]
)
async def test_019_ac34_invalid_name_is_422_with_field_code(
    api_env: ApiEnv, field: str, code: str, bad: str
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    user, (token,) = await seed(env, ws, "user")

    response = await env.client.put(ME_NAME, json={**VALID, field: bad}, headers=env.auth(token))

    assert response.status_code == 422, response.text
    assert code_of(response) == code
    assert await _db_names(env, user.id) == (None, None)
    assert await events(env, entity_id=user.id) == []


async def test_019_ac34_name_longer_than_100_is_422(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, (token,) = await seed(env, ws, "user")

    response = await env.client.put(
        ME_NAME, json={**VALID, "last_name": "я" * 101}, headers=env.auth(token)
    )

    assert response.status_code == 422, response.text
    assert code_of(response) == "last_name_invalid"


async def test_019_ac34_put_me_name_rejects_extra_fields_and_missing(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    user, (token,) = await seed(env, ws, "user")

    extra = await env.client.put(
        ME_NAME, json={**VALID, "role": "tech_admin"}, headers=env.auth(token)
    )
    missing = await env.client.put(ME_NAME, json={"first_name": "Иван"}, headers=env.auth(token))

    assert extra.status_code == 422, extra.text
    assert missing.status_code == 422, missing.text
    assert await _db_names(env, user.id) == (None, None)


async def test_019_ac34_put_me_name_without_session_is_401(api_env: ApiEnv) -> None:
    response = await api_env.client.put(ME_NAME, json=VALID)

    assert response.status_code == 401, response.text


async def test_019_ac34_put_me_name_without_role_is_403_no_role(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    user, (token,) = await seed(env, ws, None)

    response = await env.client.put(ME_NAME, json=VALID, headers=env.auth(token))

    assert response.status_code == 403, response.text
    assert code_of(response) == "no_role"
    assert await _db_names(env, user.id) == (None, None)


async def test_019_ac34_put_me_name_with_forced_password_change_is_403(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    user, (token,) = await seed(env, ws, "user", must_change_password=True)

    response = await env.client.put(ME_NAME, json=VALID, headers=env.auth(token))

    assert response.status_code == 403, response.text
    assert code_of(response) == "password_change_required"
    assert await _db_names(env, user.id) == (None, None)


@pytest.mark.parametrize("role", ["business_admin", "user"])
async def test_019_ac34_non_ta_cannot_rename_other_via_admin_endpoint(
    api_env: ApiEnv, role: str
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, (token,) = await seed(env, ws, role)
    target, _ = await seed(env, ws, "user")

    response = await env.client.put(
        f"{ADMIN_USERS}/{target.id}/name", json=VALID, headers=env.auth(token)
    )

    assert response.status_code == 403, response.text
    assert await _db_names(env, target.id) == (None, None)


async def test_019_ac34_name_changed_event_actor_is_self_and_has_no_values(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    user, (token,) = await seed(env, ws, "business_admin")

    response = await env.client.put(
        ME_NAME,
        json={"first_name": "Уникум", "last_name": "Неповторимов"},
        headers=env.auth(token),
    )

    assert response.status_code == 200, response.text
    rows = await events(env, entity_id=user.id)
    assert [e.action for e in rows] == ["user.name_changed"]
    assert rows[0].actor_id == user.id
    assert rows[0].entity_id == user.id
    blob = repr([tuple(r) for r in rows])
    assert "Уникум" not in blob
    assert "Неповторимов" not in blob
    assert set(rows[0].changed_fields) == {"first_name", "last_name"}


async def test_019_ac34_changed_fields_lists_only_really_changed(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    user, (token,) = await seed(env, ws, "user")
    await env.client.put(ME_NAME, json=VALID, headers=env.auth(token))

    again = await env.client.put(
        ME_NAME, json={**VALID, "last_name": "Сидоров"}, headers=env.auth(token)
    )

    assert again.status_code == 200, again.text
    rows = await events(env, entity_id=user.id)
    assert [e.action for e in rows] == ["user.name_changed", "user.name_changed"]
    assert set(rows[0].changed_fields) == {"first_name", "last_name"}
    assert list(rows[1].changed_fields) == ["last_name"]


@pytest.mark.parametrize(
    "same", [VALID, {"first_name": " Иван ", "last_name": "Петров "}], ids=["exact", "padded"]
)
async def test_019_ac34_same_name_again_is_200_and_writes_no_event(
    api_env: ApiEnv, same: dict[str, str]
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    user, (token,) = await seed(env, ws, "user")
    first = await env.client.put(ME_NAME, json=VALID, headers=env.auth(token))
    assert first.status_code == 200, first.text
    before = await events(env, entity_id=user.id)

    again = await env.client.put(ME_NAME, json=same, headers=env.auth(token))

    assert again.status_code == 200, again.text
    assert (again.json()["first_name"], again.json()["last_name"]) == ("Иван", "Петров")
    after = await events(env, entity_id=user.id)
    assert len(before) == 1
    assert len(after) == len(before)
    assert [e.action for e in after] == ["user.name_changed"]


@pytest.mark.parametrize("field", ["first_name", "last_name"])
@pytest.mark.parametrize(
    "bad", ["ZZQ019MARKER" + "я" * (101 - len("ZZQ019MARKER")), "ZZQ019MARKER\nx"]
)
async def test_019_ac34_422_body_does_not_echo_submitted_name(
    api_env: ApiEnv, field: str, bad: str
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    user, (token,) = await seed(env, ws, "user")

    response = await env.client.put(ME_NAME, json={**VALID, field: bad}, headers=env.auth(token))

    assert response.status_code == 422, response.text
    assert "ZZQ019MARKER" not in response.text
    assert await _db_names(env, user.id) == (None, None)


async def test_019_nfr1_put_me_name_logs_carry_no_name_values(
    api_env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    user, (token,) = await seed(env, ws, "user")
    marker = "Ivanka-ZZLOG019"
    caplog.set_level(logging.INFO)

    response = await env.client.put(
        ME_NAME, json={"first_name": marker, "last_name": "Петров"}, headers=env.auth(token)
    )

    assert response.status_code == 200, response.text
    assert await _db_names(env, user.id) == (marker, "Петров")
    records = [r for r in caplog.records if r.levelno >= logging.INFO]
    # контроль: запись access-лога этого запроса реально захвачена, иначе проверка пуста
    assert any(getattr(r, "path", None) == ME_NAME for r in records), caplog.text
    leaked = [
        r.getMessage() for r in records if marker in r.getMessage() or marker in repr(r.__dict__)
    ]
    assert leaked == []
