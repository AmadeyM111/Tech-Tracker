"""T78: ``POST /api/v1/tasks/{id}/move`` (AC-61, AC-21, FR-19b, FR-28a, D-61, plan §11.4).

Тело ``{status, before_task_id?, after_task_id?}`` -> 204. ``after`` — сосед сверху, ``before`` —
снизу. Порядок проверок: 422 схемы -> 404 -> 403 -> 422 домена. 503 ``service_busy`` с
``Retry-After: 5``; у 403/404/422 заголовка нет (ревью T77 п.1).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    busy_database,
    error,
    hold_row,
    make_api_world,
    make_foreign,
    mk,
    rows,
    send,
    task_db,
    task_url,
)


def _move(task_id: Any) -> str:
    return f"{task_url(task_id)}/move"


async def _column(env: ApiEnv, project_id: uuid.UUID, status: str) -> list[uuid.UUID]:
    found = await rows(
        env,
        "SELECT id FROM task WHERE project_id = :p AND status = :s AND deleted_at IS NULL "
        "AND parent_id IS NULL ORDER BY position, created_at, id",
        p=project_id,
        s=status,
    )
    return [r[0] for r in found]


async def _board_ids(env: ApiEnv, token: str, project_id: Any, status: str) -> list[str]:
    r = await send(env, token, "GET", f"/api/v1/projects/{project_id}/board")
    assert r.status_code == 200, r.text
    (col,) = [c for c in r.json()["columns"] if c["status"] == status]
    return [c["id"] for c in col["tasks"]]


async def _column3(env: ApiEnv, w: Any, status: str = "todo") -> list[uuid.UUID]:
    return [
        await mk(env, w, title=n, status=status, position=p)
        for n, p in (("a", 1000), ("b", 2000), ("c", 3000))
    ]


async def test_ac61_move_between_neighbours_second_user_sees_same_order(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    a, b, c = await _column3(env, w)
    d = await mk(env, w, title="d", status="in_progress", position=1000)

    r = await send(
        env,
        w.tok("ba"),
        "POST",
        _move(d),
        {"status": "todo", "after_task_id": str(a), "before_task_id": str(b)},
    )

    assert r.status_code == 204, r.text
    assert r.content == b""
    expected = [str(x) for x in (a, d, b, c)]
    assert await _board_ids(env, w.tok("ba"), w.project_id, "todo") == expected
    assert await _board_ids(env, w.tok("usr"), w.project_id, "todo") == expected
    assert await _board_ids(env, w.tok("ba"), w.project_id, "in_progress") == []
    row = await task_db(env, d)
    assert row.status == "todo"
    assert row.position is not None


async def test_move_without_neighbours_goes_to_end_of_target_column(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    a, b, c = await _column3(env, w, "review")
    d = await mk(env, w, title="d", status="todo", position=500)

    r = await send(env, w.tok("ba"), "POST", _move(d), {"status": "review"})

    assert r.status_code == 204, r.text
    assert await _column(env, w.project_id, "review") == [a, b, c, d]


async def test_move_with_only_after_inserts_right_below_it(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    a, b, c = await _column3(env, w)
    d = await mk(env, w, title="d", status="done", position=100)

    r = await send(env, w.tok("ba"), "POST", _move(d), {"status": "todo", "after_task_id": str(b)})

    assert r.status_code == 204, r.text
    assert await _column(env, w.project_id, "todo") == [a, b, d, c]


async def test_move_with_only_before_inserts_right_above_it(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    a, b, c = await _column3(env, w)
    d = await mk(env, w, title="d", status="done", position=100)

    r = await send(env, w.tok("ba"), "POST", _move(d), {"status": "todo", "before_task_id": str(a)})

    assert r.status_code == 204, r.text
    assert await _column(env, w.project_id, "todo") == [d, a, b, c]


async def test_move_within_same_column_reorders(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    a, b, c = await _column3(env, w)

    r = await send(env, w.tok("ba"), "POST", _move(a), {"status": "todo", "after_task_id": str(c)})

    assert r.status_code == 204, r.text
    assert await _column(env, w.project_id, "todo") == [b, c, a]


async def test_move_positions_stay_unique_after_many_inserts_between_same_neighbours(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    a = await mk(env, w, title="a", position=1000)
    z = await mk(env, w, title="z", position=1001)  # щель исчерпана -> перенумерация
    movers = [await mk(env, w, title=f"m{i}", status="done", position=10 * i) for i in range(5)]

    for m in movers:
        r = await send(
            env,
            w.tok("ba"),
            "POST",
            _move(m),
            {"status": "todo", "after_task_id": str(a), "before_task_id": str(z)},
        )
        assert r.status_code == 204, r.text

    col = await _column(env, w.project_id, "todo")
    assert col[0] == a and col[-1] == z and len(col) == 7
    found = await rows(
        env,
        "SELECT position FROM task WHERE project_id = :p AND status = 'todo' "
        "AND deleted_at IS NULL",
        p=w.project_id,
    )
    positions = [r[0] for r in found]
    assert len(set(positions)) == len(positions)


async def test_fr19b_assignee_moves_own_foreign_task(api_env: ApiEnv) -> None:
    """Исполнитель («Пользователь», не автор) переносит свою задачу (FR-19b)."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, by="ba", assignee="usr", status="todo", position=1000)
    other = await mk(env, w, by="ba", status="in_progress", position=1000)

    r = await send(env, w.tok("usr"), "POST", _move(t), {"status": "in_progress"})

    assert r.status_code == 204, r.text
    assert await _column(env, w.project_id, "in_progress") == [other, t]


