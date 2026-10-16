"""R3-T02, R3-T03: БА-участник правит, переназначает и удаляет любое в проекте; БА-не участник
не имеет доступа (spec 002: AC-13, AC-14, AC-15, FR-9, FR-10, 001/FR-5).

Шаги критериев повторяются буквально на фикстуре spec 002 §6 (``roles002_support``).
"""

from __future__ import annotations

from typing import Any

from tests.conftest import ApiEnv
from tests.projects_api_support import rows, set_blocked
from tests.roles002_support import (
    World002,
    error,
    make_world_002,
    members_url,
    pj,
    send,
    snapshot,
)

TASKS = "/api/v1/tasks"
COMMENTS = "/api/v1/comments"
PROJECTS = "/api/v1/projects"


def _list_url(w: World002, task: str) -> str:
    return f"{TASKS}/{w.tasks[task]}/comments"


async def _comment(env: ApiEnv, w: World002, name: str) -> Any:
    found = await rows(
        env,
        "SELECT body, deleted_at, deleted_batch_id FROM comment WHERE id = :c",
        c=w.comments[name],
    )
    assert len(found) == 1
    return found[0]


# --- AC-13 -------------------------------------------------------------------------------


async def test_002_ac13_ba_member_deletes_foreign_comment_c1(api_env: ApiEnv) -> None:
    """AC-13 (FR-9): ba.member (участник P, не владелец, не автор) удаляет c1 (автор u1) -> 204,
    комментарий удалён мягко; c2 не тронут; в списке c1 - заглушка без текста."""
    env = api_env
    w = await make_world_002(env)
    before = await snapshot(env, w)
    assert (await _comment(env, w, "c1")).deleted_at is None

    r = await send(env, w.tok("ba.member"), "DELETE", f"{COMMENTS}/{w.comments['c1']}")

    assert r.status_code == 204, r.text
    c1 = await _comment(env, w, "c1")
    assert c1.deleted_at is not None
    assert c1.deleted_batch_id is not None
    assert (await _comment(env, w, "c2")).deleted_at is None
    assert (await _comment(env, w, "c3")).deleted_at is None
    after = await snapshot(env, w)
    assert after["events"] == before["events"]  # комментарии журнал не пишут (D-55)
    assert after["tasks"] == before["tasks"]

    r = await send(env, w.tok("u1"), "GET", _list_url(w, "T1"))
    assert r.status_code == 200, r.text
    items = {i["id"]: i for i in r.json()["items"]}
    assert items[str(w.comments["c1"])]["is_deleted"] is True
    assert items[str(w.comments["c1"])]["body"] is None
    assert items[str(w.comments["c2"])]["is_deleted"] is False


async def test_002_ac13_ba_member_comment_permissions_flag_delete_true(api_env: ApiEnv) -> None:
    """AC-13, FR-21: в списке комментариев T1 для ba.member delete=True у чужих c1 и c2,
    edit=False (правка только у автора); у u1 на чужой c2 delete=False (AC-16)."""
    env = api_env
    w = await make_world_002(env)

    r = await send(env, w.tok("ba.member"), "GET", _list_url(w, "T1"))
    assert r.status_code == 200, r.text
    perms = {i["id"]: i["permissions"] for i in r.json()["items"]}
    assert perms == {
        str(w.comments["c1"]): {"edit": False, "delete": True},
        str(w.comments["c2"]): {"edit": False, "delete": True},
    }

    r = await send(env, w.tok("u1"), "GET", _list_url(w, "T1"))
    perms = {i["id"]: i["permissions"] for i in r.json()["items"]}
    assert perms[str(w.comments["c1"])] == {"edit": True, "delete": True}
    assert perms[str(w.comments["c2"])] == {"edit": False, "delete": False}


