"""S08-T02/T03: «Сводка» — ``GET /me/overview`` и ``GET /me/overview/tasks`` (spec 008).

AC-1…AC-11, AC-15. Часы — FixedClock приложения (2026-10-13T09:00Z → сегодня 13.10, вторник МСК).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import update

from app.domain.projects.models import Project
from app.domain.tasks.models import Task
from tests.conftest import ApiEnv
from tests.factories import (
    make_project,
    make_project_member,
    make_task,
    make_user,
    make_workspace,
)

TODAY = date(2026, 10, 13)  # FIXED_NOW = 2026-10-13T09:00Z, вторник
OVERVIEW = "/api/v1/me/overview"
TASKS = "/api/v1/me/overview/tasks"
PROJECTS = "/api/v1/me/overview/projects"


@dataclass
class World:
    env: ApiEnv
    me: Any
    other: Any
    token: str
    mine: Any  # проект, где я владелец
    shared: Any  # проект, где я участник (владелец — other)
    foreign: Any  # проект без меня


async def _world(env: ApiEnv) -> World:
    async with env.sessionmaker() as s:
        wsrow = await make_workspace(s)
        ws = wsrow.id
        me = await make_user(s, role="business_admin", workspace=wsrow)
        other = await make_user(s, role="business_admin", workspace=wsrow)
        mine = await make_project(s, workspace_id=ws, owner_id=me.id, name="Мой")
        shared = await make_project(s, workspace_id=ws, owner_id=other.id, name="Общий")
        await make_project_member(s, project_id=shared.id, user_id=me.id, workspace_id=ws)
        foreign = await make_project(s, workspace_id=ws, owner_id=other.id, name="Чужой")
        await s.commit()
    return World(env, me, other, await env.login_ok(me), mine, shared, foreign)


async def _task(w: World, project: Any, **kw: Any) -> Any:
    async with w.env.sessionmaker() as s:
        kw.setdefault("created_by", w.other.id)
        row = await make_task(s, project_id=project.id, workspace_id=w.me.workspace_id, **kw)
        await s.commit()
    return row


async def _get(w: World, url: str, **params: Any) -> Any:
    return await w.env.client.get(url, params=params, headers=w.env.auth(w.token))


async def _ids(w: World, **params: Any) -> set[Any]:
    response = await _get(w, TASKS, page_size=100, **params)
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


async def test_008_ac1_ac2_counts_only_my_live_tasks(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    for status in ("todo", "todo", "in_progress", "review", "done"):
        await _task(w, w.mine if status != "review" else w.shared, status=status)
    parent = await _task(w, w.mine, status="todo")
    await _task(w, w.mine, status="in_progress", parent_id=parent.id)  # подзадача считается (Q-1)
    await _task(w, w.foreign, status="todo")
    gone = await _task(w, w.mine, status="todo")
    await api_env.execute(
        update(Task).where(Task.id == gone.id).values(deleted_at=api_env.clock.now())
    )
    await _task(w, w.shared, status="done")
    body = (await _get(w, OVERVIEW)).json()
    # review в «Общем» создал other, владелец other — «Нужно проверить» = 0 (FR-3)
    assert body == {
        "total": 8,
        "todo": 3,
        "in_progress": 2,
        "review": 1,
        "done": 2,
        "needs_review": 0,
    }
    assert body["todo"] + body["in_progress"] + body["review"] + body["done"] == body["total"]
    await api_env.execute(
        update(Project).where(Project.id == w.shared.id).values(deleted_at=api_env.clock.now())
    )
    after = (await _get(w, OVERVIEW)).json()
    assert after["total"] == 6 and after["review"] == 0 and after["done"] == 1


async def test_008_ac3_ac4_needs_review_author_or_owner(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    a = await _task(w, w.shared, status="review", created_by=w.me.id)  # я автор
    b = await _task(w, w.mine, status="review")  # я владелец проекта
    await _task(w, w.shared, status="review", assignee_id=w.me.id)  # только исполнитель
    d = await _task(w, w.shared, status="review", created_by=w.me.id, assignee_id=w.me.id)
    await _task(w, w.mine, status="in_progress", created_by=w.me.id)  # не review
    assert (await _get(w, OVERVIEW)).json()["needs_review"] == 3
    assert await _ids(w, needs_review="true") == {str(a.id), str(b.id), str(d.id)}


async def test_008_ac5_priority_multiselect(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    low = await _task(w, w.mine, priority="low")
    await _task(w, w.mine, priority="medium")
    high = await _task(w, w.mine, priority="high")
    assert await _ids(w, priority=["low", "high"]) == {str(low.id), str(high.id)}


async def test_008_ac7_due_presets_moscow(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    t = {
        "yesterday": await _task(w, w.mine, due_date=TODAY - timedelta(days=1)),
        "done_yesterday": await _task(w, w.mine, due_date=TODAY - timedelta(days=1), status="done"),
        "today": await _task(w, w.mine, due_date=TODAY),
        "tomorrow": await _task(w, w.mine, due_date=TODAY + timedelta(days=1)),
        "sunday": await _task(w, w.mine, due_date=date(2026, 10, 18)),
        "next_monday": await _task(w, w.mine, due_date=date(2026, 10, 19)),
        "none": await _task(w, w.mine),
    }

    def ids(*names: str) -> set[str]:
        return {str(t[n].id) for n in names}

    assert await _ids(w, due="overdue") == ids("yesterday")
    assert await _ids(w, due="today") == ids("today")
    assert await _ids(w, due="tomorrow") == ids("tomorrow")
    assert await _ids(w, due="week") == ids("today", "tomorrow", "sunday")
    assert await _ids(w, due="none") == ids("none")


async def test_008_ac6_today_boundary_follows_moscow_clock(api_env: ApiEnv) -> None:
    from datetime import UTC, datetime

    api_env.clock.set(datetime(2026, 11, 9, 20, 59, 59, tzinfo=UTC))  # до входа: сессия свежая
    w = await _world(api_env)
    nov9 = await _task(w, w.mine, due_date=date(2026, 11, 9))
    nov10 = await _task(w, w.mine, due_date=date(2026, 11, 10))
    assert await _ids(w, due="today") == {str(nov9.id)}
    api_env.clock.set(datetime(2026, 11, 9, 21, 0, 0, tzinfo=UTC))
    assert await _ids(w, due="today") == {str(nov10.id)}


async def test_008_ac8_hot_flag_and_order(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    await _task(w, w.mine, title="без срока")
    hot_old = await _task(w, w.mine, priority="high", due_date=TODAY - timedelta(days=1))
    hot_today = await _task(w, w.mine, priority="high", due_date=TODAY)
    await _task(w, w.mine, priority="high", due_date=TODAY + timedelta(days=1))
    await _task(w, w.mine, priority="medium", due_date=TODAY - timedelta(days=2))
    await _task(w, w.mine, priority="high", due_date=TODAY - timedelta(days=3), status="done")
    items = (await _get(w, TASKS)).json()["items"]
    assert {i["id"] for i in items if i["hot"]} == {str(hot_old.id), str(hot_today.id)}
    dues = [i["due_date"] for i in items]
    assert dues[-1] is None and dues[:-1] == sorted(dues[:-1]), (
        "срок по возрастанию, пустой в конце"
    )
    assert set(items[0]) == {
        "id",
        "title",
        "project",
        "parent_id",
        "status",
        "priority",
        "due_date",
        "assignee",
        "hot",
    }


async def test_008_ac9_total_and_paging(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    for _ in range(7):
        await _task(w, w.mine, status="in_progress")
    await _task(w, w.mine, status="todo")
    page = (await _get(w, TASKS, status="in_progress", page_size=5)).json()
    assert (len(page["items"]), page["total"], page["has_next"]) == (5, 7, True)
    page2 = (await _get(w, TASKS, status="in_progress", page_size=5, page=2)).json()
    assert (len(page2["items"]), page2["total"], page2["has_next"]) == (2, 7, False)


async def test_008_project_filter(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    a = await _task(w, w.shared)
    await _task(w, w.mine)
    assert await _ids(w, project_id=str(w.shared.id)) == {str(a.id)}


async def test_008_ac10_tech_admin_gets_403(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="tech_admin")
    token = await api_env.login_ok(user)
    for url in (OVERVIEW, TASKS, PROJECTS):
        response = await api_env.client.get(url, headers=api_env.auth(token))
        assert response.status_code == 403, url


async def test_008_ac10_anonymous_401_and_foreign_project_404(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    assert (await api_env.client.get(OVERVIEW)).status_code == 401
    assert (await api_env.client.get(TASKS)).status_code == 401
    for pid in (w.foreign.id, "00000000-0000-4000-8000-000000000000"):
        response = await _get(w, TASKS, project_id=str(pid))
        assert response.status_code == 404, pid


@pytest.mark.parametrize(
    "params",
    [
        {"priority": "urgent"},
        {"due": "someday"},
        {"status": ["todo", "done"]},
        {"due": ["today", "week"]},
        {"page_size": 101},
    ],
    ids=["priority", "due", "two-status", "two-due", "page-size"],
)
async def test_008_ac11_validation(api_env: ApiEnv, params: dict[str, Any]) -> None:
    w = await _world(api_env)
    response = await _get(w, TASKS, **params)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_008_ac15_tiles_ignore_list_filters(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    await _task(w, w.mine, priority="high")
    await _task(w, w.shared, priority="low")
    plain = (await _get(w, OVERVIEW)).json()
    filtered = (await _get(w, OVERVIEW, project_id=str(w.mine.id), priority="high")).json()
    assert plain == filtered and plain["total"] == 2


async def test_008_review_project_filter_lists_only_my_projects_by_name(api_env: ApiEnv) -> None:
    """Ревью 008: фильтр по проекту — проекты по членству (владелец/участник), без лимита 100."""
    w = await _world(api_env)
    async with w.env.sessionmaker() as s:
        for i in range(105):  # больше прежнего фиксированного page_size=100
            await make_project(
                s, workspace_id=w.me.workspace_id, owner_id=w.me.id, name=f"Проект {i:03d}"
            )
        gone = await make_project(
            s, workspace_id=w.me.workspace_id, owner_id=w.me.id, name="Удалённый"
        )
        await s.commit()
    await api_env.execute(
        update(Project).where(Project.id == gone.id).values(deleted_at=api_env.clock.now())
    )
    body = (await _get(w, PROJECTS)).json()
    names = [p["name"] for p in body["items"]]
    assert len(names) == 107  # 105 + «Мой» + «Общий»; без «Чужой» и удалённого
    assert "Чужой" not in names and "Удалённый" not in names
    assert names == sorted(names, key=str.lower)
    assert (await api_env.client.get(PROJECTS)).status_code == 401
