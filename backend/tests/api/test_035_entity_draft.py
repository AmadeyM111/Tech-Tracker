"""CD-06 / спека 035: MCP propose_entities, commit только явно."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from tests.api.test_m20_t08_mcp_tools import _agent_token, _call, _error_code, _payload, _task_count
from tests.conftest import ApiEnv
from tests.projects_api_support import make_api_world
from tests.tasks_api_support import mk


async def test_ac1_without_commit_writes_nothing(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    before = await _task_count(env, w)
    result = await _call(
        env,
        token,
        "propose_entities",
        {"text": "task: Новая из текста", "project_id": str(w.project_id)},
    )
    assert result.get("isError") in (False, None), result
    body = _payload(result)
    assert body["committed"] == []
    assert body["drafts"][0]["type"] == "task"
    assert body["drafts"][0]["title"] == "Новая из текста"
    assert await _task_count(env, w) == before


async def test_ac2_commit_creates_task_with_client_name(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba", name="Claude Code")
    result = await _call(
        env,
        token,
        "propose_entities",
        {
            "text": "task: Новая",
            "commit": True,
            "project_id": str(w.project_id),
        },
    )
    assert result.get("isError") in (False, None), result
    body = _payload(result)
    task_id = UUID(body["committed"][0]["task_id"])
    assert body["committed"][0]["type"] == "task"
    rows = await env.execute(
        text(
            "SELECT client_name FROM domain_event "
            "WHERE entity_id = :id AND action = 'task.created'"
        ).bindparams(id=task_id)
    )
    assert rows is not None and rows[0][0] == "Claude Code"
    titles = await env.execute(text("SELECT title FROM task WHERE id = :id").bindparams(id=task_id))
    assert titles is not None and titles[0][0] == "Новая"


async def test_ac3_parse_error_writes_nothing(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    before = await _task_count(env, w)
    result = await _call(
        env,
        token,
        "propose_entities",
        {"text": "это не сущности", "commit": True, "project_id": str(w.project_id)},
    )
    assert _error_code(result) == "entity_parse_error"
    assert await _task_count(env, w) == before


async def test_ac4_incident_adds_blocker_comment(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    result = await _call(
        env,
        token,
        "propose_entities",
        {
            "text": "incident: Падение",
            "commit": True,
            "project_id": str(w.project_id),
        },
    )
    assert result.get("isError") in (False, None), result
    body = _payload(result)
    task_id = UUID(body["committed"][0]["task_id"])
    comments = await env.execute(
        text("SELECT body FROM comment WHERE task_id = :id AND deleted_at IS NULL").bindparams(
            id=task_id
        )
    )
    assert comments is not None
    assert [row[0] for row in comments] == ["блокер"]


async def test_ac5_note_on_existing_task_is_comment(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    existing = await mk(env, w, title="Живая")
    token = await _agent_token(env, w, "ba")
    before = await _task_count(env, w)
    result = await _call(
        env,
        token,
        "propose_entities",
        {
            "text": f"note: Уточнить | existing_task_id={existing}",
            "commit": True,
        },
    )
    assert result.get("isError") in (False, None), result
    body = _payload(result)
    assert body["committed"][0]["task_id"] == str(existing)
    assert await _task_count(env, w) == before
    comments = await env.execute(
        text("SELECT body FROM comment WHERE task_id = :id AND deleted_at IS NULL").bindparams(
            id=existing
        )
    )
    assert comments is not None
    assert [row[0] for row in comments] == ["Уточнить"]