async def test_002_ac13_ba_member_cannot_edit_foreign_comment_c1(api_env: ApiEnv) -> None:
    """FR-9: правка комментария остаётся за автором; ba.member правит c1 (автор u1) -> 403,
    данные не изменены."""
    env = api_env
    w = await make_world_002(env)
    before = await snapshot(env, w)

    r = await send(
        env, w.tok("ba.member"), "PATCH", f"{COMMENTS}/{w.comments['c1']}", {"body": "правка"}
    )

    assert error(r) == (403, "forbidden")
    assert await snapshot(env, w) == before


async def test_002_ac13_ba_owner_still_deletes_foreign_comment(api_env: ApiEnv) -> None:
    """AC-13 (регресс): владелец-БА по-прежнему удаляет чужой комментарий c2 (автор u2)."""
    env = api_env
    w = await make_world_002(env)

    r = await send(env, w.tok("ba.owner"), "DELETE", f"{COMMENTS}/{w.comments['c2']}")

    assert r.status_code == 204, r.text
    assert (await _comment(env, w, "c2")).deleted_at is not None


# --- AC-15 -------------------------------------------------------------------------------


async def test_002_ac15_ba_out_comments_denied_then_self_add_allows_reading(
    api_env: ApiEnv,
) -> None:
    """AC-15 (FR-10): ba.out не участник P - удаление c1 и чтение комментариев T1 -> 403, данные
    не изменены, журнал не пополнен. После самодобавления в P чтение комментариев T1 -> 200."""
    env = api_env
    w = await make_world_002(env)
    before = await snapshot(env, w)

    r = await send(env, w.tok("ba.out"), "DELETE", f"{COMMENTS}/{w.comments['c1']}")
    assert error(r) == (403, "forbidden")
    r = await send(env, w.tok("ba.out"), "GET", _list_url(w, "T1"))
    assert error(r) == (403, "forbidden")
    r = await send(
        env, w.tok("ba.out"), "PATCH", f"{COMMENTS}/{w.comments['c1']}", {"body": "правка"}
    )
    assert error(r) == (403, "forbidden")
    r = await send(env, w.tok("ba.out"), "POST", _list_url(w, "T1"), {"body": "новый"})
    assert error(r) == (403, "forbidden")
    assert await snapshot(env, w) == before
    assert (await _comment(env, w, "c1")).deleted_at is None

    r = await send(
        env, w.tok("ba.out"), "POST", members_url(w.project_id), {"user_id": str(w.uid("ba.out"))}
    )
    assert r.status_code == 204, r.text
    r = await send(env, w.tok("ba.out"), "GET", _list_url(w, "T1"))
    assert r.status_code == 200, r.text
    assert {i["id"] for i in r.json()["items"]} == {
        str(w.comments["c1"]),
        str(w.comments["c2"]),
    }


async def test_002_ac15_ba_out_deletes_comment_after_self_add(api_env: ApiEnv) -> None:
    """FR-9, FR-10: самодобавленный в P ba.out получает право участника - удаляет c1 -> 204."""
    env = api_env
    w = await make_world_002(env)
    r = await send(
        env, w.tok("ba.out"), "POST", members_url(w.project_id), {"user_id": str(w.uid("ba.out"))}
    )
    assert r.status_code == 204, r.text

    r = await send(env, w.tok("ba.out"), "DELETE", f"{COMMENTS}/{w.comments['c1']}")

    assert r.status_code == 204, r.text
    assert (await _comment(env, w, "c1")).deleted_at is not None


# --- R3-T03: задачи ------------------------------------------------------------------------


def _task_url(w: World002, task: str) -> str:
    return f"{TASKS}/{w.tasks[task]}"


async def _task(env: ApiEnv, w: World002, name: str) -> Any:
    found = await rows(
        env,
        "SELECT title, description, status, priority, due_date, assignee_id, deleted_at "
        "FROM task WHERE id = :t",
        t=w.tasks[name],
    )
    assert len(found) == 1
    return found[0]


