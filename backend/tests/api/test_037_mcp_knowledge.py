"""CD-08 / CD-09 / спека 037: MCP list/get/upsert_knowledge."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from tests.api.test_m20_t08_mcp_tools import _agent_token, _call, _error_code, _payload
from tests.conftest import ApiEnv
from tests.projects_api_support import ApiWorld, add_project, make_api_world


async def _count(env: ApiEnv, w: ApiWorld) -> int:
    rows = await env.execute(
        text("SELECT count(*) FROM knowledge_record WHERE workspace_id = :w").bindparams(w=w.ws.id)
    )
    assert rows is not None
    return int(rows[0][0])


def _decision(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "scope": "space",
        "type": "decision",
        "title": "Идём в соседние ДЦ",
        "body": "Эти дата-центры лежат",
    }
    body.update(over)
    return body


async def test_ac4_unstructured_without_type_writes_nothing(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    before = await _count(env, w)
    result = await _call(
        env,
        token,
        "upsert_knowledge",
        {"scope": "space", "title": "пересказ созвона", "body": "поговорили о ДЦ", "commit": True},
    )
    assert _error_code(result) == "knowledge_unstructured"
    assert await _count(env, w) == before


async def test_ac5_without_commit_writes_nothing(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba")
    before = await _count(env, w)
    result = await _call(env, token, "upsert_knowledge", _decision())
    assert result.get("isError") in (False, None), result
    body = _payload(result)
    assert body["committed"] is False
    assert body["record"] is None
    assert body["draft"]["type"] == "decision"
    assert await _count(env, w) == before


async def test_ac6_commit_writes_client_name(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ba", name="Claude Code")
    result = await _call(env, token, "upsert_knowledge", _decision(commit=True))
    assert result.get("isError") in (False, None), result
    body = _payload(result)
    assert body["committed"] is True
    record = body["record"]
    assert record["scope"] == "space"
    assert record["client_name"] == "Claude Code"
    rows = await env.execute(
        text("SELECT client_name, kind FROM knowledge_record WHERE id = :id").bindparams(
            id=UUID(str(record["id"]))
        )
    )
    assert rows is not None and rows[0][0] == "Claude Code" and rows[0][1] == "decision"


async def test_ac1_space_visible_to_other_project_member(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    await add_project(
        env, w.ws, w.people["usr2"].user, name="Второй", members=("usr2",), people=w.people
    )
    ba = await _agent_token(env, w, "ba", name="Claude Code")
    created = await _call(env, ba, "upsert_knowledge", _decision(commit=True))
    kid = _payload(created)["record"]["id"]
    usr2 = await _agent_token(env, w, "usr2")
    listed = await _call(env, usr2, "list_knowledge", {})
    assert listed.get("isError") in (False, None), listed
    ids = {item["id"] for item in _payload(listed)["items"]}
    assert kid in ids
    got = await _call(env, usr2, "get_knowledge", {"knowledge_id": kid})
    assert _payload(got)["title"] == "Идём в соседние ДЦ"


async def test_ac2_project_record_hidden_from_other_project(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    project_b = await add_project(
        env, w.ws, w.people["usr2"].user, name="Второй", members=("usr2",), people=w.people
    )
    ba = await _agent_token(env, w, "ba")
    created = await _call(
        env,
        ba,
        "upsert_knowledge",
        _decision(scope="project", project_id=str(w.project_id), commit=True),
    )
    kid = _payload(created)["record"]["id"]
    usr2 = await _agent_token(env, w, "usr2")
    listed = await _call(env, usr2, "list_knowledge", {"project_id": str(project_b)})
    assert listed.get("isError") in (False, None), listed
    ids = {item["id"] for item in _payload(listed)["items"]}
    assert kid not in ids
    got = await _call(env, usr2, "get_knowledge", {"knowledge_id": kid})
    assert _error_code(got) == "forbidden"


async def test_ac3_non_member_list_is_forbidden(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "usr2")
    result = await _call(env, token, "list_knowledge", {"project_id": str(w.project_id)})
    assert _error_code(result) in {"forbidden", "not_found"}
