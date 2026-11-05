"""R7-T10: email в админке учётных записей (spec 007, plan §4.4, PR-1, PR-3, PR-4, Q-6, Q-8).

AC-1 (API), AC-14 (бэкенд: ``email`` в списке и ``GET``), FR-1, FR-2.
Контракт: ``POST /admin/users`` принимает ``email``; ``PUT /admin/users/{id}/email``
с телом ``{email: str|null}``; ``AdminUser.email``;
занятый адрес -> 409 ``email_taken``; плохой формат -> 422 ``email_invalid``;
событие ``user.email_changed`` без значений; повтор того же значения событие не пишет.
"""

import uuid
from typing import Any

import httpx
from sqlalchemy import text

from tests.admin_support import (
    ADMIN_USERS,
    OTP,
    OTP_FIELD,
    admin_in_new_workspace,
    code_of,
    events,
    new_workspace,
)
from tests.admin_support import (
    seed as _seed_base,
)
from tests.conftest import ApiEnv

AUDIT = "/api/v1/admin/audit"
CHANGED = "user.email_changed"


async def seed(
    env: ApiEnv, ws: Any, role: str | None, *, email: str | None = None
) -> tuple[Any, list[str]]:
    """``admin_support.seed`` + email (минуя API; значение уже в нижнем регистре)."""
    user, tokens = await _seed_base(env, ws, role)
    if email is not None:
        await env.execute(
            text("UPDATE app_user SET email = :e WHERE id = :u").bindparams(e=email, u=user.id)
        )
    return user, tokens


async def _put(env: ApiEnv, token: str | None, user_id: Any, body: Any) -> httpx.Response:
    headers = {} if token is None else env.auth(token)
    return await env.client.put(f"{ADMIN_USERS}/{user_id}/email", json=body, headers=headers)


async def _create(env: ApiEnv, token: str, login: str, **extra: Any) -> httpx.Response:
    body = {"login": login, OTP_FIELD: OTP, **extra}
    return await env.client.post(ADMIN_USERS, json=body, headers=env.auth(token))


async def _stored_email(env: ApiEnv, user_id: Any) -> str | None:
    rows = await env.execute(
        text("SELECT email FROM app_user WHERE id = :u").bindparams(u=uuid.UUID(str(user_id)))
    )
    assert rows
    return None if rows[0][0] is None else str(rows[0][0])


async def _email_events(env: ApiEnv, user_id: Any) -> list[Any]:
    found = await events(env, entity_id=uuid.UUID(str(user_id)))
    return [e for e in found if e.action == CHANGED]


# --- AC-1: нормализация, уникальность -----------------------------------------------------------


async def test_007_ac1_create_with_email_normalizes_and_returns_lowercase(api_env: ApiEnv) -> None:
    _, _, token = await admin_in_new_workspace(api_env)

    response = await _create(api_env, token, "ivan.new", email="  A@X.ru ")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "a@x.ru"
    assert await _stored_email(api_env, body["id"]) == "a@x.ru"


async def test_007_ac1_second_user_cannot_take_same_email_case_insensitive_on_create(
    api_env: ApiEnv,
) -> None:
    _, _, token = await admin_in_new_workspace(api_env)
    assert (await _create(api_env, token, "first.one", email="A@x.ru")).status_code == 201

    response = await _create(api_env, token, "second.one", email="a@X.ru")

    assert (response.status_code, code_of(response)) == (409, "email_taken")
    assert "a@x.ru" not in response.text.lower()
    rows = await api_env.execute(text("SELECT count(*) FROM app_user WHERE login = 'second.one'"))
    assert rows and rows[0][0] == 0


async def test_007_ac1_put_taken_email_gives_409_email_taken(api_env: ApiEnv) -> None:
    ws, _, token = await admin_in_new_workspace(api_env)
    await seed(api_env, ws, "user", email="a@x.ru")
    other, _ = await seed(api_env, ws, "user")

    response = await _put(api_env, token, other.id, {"email": "a@X.ru"})

    assert (response.status_code, code_of(response)) == (409, "email_taken")
    assert await _stored_email(api_env, other.id) is None
    assert await _email_events(api_env, other.id) == []