async def test_fr19b_ba_member_non_owner_moves_own_assigned_task_only(api_env: ApiEnv) -> None:
    """Обращён по 002/AC-13 (FR-9): БА-участник не владелец переносит и свою, и чужую задачу."""
    env = api_env
    w = await make_api_world(env)
    mine = await mk(env, w, by="ba", assignee="ba2", position=1000)
    foreign = await mk(env, w, by="ba", assignee="usr", position=2000)

    ok = await send(env, w.tok("ba2"), "POST", _move(mine), {"status": "done"})
    denied = await send(env, w.tok("ba2"), "POST", _move(foreign), {"status": "done"})

    assert ok.status_code == 204, ok.text
    assert denied.status_code == 204, denied.text
    assert (await task_db(env, mine)).status == "done"
    assert (await task_db(env, foreign)).status == "done"


async def test_move_forbidden_for_user_on_task_of_another_assignee(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, by="ba", assignee="ba2", position=1000)

    r = await send(env, w.tok("usr"), "POST", _move(t), {"status": "done"})

    assert error(r) == (403, "forbidden")
    assert "Retry-After" not in r.headers
    assert (await task_db(env, t)).status == "todo"


async def test_move_allowed_for_owner_and_mixed_member_on_any_task(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, by="ba", assignee="usr", position=1000)

    r1 = await send(env, w.tok("ba"), "POST", _move(t), {"status": "review"})
    r2 = await send(env, w.tok("sm_m"), "POST", _move(t), {"status": "done"})

    assert (r1.status_code, r2.status_code) == (204, 204)
    assert (await task_db(env, t)).status == "done"


async def test_move_non_member_is_403_and_task_unchanged(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", position=1000)

    for who in ("ba3", "sm", "usr2"):
        r = await send(env, w.tok(who), "POST", _move(t), {"status": "done"})
        assert error(r) == (403, "forbidden"), who
        assert "Retry-After" not in r.headers
    row = await task_db(env, t)
    assert (row.status, row.position) == ("todo", 1000)


async def test_move_tech_admin_and_no_role_are_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, position=1000)
    for who in ("ta", "norole"):
        r = await send(env, w.tok(who), "POST", _move(t), {"status": "done"})
        assert r.status_code == 403, who


async def test_move_unauthenticated_is_401(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, position=1000)
    assert (await send(env, None, "POST", _move(t), {"status": "done"})).status_code == 401


