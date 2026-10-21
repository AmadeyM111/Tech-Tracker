"""T17: изоляция пространств в ``/api/v1/admin/users*`` (AC-21, FR-45a, BR-2, FR-13).

- пользователь другого пространства недоступен ни одним эндпоинтом: 404, ответ неотличим от
  ответа для несуществующего id (``not_found``), данные цели не меняются;
- БА и Пользователь получают 403 раньше, чем 404 (FR-45a);
- раздел администрирования не отдаёт бизнес-данных (BR-2).
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from tests.admin_support import (
    ADMIN_USERS,
    ADMIN_VIEW_FIELDS,
    PW,
    admin_call,
    code_of,
    events,
    member_role,
    new_workspace,
    seed,
)
from tests.conftest import ApiEnv
from tests.db_support import BACKEND_DIR
from tests.tasks_api_support import TASK_REQ

ACTIONS = ("get", "block", "unblock", "reset", "revoke", "role_user", "role_none", "role_ta")


async def _two_workspaces(env: ApiEnv) -> tuple[Any, Any, str, Any, list[str]]:
    ws1 = await new_workspace(env)
    admin1, (token1,) = await seed(env, ws1, "tech_admin")
    ws2 = await new_workspace(env)
    await seed(env, ws2, "tech_admin")
    victim, victim_tokens = await seed(env, ws2, "user", password=PW, sessions=2)
    return ws1, admin1, token1, victim, victim_tokens


@pytest.mark.parametrize("action", ACTIONS)
async def test_ac21_foreign_workspace_user_is_404_not_found_on_every_endpoint(
    api_env: ApiEnv, action: str
) -> None:
    env = api_env
    ws1, _, token, victim, _ = await _two_workspaces(env)
    mine, _ = await seed(env, ws1, "user")
    own = await admin_call(env, token, "get", mine.id)  # раздел есть; 404 — именно изоляция
    assert own.status_code == 200, own.text

    response = await admin_call(env, token, action, victim.id)
    unknown = await admin_call(env, token, action, uuid.uuid4())

    assert response.status_code == 404, response.text
    assert code_of(response) == "not_found"
    assert response.json() == unknown.json()  # неотличимо от несуществующего id (FR-13)


async def test_ac21_foreign_workspace_user_state_is_untouched_after_all_attempts(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws1, _, token, victim, victim_tokens = await _two_workspaces(env)
    mine, _ = await seed(env, ws1, "user")
    assert (await admin_call(env, token, "get", mine.id)).status_code == 200
    before = await env.user_row(victim.id)

    for action in ACTIONS:
        assert (await admin_call(env, token, action, victim.id)).status_code == 404

    after = await env.user_row(victim.id)
    assert after.is_blocked is False
    assert after.password_hash == before.password_hash
    assert after.must_change_password is False
    assert await member_role(env, victim.id) == "user"
    assert len(await env.session_ids(victim.id)) == 2
    assert (await env.me(victim_tokens[0])).status_code == 200
    assert (await env.login(victim.login, PW)).status_code == 200
    assert await events(env, entity_id=victim.id) == []


async def test_ac21_list_contains_only_own_workspace_users(api_env: ApiEnv) -> None:
    env = api_env
    ws1, admin1, token, victim, _ = await _two_workspaces(env)
    mine, _ = await seed(env, ws1, "user")

    response = await env.client.get(ADMIN_USERS, headers=env.auth(token))

    ids = {i["id"] for i in response.json()["items"]}
    assert ids == {str(admin1.id), str(mine.id)}
    assert str(victim.id) not in response.text
    assert victim.login not in response.text


async def test_ac21_admin_of_other_workspace_sees_symmetrically_nothing_of_first(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws1, admin1, _, _, _ = await _two_workspaces(env)
    ws2 = await new_workspace(env)
    # 002/FR-1: администратор второго пространства - ТА (прежде СМ-администратор)
    admin2, (token2,) = await seed(env, ws2, "tech_admin")
    assert (await admin_call(env, token2, "get", admin2.id)).status_code == 200

    response = await admin_call(env, token2, "get", admin1.id)
    blocked = await admin_call(env, token2, "block", admin1.id)

    assert (response.status_code, blocked.status_code) == (404, 404)
    assert (await env.user_row(admin1.id)).is_blocked is False
    assert ws1.id


@pytest.mark.parametrize("role", ["business_admin", "user"])
@pytest.mark.parametrize("action", ACTIONS)
async def test_fr45a_business_admin_and_user_get_403_before_404_for_any_id(
    api_env: ApiEnv, role: str, action: str
) -> None:
    env = api_env
    ws1, _, _, victim, _ = await _two_workspaces(env)
    _, (token,) = await seed(env, ws1, role)

    for target in (victim.id, uuid.uuid4()):  # чужое пространство и несуществующий id
        response = await admin_call(env, token, action, target)
        assert response.status_code == 403, (target, response.text)
        assert code_of(response) == "forbidden"


async def test_fr45a_list_and_create_for_business_admin_are_403(api_env: ApiEnv) -> None:
    env = api_env
    ws1, *_ = await _two_workspaces(env)
    _, (token,) = await seed(env, ws1, "business_admin")

    listed = await env.client.get(ADMIN_USERS, headers=env.auth(token))
    created = await admin_call(env, token, "create", uuid.uuid4())

    assert (listed.status_code, created.status_code) == (403, 403)


async def test_br2_tech_admin_responses_contain_no_business_data(api_env: ApiEnv) -> None:
    """Раздел отдаёт только представление учётной записи (BR-2): ни проектов, ни задач."""
    env = api_env
    ws, _, token, _, _ = await _two_workspaces(env)
    target, _ = await seed(env, ws, "user")

    listed = await env.client.get(ADMIN_USERS, headers=env.auth(token))
    got = await env.client.get(f"{ADMIN_USERS}/{target.id}", headers=env.auth(token))
    role = await admin_call(env, token, "role_ba", target.id)

    for item in listed.json()["items"] + [got.json(), role.json()]:
        assert set(item) == ADMIN_VIEW_FIELDS
    for response in (listed, got, role):
        lowered = response.text.lower()
        for word in ("project", "task", "deal", "account_id", "comment"):
            assert word not in lowered, word


def test_br2_admin_api_sources_do_not_mention_business_sections() -> None:
    """Как для сервиса (T16, п.7): в модулях раздела нет подстрок ``projects``/``tasks``."""
    for rel in ("app/api/v1/admin_users.py", "app/api/v1/schemas/admin.py"):
        source = (BACKEND_DIR / rel).read_text(encoding="utf-8").lower()
        for word in ("projects", "tasks"):
            assert word not in source, (rel, word)


async def test_ac21_foreign_user_login_in_create_is_login_taken_not_leaking_profile(
    api_env: ApiEnv,
) -> None:
    """Логин глобален: создание с занятым чужим логином — 422 ``login_taken`` без профиля."""
    env = api_env
    _, _, token, victim, _ = await _two_workspaces(env)

    response = await env.client.post(
        ADMIN_USERS,
        json={"login": victim.login, "one_time_password": "Unr3lated-Pa55phrase-91"},
        headers=env.auth(token),
    )

    assert response.status_code == 422
    assert code_of(response) == "login_taken"
    assert str(victim.id) not in response.text
    rows = await env.execute(
        text("SELECT count(*) FROM workspace_member WHERE user_id = :u").bindparams(u=victim.id)
    )
    assert rows and rows[0][0] == 1


# --- T72: проекты и участники (AC-21, AC-94, BR-2, FR-13) ----------------------------------


async def test_t72_ac21_foreign_projects_and_members_are_invisible_and_untouched(
    api_env: ApiEnv,
) -> None:
    from tests.projects_api_support import (
        PROJECTS,
        error,
        make_api_world,
        make_foreign,
        member_ids,
        members_url,
        pj,
        project_db,
        send,
    )

    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)
    pid = foreign.project_id
    missing = uuid.uuid4()
    before_members = await member_ids(env, pid)
    before_row = await project_db(env, pid)

    # списки
    for who in ("ba3", "ba", "usr"):
        listed = await send(env, w.tok(who), "GET", PROJECTS)
        assert listed.status_code == 200, listed.text
        assert str(pid) not in listed.text
        assert foreign.ba.login not in listed.text
    # карточка, правка, владелец, удаление, участники: 404, неотличимо от несуществующего
    calls = [
        ("GET", pj(pid), None),
        ("PATCH", pj(pid), {"name": "Взлом"}),
        ("PUT", f"{pj(pid)}/owner", {"user_id": str(w.uid("ba2"))}),
        ("DELETE", pj(pid), None),
        ("GET", members_url(pid), None),
        ("POST", members_url(pid), {"user_id": str(w.uid("usr2"))}),
        ("DELETE", members_url(pid, foreign.usr.id), None),
    ]
    for who in ("ba3", "ba", "usr2"):
        for method, url, body in calls:
            r = await send(env, w.tok(who), method, url, body)
            ref = await send(env, w.tok(who), method, url.replace(str(pid), str(missing)), body)
            assert error(r) == (404, "not_found"), (who, method, url)
            assert r.json() == ref.json()

    # состояние чужого проекта не изменилось
    assert await member_ids(env, pid) == before_members
    after_row = await project_db(env, pid)
    assert (after_row.name, after_row.owner_id, after_row.deleted_at) == (
        before_row.name,
        before_row.owner_id,
        None,
    )


async def test_t72_ac21_foreign_user_cannot_be_member_or_owner_of_own_project(
    api_env: ApiEnv,
) -> None:
    from tests.projects_api_support import (
        error,
        make_api_world,
        make_foreign,
        member_ids,
        members_url,
        pj,
        project_db,
        send,
    )

    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)
    before = await member_ids(env, w.project_id)

    added = await send(
        env, w.tok("ba"), "POST", members_url(w.project_id), {"user_id": str(foreign.usr.id)}
    )
    moved = await send(
        env,
        w.tok("ba3"),
        "PUT",
        f"{pj(w.project_id)}/owner",
        {"user_id": str(foreign.ba.id)},
    )
    removed = await send(env, w.tok("ba"), "DELETE", members_url(w.project_id, foreign.usr.id))

    assert error(added) == (422, "user_not_found")
    assert error(moved) == (422, "user_not_found")
    assert error(removed) == (404, "not_found")
    assert foreign.usr.login not in added.text + moved.text
    assert await member_ids(env, w.project_id) == before
    assert (await project_db(env, w.project_id)).owner_id == w.uid("ba")


async def test_t72_ac21_foreign_workspace_user_sees_nothing_symmetrically(
    api_env: ApiEnv,
) -> None:
    from tests.projects_api_support import PROJECTS, make_api_world, make_foreign, pj, send

    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)

    mine = await send(env, foreign.ba_token, "GET", PROJECTS)
    card = await send(env, foreign.ba_token, "GET", pj(w.project_id))

    assert [i["id"] for i in mine.json()["items"]] == [str(foreign.project_id)]
    assert card.status_code == 404
    assert "Основной" not in mine.text


# --- T77: задачи (AC-21, IDOR) ---------------------------------------------------------------


async def test_t77_ac21_foreign_task_is_invisible_and_untouched(api_env: ApiEnv) -> None:
    from tests.projects_api_support import error, make_api_world, make_foreign, send
    from tests.tasks_api_support import task_db, task_url

    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)
    made = await send(
        env,
        foreign.ba_token,
        "POST",
        f"/api/v1/projects/{foreign.project_id}/tasks",
        {"title": "Чужая", **TASK_REQ, "assignee_id": str(foreign.usr.id)},
    )
    assert made.status_code == 201, made.text
    tid = made.json()["id"]
    before = await task_db(env, tid)

    for who in ("ba", "ba2", "usr"):
        for method, url, body in (
            ("GET", task_url(tid), None),
            ("PATCH", task_url(tid), {"title": "Взлом", "assignee_id": str(w.uid("usr"))}),
            ("DELETE", task_url(tid), None),
            ("POST", f"{task_url(tid)}/subtasks", {"title": "Взлом"}),
        ):
            r = await send(env, w.tok(who), method, url, body)
            assert error(r) == (404, "not_found"), (who, method)
    after = await task_db(env, tid)
    assert (after.title, after.assignee_id, after.deleted_at, after.updated_at) == (
        before.title,
        before.assignee_id,
        before.deleted_at,
        before.updated_at,
    )
    mine = await send(env, w.tok("usr"), "GET", "/api/v1/me/tasks")
    assert tid not in mine.text


async def test_t77_ac21_foreign_user_as_assignee_is_user_not_found(api_env: ApiEnv) -> None:
    from tests.projects_api_support import error, make_api_world, make_foreign, send

    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)

    r = await send(
        env,
        w.tok("ba"),
        "POST",
        f"/api/v1/projects/{w.project_id}/tasks",
        {"title": "Т", **TASK_REQ, "assignee_id": str(foreign.usr.id)},
    )

    assert error(r) == (422, "user_not_found")


# --- T80: комментарии (AC-21, IDOR) -----------------------------------------------------------


async def test_t80_ac21_foreign_comments_are_invisible_and_untouched(api_env: ApiEnv) -> None:
    from tests.projects_api_support import error, make_api_world, make_foreign, send
    from tests.tasks_api_support import rows

    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)
    made = await send(
        env,
        foreign.ba_token,
        "POST",
        f"/api/v1/projects/{foreign.project_id}/tasks",
        {"title": "Чужая", **TASK_REQ},
    )
    tid = made.json()["id"]
    created = await send(
        env, foreign.ba_token, "POST", f"/api/v1/tasks/{tid}/comments", {"body": "тайна"}
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    for who in ("ba", "ba2", "usr"):
        for method, url, body in (
            ("GET", f"/api/v1/tasks/{tid}/comments", None),
            ("POST", f"/api/v1/tasks/{tid}/comments", {"body": "взлом"}),
            ("PATCH", f"/api/v1/comments/{cid}", {"body": "взлом"}),
            ("DELETE", f"/api/v1/comments/{cid}", None),
        ):
            r = await send(env, w.tok(who), method, url, body)
            assert error(r) == (404, "not_found"), (who, method)
            assert "тайна" not in r.text
    found = await rows(
        env,
        "SELECT body, edited_at, deleted_at FROM comment WHERE task_id = :t",
        t=uuid.UUID(tid),
    )
    assert [tuple(r) for r in found] == [("тайна", None, None)]