async def test_002_ac13_ba_member_edits_foreign_task_t1_all_fields(api_env: ApiEnv) -> None:
    """AC-13 (FR-9): ba.member (участник P, не владелец, не автор, не исполнитель) меняет у T1
    название, описание, срок, приоритет и статус, затем исполнителя на u2 -> 200, всё сохранено."""
    env = api_env
    w = await make_world_002(env)

    r = await send(
        env,
        w.tok("ba.member"),
        "PATCH",
        _task_url(w, "T1"),
        {
            "title": "T1 new",
            "description": "new descr",
            "due_date": "2031-05-04",
            "priority": "high",
            "status": "in_progress",
        },
    )
    assert r.status_code == 200, r.text
    r = await send(
        env, w.tok("ba.member"), "PATCH", _task_url(w, "T1"), {"assignee_id": str(w.uid("u2"))}
    )
    assert r.status_code == 200, r.text
    assert r.json()["assignee"]["id"] == str(w.uid("u2"))

    t1 = await _task(env, w, "T1")
    assert t1.title == "T1 new"
    assert t1.description == "new descr"
    assert str(t1.due_date) == "2031-05-04"
    assert t1.priority == "high"
    assert t1.status == "in_progress"
    assert t1.assignee_id == w.uid("u2")

    r = await send(env, w.tok("ba.member"), "GET", _task_url(w, "T1"))
    assert r.status_code == 200, r.text
    perms = r.json()["permissions"]
    assert perms["edit"] is True
    assert perms["change_assignee"] is True
    assert perms["delete"] is True
    assert perms["create_subtask"] is True


async def test_002_ac13_ba_member_creates_tasks_and_subtasks(api_env: ApiEnv) -> None:
    """AC-13 (FR-9): ba.member создаёт задачу без исполнителя и задачу для u1, создаёт к T3
    подзадачу для u2 и подзадачу без исполнителя -> 201, всё создано."""
    env = api_env
    w = await make_world_002(env)
    tok = w.tok("ba.member")

    r = await send(env, tok, "POST", f"{PROJECTS}/{w.project_id}/tasks", {"title": "free"})
    assert r.status_code == 201, r.text
    assert r.json()["assignee"] is None
    r = await send(
        env,
        tok,
        "POST",
        f"{PROJECTS}/{w.project_id}/tasks",
        {"title": "for u1", "assignee_id": str(w.uid("u1"))},
    )
    assert r.status_code == 201, r.text
    assert r.json()["assignee"]["id"] == str(w.uid("u1"))

    r = await send(
        env,
        tok,
        "POST",
        f"{_task_url(w, 'T3')}/subtasks",
        {"title": "sub u2", "assignee_id": str(w.uid("u2"))},
    )
    assert r.status_code == 201, r.text
    assert r.json()["parent_id"] == str(w.tasks["T3"])
    assert r.json()["assignee"]["id"] == str(w.uid("u2"))
    r = await send(env, tok, "POST", f"{_task_url(w, 'T3')}/subtasks", {"title": "sub free"})
    assert r.status_code == 201, r.text
    assert r.json()["assignee"] is None

    found = await rows(
        env,
        "SELECT title, parent_id, assignee_id FROM task WHERE project_id = :p "
        "AND title IN ('free', 'for u1', 'sub u2', 'sub free') ORDER BY title",
        p=w.project_id,
    )
    assert [(x.title, x.parent_id, x.assignee_id) for x in found] == [
        ("for u1", None, w.uid("u1")),
        ("free", None, None),
        ("sub free", w.tasks["T3"], None),
        ("sub u2", w.tasks["T3"], w.uid("u2")),
    ]


