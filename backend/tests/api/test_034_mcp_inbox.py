"""Спека 034: MCP ingest_message и list_stuck_work (CD-02, CD-04)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from tests.api.test_m20_t07_mcp_core import _list_names
from tests.api.test_m20_t08_mcp_tools import _agent_token, _call, _error_code, _payload
from tests.conftest import ApiEnv
from tests.projects_api_support import make_api_world, send
from tests.tasks_api_support import mk, task_url

TOKENS = "/api/v1/me/tokens"


async def _read_only_token(env: ApiEnv, w: Any, who: str) -> str:
    response = await send(env, w.tok(who), "POST", TOKENS, {"name": "observer", "read_only": True})
    assert response.status_code == 201, response.text
    return str(response.json()["token"])


async def test_034_ac1_ingest_creates_task_with_source(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    result = await _call(
        env,
        token,
        "ingest_message",
        {
            "project_id": str(w.project_id),
            "source": "telegram",
            "external_id": "chat:1",
            "text": "Срочный баг\nподробности",
            "url": "https://t.me/c/1/1",
        },
    )
    assert result.get("isError") in (False, None), result
    body = _payload(result)
    task_id = body["task_id"]
    assert body["comment_id"] is None
    card = _payload(await _call(env, token, "get_task", {"task_id": task_id}))
    assert card["description"] == "Срочный баг\nподробности"
    assert card["title"] == "Срочный баг"
    assert card["source"] == "telegram"
    assert card["source_url"] == "https://t.me/c/1/1"
    rest = await send(env, w.tok("ba"), "GET", task_url(task_id))
    assert rest.status_code == 200, rest.text
    assert rest.json()["source"] == "telegram"


async def test_034_ac2_ingest_with_task_id_adds_comment_keeps_status(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    task_id = await mk(env, w, title="Живая")
    token = await _agent_token(env, w, "ba")
    before = _payload(await _call(env, token, "get_task", {"task_id": str(task_id)}))
    result = await _call(
        env,
        token,
        "ingest_message",
        {
            "project_id": str(w.project_id),
            "source": "telegram",
            "external_id": "chat:2",
            "text": "комментарий из чата",
            "task_id": str(task_id),
            "url": "https://t.me/c/1/2",
        },
    )
    assert result.get("isError") in (False, None), result
    body = _payload(result)
    assert body["task_id"] == str(task_id)
    assert body["comment_id"] is not None
    listed = _payload(await _call(env, token, "list_comments", {"task_id": str(task_id)}))
    mine = [c for c in listed["items"] if c["id"] == body["comment_id"]]
    assert len(mine) == 1
    assert mine[0]["body"] == "комментарий из чата"
    assert mine[0]["source"] == "telegram"
    assert mine[0]["source_url"] == "https://t.me/c/1/2"
    after = _payload(await _call(env, token, "get_task", {"task_id": str(task_id)}))
    assert after["status"] == before["status"]


async def test_034_ac3_ingest_is_idempotent(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    args = {
        "project_id": str(w.project_id),
        "source": "telegram",
        "external_id": "chat:dup",
        "text": "один раз",
    }
    first = _payload(await _call(env, token, "ingest_message", args))
    second = _payload(await _call(env, token, "ingest_message", args))
    assert first["task_id"] == second["task_id"]
    assert first["comment_id"] == second["comment_id"]
    count = await env.execute(
        text(f"SELECT count(*) FROM task WHERE project_id = '{w.project_id}'")
    )
    assert int(count[0][0]) == 1


async def test_034_ac4_foreign_project_is_forbidden(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "usr2")
    result = await _call(
        env,
        token,
        "ingest_message",
        {
            "project_id": str(w.project_id),
            "source": "telegram",
            "external_id": "chat:x",
            "text": "чужое",
        },
    )
    assert _error_code(result) == "forbidden"
    rows = await env.execute(text("SELECT count(*) FROM external_message"))
    assert int(rows[0][0]) == 0


async def test_034_ac5_stuck_after_48h_overdue_is_separate(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    stale_overdue = await mk(env, w, title="Застряла просроченная", due_date=date(2026, 10, 13))
    stale_ok = await mk(env, w, title="Застряла в срок", due_date=date(2026, 12, 1))
    done = await mk(env, w, title="Готово", status="done", due_date=date(2026, 10, 13))
    token = await _agent_token(env, w, "ba")
    env.clock.advance(timedelta(hours=49))
    listed = _payload(await _call(env, token, "list_stuck_work", {}))
    by_id = {item["id"]: item for item in listed["items"]}
    assert str(done) not in by_id
    assert by_id[str(stale_overdue)]["overdue"] is True
    assert by_id[str(stale_ok)]["overdue"] is False
    assert by_id[str(stale_ok)]["blocked"] is None
    assert by_id[str(stale_ok)]["open_dod"] is None


async def test_034_ac6_fresh_comment_drops_from_stuck(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    task_id = await mk(env, w, title="Ожила")
    token = await _agent_token(env, w, "ba")
    env.clock.advance(timedelta(hours=49))
    await _call(env, token, "add_comment", {"task_id": str(task_id), "body": "есть движение"})
    listed = _payload(await _call(env, token, "list_stuck_work", {}))
    assert str(task_id) not in {item["id"] for item in listed["items"]}


async def test_034_ac7_read_only_sees_stuck_hides_ingest(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _read_only_token(env, w, "ba")
    names = set(await _list_names(env, token))
    assert "list_stuck_work" in names
    assert "ingest_message" not in names
    denied = await _call(
        env,
        token,
        "ingest_message",
        {
            "project_id": str(w.project_id),
            "source": "telegram",
            "external_id": "nope",
            "text": "нет",
        },
    )
    assert _error_code(denied) == "forbidden"
