"""T77: ``POST /api/v1/tasks/{id}/subtasks`` (AC-7, AC-8, AC-47, AC-109, FR-21, FR-19b, SC-20).

Подзадача: статус ``todo``, позиции нет, проект родителя, один уровень вложенности.
Права — plan §11.5: ``can_create_task(assignee)`` и (полная правка родителя или исполнитель
родителя). БА-участник не владелец не создаёт подзадачу к чужой задаче и к своей задаче,
созданной другому или без исполнителя (ревью T74 п.6).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    DETAIL_FIELDS,
    error,
    make_api_world,
    mk,
    rows,
    send,
    task_db,
    task_url,
)


def _sub_url(task_id: Any) -> str:
    return f"{task_url(task_id)}/subtasks"


async def _children(env: ApiEnv, parent: Any) -> int:
    found = await rows(env, "SELECT count(*) FROM task WHERE parent_id = :p", p=parent)
    return int(found[0][0])


async def test_ac7_create_subtask_shape_parent_project_status_and_no_position(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, status="in_progress")

    r = await send(env, w.tok("ba"), "POST", _sub_url(parent), {"title": "Подзадача"})

    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == DETAIL_FIELDS
    assert body["parent_id"] == str(parent)
    assert body["project"]["id"] == str(w.project_id)
    assert body["status"] == "todo"  # не наследует статус родителя
    assert body["priority"] == "base"
    assert body["position"] is None
    assert body["subtasks"] == []
    assert body["progress"] is None
    assert body["assignee"] is None  # БА не передал исполнителя
    assert body["author"]["id"] == str(w.uid("ba"))
    assert body["permissions"]["create_subtask"] is False  # второй уровень закрыт
    row = await task_db(env, body["id"])
    assert (row.parent_id, row.position, row.workspace_id) == (parent, None, w.ws.id)
    card = (await send(env, w.tok("ba"), "GET", task_url(parent))).json()
    assert [s["id"] for s in card["subtasks"]] == [body["id"]]
    assert card["progress"] == 0


async def test_ac7_subtask_accepts_all_task_fields(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)

    r = await send(
        env,
        w.tok("ba"),
        "POST",
        _sub_url(parent),
        {
            "title": "П",
            "description": "О",
            "assignee_id": str(w.uid("usr")),
            "due_date": "2026-10-20",
            "priority": "high",
        },
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["description"], body["due_date"], body["priority"]) == ("О", "2026-10-20", "high")
    assert body["assignee"]["id"] == str(w.uid("usr"))


async def test_ac8_subtask_of_subtask_is_422_depth_exceeded_nothing_created(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    sub = await mk(env, w, parent=parent)

    r = await send(env, w.tok("ba"), "POST", _sub_url(sub), {"title": "Второй уровень"})

    assert error(r) == (422, "subtask_depth_exceeded")
    assert await _children(env, sub) == 0


async def test_ac8_depth_check_comes_after_permission_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    sub = await mk(env, w, parent=parent)  # ba2 — участник без прав на чужую задачу

    r = await send(env, w.tok("ba2"), "POST", _sub_url(sub), {"title": "Второй уровень"})

    assert error(r) == (403, "forbidden")


async def test_ac47_assignee_creates_subtask_for_himself_default_is_himself(
    api_env: ApiEnv,
) -> None:
    """AC-109 (последняя часть): исполнитель чужой задачи без исполнителя в запросе — он сам."""
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, assignee="usr")

    omitted = await send(env, w.tok("usr"), "POST", _sub_url(parent), {"title": "Без поля"})
    explicit = await send(
        env,
        w.tok("usr"),
        "POST",
        _sub_url(parent),
        {"title": "Себе", "assignee_id": str(w.uid("usr"))},
    )

    for r in (omitted, explicit):
        assert r.status_code == 201, r.text
        assert r.json()["assignee"] == {"id": str(w.uid("usr")), "login": w.login("usr")}
        assert r.json()["author"]["id"] == str(w.uid("usr"))


@pytest.mark.parametrize(
    "assignee", ["ba2", "sm_m", None], ids=["other_member", "other_mixed", "explicit_null"]
)
async def test_ac47_assignee_cannot_create_subtask_for_other_or_null_403(
    api_env: ApiEnv, assignee: str | None
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, assignee="usr")
    body: dict[str, Any] = {
        "title": "Другому",
        "assignee_id": None if assignee is None else str(w.uid(assignee)),
    }

    r = await send(env, w.tok("usr"), "POST", _sub_url(parent), body)

    assert error(r) == (403, "forbidden")
    assert await _children(env, parent) == 0


async def test_ac47_assignee_of_foreign_task_cannot_edit_it_but_subtask_is_allowed(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, assignee="usr", title="Т")

    sub = await send(env, w.tok("usr"), "POST", _sub_url(parent), {"title": "Своя подзадача"})
    title = await send(env, w.tok("usr"), "PATCH", task_url(parent), {"title": "Другое"})

    assert sub.status_code == 201
    assert error(title) == (403, "forbidden")
    assert (await task_db(env, parent)).title == "Т"


async def test_user_creates_subtask_to_own_task_for_self_but_not_for_other(
    api_env: ApiEnv,
) -> None:
    """BR-1: «Пользователь» не создаёт задачу другому и через подзадачу (исправление §4.5)."""
    env = api_env
    w = await make_api_world(env)
    parent = (
        await send(
            env, w.tok("usr"), "POST", f"/api/v1/projects/{w.project_id}/tasks", {"title": "Т"}
        )
    ).json()["id"]

    own = await send(env, w.tok("usr"), "POST", _sub_url(parent), {"title": "Себе"})
    other = await send(
        env,
        w.tok("usr"),
        "POST",
        _sub_url(parent),
        {"title": "Ba2", "assignee_id": str(w.uid("ba2"))},
    )

    assert own.status_code == 201, own.text
    assert error(other) == (403, "forbidden")
    assert await _children(env, uuid.UUID(parent)) == 1


async def test_user_without_relation_to_task_cannot_create_subtask(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, assignee="ba2")  # usr — участник, но не исполнитель и не автор

    r = await send(env, w.tok("usr"), "POST", _sub_url(parent), {"title": "Чужой"})

    assert error(r) == (403, "forbidden")
    assert await _children(env, parent) == 0


@pytest.mark.parametrize(
    ("by", "assignee", "expected"),
    [
        ("ba", "usr", 403),  # чужая задача
        ("ba", None, 403),  # создана владельцем без исполнителя
        ("ba2", None, 403),  # своя, но без исполнителя (не «своя» по FR-19)
        ("ba2", "usr", 403),  # своя, но исполнитель — другой
        ("ba2", "ba2", 201),  # своя и исполнитель — он сам
        ("ba", "ba2", 201),  # он исполнитель (FR-19b)
    ],
)
async def test_t74_review_6_ba_member_not_owner_subtask_formula(
    api_env: ApiEnv, by: str, assignee: str | None, expected: int
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, by=by, assignee=assignee)

    r = await send(env, w.tok("ba2"), "POST", _sub_url(parent), {"title": "Подзадача"})

    assert r.status_code == expected, r.text
    assert await _children(env, parent) == (1 if expected == 201 else 0)


async def test_owner_and_mixed_member_create_subtask_with_any_assignee(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, by="usr", assignee="usr")

    for who in ("ba", "sm_m"):
        r = await send(
            env,
            w.tok(who),
            "POST",
            _sub_url(parent),
            {"title": f"От {who}", "assignee_id": str(w.uid("ba2"))},
        )
        assert r.status_code == 201, (who, r.text)
        assert r.json()["assignee"]["id"] == str(w.uid("ba2"))


@pytest.mark.parametrize("who", ["usr2", "ba3", "sm"])
async def test_non_member_cannot_create_subtask_403(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, assignee="usr")

    r = await send(env, w.tok(who), "POST", _sub_url(parent), {"title": "Не участник"})

    assert error(r) == (403, "forbidden")
    assert await _children(env, parent) == 0


async def test_subtask_of_deleted_or_unknown_parent_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    gone = await mk(env, w, deleted=True)
    live = await mk(env, w)
    ok = await send(env, w.tok("ba"), "POST", _sub_url(live), {"title": "x"})
    assert ok.status_code == 201, ok.text  # маршрут существует

    for target in (gone, uuid.uuid4()):
        r = await send(env, w.tok("ba"), "POST", _sub_url(target), {"title": "x"})
        assert error(r) == (404, "not_found")


async def test_subtask_of_task_in_deleted_project_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    pre = await send(env, w.tok("ba"), "POST", _sub_url(parent), {"title": "до удаления"})
    assert pre.status_code == 201, pre.text
    assert (
        await send(env, w.tok("ba"), "DELETE", f"/api/v1/projects/{w.project_id}")
    ).status_code == 204

    r = await send(env, w.tok("ba"), "POST", _sub_url(parent), {"title": "x"})

    assert error(r) == (404, "not_found")


async def test_subtask_validation_422_codes_and_nothing_created(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    bad = [
        {"title": ""},
        {"title": "   "},
        {"title": "Я" * 256},
        {"title": "a\x00b"},
        {"title": "ok", "description": "д" * 10_001},
        {"title": "ok", "due_date": "2026-10-20T10:00:00Z"},
        {"title": "ok", "due_date": "2026-02-30"},
        {"title": "ok", "priority": "urgent"},
        {"title": "ok", "x": 1},
        {"title": None},
    ]

    for payload in bad:
        r = await send(env, w.tok("ba"), "POST", _sub_url(parent), payload)
        assert error(r) == (422, "validation_error"), payload
    assert await _children(env, parent) == 0


async def test_ac7_subtask_status_drives_parent_progress(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    ids = []
    for i in range(3):
        r = await send(env, w.tok("ba"), "POST", _sub_url(parent), {"title": f"П{i}"})
        ids.append(r.json()["id"])

    assert (await send(env, w.tok("ba"), "GET", task_url(parent))).json()["progress"] == 0
    await send(env, w.tok("ba"), "PATCH", task_url(ids[0]), {"status": "done"})
    assert (await send(env, w.tok("ba"), "GET", task_url(parent))).json()["progress"] == 33
    await send(env, w.tok("ba"), "PATCH", task_url(ids[1]), {"status": "review"})
    assert (await send(env, w.tok("ba"), "GET", task_url(parent))).json()["progress"] == 33
    await send(env, w.tok("ba"), "PATCH", task_url(ids[1]), {"status": "done"})
    await send(env, w.tok("ba"), "PATCH", task_url(ids[2]), {"status": "done"})
    assert (await send(env, w.tok("ba"), "GET", task_url(parent))).json()["progress"] == 100


async def test_subtask_has_the_same_project_even_when_sent_via_task_of_other_project(
    api_env: ApiEnv,
) -> None:
    """Проект подзадачи берётся у родителя; в теле ``project_id`` недопустим (extra)."""
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)

    r = await send(
        env, w.tok("ba"), "POST", _sub_url(parent), {"title": "x", "project_id": str(uuid.uuid4())}
    )

    assert error(r) == (422, "validation_error")
