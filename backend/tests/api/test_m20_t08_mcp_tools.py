"""M20-T08: инструменты MCP по доменам (ADR-0018, PN-10, PN-11; AC-5, AC-7, AC-8).

Мир — ``make_api_world`` (проект ``ba`` владелец, ``usr`` участник, ``usr2`` не участник).
Токены агентов выпускаются через REST (cookie-сессия), вызовы — через ``/mcp`` с Bearer.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from tests.api.test_m20_t07_mcp_core import PROTOCOL
from tests.conftest import ApiEnv
from tests.projects_api_support import ApiWorld, make_api_world, send
from tests.tasks_api_support import mk, task_url

MCP = "/mcp"
TOKENS = "/api/v1/me/tokens"


async def _agent_token(env: ApiEnv, w: ApiWorld, who: str, name: str = "Claude Code") -> str:
    response = await send(env, w.tok(who), "POST", TOKENS, {"name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["token"])


async def _call(env: ApiEnv, token: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = await env.client.post(
        MCP,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL,
        },
    )
    assert response.status_code == 200, response.text
    return dict(response.json()["result"])


def _payload(result: dict[str, Any]) -> Any:
    import json

    return json.loads(result["content"][0]["text"])


def _error_code(result: dict[str, Any]) -> str:
    assert result["isError"] is True, result
    return str(_payload(result)["code"])


async def _task_count(env: ApiEnv, w: ApiWorld) -> int:
    # w.project_id — UUID из фикстуры мира, не пользовательский ввод
    rows = await env.execute(text(f"SELECT count(*) FROM task WHERE project_id = '{w.project_id}'"))
    assert rows is not None
    return int(rows[0][0])


async def test_registry_lists_ten_tools_for_business_roles(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    response = await env.client.post(
        MCP,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL,
        },
    )
    names = sorted(t["name"] for t in response.json()["result"]["tools"])
    assert names == sorted(
        [
            "add_comment",
            "create_subtask",
            "create_task",
            "get_project",
            "get_task",
            "list_comments",
            "list_my_tasks",
            "list_project_tasks",
            "list_projects",
            "update_task",
        ]
    )


async def test_ac5_user_cannot_create_task_for_another_user(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "usr")
    before = await _task_count(env, w)
    result = await _call(
        env,
        token,
        "create_task",
        {
            "project_id": str(w.project_id),
            "title": "Чужая задача",
            "description": "Описание",
            "due_date": "2026-12-01",
            "assignee_id": str(w.uid("ba")),
        },
    )
    assert _error_code(result) == "forbidden"
    assert await _task_count(env, w) == before


async def test_ac7_task_created_by_agent_is_visible_in_rest(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    result = await _call(
        env,
        token,
        "create_task",
        {
            "project_id": str(w.project_id),
            "title": "Из агента",
            "description": "Описание",
            "due_date": "2026-12-01",
            "assignee_id": str(w.uid("usr")),
        },
    )
    assert result.get("isError") in (False, None), result
    task = _payload(result)
    assert task["title"] == "Из агента"
    assert task["assignee"]["id"] == str(w.uid("usr"))

    rest = await send(env, w.tok("ba"), "GET", task_url(task["id"]))
    assert rest.status_code == 200, rest.text
    assert rest.json()["title"] == "Из агента"


async def test_ac8_agent_action_shows_client_name_in_project_feed(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba", name="Claude Code на ноутбуке")
    await _call(
        env,
        token,
        "create_task",
        {
            "project_id": str(w.project_id),
            "title": "Через агента",
            "description": "Описание",
            "due_date": "2026-12-01",
        },
    )
    feed = await send(env, w.tok("ba"), "GET", f"/api/v1/projects/{w.project_id}/activity")
    assert feed.status_code == 200, feed.text
    via = [i["via_client"] for i in feed.json()["items"] if i["action"] == "task.created"]
    assert via == ["Claude Code на ноутбуке"]


async def test_list_my_tasks_and_get_task_for_assignee(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    mine = await mk(env, w, assignee="usr", title="Моя задача")
    await mk(env, w, assignee="ba", title="Чужая")
    token = await _agent_token(env, w, "usr")

    listed = _payload(await _call(env, token, "list_my_tasks", {}))
    assert [i["id"] for i in listed["items"]] == [str(mine)]

    card = _payload(await _call(env, token, "get_task", {"task_id": str(mine)}))
    assert card["id"] == str(mine)
    assert card["title"] == "Моя задача"


async def test_list_project_tasks_filters_by_status(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    done = await mk(env, w, title="Готово", status="done")
    await mk(env, w, title="В работе", status="in_progress")
    token = await _agent_token(env, w, "ba")

    result = _payload(
        await _call(
            env, token, "list_project_tasks", {"project_id": str(w.project_id), "status": "done"}
        )
    )
    assert [i["id"] for i in result["items"]] == [str(done)]


async def test_update_task_status_is_seen_in_rest(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    task = await mk(env, w, assignee="usr", title="Двигаем", status="todo")
    token = await _agent_token(env, w, "usr")

    updated = _payload(
        await _call(env, token, "update_task", {"task_id": str(task), "status": "in_progress"})
    )
    assert updated["status"] == "in_progress"

    rest = await send(env, w.tok("ba"), "GET", task_url(task))
    assert rest.json()["status"] == "in_progress"


async def test_create_subtask_links_to_parent(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="Родитель")
    token = await _agent_token(env, w, "ba")

    sub = _payload(
        await _call(
            env,
            token,
            "create_subtask",
            {
                "task_id": str(parent),
                "title": "Подзадача",
                "description": "Описание",
                "due_date": "2026-12-01",
            },
        )
    )
    assert sub["parent_id"] == str(parent)


async def test_comments_round_trip(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    task = await mk(env, w, assignee="usr", title="Обсуждение")
    token = await _agent_token(env, w, "usr")

    added = _payload(
        await _call(env, token, "add_comment", {"task_id": str(task), "body": "Готово к проверке"})
    )
    assert added["task_id"] == str(task)

    listed = _payload(await _call(env, token, "list_comments", {"task_id": str(task)}))
    assert [c["id"] for c in listed["items"]] == [added["id"]]


async def test_projects_visible_to_members_only(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    member_token = await _agent_token(env, w, "usr")
    outsider_token = await _agent_token(env, w, "usr2")

    listed = _payload(await _call(env, member_token, "list_projects", {}))
    assert str(w.project_id) in [p["id"] for p in listed["items"]]

    card = _payload(
        await _call(env, member_token, "get_project", {"project_id": str(w.project_id)})
    )
    assert card["name"] == "Основной"

    denied = await _call(env, outsider_token, "get_project", {"project_id": str(w.project_id)})
    assert _error_code(denied) == "forbidden"


async def test_invalid_arguments_are_validation_error(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    result = await _call(
        env, token, "create_task", {"project_id": str(w.project_id), "description": "нет названия"}
    )
    assert _error_code(result) == "validation_error"


async def test_unknown_project_id_is_not_leaked(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    result = await _call(env, token, "get_project", {"project_id": str(UUID(int=1))})
    assert result["isError"] is True