async def test_007_ac1_email_taken_across_workspaces(api_env: ApiEnv) -> None:
    """Уникальность глобальна (``UNIQUE (email)``), а не по пространству."""
    ws, _, token = await admin_in_new_workspace(api_env)
    foreign, _ = await seed(api_env, await new_workspace(api_env), "user", email="shared@x.ru")
    mine, _ = await seed(api_env, ws, "user")

    response = await _put(api_env, token, mine.id, {"email": "shared@x.ru"})

    assert (response.status_code, code_of(response)) == (409, "email_taken")
    assert await _stored_email(api_env, foreign.id) == "shared@x.ru"


async def test_007_ac1_put_sets_changes_and_returns_admin_user(api_env: ApiEnv) -> None:
    ws, _, token = await admin_in_new_workspace(api_env)
    target, _ = await seed(api_env, ws, "user")

    first = await _put(api_env, token, target.id, {"email": " Ivan.Petrov@Example.COM "})
    second = await _put(api_env, token, target.id, {"email": "new@example.com"})

    assert first.status_code == 200, first.text
    assert first.json()["email"] == "ivan.petrov@example.com"
    assert first.json()["id"] == str(target.id)
    assert second.status_code == 200, second.text
    assert second.json()["email"] == "new@example.com"
    assert await _stored_email(api_env, target.id) == "new@example.com"


async def test_007_ac1_empty_string_and_null_clear_email(api_env: ApiEnv) -> None:
    ws, _, token = await admin_in_new_workspace(api_env)
    one, _ = await seed(api_env, ws, "user", email="one@x.ru")
    two, _ = await seed(api_env, ws, "user", email="two@x.ru")

    r_empty = await _put(api_env, token, one.id, {"email": ""})
    r_null = await _put(api_env, token, two.id, {"email": None})

    assert r_empty.status_code == 200, r_empty.text
    assert r_empty.json()["email"] is None
    assert r_null.status_code == 200, r_null.text
    assert r_null.json()["email"] is None
    assert await _stored_email(api_env, one.id) is None
    assert await _stored_email(api_env, two.id) is None
    assert len(await _email_events(api_env, one.id)) == 1
    assert len(await _email_events(api_env, two.id)) == 1


async def test_007_ac1_create_without_email_or_with_empty_is_allowed(api_env: ApiEnv) -> None:
    _, _, token = await admin_in_new_workspace(api_env)

    plain = await _create(api_env, token, "no.email.one")
    null = await _create(api_env, token, "no.email.two", email=None)
    empty = await _create(api_env, token, "no.email.three", email="")
    # второй и третий «пустые» не конфликтуют между собой (NULL не уникален)

    for response in (plain, null, empty):
        assert response.status_code == 201, response.text
        assert response.json()["email"] is None


async def test_007_ac1_invalid_email_gives_422_email_invalid_on_put_and_create(
    api_env: ApiEnv,
) -> None:
    ws, _, token = await admin_in_new_workspace(api_env)
    target, _ = await seed(api_env, ws, "user", email="keep@x.ru")

    for bad in ("not-an-email", "a@@x.ru", "@x.ru", "a@", "a b@x.ru", "a@x.ru\n"):
        response = await _put(api_env, token, target.id, {"email": bad})
        assert (response.status_code, code_of(response)) == (422, "email_invalid"), bad
        created = await _create(api_env, token, f"bad.{uuid.uuid4().hex[:8]}", email=bad)
        assert (created.status_code, code_of(created)) == (422, "email_invalid"), bad

    assert await _stored_email(api_env, target.id) == "keep@x.ru"
    assert await _email_events(api_env, target.id) == []


async def test_007_ac1_too_long_email_gives_422_and_changes_nothing(api_env: ApiEnv) -> None:
    ws, _, token = await admin_in_new_workspace(api_env)
    target, _ = await seed(api_env, ws, "user", email="keep@x.ru")
    long_email = "a" * 250 + "@x.ru"  # 255 символов

    response = await _put(api_env, token, target.id, {"email": long_email})
    created = await _create(api_env, token, "too.long.mail", email=long_email)

    assert response.status_code == 422
    assert created.status_code == 422
    assert await _stored_email(api_env, target.id) == "keep@x.ru"


