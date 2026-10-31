"""R7-T13: операции чтения по ключу (007).

AC-16 (изоляция пространств), AC-18 (проекты по членству), AC-19 (мои задачи), AC-20 (задачи
проекта), AC-21 (права в карточке по ключу); FR-17 (удаление и правка/удаление комментариев по
ключу запрещены, З-6), FR-19…FR-22, FR-34; plan §4.8, PD-3. Заметка ревью R7-T12: строка агента
с ``must_change_password = true`` не мешает ключу, ``/me`` по ключу показывает ``false``.

Секрет ключа в сообщения ``assert`` не попадает: запросы идут через ``hide(...)``-ключи мира.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import text

from tests.agents007_support import (
    CLOCK,
    ME_URL,
    MY_TASKS_URL,
    PROJECTS_URL,
    World007,
    bearer,
    make_world007,
)
from tests.conftest import ApiEnv

TASKS_URL = "/api/v1/tasks"
PROJECT_TASKS = "/api/v1/projects/{pid}/tasks"
COMMENTS = "/api/v1/tasks/{tid}/comments"


async def by_key(env: ApiEnv, key: Any, url: str, **params: Any) -> httpx.Response:
    return await env.client.get(url, headers=bearer(key.secret), params=params or None)


async def by_cookie(env: ApiEnv, w: World007, who: str, url: str, **params: Any) -> httpx.Response:
    return await env.client.get(url, headers=env.auth(w.cookie(who)), params=params or None)


def ids(r: httpx.Response) -> set[str]:
    assert r.status_code == 200, r.status_code
    return {i["id"] for i in r.json()["items"]}


def perms(r: httpx.Response) -> dict[str, bool]:
    assert r.status_code == 200, r.status_code
    return dict(r.json()["permissions"])


# --- AC-18 ---------------------------------------------------------------------------------


async def test_007_ac18_projects_by_key_membership_only(api_env: ApiEnv) -> None:
    """AC-18 (FR-19): по K_u и по K_ba P есть, P2 нет (у агента-БА тоже)."""
    env = api_env
    w = await make_world007(env)
    for key in (w.K_u, w.K_ba):
        r = await by_key(env, key, PROJECTS_URL)
        assert ids(r) == {str(w.P)}
        item = r.json()["items"][0]
        assert item["name"] == "P"
        assert item["owner"]["id"] == str(w.ba1.id)


async def test_007_ac18_ba_by_cookie_still_sees_all_projects(api_env: ApiEnv) -> None:
    """AC-18: у ba1 по cookie P2 по-прежнему в списке (поведение людей не меняется)."""
    env = api_env
    w = await make_world007(env)
    r = await by_cookie(env, w, "ba1", PROJECTS_URL)
    assert {str(w.P), str(w.P2)} <= ids(r)


async def test_007_ac18_ba_agent_not_member_sees_no_project_without_membership(
    api_env: ApiEnv,
) -> None:
    """FR-19: исключение агента-БА из P убирает P из списка (область действия - членство)."""
    env = api_env
    w = await make_world007(env)
    await env.execute(
        text("DELETE FROM project_member WHERE project_id = :p AND user_id = :u").bindparams(
            p=w.P, u=w.agent_ba.id
        )
    )
    r = await by_key(env, w.K_ba, PROJECTS_URL)
    assert ids(r) == set()


# --- AC-19 ---------------------------------------------------------------------------------


async def test_007_ac19_my_tasks_by_key(api_env: ApiEnv) -> None:
    """AC-19 (FR-20): по K_u в ответе T1 и T3, нет T2 и T9."""
    env = api_env
    w = await make_world007(env)
    got = ids(await by_key(env, w.K_u, MY_TASKS_URL))
    assert {str(w.T1), str(w.T3)} <= got
    assert str(w.T2) not in got
    assert str(w.T9) not in got


# --- AC-20 ---------------------------------------------------------------------------------


async def test_007_ac20_project_tasks_status_filter(api_env: ApiEnv) -> None:
    """AC-20: задачи P со status=todo - T1 и T2, нет T3."""
    env = api_env
    w = await make_world007(env)
    got = ids(await by_key(env, w.K_u, PROJECT_TASKS.format(pid=w.P), status="todo"))
    assert got == {str(w.T1), str(w.T2)}


async def test_007_ac20_project_tasks_assignee_filter(api_env: ApiEnv) -> None:
    """AC-20: фильтр исполнителя u1 - только T2."""
    env = api_env
    w = await make_world007(env)
    got = ids(await by_key(env, w.K_u, PROJECT_TASKS.format(pid=w.P), assignee_id=str(w.u1.id)))
    assert got == {str(w.T2)}


async def test_007_ac20_project_tasks_other_project_forbidden(api_env: ApiEnv) -> None:
    """AC-20 (FR-21): P2 (агент не участник) -> 403 forbidden."""
    env = api_env
    w = await make_world007(env)
    r = await by_key(env, w.K_u, PROJECT_TASKS.format(pid=w.P2))
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


async def test_007_ac20_project_tasks_unknown_project_not_found(api_env: ApiEnv) -> None:
    """AC-20 (FR-21): несуществующий проект -> 404 not_found."""
    env = api_env
    w = await make_world007(env)
    r = await by_key(env, w.K_u, PROJECT_TASKS.format(pid=uuid.uuid4()))
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


async def test_007_ac20_project_tasks_soft_deleted_project_not_found(api_env: ApiEnv) -> None:
    """FR-21: удалённый проект -> 404."""
    env = api_env
    w = await make_world007(env)
    await env.execute(
        text("UPDATE project SET deleted_at = :t WHERE id = :p").bindparams(t=CLOCK, p=w.P)
    )
    r = await by_key(env, w.K_u, PROJECT_TASKS.format(pid=w.P))
    assert r.status_code == 404


# --- AC-21 ---------------------------------------------------------------------------------


async def test_007_ac21_card_t1_by_key_u(api_env: ApiEnv) -> None:
    """AC-21: T1 по K_u - автор ba1, исполнитель agent.u; права: правка нет, статус да,
    исполнитель нет, подзадача да, удаление нет."""
    env = api_env
    w = await make_world007(env)
    r = await by_key(env, w.K_u, f"{TASKS_URL}/{w.T1}")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "T1"
    assert body["author"]["id"] == str(w.ba1.id)
    assert body["assignee"]["id"] == str(w.agent_u.id)
    assert perms(r) == {
        "edit": False,
        "change_status": True,
        "change_assignee": False,
        "create_subtask": True,
        "delete": False,
    }


async def test_007_ac21_card_t2_by_key_u(api_env: ApiEnv) -> None:
    """AC-21: T2 (исполнитель u1) - 200, смена статуса нет."""
    env = api_env
    w = await make_world007(env)
    r = await by_key(env, w.K_u, f"{TASKS_URL}/{w.T2}")
    assert r.status_code == 200
    p = perms(r)
    assert p["change_status"] is False
    assert p["delete"] is False
    assert p["edit"] is False


async def test_007_ac21_card_t9_other_project_forbidden(api_env: ApiEnv) -> None:
    """AC-21: T9 (P2) -> 403."""
    env = api_env
    w = await make_world007(env)
    for key in (w.K_u, w.K_ba):
        r = await by_key(env, key, f"{TASKS_URL}/{w.T9}")
        assert r.status_code == 403, r.status_code


async def test_007_ac21_card_ba_agent_delete_false_ba_cookie_true(api_env: ApiEnv) -> None:
    """AC-21 / FR-17 / З-6: карточка задачи P у agent.ba по ключу - delete false, остальные
    права БА-участника сохраняются; у ba1 по cookie - delete true."""
    env = api_env
    w = await make_world007(env)
    by_ba_key = perms(await by_key(env, w.K_ba, f"{TASKS_URL}/{w.T2}"))
    assert by_ba_key == {
        "edit": True,
        "change_status": True,
        "change_assignee": True,
        "create_subtask": True,
        "delete": False,
    }
    by_ba_cookie = perms(await by_cookie(env, w, "ba1", f"{TASKS_URL}/{w.T2}"))
    assert by_ba_cookie["delete"] is True


async def test_007_ac21_card_own_task_agent_u_delete_false(api_env: ApiEnv) -> None:
    """FR-17 / З-6: у агента-П своя задача (автор и исполнитель - он): edit true, delete false
    (для человека-П в той же ситуации delete true)."""
    env = api_env
    w = await make_world007(env)
    r = await by_key(env, w.K_u, f"{TASKS_URL}/{w.T3}")
    p = perms(r)
    assert p["edit"] is True
    assert p["delete"] is False


async def test_007_ac21_comment_permissions_by_key(api_env: ApiEnv) -> None:
    """AC-21 / З-6: комментарии агента по ключу - edit false, delete false, в том числе свой
    комментарий и чужой (c1) у агента-БА; по cookie у ba1 delete true."""
    from tests.factories import make_comment

    env = api_env
    w = await make_world007(env)
    async with env.sessionmaker() as s:
        own_u = await make_comment(
            s, task_id=w.T1, workspace_id=w.ws.id, created_by=w.agent_u.id, body="own-u"
        )
        own_ba = await make_comment(
            s, task_id=w.T1, workspace_id=w.ws.id, created_by=w.agent_ba.id, body="own-ba"
        )
        await s.commit()
    url = COMMENTS.format(tid=w.T1)

    def comment_perms(r: httpx.Response) -> dict[str, dict[str, bool]]:
        assert r.status_code == 200, r.status_code
        return {i["id"]: i["permissions"] for i in r.json()["items"]}

    got_u = comment_perms(await by_key(env, w.K_u, url))
    assert got_u[str(own_u.id)] == {"edit": False, "delete": False}
    assert got_u[str(w.c1)] == {"edit": False, "delete": False}

    got_ba = comment_perms(await by_key(env, w.K_ba, url))
    assert got_ba[str(own_ba.id)] == {"edit": False, "delete": False}
    assert got_ba[str(w.c1)] == {"edit": False, "delete": False}

    got_cookie = comment_perms(await by_cookie(env, w, "ba1", url))
    assert got_cookie[str(w.c1)] == {"edit": False, "delete": True}
    assert got_cookie[str(own_u.id)]["delete"] is True


async def test_007_ac21_human_user_own_task_delete_still_true(api_env: ApiEnv) -> None:
    """Регресс: для человека-П своя задача (автор и исполнитель) - edit и delete true."""
    from tests.factories import make_task

    env = api_env
    w = await make_world007(env)
    async with env.sessionmaker() as s:
        t = await make_task(
            s,
            project_id=w.P,
            workspace_id=w.ws.id,
            created_by=w.u1.id,
            assignee_id=w.u1.id,
            title="own-human",
        )
        await s.commit()
    r = await by_cookie(env, w, "u1", f"{TASKS_URL}/{t.id}")
    p = perms(r)
    assert p["edit"] is True
    assert p["delete"] is True


# --- AC-16 ---------------------------------------------------------------------------------


async def test_007_ac16_other_workspace_is_not_found(api_env: ApiEnv) -> None:
    """AC-16 (FR-34): проект и задача TW второго пространства W2 (фабрики БД) - по K_ba
    карточка TW и список задач проекта W2 дают 404."""
    from tests.factories import make_project, make_task, make_user, make_workspace

    env = api_env
    w = await make_world007(env)
    async with env.sessionmaker() as s:
        w2 = await make_workspace(s)
        owner = await make_user(s, workspace=w2, role="business_admin", login="ba.w2")
        p2 = await make_project(s, workspace_id=w2.id, owner_id=owner.id, name="PW")
        tw = await make_task(
            s, project_id=p2.id, workspace_id=w2.id, created_by=owner.id, title="TW"
        )
        await s.commit()

    r_card = await by_key(env, w.K_ba, f"{TASKS_URL}/{tw.id}")
    assert r_card.status_code == 404
    assert r_card.json()["code"] == "not_found"
    r_list = await by_key(env, w.K_ba, PROJECT_TASKS.format(pid=p2.id))
    assert r_list.status_code == 404
    assert r_list.json()["code"] == "not_found"
    listed = ids(await by_key(env, w.K_ba, PROJECTS_URL))
    assert str(p2.id) not in listed


# --- заметка ревью R7-T12 ------------------------------------------------------------------


async def test_007_r7t12_note_must_change_password_row_key_works(api_env: ApiEnv) -> None:
    """Заметка ревью R7-T12: у строки агента в БД must_change_password = true - ключ работает,
    /me по ключу показывает false (флаг для запроса по ключу не действует)."""
    env = api_env
    w = await make_world007(env)
    await env.execute(
        text("UPDATE app_user SET must_change_password = true WHERE id = :u").bindparams(
            u=w.agent_u.id
        )
    )
    row = await env.user_row(w.agent_u.id)
    assert row.must_change_password is True  # предусловие

    r = await env.client.get(ME_URL, headers=bearer(w.K_u.secret))
    assert r.status_code == 200
    assert r.json()["must_change_password"] is False
    r2 = await by_key(env, w.K_u, PROJECTS_URL)
    assert r2.status_code == 200


async def test_007_z6_me_by_key_capabilities_fact(api_env: ApiEnv) -> None:
    """З-6 / open-items п.7: фиксируем ТЕКУЩЕЕ поведение как факт, фильтрации не требуем:
    /me по ключу отдаёт capabilities по роли учётной записи (у agent.ba они не пусты и
    совпадают с /me человека-БА). Если фильтрация появится, тест правится осознанно."""
    env = api_env
    w = await make_world007(env)
    r_agent = await by_key(env, w.K_ba, ME_URL)
    r_human = await by_cookie(env, w, "ba1", ME_URL)
    assert r_agent.status_code == 200
    assert r_human.status_code == 200
    assert r_agent.json()["capabilities"] == r_human.json()["capabilities"]
    assert r_agent.json()["capabilities"] != []
