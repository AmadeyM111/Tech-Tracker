"""Спека 036: evidence, mode, classify_task (CD-07, CD-10, CD-11)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from tests.api.test_m20_t08_mcp_tools import _agent_token, _call, _error_code, _payload, _task_count
from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    TASK_REQ,
    error,
    make_api_world,
    mk,
    project_tasks_url,
    send,
    task_url,
)

RESEARCH_DOD = [
    {"body": "источник: ссылка на материал", "required": True, "kind": "checklist"},
    {"body": "полнота охвата", "required": True, "kind": "checklist"},
    {"body": "проверка выводов", "required": True, "kind": "checklist"},
]


def _dod(task_id: UUID | str) -> str:
    return f"{task_url(task_id)}/dod-criteria"


async def _create_research(env: ApiEnv, w: Any, title: str = "Исследование") -> dict[str, Any]:
    r = await send(
        env,
        w.tok("ba"),
        "POST",
        project_tasks_url(w.project_id),
        {"title": title, **TASK_REQ, "mode": "research", "dod_criteria": RESEARCH_DOD},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_ac07_1_empty_required_evidence_blocks_done(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, title="Артефакт")
    r = await send(
        env,
        w.tok("ba"),
        "POST",
        _dod(tid),
        {"body": "Отчёт", "required": True, "kind": "evidence"},
    )
    assert r.status_code == 201, r.text
    card = r.json()
    assert card["dod"]["missing_artifacts"] == ["Отчёт"]
    closed = await send(env, w.tok("ba"), "PATCH", task_url(tid), {"status": "done"})
    assert error(closed) == (422, "dod_open")
    assert (await send(env, w.tok("ba"), "GET", task_url(tid))).json()["status"] == "todo"


async def test_ac07_2_agent_marks_evidence_cannot_close(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, assignee="usr", title="С URL")
    card = (
        await send(
            env,
            w.tok("ba"),
            "POST",
            _dod(tid),
            {"body": "Ссылка", "required": True, "kind": "evidence"},
        )
    ).json()
    cid = card["dod"]["items"][0]["id"]
    token = await _agent_token(env, w, "usr")
    checked = _payload(
        await _call(
            env,
            token,
            "check_dod_criterion",
            {
                "task_id": str(tid),
                "criterion_id": cid,
                "checked": True,
                "evidence_ref": "https://example.com/report",
            },
        )
    )
    assert checked["dod"]["items"][0]["checked"] is True
    assert checked["dod"]["items"][0]["evidence_ref"] == "https://example.com/report"
    assert checked["dod"]["missing_artifacts"] == []
    events = await env.execute(
        text(
            "SELECT client_name FROM domain_event"
            " WHERE entity_id = :t AND action = 'task.dod_checked'"
        ).bindparams(t=tid)
    )
    assert events is not None and events[0][0] == "Claude Code"
    closed = await _call(env, token, "update_task", {"task_id": str(tid), "status": "done"})
    assert _error_code(closed) == "human_close_only"


async def test_ac07_3_human_closes_when_evidence_filled(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, title="Закрыть")
    card = (
        await send(
            env,
            w.tok("ba"),
            "POST",
            _dod(tid),
            {"body": "Файл", "required": True, "kind": "evidence"},
        )
    ).json()
    cid = card["dod"]["items"][0]["id"]
    patched = await send(
        env,
        w.tok("ba"),
        "PATCH",
        f"{_dod(tid)}/{cid}",
        {"checked": True, "evidence_ref": "artifact-1"},
    )
    assert patched.status_code == 200, patched.text
    r = await send(env, w.tok("ba"), "PATCH", task_url(tid), {"status": "done"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"


async def test_ac11_1_research_without_dod_is_422(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _task_count(env, w)
    r = await send(
        env,
        w.tok("ba"),
        "POST",
        project_tasks_url(w.project_id),
        {"title": "Сравни конкурента", **TASK_REQ, "mode": "research"},
    )
    assert error(r) == (422, "dod_required")
    assert "источник" in r.json()["detail"]
    assert await _task_count(env, w) == before


async def test_ac11_2_parent_dod_not_replaced_by_child_evidence(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await _create_research(env, w, "Родитель research")
    pid = UUID(parent["id"])
    sub = await send(
        env,
        w.tok("ba"),
        "POST",
        f"{task_url(pid)}/subtasks",
        {
            "title": "Дочерняя",
            "dod_criteria": [{"body": "Отчёт", "required": True, "kind": "evidence"}],
        },
    )
    assert sub.status_code == 201, sub.text
    sid = UUID(sub.json()["id"])
    cid = sub.json()["dod"]["items"][0]["id"]
    await send(
        env,
        w.tok("ba"),
        "PATCH",
        f"{_dod(sid)}/{cid}",
        {"checked": True, "evidence_ref": "https://example.com/a"},
    )
    done_sub = await send(env, w.tok("ba"), "PATCH", task_url(sid), {"status": "done"})
    assert done_sub.status_code == 200, done_sub.text
    blocked = await send(env, w.tok("ba"), "PATCH", task_url(pid), {"status": "done"})
    assert error(blocked) == (422, "dod_open")
    for item in parent["dod"]["items"]:
        await send(
            env,
            w.tok("ba"),
            "PATCH",
            f"{_dod(pid)}/{item['id']}",
            {"checked": True},
        )
    closed = await send(env, w.tok("ba"), "PATCH", task_url(pid), {"status": "done"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "done"


async def test_ac11_3_propose_entities_without_commit_writes_nothing(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    before = await _task_count(env, w)
    result = await _call(
        env,
        token,
        "propose_entities",
        {"text": "task: Исслед конкурента", "project_id": str(w.project_id), "mode": "research"},
    )
    assert result.get("isError") in (False, None), result
    body = _payload(result)
    assert body["committed"] == []
    assert await _task_count(env, w) == before


async def test_ac10_1_classify_research_without_commit(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    before_events = await env.execute(text("SELECT count(*) FROM domain_event"))
    before_tasks = await _task_count(env, w)
    result = _payload(
        await _call(env, token, "classify_task", {"text": "сравни нас с конкурентом"})
    )
    assert result["mode"] == "research"
    assert "source" in result["missing"]
    assert result["can_run_without_human"] is False
    assert result["committed"] is False
    assert result["task_id"] is None
    after_events = await env.execute(text("SELECT count(*) FROM domain_event"))
    assert after_events is not None and before_events is not None
    assert after_events[0][0] == before_events[0][0]
    assert await _task_count(env, w) == before_tasks


async def test_ac10_2_routine_closed_can_run_without_human(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    created = await send(
        env,
        w.tok("ba"),
        "POST",
        project_tasks_url(w.project_id),
        {
            "title": "Регламент",
            **TASK_REQ,
            "description": "источник полнота проверка evidence https://example.com",
            "dod_criteria": [
                {
                    "body": "источник полнота проверка evidence",
                    "required": True,
                    "kind": "evidence",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    tid = UUID(created.json()["id"])
    cid = created.json()["dod"]["items"][0]["id"]
    await send(
        env,
        w.tok("ba"),
        "PATCH",
        f"{_dod(tid)}/{cid}",
        {"checked": True, "evidence_ref": "https://example.com/done"},
    )
    token = await _agent_token(env, w, "ba")
    result = _payload(await _call(env, token, "classify_task", {"task_id": str(tid)}))
    assert result["mode"] == "routine"
    assert result["missing"] == []
    assert result["can_run_without_human"] is False
    assert result["committed"] is False
    assert result["task_id"] == str(tid)


async def test_ac10_3_research_agent_cannot_close(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await _create_research(env, w)
    tid = UUID(parent["id"])
    for item in parent["dod"]["items"]:
        await send(
            env,
            w.tok("ba"),
            "PATCH",
            f"{_dod(tid)}/{item['id']}",
            {"checked": True},
        )
    token = await _agent_token(env, w, "ba")
    closed = await _call(env, token, "update_task", {"task_id": str(tid), "status": "done"})
    assert _error_code(closed) == "human_close_only"
    modes = await env.execute(
        text("SELECT mode, status FROM task WHERE id = :id").bindparams(id=tid)
    )
    assert modes is not None
    assert modes[0][0] == "research"
    assert modes[0][1] == "todo"


async def test_classify_commit_writes_only_mode(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    tid = await mk(env, w, title="сравни конкурента")
    token = await _agent_token(env, w, "ba")
    before = await env.execute(
        text("SELECT status, mode FROM task WHERE id = :id").bindparams(id=tid)
    )
    result = _payload(
        await _call(
            env,
            token,
            "classify_task",
            {"task_id": str(tid), "commit": True},
        )
    )
    assert result["mode"] == "research"
    after = await env.execute(
        text("SELECT status, mode FROM task WHERE id = :id").bindparams(id=tid)
    )
    assert after is not None and before is not None
    assert after[0][0] == before[0][0] == "todo"
    assert after[0][1] == "research"
