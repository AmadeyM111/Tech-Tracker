"""T77: ``GET /api/v1/me/tasks`` — личный список исполнителя (AC-6, AC-75, AC-80, FR-27, FR-47).

Исполнитель = актор; задача и проект не удалены; актор — участник проекта; подзадачи включены;
``ORDER BY due_date ASC NULLS LAST, id``; ``Page[TaskListItem]`` без ``description``.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    LIST_FIELDS,
    ME_TASKS,
    PAGE_FIELDS,
    add_project,
    error,
    extra_user,
    make_api_world,
    make_foreign,
    mk,
    rows,
    send,
    task_url,
)


async def test_ac6_each_member_sees_exactly_own_assigned_tasks(api_env: ApiEnv) -> None:
    """001/AC-6 (не поведение СМ): задачи прежнего ``sm_m`` перенесены на ``ba2``."""
    env = api_env
    w = await make_api_world(env)
    mine: dict[str, set[str]] = {"usr": set(), "ba2": set(), "ba": set()}
    plan = [("usr", 1), ("usr", 2), ("ba2", 3), ("ba2", 4), ("ba2", 5)]
    for who, day in plan:
        t = await mk(env, w, assignee=who, due_date=date(2026, 11, day))
        mine[who].add(str(t))
    await mk(env, w)  # без исполнителя — ни у кого

    for who, expected in mine.items():
        r = await send(env, w.tok(who), "GET", ME_TASKS)
        assert r.status_code == 200, r.text
        assert {i["id"] for i in r.json()["items"]} == expected, who


async def test_page_shape_item_fields_and_no_description(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(
        env,
        w,
        assignee="usr",
        title="Моя",
        description="Длинное описание",
        priority="high",
        due_date=date(2026, 12, 1),
        status="review",
    )

    r = await send(env, w.tok("usr"), "GET", ME_TASKS)

    body = r.json()
    assert set(body) == PAGE_FIELDS
    assert (body["page"], body["page_size"], body["has_next"]) == (1, 50, False)
    item = body["items"][0]
    assert set(item) == LIST_FIELDS  # description в списках нет
    assert "Длинное описание" not in r.text
    assert item["id"] == str(t)
    assert item["project"] == {"id": str(w.project_id), "name": "Основной"}
    assert (item["title"], item["status"], item["priority"], item["due_date"]) == (
        "Моя",
        "review",
        "high",
        "2026-12-01",
    )
    assert item["assignee"] == {"id": str(w.uid("usr")), "login": w.login("usr")}
    assert item["parent_id"] is None
    assert item["created_at"]


async def test_order_due_date_asc_nulls_last_then_id(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    none_a = await mk(env, w, assignee="usr", due_date=None)
    late = await mk(env, w, assignee="usr", due_date=date(2026, 12, 31))
    early = await mk(env, w, assignee="usr", due_date=date(2026, 1, 1))
    same = [await mk(env, w, assignee="usr", due_date=date(2026, 6, 1)) for _ in range(3)]
    none_b = await mk(env, w, assignee="usr", due_date=None)

    r = await send(env, w.tok("usr"), "GET", ME_TASKS)

    ids = [i["id"] for i in r.json()["items"]]
    assert ids[0] == str(early)
    assert ids[1:4] == sorted(str(x) for x in same)
    assert ids[4] == str(late)
    assert ids[5:] == sorted([str(none_a), str(none_b)])


async def test_ac80_subtasks_are_in_the_list_with_parent_id(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    sub = await mk(env, w, assignee="usr", parent=parent)

    r = await send(env, w.tok("usr"), "GET", ME_TASKS)

    assert [(i["id"], i["parent_id"]) for i in r.json()["items"]] == [(str(sub), str(parent))]


async def test_excludes_deleted_task_deleted_project_non_member_and_other_workspace(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    visible = await mk(env, w, assignee="usr", title="Видимая")
    await mk(env, w, assignee="usr", deleted=True, title="Удалённая")
    dead_project = await add_project(
        env,
        w.ws,
        w.people["ba"].user,
        name="Удалён",
        members=["usr"],
        people=w.people,
        deleted=True,
    )
    await mk(env, w, assignee="usr", project_id=dead_project, title="В удалённом проекте")
    not_member_project = await add_project(env, w.ws, w.people["ba"].user, name="Без usr")
    await mk(env, w, assignee="usr", project_id=not_member_project, title="Где не участник")
    foreign = await make_foreign(env)
    await mk(env, w, assignee="ba2", title="Чужая исполнителю")
    assert foreign.project_id

    r = await send(env, w.tok("usr"), "GET", ME_TASKS)

    assert [i["id"] for i in r.json()["items"]] == [str(visible)]


async def test_fr47_pagination_has_next_page_two_and_default_size(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    ids = [await mk(env, w, assignee="usr", due_date=date(2026, 5, d)) for d in range(1, 6)]

    p1 = (await send(env, w.tok("usr"), "GET", f"{ME_TASKS}?page_size=2")).json()
    p2 = (await send(env, w.tok("usr"), "GET", f"{ME_TASKS}?page=2&page_size=2")).json()
    p3 = (await send(env, w.tok("usr"), "GET", f"{ME_TASKS}?page=3&page_size=2")).json()

    assert [i["id"] for i in p1["items"]] == [str(x) for x in ids[:2]]
    assert (p1["page"], p1["page_size"], p1["has_next"]) == (1, 2, True)
    assert [i["id"] for i in p2["items"]] == [str(x) for x in ids[2:4]]
    assert p2["has_next"] is True
    assert [i["id"] for i in p3["items"]] == [str(ids[4])]
    assert p3["has_next"] is False


@pytest.mark.parametrize(
    "query", ["?page=0", "?page=-1", "?page=x", "?page_size=0", "?page_size=101", "?page_size=x"]
)
async def test_fr47_invalid_page_params_are_422(api_env: ApiEnv, query: str) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(env, w.tok("ba"), "GET", f"{ME_TASKS}{query}")

    assert error(r) == (422, "validation_error")


async def test_ac75_no_role_and_tech_admin_get_403_unauthenticated_401(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    assert error(await send(env, w.tok("norole"), "GET", ME_TASKS)) == (403, "no_role")
    assert error(await send(env, w.tok("ta"), "GET", ME_TASKS)) == (403, "forbidden")
    assert error(await send(env, w.tok("otp"), "GET", ME_TASKS)) == (
        403,
        "password_change_required",
    )
    assert error(await send(env, None, "GET", ME_TASKS)) == (401, "not_authenticated")


async def test_user_with_role_removed_later_gets_403_no_role(api_env: ApiEnv) -> None:
    from tests.admin_support import admin_call

    env = api_env
    w = await make_api_world(env)
    await mk(env, w, assignee="usr")
    assert (await send(env, w.tok("usr"), "GET", ME_TASKS)).status_code == 200

    removed = await admin_call(env, w.tok("ta"), "role_none", w.uid("usr"))
    assert removed.status_code in (200, 204), removed.text

    assert error(await send(env, w.tok("usr"), "GET", ME_TASKS)) == (403, "no_role")


async def test_list_has_no_tasks_of_other_assignees_even_in_shared_project(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    extra = await extra_user(env, w, "user", "pt.extra")
    await mk(env, w, assignee="usr", title="Чужая")
    own = await mk(env, w, assignee=extra.user.id, title="Своя")

    r = await send(env, extra.token, "GET", ME_TASKS)

    assert [i["id"] for i in r.json()["items"]] == [str(own)]


async def test_removed_member_task_is_not_in_personal_list(api_env: ApiEnv) -> None:
    """Исполнитель исключён из проекта (FR-15a): снимается со всех задач проекта."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr")

    removed = await send(
        env, w.tok("ba"), "DELETE", f"/api/v1/projects/{w.project_id}/members/{w.uid('usr')}"
    )
    assert removed.status_code == 204, removed.text

    r = await send(env, w.tok("usr"), "GET", ME_TASKS)
    assert r.json()["items"] == []
    found = await rows(env, "SELECT assignee_id FROM task WHERE id = :t", t=t)
    assert found[0][0] is None
    assert task_url(uuid.uuid4())