async def test_move_unknown_deleted_and_deleted_project_task_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    gone = await mk(env, w, deleted=True, position=1000)
    live_in_deleted_project = await mk(env, w, position=2000)

    cases = [uuid.uuid4(), gone]
    for tid in cases:
        r = await send(env, w.tok("ba"), "POST", _move(tid), {"status": "done"})
        assert error(r) == (404, "not_found"), tid
        assert "Retry-After" not in r.headers
    assert (
        await send(env, w.tok("ba"), "DELETE", f"/api/v1/projects/{w.project_id}")
    ).status_code == 204
    r = await send(env, w.tok("ba"), "POST", _move(live_in_deleted_project), {"status": "done"})
    assert error(r) == (404, "not_found")


async def test_ac21_move_foreign_workspace_task_is_404(api_env: ApiEnv) -> None:
    from tests.factories import make_task

    env = api_env
    w = await make_api_world(env)
    f = await make_foreign(env)
    async with env.sessionmaker() as s:
        row = await make_task(
            s,
            project_id=f.project_id,
            workspace_id=f.ws.id,
            created_by=f.ba.id,
            position=1000,
        )
        await s.commit()

    r = await send(env, w.tok("ba"), "POST", _move(row.id), {"status": "done"})

    assert error(r) == (404, "not_found")
    assert (await task_db(env, row.id)).status == "todo"


async def test_move_subtask_is_422_validation_error_for_member(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, position=1000)
    sub = await mk(env, w, parent=parent)

    r = await send(env, w.tok("ba"), "POST", _move(sub), {"status": "done"})

    assert error(r) == (422, "validation_error")
    assert "Retry-After" not in r.headers
    row = await task_db(env, sub)
    assert (row.status, row.position) == ("todo", None)


async def test_move_subtask_by_non_member_is_403_not_422(api_env: ApiEnv) -> None:
    """Порядок: 403 раньше доменного 422 (подзадача)."""
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, position=1000)
    sub = await mk(env, w, parent=parent)

    r = await send(env, w.tok("usr2"), "POST", _move(sub), {"status": "done"})

    assert error(r) == (403, "forbidden")


async def test_move_invalid_neighbours_is_422_invalid_neighbors(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    a, b, c = await _column3(env, w)
    d = await mk(env, w, title="d", status="done", position=100)
    in_other_column = await mk(env, w, status="review", position=1000)
    sub = await mk(env, w, parent=a)
    from tests.tasks_api_support import add_project

    other_project = await add_project(env, w.ws, w.people["ba"].user, name="П2")
    foreign_project_task = await mk(env, w, project_id=other_project, position=1000)
    deleted = await mk(env, w, deleted=True, position=1500)

    bad_bodies: list[dict[str, Any]] = [
        {"status": "todo", "after_task_id": str(d)},  # сама задача
        {"status": "todo", "after_task_id": str(in_other_column)},
        {"status": "todo", "before_task_id": str(uuid.uuid4())},
        {"status": "todo", "after_task_id": str(sub)},
        {"status": "todo", "after_task_id": str(foreign_project_task)},
        {"status": "todo", "after_task_id": str(deleted)},
        {"status": "todo", "after_task_id": str(a), "before_task_id": str(a)},
    ]
    for body in bad_bodies:
        r = await send(env, w.tok("ba"), "POST", _move(d), body)
        assert error(r) == (422, "invalid_neighbors"), body
        assert "Retry-After" not in r.headers
    row = await task_db(env, d)
    assert (row.status, row.position) == ("done", 100)
    assert await _column(env, w.project_id, "todo") == [a, b, c]


async def test_move_schema_422_checked_before_404_and_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, position=1000)
    bad = [
        {"status": "archived"},
        {},
        {"status": None},
        {"status": "done", "after_task_id": "not-a-uuid"},
        {"status": "done", "before_task_id": 5},
    ]
    for who, tid in (("ba", t), ("usr2", t), ("ba", uuid.uuid4())):
        for body in bad:
            r = await send(env, w.tok(who), "POST", _move(tid), body)
            assert error(r) == (422, "validation_error"), (who, body)
            assert "Retry-After" not in r.headers
    r = await send(env, w.tok("ba"), "POST", _move("not-a-uuid"), {"status": "done"})
    assert r.status_code == 422
    assert (await task_db(env, t)).status == "todo"


