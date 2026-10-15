"""T77: ``DELETE /api/v1/tasks/{id}`` — мягкое удаление с каскадом (AC-18, AC-99, AC-7, D-56).

204 без тела; запись сохраняется с ``deleted_at``; далее 404 на любой операции; подзадачи и
комментарии удаляются пакетом с одним ``deleted_batch_id``; ранее удалённые не затрагиваются.
"""

from __future__ import annotations

from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    comment_rows,
    error,
    make_api_world,
    mk,
    send,
    task_db,
    task_url,
)


async def test_ac99_user_deletes_own_task_204_then_404_everywhere(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    created = await send(
        env, w.tok("usr"), "POST", f"/api/v1/projects/{w.project_id}/tasks", {"title": "Своя"}
    )
    t = created.json()["id"]

    r = await send(env, w.tok("usr"), "DELETE", task_url(t))

    assert r.status_code == 204
    assert r.content == b""
    row = await task_db(env, t)
    assert row.deleted_at is not None and row.deleted_batch_id is not None  # AC-18: запись есть
    for who in ("usr", "ba", "sm_m"):
        for method, url, body in (
            ("GET", task_url(t), None),
            ("PATCH", task_url(t), {"title": "x"}),
            ("DELETE", task_url(t), None),
            ("POST", f"{task_url(t)}/subtasks", {"title": "x"}),
        ):
            got = await send(env, w.tok(who), method, url, body)
            assert error(got) == (404, "not_found"), (who, method)


async def test_ac18_deleted_task_is_not_in_lists_and_counters(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr")
    keep = await mk(env, w, assignee="usr")

    assert (await send(env, w.tok("ba"), "DELETE", task_url(t))).status_code == 204

    project_list = await send(env, w.tok("ba"), "GET", f"/api/v1/projects/{w.project_id}/tasks")
    mine = await send(env, w.tok("usr"), "GET", "/api/v1/me/tasks")
    card = await send(env, w.tok("ba"), "GET", f"/api/v1/projects/{w.project_id}")
    assert [i["id"] for i in project_list.json()["items"]] == [str(keep)]
    assert [i["id"] for i in mine.json()["items"]] == [str(keep)]
    assert card.json()["task_count"] == 1


async def test_ac99_parent_delete_cascades_to_subtasks_and_comments_one_batch(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, comment=True)
    sub = await mk(env, w, parent=parent, comment=True)
    other = await mk(env, w, comment=True)

    r = await send(env, w.tok("ba"), "DELETE", task_url(parent))

    assert r.status_code == 204
    p, s, o = await task_db(env, parent), await task_db(env, sub), await task_db(env, other)
    assert p.deleted_at is not None and s.deleted_at is not None
    assert s.deleted_batch_id == p.deleted_batch_id
    assert o.deleted_at is None
    for task_id in (parent, sub):
        comments = await comment_rows(env, task_id)
        assert len(comments) == 1
        assert comments[0].deleted_at is not None
        assert comments[0].deleted_batch_id == p.deleted_batch_id
    assert (await comment_rows(env, other))[0].deleted_at is None
    assert error(await send(env, w.tok("ba"), "GET", task_url(sub))) == (404, "not_found")
    listed = await send(env, w.tok("ba"), "GET", f"/api/v1/projects/{w.project_id}/tasks")
    assert [i["id"] for i in listed.json()["items"]] == [str(other)]


async def test_d56_earlier_deleted_subtask_keeps_its_own_batch(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    early = await mk(env, w, parent=parent)
    live = await mk(env, w, parent=parent)
    assert (await send(env, w.tok("ba"), "DELETE", task_url(early))).status_code == 204
    early_row = await task_db(env, early)

    assert (await send(env, w.tok("ba"), "DELETE", task_url(parent))).status_code == 204

    after = await task_db(env, early)
    assert (after.deleted_at, after.deleted_batch_id) == (
        early_row.deleted_at,
        early_row.deleted_batch_id,
    )
    assert (await task_db(env, live)).deleted_batch_id == (
        await task_db(env, parent)
    ).deleted_batch_id
    assert after.deleted_batch_id != (await task_db(env, parent)).deleted_batch_id


async def test_ac7_deleting_subtask_leaves_parent_and_recomputes_progress(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    done = await mk(env, w, parent=parent, status="done")
    todo = await mk(env, w, parent=parent)
    assert (await send(env, w.tok("ba"), "GET", task_url(parent))).json()["progress"] == 50

    assert (await send(env, w.tok("ba"), "DELETE", task_url(todo))).status_code == 204

    card = (await send(env, w.tok("ba"), "GET", task_url(parent))).json()
    assert card["progress"] == 100
    assert [s["id"] for s in card["subtasks"]] == [str(done)]
    assert (await task_db(env, parent)).deleted_at is None


async def test_delete_twice_is_404_and_data_untouched(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    assert (await send(env, w.tok("ba"), "DELETE", task_url(t))).status_code == 204
    stamp = await task_db(env, t)

    again = await send(env, w.tok("ba"), "DELETE", task_url(t))

    assert error(again) == (404, "not_found")
    assert (await task_db(env, t)).deleted_at == stamp.deleted_at


async def test_ac99_forbidden_delete_changes_nothing(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", comment=True)
    sub = await mk(env, w, parent=t)

    for who in ("usr", "ba2"):
        assert error(await send(env, w.tok(who), "DELETE", task_url(t))) == (403, "forbidden")

    assert (await task_db(env, t)).deleted_at is None
    assert (await task_db(env, sub)).deleted_at is None
    assert (await comment_rows(env, t))[0].deleted_at is None
