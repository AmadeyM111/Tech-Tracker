"""T77: ``GET /api/v1/projects/{id}/tasks`` (AC-18, AC-22, AC-43, AC-80, FR-26, FR-27, FR-47).

Подзадачи включены; фильтры ``assignee_id`` и ``status`` — через «И»; порядок
``created_at DESC, id DESC``; ``Page[TaskListItem]`` (по умолчанию 50, максимум 100) без описания.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    LIST_FIELDS,
    PAGE_FIELDS,
    add_project,
    error,
    make_api_world,
    make_foreign,
    mk,
    pj,
    project_tasks_url,
    send,
    task_url,
)

BASE = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


async def _list(env: ApiEnv, w: Any, who: str, query: str = "", project: Any = None) -> Any:
    return await send(env, w.tok(who), "GET", project_tasks_url(project or w.project_id, query))


async def test_ac22_51_tasks_first_page_has_50_and_next(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for i in range(51):
        await mk(env, w, title=f"З{i}", created_at=BASE + timedelta(minutes=i))

    p1 = (await _list(env, w, "ba")).json()
    p2 = (await _list(env, w, "ba", "?page=2")).json()
    big = (await _list(env, w, "ba", "?page_size=100")).json()

    assert set(p1) == PAGE_FIELDS
    assert (len(p1["items"]), p1["has_next"], p1["page"], p1["page_size"]) == (50, True, 1, 50)
    assert (len(p2["items"]), p2["has_next"]) == (1, False)
    assert p2["items"][0]["title"] == "З0"  # самая старая — последняя
    assert (len(big["items"]), big["has_next"]) == (51, False)
    ids = [i["id"] for i in p1["items"]] + [i["id"] for i in p2["items"]]
    assert len(set(ids)) == 51


async def test_order_created_at_desc_then_id_desc(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    old = await mk(env, w, created_at=BASE)
    new = await mk(env, w, created_at=BASE + timedelta(days=1))
    tie = [await mk(env, w, created_at=BASE + timedelta(hours=1)) for _ in range(3)]

    r = await _list(env, w, "ba")

    ids = [i["id"] for i in r.json()["items"]]
    assert ids[0] == str(new)
    assert ids[1:4] == sorted((str(x) for x in tie), reverse=True)
    assert ids[4] == str(old)


async def test_item_shape_no_description_and_names(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    await mk(env, w, assignee="usr", title="Т", description="Скрытое-описание", priority="high")

    r = await _list(env, w, "usr")

    item = r.json()["items"][0]
    assert set(item) == LIST_FIELDS
    assert "Скрытое-описание" not in r.text
    assert item["project"] == {"id": str(w.project_id), "name": "Основной"}
    assert item["assignee"]["login"] == w.login("usr")
    assert item["priority"] == "high"


async def test_ac22_filters_by_assignee_and_status_are_anded(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    a_todo = await mk(env, w, assignee="usr", status="todo")
    a_done = await mk(env, w, assignee="usr", status="done")
    b_done = await mk(env, w, assignee="ba2", status="done")
    nobody = await mk(env, w, status="done")

    by_assignee = await _list(env, w, "ba", f"?assignee_id={w.uid('usr')}")
    by_status = await _list(env, w, "ba", "?status=done")
    both = await _list(env, w, "ba", f"?assignee_id={w.uid('usr')}&status=done")
    none = await _list(env, w, "ba", f"?assignee_id={w.uid('ba2')}&status=todo")

    assert {i["id"] for i in by_assignee.json()["items"]} == {str(a_todo), str(a_done)}
    assert {i["id"] for i in by_status.json()["items"]} == {str(a_done), str(b_done), str(nobody)}
    assert [i["id"] for i in both.json()["items"]] == [str(a_done)]
    assert none.json()["items"] == []


@pytest.mark.parametrize("status", ["todo", "in_progress", "review", "done"])
async def test_status_filter_accepts_every_status(api_env: ApiEnv, status: str) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, status=status)
    await mk(env, w, status="todo" if status != "todo" else "done")

    r = await _list(env, w, "ba", f"?status={status}")

    assert [i["id"] for i in r.json()["items"]] == [str(t)]


@pytest.mark.parametrize(
    "query",
    [
        "?status=archived",
        "?status=",
        "?status=DONE",
        "?assignee_id=not-a-uuid",
        "?assignee_id=5",
        "?page=0",
        "?page=x",
        "?page_size=0",
        "?page_size=101",
    ],
)
async def test_invalid_query_is_422(api_env: ApiEnv, query: str) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _list(env, w, "ba", query)

    assert error(r) == (422, "validation_error")


async def test_ac80_list_contains_subtasks_and_project_task_count_counts_top_level_only(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    s1 = await mk(env, w, parent=parent, assignee="usr")
    s2 = await mk(env, w, parent=parent)

    r = await _list(env, w, "ba")

    items = {i["id"]: i for i in r.json()["items"]}
    assert set(items) == {str(parent), str(s1), str(s2)}
    assert items[str(s1)]["parent_id"] == str(parent)
    assert items[str(parent)]["parent_id"] is None
    card = await send(env, w.tok("ba"), "GET", pj(w.project_id))
    assert card.json()["task_count"] == 1
    listed = await send(env, w.tok("ba"), "GET", "/api/v1/projects")
    assert [p["task_count"] for p in listed.json()["items"]] == [1]


async def test_ac18_deleted_tasks_and_subtasks_are_not_listed_or_counted(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    keep = await mk(env, w)
    gone = await mk(env, w)
    sub = await mk(env, w, parent=gone)
    await mk(env, w, deleted=True)
    assert (await send(env, w.tok("ba"), "DELETE", task_url(gone))).status_code == 204

    r = await _list(env, w, "ba")

    assert [i["id"] for i in r.json()["items"]] == [str(keep)]
    assert str(sub) not in r.text
    card = await send(env, w.tok("ba"), "GET", pj(w.project_id))
    assert card.json()["task_count"] == 1


async def test_list_has_only_tasks_of_this_project(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    other = await add_project(
        env, w.ws, w.people["ba"].user, name="Второй", members=["usr"], people=w.people
    )
    mine = await mk(env, w)
    await mk(env, w, project_id=other)

    r = await _list(env, w, "usr")

    assert [i["id"] for i in r.json()["items"]] == [str(mine)]


@pytest.mark.parametrize("who", ["ba", "ba2", "sm_m", "usr"])
async def test_members_see_all_tasks_not_only_own(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    ids = {str(await mk(env, w, assignee=a)) for a in ("usr", "ba2", None)}

    r = await _list(env, w, who)

    assert r.status_code == 200, r.text
    assert {i["id"] for i in r.json()["items"]} == ids


@pytest.mark.parametrize("who", ["usr2", "ba3", "sm"])
async def test_non_member_gets_403_for_list(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    await mk(env, w, title="Секрет-задача")

    r = await _list(env, w, who)

    assert error(r) == (403, "forbidden")
    assert "Секрет-задача" not in r.text


async def test_unknown_deleted_and_foreign_project_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    dead = await add_project(env, w.ws, w.people["ba"].user, name="Удалён", deleted=True)
    foreign = (await make_foreign(env)).project_id
    assert (await _list(env, w, "ba")).status_code == 200  # маршрут существует

    for project in (uuid.uuid4(), dead, foreign):
        for who in ("ba", "usr", "usr2"):
            r = await _list(env, w, who, project=project)
            assert error(r) == (404, "not_found"), (who, project)


async def test_invalid_project_uuid_is_422_and_ta_is_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    bad = await send(env, w.tok("ba"), "GET", "/api/v1/projects/not-a-uuid/tasks")
    ta = await _list(env, w, "ta")

    assert error(bad) == (422, "validation_error")
    assert error(ta) == (403, "forbidden")
