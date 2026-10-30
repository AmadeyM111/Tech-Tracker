"""R7-T05, R7-T06: признак «агент» (``is_agent``) в ссылках на пользователя, справочнике,
``/me`` и «Учётных записях» (007/FR-31, AC-36, plan §4.4, PD-10).

Агент создаётся фабрикой уровня БД (``make_user(is_agent=True)``), запросы идут через обычный
cookie-API ``ba1``. Ссылка на пользователя — ровно ``{id, login, is_agent}``.
"""

from __future__ import annotations

import uuid
from typing import Any

from tests.admin_support import ADMIN_USERS, ADMIN_VIEW_FIELDS, OTP, OTP_FIELD
from tests.conftest import ApiEnv
from tests.projects_api_support import (
    PROJECTS,
    ApiWorld,
    Person,
    add_member_row,
    add_project,
    make_api_world,
    members_url,
    pj,
    send,
)
from tests.tasks_api_support import mk, task_url

REF_KEYS = {"id", "login", "is_agent"}
DIR_KEYS = {"id", "login", "role", "is_agent"}


async def _agent_world(env: ApiEnv) -> tuple[ApiWorld, uuid.UUID]:
    """Мир проекта + ``agent.u`` (роль «Пользователь», участник проекта, без сессии)."""
    w = await make_api_world(env)
    user = await env.new_user(workspace=w.ws, role="user", login="agent.u", is_agent=True)
    w.people["agent"] = Person(user, "")
    await add_member_row(env, w, user)
    return w, user.id


def _ref_ok(ref: Any, who_id: uuid.UUID, login: str, is_agent: bool) -> None:
    assert set(ref) == REF_KEYS
    assert ref["id"] == str(who_id)
    assert ref["login"] == login
    assert ref["is_agent"] is is_agent


async def test_ac36_task_card_author_assignee_and_subtask_assignee(api_env: ApiEnv) -> None:
    env = api_env
    w, agent_id = await _agent_world(env)
    task = await mk(env, w, by="agent", assignee="agent", title="T")
    sub = await mk(env, w, by="ba", assignee="agent", parent=task, title="S")
    human = await mk(env, w, by="ba", assignee="usr", title="H")

    r = await send(env, w.tok("ba"), "GET", task_url(task))

    assert r.status_code == 200, r.text
    body = r.json()
    _ref_ok(body["author"], agent_id, "agent.u", True)
    _ref_ok(body["assignee"], agent_id, "agent.u", True)
    (brief,) = [s for s in body["subtasks"] if s["id"] == str(sub)]
    _ref_ok(brief["assignee"], agent_id, "agent.u", True)

    rh = await send(env, w.tok("ba"), "GET", task_url(human))
    assert rh.status_code == 200, rh.text
    _ref_ok(rh.json()["author"], w.uid("ba"), w.login("ba"), False)
    _ref_ok(rh.json()["assignee"], w.uid("usr"), w.login("usr"), False)


async def test_ac36_subtask_card_assignee_is_agent(api_env: ApiEnv) -> None:
    env = api_env
    w, agent_id = await _agent_world(env)
    task = await mk(env, w, by="ba")
    sub = await mk(env, w, by="ba", assignee="agent", parent=task)

    r = await send(env, w.tok("ba"), "GET", task_url(sub))

    assert r.status_code == 200, r.text
    _ref_ok(r.json()["assignee"], agent_id, "agent.u", True)
    _ref_ok(r.json()["author"], w.uid("ba"), w.login("ba"), False)


async def test_ac36_comment_authors(api_env: ApiEnv) -> None:
    from tests.factories import make_comment

    env = api_env
    w, agent_id = await _agent_world(env)
    task = await mk(env, w, by="ba")
    async with env.sessionmaker() as session:
        await make_comment(session, task_id=task, workspace_id=w.ws.id, created_by=agent_id)
        await make_comment(session, task_id=task, workspace_id=w.ws.id, created_by=w.uid("ba"))
        await make_comment(session, task_id=task, workspace_id=w.ws.id, created_by=w.uid("usr"))
        await session.commit()

    r = await send(env, w.tok("ba"), "GET", f"{task_url(task)}/comments")

    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 3
    flags = {i["author"]["login"]: i["author"]["is_agent"] for i in items}
    assert flags == {"agent.u": True, w.login("ba"): False, w.login("usr"): False}
    for item in items:
        assert set(item["author"]) == REF_KEYS


async def test_ac36_project_members(api_env: ApiEnv) -> None:
    env = api_env
    w, agent_id = await _agent_world(env)

    r = await send(env, w.tok("ba"), "GET", members_url(w.project_id))

    assert r.status_code == 200, r.text
    by_login = {i["user"]["login"]: i["user"] for i in r.json()["items"]}
    _ref_ok(by_login["agent.u"], agent_id, "agent.u", True)
    _ref_ok(by_login[w.login("ba")], w.uid("ba"), w.login("ba"), False)
    _ref_ok(by_login[w.login("usr")], w.uid("usr"), w.login("usr"), False)


async def test_ac36_users_directory(api_env: ApiEnv) -> None:
    env = api_env
    w, agent_id = await _agent_world(env)

    r = await send(env, w.tok("ba"), "GET", "/api/v1/users")

    assert r.status_code == 200, r.text
    items = r.json()["items"]
    for item in items:
        assert set(item) == DIR_KEYS
    by_login = {i["login"]: i for i in items}
    assert by_login["agent.u"]["id"] == str(agent_id)
    assert by_login["agent.u"]["is_agent"] is True
    assert by_login[w.login("ba")]["is_agent"] is False
    assert by_login[w.login("usr")]["is_agent"] is False


