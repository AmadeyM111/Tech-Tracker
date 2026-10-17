"""T77: матрица «роль × состояние задачи × операция» (AC-9, AC-11, AC-46, AC-47, AC-99, AC-103).

Состояния (автор -> исполнитель), проект: владелец ``ba``; участники ``ba2``, ``usr``:

* ``assigned``   ``ba -> usr``   — задача поставлена «Пользователю» владельцем;
* ``own_usr``    ``usr -> usr``  — своя задача «Пользователя»;
* ``unassigned`` ``ba -> —``     — без исполнителя;
* ``own_ba2``    ``ba2 -> ba2``  — своя задача БА-участника, не владельца;
* ``to_ba2``     ``ba -> ba2``   — задача БА-участнику, не владельцу.

Операции: ``view`` (GET), ``title`` (PATCH названия), ``status`` (PATCH статуса), ``assignee``
(PATCH исполнителя на ``ba``), ``delete`` (DELETE), ``subtask`` (POST подзадачи без
исполнителя). Ожидания записаны явно по plan §11.5, а не выведены из кода политики.
Поля ``permissions`` карточки обязаны совпадать с фактическим исходом операций.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    error,
    make_api_world,
    mk,
    send,
    task_db,
    task_url,
)

STATES: dict[str, tuple[str, str | None]] = {
    "assigned": ("ba", "usr"),
    "own_usr": ("usr", "usr"),
    "unassigned": ("ba", None),
    "own_ba2": ("ba2", "ba2"),
    "to_ba2": ("ba", "ba2"),
}
OPS = ("title", "status", "assignee", "delete", "subtask")
ALL = {op: True for op in OPS}
NONE = {op: False for op in OPS}

# роль -> состояние -> какие операции разрешены (view у участников всегда разрешён)
EXPECTED: dict[str, dict[str, dict[str, bool]]] = {
    "ba": {s: ALL for s in STATES},
    # 002/AC-13, AC-14 (FR-9): БА-участник не владелец может всё в любом состоянии
    "ba2": {s: ALL for s in STATES},
    "usr": {
        "assigned": {**NONE, "status": True, "subtask": True},
        "own_usr": {**ALL, "assignee": False},
        "unassigned": NONE,
        "own_ba2": NONE,
        "to_ba2": NONE,
    },
}
PERMISSION_KEY = {
    "title": "edit",
    "status": "change_status",
    "assignee": "change_assignee",
    "delete": "delete",
    "subtask": "create_subtask",
}


async def _op(env: ApiEnv, w: Any, who: str, op: str, task_id: Any) -> Any:
    token = w.tok(who)
    if op == "view":
        return await send(env, token, "GET", task_url(task_id))
    if op == "title":
        return await send(env, token, "PATCH", task_url(task_id), {"title": "Новое название"})
    if op == "status":
        return await send(env, token, "PATCH", task_url(task_id), {"status": "in_progress"})
    if op == "assignee":
        return await send(env, token, "PATCH", task_url(task_id), {"assignee_id": str(w.uid("ba"))})
    if op == "delete":
        return await send(env, token, "DELETE", task_url(task_id))
    assert op == "subtask"
    return await send(env, token, "POST", f"{task_url(task_id)}/subtasks", {"title": "Подзадача"})


async def _fresh(env: ApiEnv, w: Any, state: str) -> Any:
    by, assignee = STATES[state]
    return await mk(env, w, by=by, assignee=assignee, title="Исходное")


@pytest.mark.parametrize("who", list(EXPECTED))
async def test_matrix_role_x_state_x_operation(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    failures: list[str] = []

    for state, allowed in EXPECTED[who].items():
        # карточка: права совпадают с таблицей
        probe = await _fresh(env, w, state)
        card = await _op(env, w, who, "view", probe)
        assert card.status_code == 200, (who, state, card.text)
        perms = card.json()["permissions"]
        for op, key in PERMISSION_KEY.items():
            if perms[key] != allowed[op]:
                failures.append(f"permissions.{key} {who}/{state}: {perms[key]} != {allowed[op]}")
        # операции — каждая на свежей задаче
        for op in OPS:
            task_id = await _fresh(env, w, state)
            r = await _op(env, w, who, op, task_id)
            want = 200 if allowed[op] else 403
            if op == "delete" and allowed[op]:
                want = 204
            if op == "subtask" and allowed[op]:
                want = 201
            if r.status_code != want:
                failures.append(f"{who}/{state}/{op}: {r.status_code} != {want} {r.text[:80]}")
                continue
            row = await task_db(env, task_id)
            if not allowed[op]:
                if (row.title, row.status, row.deleted_at, row.assignee_id) != (
                    "Исходное",
                    "todo",
                    None,
                    w.uid(STATES[state][1]) if STATES[state][1] else None,
                ):
                    failures.append(f"{who}/{state}/{op}: данные изменены при 403")
                if error(r) != (403, "forbidden"):
                    failures.append(f"{who}/{state}/{op}: код {error(r)}")
    assert failures == []


@pytest.mark.parametrize("who", ["usr2", "ba3"])
@pytest.mark.parametrize("state", list(STATES))
async def test_ac11_ac103_non_member_gets_403_on_every_operation(
    api_env: ApiEnv, who: str, state: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    for op in ("view", *OPS):
        task_id = await _fresh(env, w, state)

        r = await _op(env, w, who, op, task_id)

        assert error(r) == (403, "forbidden"), (who, state, op)
        row = await task_db(env, task_id)
        assert (row.title, row.status, row.deleted_at) == ("Исходное", "todo", None)


async def test_ac103_ba_non_member_adds_himself_and_then_changes_foreign_task(
    api_env: ApiEnv,
) -> None:
    """AC 002 AC-15 (прежде СМ ``sm``): БА-неучастник ``ba3`` - 403, после вступления - успех."""
    from tests.tasks_api_support import add_member_row

    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", title="Исходное")
    assert error(await _op(env, w, "ba3", "title", t)) == (403, "forbidden")

    await add_member_row(env, w, w.people["ba3"].user)

    for op, want in (("title", 200), ("assignee", 200), ("subtask", 201)):
        r = await _op(env, w, "ba3", op, t)
        assert r.status_code == want, (op, r.text)
    deleted = await _op(env, w, "ba3", "delete", t)
    assert deleted.status_code == 204


async def test_ac99_ba_member_deletes_foreign_task_non_member_cannot(api_env: ApiEnv) -> None:
    """Обращён по 002/AC-13 (FR-9): чужую задачу удаляет БА-участник не владелец; «Пользователь»
    (участник, не автор) и не участник ba3 - 403. Прежняя проверка СМ-участника ``sm_m`` на второй
    задаче дублировала проверку ``ba2`` (``sm_m`` -> ``ba2``, AC-13) и снята."""
    env = api_env
    w = await make_api_world(env)
    foreign = await mk(env, w, by="usr", assignee="usr")

    assert error(await _op(env, w, "ba3", "delete", foreign)) == (403, "forbidden")
    assert (await task_db(env, foreign)).deleted_at is None
    assert (await _op(env, w, "ba2", "delete", foreign)).status_code == 204
    assert (await task_db(env, foreign)).deleted_at is not None


async def test_ac99_assignee_cannot_delete_task_assigned_by_other(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr")

    assert error(await _op(env, w, "usr", "delete", t)) == (403, "forbidden")
    assert (await task_db(env, t)).deleted_at is None


async def test_subtask_card_permissions_follow_the_same_rules(api_env: ApiEnv) -> None:
    """Подзадача: права по её автору и исполнителю; ``create_subtask`` всегда false."""
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    sub = await mk(env, w, by="usr", assignee="usr", parent=parent)

    own = (await send(env, w.tok("usr"), "GET", task_url(sub))).json()["permissions"]
    owner = (await send(env, w.tok("ba"), "GET", task_url(sub))).json()["permissions"]
    other = (await send(env, w.tok("ba2"), "GET", task_url(sub))).json()["permissions"]

    assert own == {
        "edit": True,
        "change_status": True,
        "change_assignee": False,
        "delete": True,
        "create_subtask": False,
    }
    assert owner == {
        "edit": True,
        "change_status": True,
        "change_assignee": True,
        "delete": True,
        "create_subtask": False,
    }
    assert other == {  # 002/AC-13: БА-участник не владелец; подзадач у подзадачи нет
        "edit": True,
        "change_status": True,
        "change_assignee": True,
        "delete": True,
        "create_subtask": False,
    }


async def test_user_assignee_changes_status_of_assigned_subtask_but_not_title(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    sub = await mk(env, w, assignee="usr", parent=parent, title="П")

    ok = await send(env, w.tok("usr"), "PATCH", task_url(sub), {"status": "done"})
    denied = await send(env, w.tok("usr"), "PATCH", task_url(sub), {"title": "Другое"})

    assert ok.status_code == 200, ok.text
    assert (ok.json()["status"], ok.json()["position"]) == ("done", None)
    assert error(denied) == (403, "forbidden")
