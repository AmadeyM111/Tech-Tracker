"""CD-05 / спека 022: метка «ИИ» по domain_event.client_name, без is_agent."""

from __future__ import annotations

from sqlalchemy import text

from tests.api.test_m20_t07_mcp_core import _list_names
from tests.api.test_m20_t08_mcp_tools import _agent_token, _call, _payload
from tests.conftest import ApiEnv
from tests.projects_api_support import make_api_world, send
from tests.tasks_api_support import TASK_REQ, project_tasks_url, task_url


async def _mcp_task(env: ApiEnv, token: str, project_id: str, title: str, **extra: object) -> dict:
    result = await _call(
        env,
        token,
        "create_task",
        {
            "project_id": project_id,
            "title": title,
            "description": "Описание",
            "due_date": "2026-12-01",
            **extra,
        },
    )
    assert result.get("isError") in (False, None), result
    return dict(_payload(result))


async def test_ac1_card_last_client_name_from_mcp(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba", name="Claude Code")
    task = await _mcp_task(env, token, str(w.project_id), "От агента")
    assert task["last_client_name"] == "Claude Code"
    rest = await send(env, w.tok("ba"), "GET", task_url(task["id"]))
    assert rest.status_code == 200, rest.text
    assert rest.json()["last_client_name"] == "Claude Code"


async def test_ac2_list_and_board_mark_agent_not_web(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba", name="Claude Code")
    agent = await _mcp_task(env, token, str(w.project_id), "Агент")
    web = await send(
        env,
        w.tok("ba"),
        "POST",
        project_tasks_url(w.project_id),
        {"title": "Веб", **TASK_REQ},
    )
    assert web.status_code == 201, web.text
    web_id = web.json()["id"]
    listed = await send(env, w.tok("ba"), "GET", project_tasks_url(w.project_id))
    by_id = {item["id"]: item for item in listed.json()["items"]}
    assert by_id[agent["id"]]["last_client_name"] == "Claude Code"
    assert by_id[web_id]["last_client_name"] is None
    board = await send(env, w.tok("ba"), "GET", f"/api/v1/projects/{w.project_id}/board")
    cards = [c for col in board.json()["columns"] for c in col["tasks"]]
    names = {c["id"]: c["last_client_name"] for c in cards}
    assert names[agent["id"]] == "Claude Code"
    assert names[web_id] is None


async def test_ac3_human_status_clears_last_client_name(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba", name="Claude Code")
    task = await _mcp_task(env, token, str(w.project_id), "Сначала агент")
    patched = await send(
        env, w.tok("ba"), "PATCH", task_url(task["id"]), {"status": "in_progress"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["last_client_name"] is None
    listed = await send(env, w.tok("ba"), "GET", project_tasks_url(w.project_id))
    item = next(i for i in listed.json()["items"] if i["id"] == task["id"])
    assert item["last_client_name"] is None


async def test_ac4_assignee_client_survives_human_title_edit(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba", name="Claude Code")
    task = await _mcp_task(env, token, str(w.project_id), "Назначить")
    await _call(
        env,
        token,
        "update_task",
        {"task_id": task["id"], "assignee_id": str(w.uid("usr"))},
    )
    patched = await send(
        env, w.tok("ba"), "PATCH", task_url(task["id"]), {"title": "Новое имя"}
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["last_client_name"] is None
    assert body["assignee_client_name"] == "Claude Code"


async def test_ac5_no_is_agent_column(api_env: ApiEnv) -> None:
    rows = await api_env.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'app_user' AND column_name = 'is_agent'"
        )
    )
    assert rows == []


async def test_ac6_tools_list_has_no_admin_mutations(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    names = set(await _list_names(env, token))
    blocked = {
        "delete_task",
        "delete_project",
        "add_member",
        "remove_member",
        "assign_role",
        "create_user",
        "delete_user",
    }
    assert names.isdisjoint(blocked)
    assert "propose_entities" in names
