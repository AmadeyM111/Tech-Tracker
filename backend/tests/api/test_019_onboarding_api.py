"""R8-T07: ``/api/v1/unassigned-accounts*`` и отказы БА на разделы ТА (spec 019: AC-26, AC-30).

FR-13a. Всё через HTTP. Правила домена (порядок проверок, блокировки) — в
``tests/domain/test_019_onboarding.py``; здесь — гейты роутера, форма ответа без email, отказы БА на
``/admin/users*`` и ``/admin/audit``, сквозной путь «назначил БА → пользователь открыл ``/projects``
той же сессией → запись в журнале».
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from sqlalchemy import text

from tests.admin_support import (
    ADMIN_USERS,
    admin_call,
    admin_in_new_workspace,
    code_of,
    member_role,
    new_workspace,
    seed,
)
from tests.factories import PLACEHOLDER_HASH

if TYPE_CHECKING:
    from tests.conftest import ApiEnv
    from tests.factories import WorkspaceRow

UNASSIGNED = "/api/v1/unassigned-accounts"
AUDIT = "/api/v1/admin/audit"
PROJECTS = "/api/v1/projects"
EMAIL = "ivan.secret@example.test"
ITEM_KEYS = {"id", "login", "first_name", "last_name", "created_at"}
PAGE_KEYS = {"items", "page", "page_size", "has_next"}


def _role_url(user_id: Any) -> str:
    return f"{UNASSIGNED}/{user_id}/role"


async def _put_unassigned_role(
    env: ApiEnv, token: str, user_id: Any, role: str | None
) -> httpx.Response:
    return await env.client.put(_role_url(user_id), json={"role": role}, headers=env.auth(token))


async def _audit(env: ApiEnv, token: str, **params: str) -> list[dict[str, Any]]:
    response = await env.client.get(AUDIT, params=params, headers=env.auth(token))
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


async def _names(env: ApiEnv, user_id: uuid.UUID) -> tuple[Any, Any]:
    rows = await env.execute(
        text("SELECT first_name, last_name FROM app_user WHERE id = :u").bindparams(u=user_id)
    )
    assert rows
    return tuple(rows[0])  # type: ignore[return-value]


async def _workspace_user_count(env: ApiEnv, workspace_id: uuid.UUID) -> int:
    rows = await env.execute(
        text("SELECT count(*) FROM workspace_member WHERE workspace_id = :w").bindparams(
            w=workspace_id
        )
    )
    assert rows
    return int(rows[0][0])


async def _ba_session(env: ApiEnv, ws: WorkspaceRow) -> tuple[Any, str]:
    ba, (token,) = await seed(env, ws, "business_admin")
    return ba, token


# --- AC-30: список без email и без учётных записей с ролью ----------------------------------


async def test_019_ac30_list_shows_both_roleless_accounts_without_email(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, ta_token = await admin_in_new_workspace(env)
    _, ba_token = await _ba_session(env, ws)
    created = await admin_call(env, ta_token, "create", "")
    assert created.status_code == 201, created.text
    ta_made = created.json()
    self_registered = await env.new_user(
        workspace=ws,
        login="self.reg",
        role=None,
        password_hash=PLACEHOLDER_HASH,
        self_registered=True,
        email=EMAIL,
        first_name="Анна",
        last_name="Смирнова",
    )

    response = await env.client.get(UNASSIGNED, headers=env.auth(ba_token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == PAGE_KEYS
    assert (body["page"], body["has_next"]) == (1, False)
    items = body["items"]
    assert [item["login"] for item in items] == sorted([ta_made["login"], self_registered.login])
    assert all(set(item) == ITEM_KEYS for item in items)
    by_login = {item["login"]: item for item in items}
    assert by_login["self.reg"]["first_name"] == "Анна"
    assert by_login["self.reg"]["last_name"] == "Смирнова"
    assert by_login[ta_made["login"]]["first_name"] == "Иван"
    assert by_login[ta_made["login"]]["last_name"] == "Петров"
    assert "email" not in response.text
    assert EMAIL not in response.text


@pytest.mark.parametrize("holder_role", ["user", "business_admin", "tech_admin"])
async def test_019_ac30_list_hides_accounts_with_role_and_foreign_workspace(
    api_env: ApiEnv, holder_role: str
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, ba_token = await _ba_session(env, ws)
    holder, _ = await seed(env, ws, holder_role)
    foreign_ws = await new_workspace(env)
    foreign, _ = await seed(env, foreign_ws, None)

    response = await env.client.get(UNASSIGNED, headers=env.auth(ba_token))

    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert str(holder.id) not in ids
    assert str(foreign.id) not in ids
    assert str(holder.id) not in response.text


async def test_019_ac30_list_pages_in_login_order(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, ba_token = await _ba_session(env, ws)
    await env.new_user(workspace=ws, login="bbb.user", role=None, password_hash=PLACEHOLDER_HASH)
    await env.new_user(workspace=ws, login="aaa.user", role=None, password_hash=PLACEHOLDER_HASH)

    first = await env.client.get(
        UNASSIGNED, params={"page": 1, "page_size": 1}, headers=env.auth(ba_token)
    )
    second = await env.client.get(
        UNASSIGNED, params={"page": 2, "page_size": 1}, headers=env.auth(ba_token)
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert [first.json()["items"][0]["login"], second.json()["items"][0]["login"]] == [
        "aaa.user",
        "bbb.user",
    ]
    assert (first.json()["has_next"], second.json()["has_next"]) == (True, False)


async def test_019_ac30_list_rejects_bad_page_params_422(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, ba_token = await _ba_session(env, ws)

    response = await env.client.get(UNASSIGNED, params={"page": 0}, headers=env.auth(ba_token))

    assert response.status_code == 422, response.text


# --- AC-26, AC-30: назначение роли «Пользователь» от БА -----------------------------------


async def test_019_ac26_ac30_ba_assigns_user_role_then_same_session_reaches_projects(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, ta_token = await admin_in_new_workspace(env)
    ba, ba_token = await _ba_session(env, ws)
    account, (account_token,) = await seed(env, ws, None)
    before = await env.client.get(PROJECTS, headers=env.auth(account_token))
    assert (before.status_code, code_of(before)) == (403, "no_role")

    response = await _put_unassigned_role(env, ba_token, account.id, "user")

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert await member_role(env, account.id) == "user"
    after = await env.client.get(PROJECTS, headers=env.auth(account_token))
    assert after.status_code == 200, after.text
    entries = await _audit(env, ta_token, actor_id=str(ba.id))
    assigned = [
        entry
        for entry in entries
        if entry["action"] == "user.role_assigned" and entry["entity_id"] == str(account.id)
    ]
    assert len(assigned) == 1, entries
    assert assigned[0]["actor"] == {"kind": "user", "id": str(ba.id), "login": ba.login}
    assert assigned[0]["details"] == {"role_from": None, "role_to": "user"}


@pytest.mark.parametrize("role", ["business_admin", "tech_admin", None], ids=["ba", "ta", "none"])
async def test_019_ac30_ba_cannot_assign_ba_ta_or_clear_roleless_account(
    api_env: ApiEnv, role: str | None
) -> None:
    env = api_env
    ws, _, ta_token = await admin_in_new_workspace(env)
    ba, ba_token = await _ba_session(env, ws)
    account, _ = await seed(env, ws, None)

    response = await _put_unassigned_role(env, ba_token, account.id, role)

    assert (response.status_code, code_of(response)) == (403, "forbidden"), response.text
    assert await member_role(env, account.id) is None
    assert await _audit(env, ta_token, actor_id=str(ba.id)) == []


@pytest.mark.parametrize(
    ("current", "role"),
    [
        ("user", None),
        ("user", "user"),
        ("user", "business_admin"),
        ("business_admin", "user"),
        ("tech_admin", "user"),
        ("tech_admin", None),
    ],
    ids=["user-clear", "user-same", "user-to-ba", "ba-to-user", "ta-to-user", "ta-clear"],
)
async def test_019_ac30_ba_cannot_change_or_clear_existing_role(
    api_env: ApiEnv, current: str, role: str | None
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, ba_token = await _ba_session(env, ws)
    target, _ = await seed(env, ws, current)

    response = await _put_unassigned_role(env, ba_token, target.id, role)

    assert (response.status_code, code_of(response)) == (403, "forbidden"), response.text
    assert await member_role(env, target.id) == current


async def test_019_ac30_repeat_assignment_is_403_and_writes_one_event(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, ta_token = await admin_in_new_workspace(env)
    ba, ba_token = await _ba_session(env, ws)
    account, _ = await seed(env, ws, None)
    first = await _put_unassigned_role(env, ba_token, account.id, "user")
    assert first.status_code == 204, first.text

    second = await _put_unassigned_role(env, ba_token, account.id, "user")

    assert (second.status_code, code_of(second)) == (403, "forbidden"), second.text
    assert await member_role(env, account.id) == "user"
    entries = await _audit(env, ta_token, actor_id=str(ba.id))
    assert [e["entity_id"] for e in entries if e["action"] == "user.role_assigned"] == [
        str(account.id)
    ]


async def test_019_ac30_unknown_or_foreign_account_is_404(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, ba_token = await _ba_session(env, ws)
    foreign, _ = await seed(env, await new_workspace(env), None)

    for target in (uuid.uuid4(), foreign.id):
        response = await _put_unassigned_role(env, ba_token, target, "user")
        assert (response.status_code, code_of(response)) == (404, "not_found"), response.text
    assert await member_role(env, foreign.id) is None


@pytest.mark.parametrize(
    "body",
    [{"role": "mixed"}, {"role": "user", "extra": 1}, {}],
    ids=["unknown-role", "extra-field", "missing-role"],
)
async def test_019_ac30_invalid_role_body_is_422_and_nothing_changes(
    api_env: ApiEnv, body: dict[str, Any]
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, ba_token = await _ba_session(env, ws)
    account, _ = await seed(env, ws, None)

    response = await env.client.put(_role_url(account.id), json=body, headers=env.auth(ba_token))

    assert response.status_code == 422, response.text
    assert await member_role(env, account.id) is None


async def test_019_ac30_broken_json_is_400(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, ba_token = await _ba_session(env, ws)
    account, _ = await seed(env, ws, None)

    response = await env.client.put(
        _role_url(account.id),
        content=b'{"role": "user"',
        headers={**env.auth(ba_token), "Content-Type": "application/json"},
    )

    assert (response.status_code, code_of(response)) == (400, "bad_request"), response.text
    assert await member_role(env, account.id) is None


# --- AC-30: отказы БА на разделы ТА ---------------------------------------------------------


@pytest.mark.parametrize(
    "attempt", ["block", "reset", "create", "name", "role_user", "list", "get", "audit"]
)
async def test_019_ac30_ba_gets_403_on_admin_users_and_audit_and_data_is_kept(
    api_env: ApiEnv, attempt: str
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, ba_token = await _ba_session(env, ws)
    target, (target_token,) = await seed(env, ws, None)
    names_before = await _names(env, target.id)
    sessions_before = await env.session_ids(target.id)

    if attempt == "name":
        response = await env.client.put(
            f"{ADMIN_USERS}/{target.id}/name",
            json={"first_name": "Чужой", "last_name": "Имя"},
            headers=env.auth(ba_token),
        )
    elif attempt == "list":
        response = await env.client.get(ADMIN_USERS, headers=env.auth(ba_token))
    elif attempt == "get":
        response = await env.client.get(f"{ADMIN_USERS}/{target.id}", headers=env.auth(ba_token))
    elif attempt == "audit":
        response = await env.client.get(AUDIT, headers=env.auth(ba_token))
    else:
        response = await admin_call(env, ba_token, attempt, target.id)

    assert (response.status_code, code_of(response)) == (403, "forbidden"), response.text
    row = await env.user_row(target.id)
    assert (row.is_blocked, row.must_change_password) == (False, False)
    assert await member_role(env, target.id) is None
    assert await _names(env, target.id) == names_before
    assert await env.session_ids(target.id) == sessions_before
    assert (await env.client.get(PROJECTS, headers=env.auth(target_token))).status_code == 403
    assert await _workspace_user_count(env, ws.id) == 3


@pytest.mark.parametrize("actor_role", ["tech_admin", "user"])
async def test_019_ac30_ta_and_user_get_403_on_unassigned_section(
    api_env: ApiEnv, actor_role: str
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, (actor_token,) = await seed(env, ws, actor_role)
    account, _ = await seed(env, ws, None)

    listed = await env.client.get(UNASSIGNED, headers=env.auth(actor_token))
    assigned = await _put_unassigned_role(env, actor_token, account.id, "user")

    assert (listed.status_code, code_of(listed)) == (403, "forbidden"), listed.text
    assert (assigned.status_code, code_of(assigned)) == (403, "forbidden"), assigned.text
    assert await member_role(env, account.id) is None


async def test_019_ac30_unassigned_routes_need_session(api_env: ApiEnv) -> None:
    listed = await api_env.client.get(UNASSIGNED)
    assigned = await api_env.client.put(_role_url(uuid.uuid4()), json={"role": "user"})

    assert (listed.status_code, code_of(listed)) == (401, "not_authenticated")
    assert (assigned.status_code, code_of(assigned)) == (401, "not_authenticated")
