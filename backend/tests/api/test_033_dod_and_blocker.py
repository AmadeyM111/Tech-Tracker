"""Спека 033: DoD и блокер (CD-01, CD-03), AC-1…AC-9."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from tests.api.test_m20_t08_mcp_tools import _agent_token, _call, _error_code, _payload
from tests.conftest import ApiEnv
from tests.tasks_api_support import error, make_api_world, mk, project_tasks_url, send, task_url

TODAY = date(2026, 10, 13)
OVERVIEW_TASKS = "/api/v1/me/overview/tasks"


def _dod(task_id: UUID | str) -> str:
    return f"{task_url(task_id)}/dod-criteria"


async def _add(
    env: ApiEnv, token: str, task_id: UUID, body: str, *, required: bool = True
) -> dict[str, Any]:
    r = await send(env, token, "POST", _dod(task_id), {"body": body, "required": required})
    assert r.status_code == 201, r.text
    return r.json()


async def test_ac1_open_required_blocks_done(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, title="DoD")
    await _add(env, w.tok("ba"), tid, "Критерий А")
    card = await _add(env, w.tok("ba"), tid, "Критерий Б")
    open_id = next(i["id"] for i in card["dod"]["items"] if i["body"] == "Критерий Б")
    first = next(i["id"] for i in card["dod"]["items"] if i["body"] == "Критерий А")
    checked = await send(env, w.tok("ba"), "PATCH", f"{_dod(tid)}/{first}", {"checked": True})
    assert checked.status_code == 200, checked.text
    r = await send(env, w.tok("ba"), "PATCH", task_url(tid), {"status": "done"})
    assert error(r) == (422, "dod_open")
    assert "Критерий Б" in r.json()["detail"]
    assert (await send(env, w.tok("ba"), "GET", task_url(tid))).json()["status"] == "todo"
    assert open_id


async def test_ac2_all_required_checked_allows_done(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, title="DoD ok")
    card = await _add(env, w.tok("ba"), tid, "Готово")
    cid = card["dod"]["items"][0]["id"]
    await send(env, w.tok("ba"), "PATCH", f"{_dod(tid)}/{cid}", {"checked": True})
    r = await send(env, w.tok("ba"), "PATCH", task_url(tid), {"status": "done"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"


async def test_ac3_mcp_checks_criterion_but_cannot_close(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, assignee="usr", title="Агент")
    card = await _add(env, w.tok("ba"), tid, "Проверка")
    cid = card["dod"]["items"][0]["id"]
    token = await _agent_token(env, w, "usr")
    checked = _payload(
        await _call(
            env,
            token,
            "check_dod_criterion",
            {"task_id": str(tid), "criterion_id": cid, "checked": True},
        )
    )
    assert checked["dod"]["items"][0]["checked"] is True
    events = await env.execute(
        text(
            "SELECT action, client_name FROM domain_event"
            " WHERE entity_id = :t AND action = 'task.dod_checked'"
        ).bindparams(t=tid)
    )
    assert events is not None and events[0][0] == "task.dod_checked"
    assert events[0][1] == "Claude Code"
    closed = await _call(env, token, "update_task", {"task_id": str(tid), "status": "done"})
    assert _error_code(closed) == "human_close_only"
    assert (await send(env, w.tok("ba"), "GET", task_url(tid))).json()["status"] == "todo"


async def test_ac4_parent_dod_not_replaced_by_done_subtasks(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="Родитель")
    await _add(env, w.tok("ba"), parent, "Родительский критерий")
    sub = await mk(env, w, title="Подзадача", parent=parent, status="done")
    r = await send(env, w.tok("ba"), "PATCH", task_url(parent), {"status": "done"})
    assert error(r) == (422, "dod_open")
    assert (await send(env, w.tok("ba"), "GET", task_url(parent))).json()["status"] == "todo"
    assert (await send(env, w.tok("ba"), "GET", task_url(sub))).json()["status"] == "done"


async def test_ac5_blocked_medium_without_due_is_not_hot(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, title="Инцидент", priority="medium")
    r = await send(
        env,
        w.tok("ba"),
        "PATCH",
        task_url(tid),
        {"blocked": True, "blocked_reason": "Ждём поставку"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["blocked"] is True
    items = (await send(env, w.tok("ba"), "GET", OVERVIEW_TASKS)).json()["items"]
    row = next(i for i in items if i["id"] == str(tid))
    assert row["blocked"] is True
    assert row["hot"] is False
    board = (await send(env, w.tok("ba"), "GET", f"/api/v1/projects/{w.project_id}/board")).json()
    cards = [c for col in board["columns"] for c in col["tasks"]]
    card = next(c for c in cards if c["id"] == str(tid))
    assert card["blocked"] is True
    assert card["hot"] is False


async def test_ac6_high_due_today_stays_hot_without_blocker(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, title="Горит", priority="high", due_date=TODAY)
    items = (await send(env, w.tok("ba"), "GET", OVERVIEW_TASKS)).json()["items"]
    row = next(i for i in items if i["id"] == str(tid))
    assert row["hot"] is True
    assert row["blocked"] is False


async def test_ac7_cannot_block_done_task(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, title="Закрыта", status="done")
    r = await send(
        env,
        w.tok("ba"),
        "PATCH",
        task_url(tid),
        {"blocked": True, "blocked_reason": "поздно"},
    )
    assert error(r) == (422, "task_already_done")
    assert (await send(env, w.tok("ba"), "GET", task_url(tid))).json()["blocked"] is False


async def test_ac8_cannot_close_blocked_and_clear_keeps_status(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, title="Блок", status="in_progress")
    put = await send(
        env,
        w.tok("ba"),
        "PATCH",
        task_url(tid),
        {"blocked": True, "blocked_reason": "Ждём ответ"},
    )
    assert put.status_code == 200, put.text
    closed = await send(env, w.tok("ba"), "PATCH", task_url(tid), {"status": "done"})
    assert error(closed) == (422, "task_blocked")
    cleared = await send(env, w.tok("ba"), "PATCH", task_url(tid), {"blocked": False})
    assert cleared.status_code == 200, cleared.text
    body = cleared.json()
    assert body["blocked"] is False
    assert body["status"] == "in_progress"
    assert body["blocked_reason"] is None


async def test_ac9_list_project_tasks_filter_blocked(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    blocked = await mk(env, w, title="С блокером")
    await mk(env, w, title="Обычная")
    await send(
        env,
        w.tok("ba"),
        "PATCH",
        task_url(blocked),
        {"blocked": True, "blocked_reason": "инцидент"},
    )
    listed = await send(env, w.tok("ba"), "GET", project_tasks_url(w.project_id, "?blocked=true"))
    assert listed.status_code == 200, listed.text
    ids = [i["id"] for i in listed.json()["items"]]
    assert ids == [str(blocked)]
    token = await _agent_token(env, w, "ba")
    mcp = _payload(
        await _call(
            env,
            token,
            "list_project_tasks",
            {"project_id": str(w.project_id), "blocked": True},
        )
    )
    assert [i["id"] for i in mcp["items"]] == [str(blocked)]