async def test_ac36_directory_sees_users_inserted_right_before_request(api_env: ApiEnv) -> None:
    """Агент и человек, созданные непосредственно перед запросом (без refresh), видны сразу."""
    env = api_env
    w = await make_api_world(env)
    agent = await env.new_user(workspace=w.ws, role="user", login="fresh.agent", is_agent=True)
    human = await env.new_user(workspace=w.ws, role="user", login="fresh.human")

    r = await send(env, w.tok("ba"), "GET", "/api/v1/users")

    assert r.status_code == 200, r.text
    by_id = {i["id"]: i for i in r.json()["items"]}
    assert by_id[str(agent.id)]["is_agent"] is True
    assert by_id[str(human.id)]["is_agent"] is False


async def test_ac36_project_list_owner(api_env: ApiEnv) -> None:
    env = api_env
    w, agent_id = await _agent_world(env)
    agent_project = await add_project(
        env, w.ws, w.people["agent"].user, name="Проект агента", members=[], people=w.people
    )

    r = await send(env, w.tok("ba"), "GET", PROJECTS)

    assert r.status_code == 200, r.text
    by_id = {i["id"]: i for i in r.json()["items"]}
    _ref_ok(by_id[str(w.project_id)]["owner"], w.uid("ba"), w.login("ba"), False)
    _ref_ok(by_id[str(agent_project)]["owner"], agent_id, "agent.u", True)

    rd = await send(env, w.tok("ba"), "GET", pj(agent_project))
    assert rd.status_code == 200, rd.text
    _ref_ok(rd.json()["owner"], agent_id, "agent.u", True)


async def test_ac36_board_card_assignee(api_env: ApiEnv) -> None:
    env = api_env
    w, agent_id = await _agent_world(env)
    mine = await mk(env, w, by="ba", assignee="agent", title="agent card")
    other = await mk(env, w, by="ba", assignee="usr", title="human card")

    r = await send(env, w.tok("ba"), "GET", f"{pj(w.project_id)}/board")

    assert r.status_code == 200, r.text
    cards = {c["id"]: c for col in r.json()["columns"] for c in col["tasks"]}
    _ref_ok(cards[str(mine)]["assignee"], agent_id, "agent.u", True)
    _ref_ok(cards[str(other)]["assignee"], w.uid("usr"), w.login("usr"), False)


async def test_ac36_task_lists_assignee(api_env: ApiEnv) -> None:
    env = api_env
    w, agent_id = await _agent_world(env)
    t = await mk(env, w, by="ba", assignee="agent")

    r = await send(env, w.tok("ba"), "GET", f"/api/v1/projects/{w.project_id}/tasks")

    assert r.status_code == 200, r.text
    (item,) = [i for i in r.json()["items"] if i["id"] == str(t)]
    _ref_ok(item["assignee"], agent_id, "agent.u", True)


# --- R7-T06: /me и «Учётные записи» ---------------------------------------------------------


async def test_fr18_me_of_human_has_is_agent_false(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(env, w.tok("usr"), "GET", "/api/v1/me")

    assert r.status_code == 200, r.text
    assert r.json()["is_agent"] is False
    assert r.json()["id"] == str(w.uid("usr"))


async def test_fr31_admin_users_list_and_card_flag(api_env: ApiEnv) -> None:
    env = api_env
    w, agent_id = await _agent_world(env)

    r = await send(env, w.tok("ta"), "GET", f"{ADMIN_USERS}?page_size=100")

    assert r.status_code == 200, r.text
    items = r.json()["items"]
    for item in items:
        assert set(item) == ADMIN_VIEW_FIELDS
    assert {"id", "login", "role", "is_blocked", "must_change_password", "created_at"} < set(
        items[0]
    )
    by_id = {i["id"]: i for i in items}
    assert by_id[str(agent_id)]["is_agent"] is True
    for who in ("ta", "ba", "usr", "norole"):
        assert by_id[str(w.uid(who))]["is_agent"] is False

    card = await send(env, w.tok("ta"), "GET", f"{ADMIN_USERS}/{agent_id}")
    assert card.status_code == 200, card.text
    assert set(card.json()) == ADMIN_VIEW_FIELDS
    assert card.json()["is_agent"] is True
    human = await send(env, w.tok("ta"), "GET", f"{ADMIN_USERS}/{w.uid('usr')}")
    assert human.status_code == 200, human.text
    assert human.json()["is_agent"] is False


async def test_fr31_create_user_response_and_card_right_after_write(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await env.client.post(
        ADMIN_USERS,
        json={"login": "brand.new", OTP_FIELD: OTP},
        headers=env.auth(w.tok("ta")),
    )

    assert r.status_code == 201, r.text
    assert r.json()["is_agent"] is False
    card = await send(env, w.tok("ta"), "GET", f"{ADMIN_USERS}/{r.json()['id']}")
    assert card.status_code == 200, card.text
    assert card.json()["is_agent"] is False


async def test_fr31_openapi_requires_is_agent(api_env: ApiEnv) -> None:
    schemas = api_env.app.openapi()["components"]["schemas"]
    for name in ("UserRef", "DirectoryUser", "AdminUser", "MeResponse"):
        assert name in schemas, name
        assert "is_agent" in schemas[name]["properties"], name
        assert "is_agent" in schemas[name].get("required", []), name
        assert schemas[name]["properties"]["is_agent"].get("type") == "boolean", name
