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
    mixed, (token2,) = await seed(env, ws2, "mixed")
    assert (await admin_call(env, token2, "get", mixed.id)).status_code == 200

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