async def test_002_ac13_ba_member_deletes_t3_with_subtask_and_comment(api_env: ApiEnv) -> None:
    """AC-13 (FR-9): ba.member удаляет T3 (автор и исполнитель u1) -> 204; T3, T3.1 удалены
    мягко, c3 тоже; запрос каждой по идентификатору -> 404 (c3 - через список комментариев T3)."""
    env = api_env
    w = await make_world_002(env)

    r = await send(env, w.tok("ba.member"), "DELETE", _task_url(w, "T3"))

    assert r.status_code == 204, r.text
    assert (await _task(env, w, "T3")).deleted_at is not None
    assert (await _task(env, w, "T3.1")).deleted_at is not None
    assert (await _comment(env, w, "c3")).deleted_at is not None
    for who in ("ba.member", "u1", "ba.owner"):
        for name in ("T3", "T3.1"):
            r = await send(env, w.tok(who), "GET", _task_url(w, name))
            assert error(r) == (404, "not_found"), (who, name, r.text)
        r = await send(env, w.tok(who), "GET", _list_url(w, "T3"))
        assert r.status_code == 404, r.text
        r = await send(env, w.tok(who), "DELETE", f"{COMMENTS}/{w.comments['c3']}")
        assert r.status_code == 404, r.text
    # T1 и её данные не затронуты
    assert (await _task(env, w, "T1")).deleted_at is None
    assert (await _task(env, w, "T1.1")).deleted_at is None
    assert (await _comment(env, w, "c1")).deleted_at is None


async def test_002_ac13_ba_member_moves_foreign_task_on_board(api_env: ApiEnv) -> None:
    """AC-13, FR-9: ba.member переносит чужую T1 (исполнитель u1) в колонку 'review' -> 204."""
    env = api_env
    w = await make_world_002(env)

    r = await send(
        env, w.tok("ba.member"), "POST", f"{_task_url(w, 'T1')}/move", {"status": "review"}
    )

    assert r.status_code == 204, r.text
    assert (await _task(env, w, "T1")).status == "review"


async def test_002_ac13_user_u1_still_cannot_edit_foreign_t1_fields(api_env: ApiEnv) -> None:
    """AC-13 (регресс границы): u2 (П, не автор T1) не правит T1 -> 403, данные не изменены."""
    env = api_env
    w = await make_world_002(env)
    before = await snapshot(env, w)

    r = await send(env, w.tok("u2"), "PATCH", _task_url(w, "T1"), {"title": "hack"})
    assert error(r) == (403, "forbidden")
    r = await send(env, w.tok("u2"), "DELETE", _task_url(w, "T1"))
    assert error(r) == (403, "forbidden")
    assert await snapshot(env, w) == before


# --- AC-14 -------------------------------------------------------------------------------


async def test_002_ac14_ba_member_reassigns_task_of_blocked_assignee(api_env: ApiEnv) -> None:
    """AC-14 (FR-9, 001/FR-5): u1 (исполнитель T1) заблокирован; ba.member переназначает T1 на
    u2 -> 200, сохранено, u2 видит себя исполнителем. Шаг «то же делает u2 -> 403» проверяется
    на свежей фикстуре в test_002_ac14_user_cannot_reassign_blocked_assignee_task_first:
    после шага ba.member u2 уже исполнитель, и повтор был бы пустым изменением (D-46)."""
    env = api_env
    w = await make_world_002(env)
    await set_blocked(env, w.uid("u1"))
    body = {"assignee_id": str(w.uid("u2"))}

    r = await send(env, w.tok("ba.member"), "PATCH", _task_url(w, "T1"), body)
    assert r.status_code == 200, r.text
    assert r.json()["assignee"]["id"] == str(w.uid("u2"))
    assert (await _task(env, w, "T1")).assignee_id == w.uid("u2")


async def test_002_ac14_user_cannot_reassign_blocked_assignee_task_first(api_env: ApiEnv) -> None:
    """AC-14: на свежей фикстуре u2 переназначает T1 заблокированного u1 на себя -> 403,
    исполнитель остался u1; журнал не пополнен."""
    env = api_env
    w = await make_world_002(env)
    await set_blocked(env, w.uid("u1"))
    before = await snapshot(env, w)

    r = await send(env, w.tok("u2"), "PATCH", _task_url(w, "T1"), {"assignee_id": str(w.uid("u2"))})

    assert error(r) == (403, "forbidden")
    assert await snapshot(env, w) == before
    assert (await _task(env, w, "T1")).assignee_id == w.uid("u1")


