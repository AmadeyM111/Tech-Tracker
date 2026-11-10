"""D24-T02: «Сводка» — диапазон срока ``due_from`` / ``due_to`` (spec 024 FR-1…FR-4; AC-1…AC-6).

Часы — FixedClock приложения (2026-10-13T09:00Z → сегодня 13.10, вторник МСК). Сценарии строятся
на тех же хелперах, что и ``test_008_overview.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from tests.conftest import ApiEnv
from tests.factories import (
    make_project,
    make_project_member,
    make_task,
    make_user,
    make_workspace,
)

TODAY = date(2026, 10, 13)  # FIXED_NOW = 2026-10-13T09:00Z, вторник
TASKS = "/api/v1/me/overview/tasks"
OVERVIEW = "/api/v1/me/overview"


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


async def _get(
    w: World, url: str, query: list[tuple[str, str]] | None = None, **params: Any
) -> Any:
    """Запрос с произвольным списком пар (для повторов параметра) или обычными параметрами."""
    if query is not None:
        return await w.env.client.get(url, params=query, headers=w.env.auth(w.token))
    return await w.env.client.get(url, params=params, headers=w.env.auth(w.token))


async def _ids(w: World, **params: Any) -> set[str]:
    response = await _get(w, TASKS, page_size=100, **params)
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


async def _seed_range_world(w: World) -> dict[str, Any]:
    """Задачи со сроками вокруг сегодняшнего дня и одна без срока (AC-1, AC-2)."""
    return {
        "yesterday": await _task(w, w.mine, due_date=TODAY - timedelta(days=1)),
        "today": await _task(w, w.mine, due_date=TODAY),
        "plus3": await _task(w, w.mine, due_date=TODAY + timedelta(days=3)),
        "plus10": await _task(w, w.mine, due_date=TODAY + timedelta(days=10)),
        "none": await _task(w, w.mine),
    }


def _ids_of(t: dict[str, Any], *names: str) -> set[str]:
    return {str(t[n].id) for n in names}


async def test_024_ac1_range_is_inclusive_on_both_ends(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    t = await _seed_range_world(w)
    got = await _ids(w, due_from=TODAY.isoformat(), due_to=(TODAY + timedelta(days=3)).isoformat())
    assert got == _ids_of(t, "today", "plus3")


async def test_024_ac2_only_from_or_only_to_is_open_range(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    t = await _seed_range_world(w)
    after = await _ids(w, due_from=TODAY.isoformat())
    assert after == _ids_of(t, "today", "plus3", "plus10")  # без «вчера» и без срока
    before = await _ids(w, due_to=(TODAY + timedelta(days=3)).isoformat())
    assert before == _ids_of(t, "yesterday", "today", "plus3")  # без «+10» и без срока


async def test_024_ac3_done_is_included_in_range_but_not_in_overdue(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    done_in_range = await _task(w, w.mine, due_date=TODAY + timedelta(days=2), status="done")
    done_yesterday = await _task(w, w.mine, due_date=TODAY - timedelta(days=1), status="done")
    assert await _ids(
        w, due_from=TODAY.isoformat(), due_to=(TODAY + timedelta(days=3)).isoformat()
    ) == {str(done_in_range.id)}
    overdue = await _ids(w, due="overdue")
    assert str(done_yesterday.id) not in overdue  # «Просрочено» по-прежнему без done (Q-3)


async def test_024_ac3_range_result_is_sorted_by_due_then_id(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    await _seed_range_world(w)
    items = (
        await _get(
            w,
            TASKS,
            due_from=TODAY.isoformat(),
            due_to=(TODAY + timedelta(days=10)).isoformat(),
            page_size=100,
        )
    ).json()["items"]
    dues = [i["due_date"] for i in items]
    assert dues == sorted(dues) and None not in dues


async def test_024_ac4_due_preset_with_range_is_422(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    for query in (
        [("due", "today"), ("due_from", "2026-10-01")],
        [("due", "week"), ("due_to", "2026-10-31")],
        [("due", "none"), ("due_from", "2026-10-01"), ("due_to", "2026-10-31")],
    ):
        response = await _get(w, TASKS, query=query)
        assert response.status_code == 422, query
        assert response.json()["code"] == "validation_error"


async def test_024_ac4_from_after_to_is_422(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    response = await _get(w, TASKS, due_from="2026-10-20", due_to="2026-10-19")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize(
    "query",
    [
        [("due_from", "31.12.2026")],
        [("due_to", "31.12.2026")],
        [("due_from", "2026-13-01")],
        [("due_from", "2026-10-13T00:00:00")],
        [("due_to", "tomorrow")],
        [("due_to", "2026-10-13"), ("due_to", "2026-10-20")],
        [("due_from", "2026-10-13"), ("due_from", "2026-10-14")],
    ],
    ids=[
        "from-dotted",
        "to-dotted",
        "from-bad-month",
        "from-with-time",
        "to-word",
        "to-twice",
        "from-twice",
    ],
)
async def test_024_ac4_bad_format_or_repeated_bound_is_422(
    api_env: ApiEnv, query: list[tuple[str, str]]
) -> None:
    w = await _world(api_env)
    response = await _get(w, TASKS, query=query)
    assert response.status_code == 422, query
    assert response.json()["code"] == "validation_error"


async def test_024_ac5_range_boundary_follows_moscow_day(api_env: ApiEnv) -> None:
    api_env.clock.set(datetime(2026, 10, 13, 21, 0, 0, tzinfo=UTC))  # 14.10 00:00 МСК
    w = await _world(api_env)
    msk_today = date(2026, 10, 14)
    today_task = await _task(w, w.mine, due_date=msk_today)
    await _task(w, w.mine, due_date=TODAY)  # 13.10 — уже вчера по Москве
    by_range = await _ids(w, due_from=msk_today.isoformat(), due_to=msk_today.isoformat())
    by_preset = await _ids(w, due="today")
    assert by_range == by_preset == {str(today_task.id)}


async def test_024_ac6_tiles_ignore_range(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    await _seed_range_world(w)
    await _task(w, w.shared, status="review", created_by=w.me.id)
    plain = (await _get(w, OVERVIEW)).json()
    ranged = (
        await _get(
            w,
            OVERVIEW,
            due_from=TODAY.isoformat(),
            due_to=(TODAY + timedelta(days=3)).isoformat(),
        )
    ).json()
    assert plain == ranged and plain["total"] == 6


async def test_024_range_combines_with_other_filters_by_and(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    keep = await _task(w, w.mine, due_date=TODAY, status="in_progress", priority="high")
    await _task(w, w.mine, due_date=TODAY, status="todo", priority="high")  # статус мимо
    await _task(w, w.mine, due_date=TODAY, status="in_progress", priority="low")  # приоритет мимо
    await _task(w, w.shared, due_date=TODAY, status="in_progress", priority="high")  # проект мимо
    await _task(
        w, w.mine, due_date=TODAY + timedelta(days=9), status="in_progress", priority="high"
    )
    got = await _ids(
        w,
        project_id=str(w.mine.id),
        status="in_progress",
        priority=["high"],
        due_from=TODAY.isoformat(),
        due_to=(TODAY + timedelta(days=3)).isoformat(),
    )
    assert got == {str(keep.id)}


async def test_024_range_with_needs_review_is_and(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    mine_review = await _task(w, w.mine, status="review", due_date=TODAY)
    await _task(w, w.shared, status="review", due_date=TODAY, created_by=w.other.id)  # не моя
    await _task(w, w.mine, status="review", due_date=TODAY + timedelta(days=9))  # вне диапазона
    got = await _ids(
        w,
        needs_review="true",
        due_from=TODAY.isoformat(),
        due_to=(TODAY + timedelta(days=3)).isoformat(),
    )
    assert got == {str(mine_review.id)}


async def test_024_range_keeps_workspace_and_membership_isolation(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    await _task(w, w.foreign, due_date=TODAY)  # проект без меня — не попадает
    mine = await _task(w, w.mine, due_date=TODAY)
    got = await _ids(w, due_from=TODAY.isoformat(), due_to=TODAY.isoformat())
    assert got == {str(mine.id)}


async def test_024_range_request_without_range_params_is_unchanged(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    t = await _seed_range_world(w)
    assert await _ids(w) == _ids_of(t, "yesterday", "today", "plus3", "plus10", "none")
    assert (await _get(w, TASKS)).status_code == 200
    assert (await api_env.client.get(TASKS, params={"due_from": "2026-10-13"})).status_code == 401
