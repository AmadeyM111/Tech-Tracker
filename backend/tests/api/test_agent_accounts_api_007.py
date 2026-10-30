"""R7-T08: API создания учётной записи агента ``POST /api/v1/admin/agents`` (007).

AC-1, AC-2, AC-3; FR-1, FR-2; plan §4.5, PD-4.

Контракт: тело ``{login, role}`` (``role`` обязателен, ``null`` = «без роли»; ``user`` /
``business_admin``; ``tech_admin`` -> 422 ``agent_role_not_allowed``), ``extra="forbid"``;
ответ 201 ``AdminUser`` (``is_agent: true``, ``must_change_password: false``); гейт
``MANAGE_ACCOUNTS`` (БА/П -> 403 ``forbidden``, без роли -> 403 ``no_role``); логин занят ->
422 ``login_taken``; недопустимый -> 422 ``login_invalid``. Одно событие ``user.agent_created``.
Секреты в сообщениях assert не печатаются.

Часы не переставляются на ``CLOCK``: сессии ``seed`` созданы на ``FIXED_NOW`` (13.10) и при сдвиге
на 02.11 истекли бы по простою (401). Результат от даты не зависит.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
import pytest

from tests.admin_support import ADMIN_VIEW_FIELDS, OTP, OTP_FIELD, PW, code_of, new_workspace, seed
from tests.agents007_support import (
    ADMIN_AGENTS,
    ADMIN_USERS,
    AUDIT,
    USERS_DIRECTORY,
    make_agent,
)
from tests.conftest import ApiEnv
from tests.projects_api_support import ApiWorld, make_api_world, members_url, send
from tests.tasks_api_support import project_tasks_url

FULL_TASK = {"title": "Задача агента", "description": "Описание", "due_date": "2026-11-10"}


async def _create(env: ApiEnv, token: str, login: str, role: Any = "user") -> httpx.Response:
    response: httpx.Response = await send(
        env, token, "POST", ADMIN_AGENTS, {"login": login, "role": role}
    )
    return response


async def _audit(env: ApiEnv, token: str) -> list[dict[str, Any]]:
    r = await send(env, token, "GET", f"{AUDIT}?page_size=100")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_next"] is False
    return list(body["items"])


async def _account(env: ApiEnv, login: str) -> list[Any]:
    from sqlalchemy import text

    rows = await env.execute(
        text(
            "SELECT id, is_agent, must_change_password, password_hash FROM app_user "
            "WHERE login = :l"
        ).bindparams(l=login.lower())
    )
    assert rows is not None
    return list(rows)


async def _agent_events(env: ApiEnv, ws_id: uuid.UUID) -> list[Any]:
    from sqlalchemy import text

    rows = await env.execute(
        text(
            "SELECT actor_id, entity_type, entity_id, action, details FROM domain_event "
            "WHERE workspace_id = :w AND action = 'user.agent_created' ORDER BY id"
        ).bindparams(w=ws_id)
    )
    assert rows is not None
    return list(rows)


async def _role_in_db(env: ApiEnv, user_id: uuid.UUID) -> str | None:
    from tests.admin_support import member_role

    role: str | None = await member_role(env, user_id)
    return role


# --- AC-1 ------------------------------------------------------------------------------------


async def test_007_ac1_create_agent_with_role_user(
    api_env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _audit(env, w.tok("ta"))

    with caplog.at_level(logging.DEBUG):
        r = await _create(env, w.tok("ta"), "agent.new", "user")

    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == ADMIN_VIEW_FIELDS  # пароля в ответе нет ни в каком поле
    assert body["login"] == "agent.new"
    assert body["role"] == "user"
    assert body["is_agent"] is True
    assert body["must_change_password"] is False
    assert body["is_blocked"] is False
    assert "$argon2" not in r.text
    assert "$argon2" not in caplog.text, "хеш пароля в логе"

    (row,) = await _account(env, "agent.new")
    assert row.id == uuid.UUID(body["id"])
    assert row.is_agent is True
    assert row.must_change_password is False
    assert str(row.password_hash).startswith("$argon2")  # хеш случайного значения (PD-4)
    assert await _role_in_db(env, row.id) == "user"

    card = await send(env, w.tok("ta"), "GET", f"{ADMIN_USERS}/{body['id']}")
    assert card.status_code == 200, card.text
    assert card.json()["is_agent"] is True
    assert card.json()["role"] == "user"

    after = await _audit(env, w.tok("ta"))
    assert len(after) == len(before) + 1
    new = [e for e in after if e["id"] not in {b["id"] for b in before}]
    assert [e["action"] for e in new] == ["user.agent_created"]
    assert new[0]["entity_type"] == "user"
    assert new[0]["entity_id"] == body["id"]
    assert new[0]["actor"]["id"] == str(w.uid("ta"))
    assert new[0]["details"]["role_to"] == "user"


async def test_007_ac1_exactly_one_event_row(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    from tests.admin_support import events

    before = await events(env, workspace_id=w.ws.id)

    r = await _create(env, w.tok("ta"), "agent.one", "business_admin")

    assert r.status_code == 201, r.text
    after = await events(env, workspace_id=w.ws.id)
    assert [e.action for e in after[len(before) :]] == ["user.agent_created"]
    assert len(await _agent_events(env, w.ws.id)) == 1


async def test_007_ac1_agent_login_is_401_same_body_as_wrong_human_password(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    human, _ = await seed(env, w.ws, "user", password=PW, login="human.pw")
    created = await _create(env, w.tok("ta"), "agent.new", "user")
    assert created.status_code == 201, created.text

    human_wrong = await env.login(human.login, "definitely-wrong-password")
    agent_try = await env.login("agent.new", "definitely-wrong-password")
    agent_other = await env.login("agent.new", PW)

    assert human_wrong.status_code == 401
    assert agent_try.status_code == 401
    assert agent_other.status_code == 401
    assert agent_try.json() == human_wrong.json()
    assert agent_other.json() == human_wrong.json()
    assert code_of(agent_try) == "invalid_credentials"
    assert env.token_from(agent_try) is None


async def test_007_ac1_reset_password_of_agent_is_422_and_no_audit_entry(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    created = await _create(env, w.tok("ta"), "agent.new", "user")
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    before = await _audit(env, w.tok("ta"))

    r = await send(
        env, w.tok("ta"), "POST", f"{ADMIN_USERS}/{agent_id}/reset-password", {OTP_FIELD: OTP}
    )

    assert r.status_code == 422, r.text
    assert code_of(r) == "agent_password_not_allowed"
    assert len(await _audit(env, w.tok("ta"))) == len(before)
    (row,) = await _account(env, "agent.new")
    assert row.must_change_password is False


# --- AC-2 ------------------------------------------------------------------------------------


async def test_007_ac2_create_agent_with_tech_admin_role_is_422_and_not_created(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _audit(env, w.tok("ta"))

    r = await _create(env, w.tok("ta"), "agent.ta", "tech_admin")

    assert r.status_code == 422, r.text
    assert code_of(r) == "agent_role_not_allowed"
    assert await _account(env, "agent.ta") == []
    assert len(await _audit(env, w.tok("ta"))) == len(before)


async def test_007_ac2_set_role_tech_admin_on_agent_is_422_role_unchanged(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    agent = await make_agent(env, "agent.u", "user", workspace=w.ws)
    before = await _audit(env, w.tok("ta"))

    r = await send(
        env, w.tok("ta"), "PUT", f"{ADMIN_USERS}/{agent.id}/role", {"role": "tech_admin"}
    )

    assert r.status_code == 422, r.text
    assert code_of(r) == "agent_role_not_allowed"
    assert await _role_in_db(env, agent.id) == "user"
    assert len(await _audit(env, w.tok("ta"))) == len(before)


async def test_007_ac2_agent_role_can_go_user_to_ba_and_back(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    created = await _create(env, w.tok("ta"), "agent.u", "user")
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    up = await send(
        env, w.tok("ta"), "PUT", f"{ADMIN_USERS}/{agent_id}/role", {"role": "business_admin"}
    )
    assert up.status_code == 200, up.text
    assert up.json()["role"] == "business_admin"
    assert up.json()["is_agent"] is True

    down = await send(env, w.tok("ta"), "PUT", f"{ADMIN_USERS}/{agent_id}/role", {"role": "user"})
    assert down.status_code == 200, down.text
    assert down.json()["role"] == "user"
    assert down.json()["is_agent"] is True


# --- AC-3 ------------------------------------------------------------------------------------


async def test_007_ac3_agent_joins_project_gets_task_and_is_in_directory(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    created = await _create(env, w.tok("ta"), "agent.new", "user")
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    added = await send(env, w.tok("ba"), "POST", members_url(w.project_id), {"user_id": agent_id})
    assert added.status_code == 204, added.text
    members = await send(env, w.tok("ba"), "GET", members_url(w.project_id))
    by_login = {i["user"]["login"]: i["user"] for i in members.json()["items"]}
    assert by_login["agent.new"]["id"] == agent_id
    assert by_login["agent.new"]["is_agent"] is True

    task = await send(
        env,
        w.tok("ba"),
        "POST",
        project_tasks_url(w.project_id),
        {**FULL_TASK, "assignee_id": agent_id},
    )
    assert task.status_code == 201, task.text
    assert task.json()["assignee"]["id"] == agent_id
    assert task.json()["assignee"]["is_agent"] is True

    directory = await send(env, w.tok("ba"), "GET", f"{USERS_DIRECTORY}?page_size=100")
    assert directory.status_code == 200, directory.text
    by_dir = {i["login"]: i for i in directory.json()["items"]}
    assert by_dir["agent.new"]["is_agent"] is True
    assert by_dir["agent.new"]["id"] == agent_id


# --- граничные -------------------------------------------------------------------------------


async def test_007_fr1_role_null_and_business_admin_are_accepted(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    none_role = await _create(env, w.tok("ta"), "agent.none", None)
    ba_role = await _create(env, w.tok("ta"), "agent.ba", "business_admin")

    assert none_role.status_code == 201, none_role.text
    assert none_role.json()["role"] is None
    assert none_role.json()["is_agent"] is True
    assert ba_role.status_code == 201, ba_role.text
    assert ba_role.json()["role"] == "business_admin"
    (event,) = [
        e
        for e in await _agent_events(env, w.ws.id)
        if e.entity_id == uuid.UUID(none_role.json()["id"])
    ]
    assert event.details["role_to"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"login": "agent.x", "role": "user", "one_time_password": "x"},
        {"login": "agent.x", "role": "user", "is_agent": True},
        {"login": "agent.x"},
        {"role": "user"},
        {"login": "agent.x", "role": "superuser"},
        {"login": 5, "role": "user"},
        {},
    ],
)
async def test_007_fr1_bad_body_is_422_validation_error(
    api_env: ApiEnv, body: dict[str, Any]
) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _audit(env, w.tok("ta"))

    r = await send(env, w.tok("ta"), "POST", ADMIN_AGENTS, body)

    assert r.status_code == 422, r.text
    assert code_of(r) == "validation_error"
    assert await _account(env, "agent.x") == []
    assert len(await _audit(env, w.tok("ta"))) == len(before)


@pytest.mark.parametrize("login", ["", "a b", "агент", "x" * 300, "bad/login"])
async def test_007_fr1_invalid_login_is_422(api_env: ApiEnv, login: str) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _audit(env, w.tok("ta"))

    r = await _create(env, w.tok("ta"), login, "user")

    assert r.status_code == 422, r.text
    assert code_of(r) in {"login_invalid", "validation_error"}
    assert len(await _audit(env, w.tok("ta"))) == len(before)


async def test_007_fr1_invalid_login_short_pattern_is_login_invalid(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _create(env, w.tok("ta"), "a b", "user")

    assert (r.status_code, code_of(r)) == (422, "login_invalid")


async def test_007_fr1_taken_login_is_422_login_taken(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    other_ws = await new_workspace(env)
    await seed(env, other_ws, "user", login="foreign.person")
    before = await _audit(env, w.tok("ta"))

    same_human = await _create(env, w.tok("ta"), w.login("usr"), "user")
    case_variant = await _create(env, w.tok("ta"), w.login("usr").upper(), "user")
    foreign = await _create(env, w.tok("ta"), "Foreign.Person", "user")
    first = await _create(env, w.tok("ta"), "agent.dup", "user")
    again = await _create(env, w.tok("ta"), "agent.dup", "business_admin")

    for r in (same_human, case_variant, foreign, again):
        assert (r.status_code, code_of(r)) == (422, "login_taken"), r.text
    assert first.status_code == 201, first.text
    assert len(await _account(env, "agent.dup")) == 1
    assert len(await _audit(env, w.tok("ta"))) == len(before) + 1


# --- гейты -----------------------------------------------------------------------------------


async def test_007_fr2_without_cookie_is_401(api_env: ApiEnv) -> None:
    env = api_env
    r = await env.client.post(ADMIN_AGENTS, json={"login": "agent.x", "role": "user"})

    assert (r.status_code, code_of(r)) == (401, "not_authenticated")
    assert await _account(env, "agent.x") == []


@pytest.mark.parametrize("who", ["ba", "usr"])
async def test_007_ac1_ba_and_user_get_403_and_nothing_created(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)

    for body in ({"login": "agent.x", "role": "user"}, {"login": "agent.x", "role": None}, {}):
        r = await send(env, w.tok(who), "POST", ADMIN_AGENTS, body)  # 403 раньше разбора тела
        assert (r.status_code, code_of(r)) == (403, "forbidden"), r.text
    assert await _account(env, "agent.x") == []


async def test_007_ac1_user_without_role_gets_403_no_role(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _create(env, w.tok("norole"), "agent.x", "user")

    assert (r.status_code, code_of(r)) == (403, "no_role")
    assert await _account(env, "agent.x") == []


async def test_007_ac1_ta_with_one_time_password_gets_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    _, (token,) = await seed(env, w.ws, "tech_admin", must_change_password=True)

    r = await _create(env, token, "agent.x", "user")

    assert (r.status_code, code_of(r)) == (403, "password_change_required")
    assert await _account(env, "agent.x") == []


async def test_007_fr2_foreign_origin_is_403_origin_mismatch(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await env.client.post(
        ADMIN_AGENTS,
        json={"login": "agent.x", "role": "user"},
        headers={**env.auth(w.tok("ta")), "Origin": "http://evil.example"},
    )

    assert (r.status_code, code_of(r)) == (403, "origin_mismatch")
    assert await _account(env, "agent.x") == []


async def test_007_fr2_agent_is_created_in_actor_workspace(api_env: ApiEnv) -> None:
    env = api_env
    w: ApiWorld = await make_api_world(env)
    other_ws = await new_workspace(env)
    _, (other_token,) = await seed(env, other_ws, "tech_admin", login="other.ta")

    r = await _create(env, w.tok("ta"), "agent.ws", "user")

    assert r.status_code == 201, r.text
    seen_here = await send(env, w.tok("ta"), "GET", f"{ADMIN_USERS}/{r.json()['id']}")
    seen_there = await send(env, other_token, "GET", f"{ADMIN_USERS}/{r.json()['id']}")
    assert seen_here.status_code == 200
    assert seen_there.status_code == 404