async def test_007_ac1_missing_field_and_extra_fields_give_422(api_env: ApiEnv) -> None:
    ws, _, token = await admin_in_new_workspace(api_env)
    target, _ = await seed(api_env, ws, "user", email="keep@x.ru")

    missing = await _put(api_env, token, target.id, {})
    extra = await _put(api_env, token, target.id, {"email": "n@x.ru", "role": "tech_admin"})

    assert missing.status_code == 422
    assert extra.status_code == 422
    assert await _stored_email(api_env, target.id) == "keep@x.ru"


async def test_007_ac1_same_value_is_noop_without_event_even_if_case_differs(
    api_env: ApiEnv,
) -> None:
    ws, _, token = await admin_in_new_workspace(api_env)
    target, _ = await seed(api_env, ws, "user", email="same@x.ru")

    again = await _put(api_env, token, target.id, {"email": "SAME@x.ru"})
    cleared = await _put(api_env, token, target.id, {"email": None})
    cleared_again = await _put(api_env, token, target.id, {"email": ""})

    assert again.status_code == 200 and again.json()["email"] == "same@x.ru"
    assert cleared.status_code == 200
    assert cleared_again.status_code == 200 and cleared_again.json()["email"] is None
    assert len(await _email_events(api_env, target.id)) == 1  # только реальная очистка


async def test_007_ac1_own_email_can_be_set_to_same_value_without_conflict(
    api_env: ApiEnv,
) -> None:
    ws, admin, token = await admin_in_new_workspace(api_env)
    await _put(api_env, token, admin.id, {"email": "boss@x.ru"})

    response = await _put(api_env, token, admin.id, {"email": "BOSS@x.ru"})

    assert response.status_code == 200, response.text
    assert response.json()["email"] == "boss@x.ru"


# --- 404 -----------------------------------------------------------------------------------------


async def test_007_ac1_unknown_and_foreign_user_give_404(api_env: ApiEnv) -> None:
    _, _, token = await admin_in_new_workspace(api_env)
    foreign, _ = await seed(api_env, await new_workspace(api_env), "user", email="f@x.ru")

    for user_id in (uuid.uuid4(), foreign.id):
        response = await _put(api_env, token, user_id, {"email": "x@x.ru"})
        assert (response.status_code, code_of(response)) == (404, "not_found")
    assert await _stored_email(api_env, foreign.id) == "f@x.ru"
    assert await _email_events(api_env, foreign.id) == []


async def test_007_ac1_malformed_user_id_gives_422(api_env: ApiEnv) -> None:
    _, _, token = await admin_in_new_workspace(api_env)

    response = await _put(api_env, token, "not-a-uuid", {"email": "x@x.ru"})

    assert response.status_code == 422


# --- 401 / 403 -----------------------------------------------------------------------------------


async def test_007_ac1_put_without_login_gives_401(api_env: ApiEnv) -> None:
    ws, _, _ = await admin_in_new_workspace(api_env)
    target, _ = await seed(api_env, ws, "user")

    for token in (None, "not-a-real-token-0123456789abcdef"):
        response = await _put(api_env, token, target.id, {"email": "x@x.ru"})
        assert (response.status_code, code_of(response)) == (401, "not_authenticated")
    assert await _stored_email(api_env, target.id) is None


async def test_007_ac1_non_admin_roles_get_403_and_nothing_changes(api_env: ApiEnv) -> None:
    ws, _, _ = await admin_in_new_workspace(api_env)
    target, _ = await seed(api_env, ws, "user", email="keep@x.ru")

    for role, expected in (
        ("business_admin", "forbidden"),
        ("user", "forbidden"),
        (None, "no_role"),
    ):
        _, (token,) = await seed(api_env, ws, role)
        for body in ({"email": "x@x.ru"}, {"email": None}, {}, {"bad": 1}):
            response = await _put(api_env, token, target.id, body)
            assert response.status_code == 403, (role, body, response.text)
            assert code_of(response) == expected, (role, body)
        unknown = await _put(api_env, token, uuid.uuid4(), {"email": "x@x.ru"})
        assert unknown.status_code == 403  # гейт раньше 404

    assert await _stored_email(api_env, target.id) == "keep@x.ru"
    assert await _email_events(api_env, target.id) == []