# --- AC-15 (задачи) ----------------------------------------------------------------------


async def test_002_ac15_ba_out_task_operations_denied_then_self_add_reads_t1(
    api_env: ApiEnv,
) -> None:
    """AC-15 (FR-10): ba.out (не участник P) запрашивает T1, список задач, доску, комментарии
    T1; создаёт задачу и подзадачу; меняет T1 и её исполнителя; удаляет c1 и T1 -> каждый раз
    403, данные не изменены. Список проектов и карточка P доступны без задач. После
    самодобавления GET T1 -> 200."""
    env = api_env
    w = await make_world_002(env)
    tok = w.tok("ba.out")
    before = await snapshot(env, w)
    pid = w.project_id

    calls: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", _task_url(w, "T1"), None),
        ("GET", f"{PROJECTS}/{pid}/tasks", None),
        ("GET", f"{PROJECTS}/{pid}/board", None),
        ("GET", _list_url(w, "T1"), None),
        ("POST", f"{PROJECTS}/{pid}/tasks", {"title": "x"}),
        ("POST", f"{_task_url(w, 'T1')}/subtasks", {"title": "x"}),
        ("PATCH", _task_url(w, "T1"), {"title": "x"}),
        ("PATCH", _task_url(w, "T1"), {"assignee_id": str(w.uid("u2"))}),
        ("DELETE", f"{COMMENTS}/{w.comments['c1']}", None),
        ("DELETE", _task_url(w, "T1"), None),
    ]
    for method, url, body in calls:
        r = await send(env, tok, method, url, body)
        assert error(r) == (403, "forbidden"), (method, url, r.status_code, r.text)
    assert await snapshot(env, w) == before

    r = await send(env, tok, "GET", PROJECTS)
    assert r.status_code == 200, r.text
    listed = [i for i in r.json()["items"] if i["id"] == str(pid)]
    assert len(listed) == 1
    assert listed[0]["name"] == "P"
    assert listed[0]["owner"]["id"] == str(w.uid("ba.owner"))
    assert listed[0]["task_count"] == 2
    assert "tasks" not in listed[0]
    r = await send(env, tok, "GET", pj(pid))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "P"
    assert r.json()["owner"]["id"] == str(w.uid("ba.owner"))
    assert r.json()["task_count"] == 2
    assert r.json()["is_member"] is False
    assert "tasks" not in r.json()

    r = await send(env, tok, "POST", members_url(pid), {"user_id": str(w.uid("ba.out"))})
    assert r.status_code == 204, r.text
    r = await send(env, tok, "GET", _task_url(w, "T1"))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == str(w.tasks["T1"])


async def test_002_ac15_self_added_ba_out_edits_reassigns_and_deletes_task(
    api_env: ApiEnv,
) -> None:
    """FR-9, FR-10: после самодобавления ba.out правит T1, меняет исполнителя и удаляет T3."""
    env = api_env
    w = await make_world_002(env)
    tok = w.tok("ba.out")
    r = await send(env, tok, "POST", members_url(w.project_id), {"user_id": str(w.uid("ba.out"))})
    assert r.status_code == 204, r.text

    r = await send(env, tok, "PATCH", _task_url(w, "T1"), {"title": "by out"})
    assert r.status_code == 200, r.text
    r = await send(env, tok, "PATCH", _task_url(w, "T1"), {"assignee_id": str(w.uid("u2"))})
    assert r.status_code == 200, r.text
    r = await send(env, tok, "DELETE", _task_url(w, "T3"))
    assert r.status_code == 204, r.text

    assert (await _task(env, w, "T1")).title == "by out"
    assert (await _task(env, w, "T1")).assignee_id == w.uid("u2")
    assert (await _task(env, w, "T3")).deleted_at is not None
