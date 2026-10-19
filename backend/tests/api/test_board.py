"""T78: ``GET /api/v1/projects/{id}/board`` (AC-25, AC-80, AC-18, AC-21, FR-28, FR-47, D-61).

Четыре колонки в порядке FR-18a (пустые тоже), карточки — неудалённые задачи верхнего уровня,
``ORDER BY position, created_at, id``; без пагинации; ``subtask_count``/``progress`` по неудалённым
подзадачам. Порядок проверок: 404 (проект) -> 403 (не участник).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    ALL_STATUSES,
    USER_REF_FIELDS,
    error,
    make_api_world,
    make_foreign,
    mk,
    pj,
    send,
)

CARD_FIELDS = {
    "id",
    "title",
    "status",
    "priority",
    "due_date",
    "assignee",
    "position",
    "subtask_count",
    "progress",
}


def _board_url(project_id: uuid.UUID | str) -> str:
    return f"{pj(project_id)}/board"


async def _board(env: ApiEnv, token: str, project_id: uuid.UUID | str) -> dict[str, Any]:
    r = await send(env, token, "GET", _board_url(project_id))
    assert r.status_code == 200, r.text
    result: dict[str, Any] = r.json()
    return result


def _col(board: dict[str, Any], status: str) -> list[dict[str, Any]]:
    (col,) = [c for c in board["columns"] if c["status"] == status]
    tasks: list[dict[str, Any]] = col["tasks"]
    return tasks


async def test_ac25_empty_project_has_four_empty_columns_in_fr18a_order(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    body = await _board(env, w.tok("ba"), w.project_id)

    assert set(body) == {"project", "columns"}
    assert body["project"] == {"id": str(w.project_id), "name": w.project_name}
    assert [c["status"] for c in body["columns"]] == list(ALL_STATUSES)
    assert all(set(c) == {"status", "tasks"} for c in body["columns"])
    assert [c["tasks"] for c in body["columns"]] == [[], [], [], []]


async def test_ac25_cards_are_grouped_by_status_with_full_shape(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t_todo = await mk(env, w, title="A", status="todo", position=1024)
    t_prog = await mk(
        env,
        w,
        title="B",
        status="in_progress",
        position=2048,
        assignee="usr",
        priority="high",
        due_date=date(2030, 1, 2),
    )
    t_done = await mk(env, w, title="C", status="done", position=1024)

    body = await _board(env, w.tok("usr"), w.project_id)

    assert [c["status"] for c in body["columns"]] == list(ALL_STATUSES)
    assert [c["id"] for c in _col(body, "todo")] == [str(t_todo)]
    assert [c["id"] for c in _col(body, "done")] == [str(t_done)]
    assert _col(body, "review") == []
    (card,) = _col(body, "in_progress")
    assert set(card) == CARD_FIELDS
    assert card["id"] == str(t_prog)
    assert card["title"] == "B"
    assert card["status"] == "in_progress"
    assert card["priority"] == "high"
    assert card["due_date"] == "2030-01-02"
    assert card["position"] == 2048
    assert set(card["assignee"]) == USER_REF_FIELDS
    assert card["assignee"]["id"] == str(w.uid("usr"))
    assert card["subtask_count"] == 0
    assert card["progress"] is None
    assert _col(body, "todo")[0]["assignee"] is None


async def test_fr28a_cards_ordered_by_position_then_created_at_then_id(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    c = await mk(env, w, title="c", position=3000)
    a = await mk(env, w, title="a", position=1000)
    b = await mk(env, w, title="b", position=2000)

    body = await _board(env, w.tok("ba"), w.project_id)

    assert [x["id"] for x in _col(body, "todo")] == [str(a), str(b), str(c)]
    assert [x["position"] for x in _col(body, "todo")] == [1000, 2000, 3000]


async def test_ac80_board_has_one_card_for_task_with_two_subtasks_and_progress(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="Родитель")
    await mk(env, w, parent=parent, status="done")
    await mk(env, w, parent=parent, status="todo")
    await mk(env, w, parent=parent, status="done", deleted=True)  # не считается

    body = await _board(env, w.tok("ba"), w.project_id)

    cards = [c for col in body["columns"] for c in col["tasks"]]
    assert [c["id"] for c in cards] == [str(parent)]
    assert cards[0]["subtask_count"] == 2
    assert cards[0]["progress"] == 50
    # подзадача в колонке «done» не создаёт отдельной карточки
    assert _col(body, "done") == []


async def test_ac80_progress_all_done_is_100_and_only_live_subtasks_counted(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    await mk(env, w, parent=parent, status="done")
    await mk(env, w, parent=parent, status="todo", deleted=True)

    (card,) = _col(await _board(env, w.tok("ba"), w.project_id), "todo")

    assert (card["subtask_count"], card["progress"]) == (1, 100)


async def test_ac18_deleted_tasks_are_not_on_board(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    live = await mk(env, w, title="жива")
    gone = await mk(env, w, title="удалена")
    assert (await send(env, w.tok("ba"), "DELETE", f"/api/v1/tasks/{gone}")).status_code == 204

    body = await _board(env, w.tok("ba"), w.project_id)

    ids = [c["id"] for col in body["columns"] for c in col["tasks"]]
    assert ids == [str(live)]


async def test_fr47_board_is_not_paginated_150_cards(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for i in range(150):
        await mk(env, w, title=f"t{i}", position=1024 * (i + 1))

    body = await _board(env, w.tok("ba"), w.project_id)

    assert set(body) == {"project", "columns"}
    assert len(_col(body, "todo")) == 150
    assert [c["position"] for c in _col(body, "todo")] == sorted(
        c["position"] for c in _col(body, "todo")
    )


async def test_board_shows_only_own_project_tasks(api_env: ApiEnv) -> None:
    from tests.tasks_api_support import add_project

    env = api_env
    w = await make_api_world(env)
    other = await add_project(env, w.ws, w.people["ba"].user, name="Другой", members=[])
    mine = await mk(env, w, title="моя")
    await mk(env, w, title="чужая", project_id=other)

    body = await _board(env, w.tok("ba"), w.project_id)

    assert [c["id"] for c in _col(body, "todo")] == [str(mine)]


async def test_member_roles_can_read_board(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    await mk(env, w)
    for who in ("ba", "ba2", "usr"):
        body = await _board(env, w.tok(who), w.project_id)
        assert len(_col(body, "todo")) == 1, who


async def test_board_non_member_is_403_for_ba_user(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for who in ("ba3", "usr2"):
        r = await send(env, w.tok(who), "GET", _board_url(w.project_id))
        assert error(r) == (403, "forbidden"), who
        assert "Retry-After" not in r.headers


async def test_board_tech_admin_and_no_role_are_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for who in ("ta", "norole"):
        r = await send(env, w.tok(who), "GET", _board_url(w.project_id))
        assert r.status_code == 403, who


async def test_board_unauthenticated_is_401(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, None, "GET", _board_url(w.project_id))
    assert r.status_code == 401


async def test_board_unknown_and_deleted_project_is_404_even_for_non_member(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("ba"), "GET", _board_url(uuid.uuid4()))
    assert error(r) == (404, "not_found")
    assert (await send(env, w.tok("ba"), "DELETE", pj(w.project_id))).status_code == 204
    for who in ("ba", "usr", "ba3"):
        r = await send(env, w.tok(who), "GET", _board_url(w.project_id))
        assert error(r) == (404, "not_found"), who
        assert "Retry-After" not in r.headers


async def test_ac21_foreign_workspace_project_board_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    f = await make_foreign(env)
    await mk(env, w)

    r = await send(env, w.tok("ba"), "GET", _board_url(f.project_id))
    assert error(r) == (404, "not_found")
    r = await send(env, f.ba_token, "GET", _board_url(w.project_id))
    assert error(r) == (404, "not_found")


async def test_board_invalid_uuid_is_422(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("ba"), "GET", "/api/v1/projects/not-a-uuid/board")
    assert r.status_code == 422