async def test_007_ac1_non_admin_cannot_create_with_email(api_env: ApiEnv) -> None:
    ws, _, _ = await admin_in_new_workspace(api_env)
    _, (token,) = await seed(api_env, ws, "business_admin")

    response = await _create(api_env, token, "sneaky.one", email="s@x.ru")

    assert response.status_code == 403


# --- AC-14: email в ответах ----------------------------------------------------------------------


async def test_007_ac14_list_and_get_return_email_or_null(api_env: ApiEnv) -> None:
    ws, admin, token = await admin_in_new_workspace(api_env)
    with_mail, _ = await seed(api_env, ws, "user", email="has@x.ru")
    without, _ = await seed(api_env, ws, None)

    listing = await api_env.client.get(
        ADMIN_USERS, params={"page_size": 100}, headers=env_auth(api_env, token)
    )
    got_with = await api_env.client.get(
        f"{ADMIN_USERS}/{with_mail.id}", headers=env_auth(api_env, token)
    )
    got_without = await api_env.client.get(
        f"{ADMIN_USERS}/{without.id}", headers=env_auth(api_env, token)
    )

    assert listing.status_code == 200, listing.text
    by_id = {item["id"]: item for item in listing.json()["items"]}
    assert by_id[str(with_mail.id)]["email"] == "has@x.ru"
    assert by_id[str(without.id)]["email"] is None
    assert by_id[str(admin.id)]["email"] is None
    assert all("email" in item for item in by_id.values())
    assert got_with.json()["email"] == "has@x.ru"
    assert got_without.json()["email"] is None


async def test_007_ac14_role_change_response_includes_email(api_env: ApiEnv) -> None:
    ws, _, token = await admin_in_new_workspace(api_env)
    target, _ = await seed(api_env, ws, "user", email="role@x.ru")

    response = await api_env.client.put(
        f"{ADMIN_USERS}/{target.id}/role",
        json={"role": "business_admin"},
        headers=api_env.auth(token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["email"] == "role@x.ru"


def env_auth(env: ApiEnv, token: str) -> dict[str, str]:
    return env.auth(token)


# --- журнал аудита (FR-2, PR-4) ---


async def test_007_fr2_email_change_writes_event_without_value(api_env: ApiEnv) -> None:
    ws, admin, token = await admin_in_new_workspace(api_env)
    target, _ = await seed(api_env, ws, "user")

    await _put(api_env, token, target.id, {"email": "secret.person@example.org"})
    await _put(api_env, token, target.id, {"email": "other.person@example.org"})

    found = await _email_events(api_env, target.id)
    assert len(found) == 2
    for event in found:
        assert event.actor_id == admin.id
        blob = str(event.details).lower()
        assert "example.org" not in blob and "person" not in blob
    audit = await api_env.client.get(
        AUDIT, params={"entity_type": "user", "page_size": 100}, headers=api_env.auth(token)
    )
    assert audit.status_code == 200, audit.text
    entries = [e for e in audit.json()["items"] if e["action"] == CHANGED]
    assert len(entries) == 2
    assert {e["entity_id"] for e in entries} == {str(target.id)}
    assert "example.org" not in audit.text and "person" not in audit.text


async def test_007_fr2_create_with_email_writes_only_user_created(api_env: ApiEnv) -> None:
    _, _, token = await admin_in_new_workspace(api_env)

    response = await _create(api_env, token, "audited.one", email="audited@example.org")

    assert response.status_code == 201, response.text
    new_id = uuid.UUID(response.json()["id"])
    actions = [e.action for e in await events(api_env, entity_id=new_id)]
    assert actions == ["user.created"]
    assert "example.org" not in str([e.details for e in await events(api_env, entity_id=new_id)])