async def test_move_404_before_403_before_domain_422(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, position=1000)
    body = {"status": "done", "after_task_id": str(uuid.uuid4())}  # соседа нет -> доменный 422

    nf = await send(env, w.tok("usr2"), "POST", _move(uuid.uuid4()), body)
    fb = await send(env, w.tok("usr2"), "POST", _move(t), body)
    dm = await send(env, w.tok("ba"), "POST", _move(t), body)

    assert error(nf) == (404, "not_found")
    assert error(fb) == (403, "forbidden")
    assert error(dm) == (422, "invalid_neighbors")


async def test_move_status_to_same_column_without_neighbours_keeps_task_in_column(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    a, b, c = await _column3(env, w)

    r = await send(env, w.tok("ba"), "POST", _move(a), {"status": "todo"})

    assert r.status_code == 204, r.text
    assert sorted(await _column(env, w.project_id, "todo")) == sorted([a, b, c])
    assert (await _column(env, w.project_id, "todo"))[-1] == a  # без соседей -> в конец


# --- 503 --------------------------------------------------------------------------------------


async def test_move_busy_project_row_gives_503_with_retry_after(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    w = await make_api_world(env)
    t = await mk(env, w, position=1000)

    async with busy_database(env), hold_row(env, "project", w.project_id):
        r = await send(env, w.tok("ba"), "POST", _move(t), {"status": "done"})
        assert r.status_code == 503, r.text
        assert r.headers.get("retry-after") == "5"
        assert r.json()["code"] == "service_busy"

    row = await task_db(env, t)
    assert (row.status, row.position) == ("todo", 1000)
    ok = await send(env, w.tok("ba"), "POST", _move(t), {"status": "done"})
    assert ok.status_code == 204, ok.text


# --- конкурентность ---------------------------------------------------------------------------


async def test_concurrent_moves_and_status_changes_no_500_and_unique_positions(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    w = await make_api_world(env)
    ids = [
        await mk(
            env, w, title=f"t{i}", status=("todo", "in_progress")[i % 2], position=1024 * (i + 1)
        )
        for i in range(12)
    ]
    sem = asyncio.Semaphore(12)
    statuses = ("todo", "in_progress", "review", "done")

    async def call(i: int) -> int:
        tid = ids[i % len(ids)]
        target = statuses[(i // 3) % 4]
        async with sem:
            if i % 4 == 3:
                r = await send(env, w.tok("ba"), "PATCH", task_url(tid), {"status": target})
            else:
                body: dict[str, Any] = {"status": target}
                if i % 4 == 1:
                    body["after_task_id"] = str(ids[(i + 5) % len(ids)])
                r = await send(env, w.tok("ba"), "POST", _move(tid), body)
        status_code: int = r.status_code
        return status_code

    codes = await asyncio.gather(*(call(i) for i in range(120)))

    assert len(codes) == 120
    assert all(c in {200, 204, 422, 503} for c in codes), sorted(set(codes))
    assert any(c in {200, 204} for c in codes)
    found = await rows(
        env,
        "SELECT status, position FROM task WHERE project_id = :p AND deleted_at IS NULL "
        "AND parent_id IS NULL",
        p=w.project_id,
    )
    keys = [(r[0], r[1]) for r in found]
    assert len(keys) == 12
    assert all(p is not None for _, p in keys)
    assert len(set(keys)) == len(keys)


async def test_move_non_adjacent_or_inverted_neighbours_after_has_priority(
    api_env: ApiEnv,
) -> None:
    """plan §4.8: если соседи не смежны или порядок обратный, приоритет у ``after`` -> 204."""
    env = api_env
    w = await make_api_world(env)
    a, b, c = await _column3(env, w)
    d = await mk(env, w, title="d", status="done", position=100)
    e = await mk(env, w, title="e", status="review", position=100)

    r1 = await send(
        env,
        w.tok("ba"),
        "POST",
        _move(d),
        {"status": "todo", "after_task_id": str(a), "before_task_id": str(c)},
    )
    r2 = await send(
        env,
        w.tok("ba"),
        "POST",
        _move(e),
        {"status": "todo", "after_task_id": str(c), "before_task_id": str(a)},
    )

    assert (r1.status_code, r2.status_code) == (204, 204), (r1.text, r2.text)
    assert await _column(env, w.project_id, "todo") == [a, d, b, c, e]
