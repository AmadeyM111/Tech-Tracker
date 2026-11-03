"""Лента проекта: ``GET /api/v1/projects/{id}/activity`` (plan §10.3, FR-38, FR-25b, ADR-0015).

AC-90: события проекта по действиям, названия и описания без значений, текст комментария не
попадает в ленту; не участник — 403; неизвестный проект — 404; ``ORDER BY id DESC``, страница.
"""

from __future__ import annotations

from typing import Any

from tests.conftest import ApiEnv
from tests.projects_api_support import (
    PAGE_FIELDS,
    make_api_world,
    pj,
    send,
)

ITEM_FIELDS = {"id", "occurred_at", "actor", "action", "entity", "changed_fields", "changes"}
SECRET_BODY = "секретный-текст-комментария"


def _feed_url(project_id: Any) -> str:
    return f"{pj(project_id)}/activity"


async def _create_task(env: ApiEnv, token: str, project_id: Any, assignee: Any) -> str:
    r = await send(
        env,
        token,
        "POST",
        f"{pj(project_id)}/tasks",
        {
            "title": "Исходное",
            "description": "Описание",
            "due_date": "2030-01-01",
            "assignee_id": str(assignee),
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_feed_lists_project_events_newest_first_without_secrets(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    ba, usr = w.tok("ba"), w.tok("usr")

    r = await send(env, ba, "PATCH", pj(w.project_id), {"name": "Новое имя"})
    assert r.status_code == 200, r.text
    tid = await _create_task(env, ba, w.project_id, w.uid("usr"))
    r = await send(env, ba, "PATCH", f"/api/v1/tasks/{tid}", {"title": "Новое", "status": "done"})
    assert r.status_code == 200, r.text
    r = await send(env, usr, "POST", f"/api/v1/tasks/{tid}/comments", {"body": SECRET_BODY})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = await send(env, usr, "DELETE", f"/api/v1/comments/{cid}")
    assert r.status_code == 204, r.text

    r = await send(env, usr, "GET", _feed_url(w.project_id))

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == PAGE_FIELDS
    items = body["items"]
    assert all(set(item) == ITEM_FIELDS for item in items)
    assert [item["action"] for item in items] == [
        "comment.deleted",
        "comment.created",
        "task.updated",
        "task.created",
        "project.updated",
    ]
    assert SECRET_BODY not in r.text  # текст комментария в ленту не попадает

    deleted_comment, _, updated, created, renamed = items
    assert deleted_comment["entity"] == {
        "type": "comment",
        "id": cid,
        "deleted": True,
        "title": None,
    }
    assert updated["changed_fields"] == ["status", "title"]
    assert updated["entity"]["title"] == "Новое"  # текущее название задачи
    assert updated["changes"] == [{"field": "status", "old": "todo", "new": "done"}]
    assert created["actor"]["kind"] == "user"
    assert created["actor"]["id"] == str(w.uid("ba"))
    assert renamed["changed_fields"] == ["name"]
    assert renamed["changes"] is None
    assert renamed["entity"]["title"] == "Новое имя"


async def test_feed_forbidden_for_non_member_and_unknown_project(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    # БА, не участник, и «Пользователь», не участник: содержимое проекта — 403 (D-45)
    for who in ("ba3", "usr2"):
        r = await send(env, w.tok(who), "GET", _feed_url(w.project_id))
        assert r.status_code == 403, (who, r.text)
    # без входа — 401
    r = await send(env, None, "GET", _feed_url(w.project_id))
    assert r.status_code == 401, r.text
    # неизвестный проект — 404
    r = await send(env, w.tok("usr"), "GET", _feed_url("00000000-0000-0000-0000-000000000001"))
    assert r.status_code == 404, r.text


async def test_feed_shows_removed_member_and_unassigned_tasks(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    ba = w.tok("ba")
    tid = await _create_task(env, ba, w.project_id, w.uid("usr"))

    r = await send(env, ba, "DELETE", f"{pj(w.project_id)}/members/{w.uid('usr')}")
    assert r.status_code == 204, r.text

    r = await send(env, ba, "GET", _feed_url(w.project_id))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [item["action"] for item in items] == [
        "member.removed",
        "task.unassigned_member_removed",
        "task.created",
    ]
    unassigned = items[1]
    assert unassigned["entity"]["id"] == tid
    assert unassigned["changes"] == [
        {
            "field": "assignee_id",
            "old": {"id": str(w.uid("usr")), "login": w.login("usr")},
            "new": None,
        }
    ]


async def test_feed_marks_deleted_task_without_title(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    ba = w.tok("ba")
    tid = await _create_task(env, ba, w.project_id, w.uid("usr"))
    r = await send(env, ba, "DELETE", f"/api/v1/tasks/{tid}")
    assert r.status_code == 204, r.text

    r = await send(env, ba, "GET", _feed_url(w.project_id))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [item["action"] for item in items] == ["task.deleted", "task.created"]
    for item in items:
        assert item["entity"] == {"type": "task", "id": tid, "deleted": True, "title": None}
        assert item["changes"] is None


async def test_feed_pagination_and_params(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    ba = w.tok("ba")
    for i in range(3):
        r = await send(env, ba, "PATCH", pj(w.project_id), {"name": f"Имя {i}"})
        assert r.status_code == 200, r.text

    first = await send(env, ba, "GET", f"{_feed_url(w.project_id)}?page=1&page_size=2")
    second = await send(env, ba, "GET", f"{_feed_url(w.project_id)}?page=2&page_size=2")

    assert first.status_code == 200, first.text
    assert [i["id"] for i in first.json()["items"]] == sorted(
        (i["id"] for i in first.json()["items"]), reverse=True
    )
    assert first.json()["has_next"] is True
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 1
    assert second.json()["has_next"] is False
    assert first.json()["items"][0]["id"] > second.json()["items"][0]["id"]

    bad = await send(env, ba, "GET", f"{_feed_url(w.project_id)}?page=0")
    assert bad.status_code == 422, bad.text
