"""Спека 027, этап 1: «Пользователь» создаёт проекты и управляет задачами в своём проекте.

FR-1 (создание, владелец), FR-2 (задачи в своём проекте), лимит 30 (Q-4). Состав и параметры
проекта (этап 2) — в test_027_members_stage2.py. Отказ для не-владельца — на каждом пути.
"""

from __future__ import annotations

from typing import Any

from tests.conftest import ApiEnv
from tests.projects_api_support import (
    PROJECTS,
    error,
    make_api_world,
    members_url,
    pj,
    send,
)
from tests.tasks_api_support import project_tasks_url, task_url

DUE = "2026-12-31"


async def _new_project(env: ApiEnv, w: Any, who: str, name: str = "Личный") -> str:
    r = await send(env, w.tok(who), "POST", PROJECTS, {"name": name})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _add_member_by_ba(env: ApiEnv, w: Any, project_id: str, who: str) -> None:
    r = await send(env, w.tok("ba"), "POST", members_url(project_id), {"user_id": str(w.uid(who))})
    assert r.status_code in (200, 201, 204), r.text


def _task_body(title: str, assignee: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"title": title, "description": "Описание", "due_date": DUE}
    if assignee is not None:
        body["assignee_id"] = str(assignee)
    return body


# --- FR-1: создание проекта ---------------------------------------------------------------------


async def test_027_user_creates_project_and_becomes_owner(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("usr2"), "POST", PROJECTS, {"name": "Мой проект"})

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner"]["id"] == str(w.uid("usr2"))
    assert body["is_member"] is True
    assert body["permissions"]["create_task"] is True
    # Этап 2: владелец-«Пользователь» управляет составом и параметрами своего проекта.
    assert body["permissions"]["manage"] is True
    assert body["permissions"]["manage_members"] is True
    assert body["permissions"]["remove_self"] is False


async def test_027_otp_and_blocked_and_norole_cannot_create(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for who, expected in (
        ("ta", (403, "forbidden")),
        ("norole", (403, "no_role")),
        ("otp", (403, "password_change_required")),
    ):
        r = await send(env, w.tok(who), "POST", PROJECTS, {"name": "Нельзя"})
        assert error(r) == expected, who


# --- Q-4: лимит 30 на «Пользователя», без лимита для БА ----------------------------------------


async def test_027_user_project_limit_is_30(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for i in range(30):
        r = await send(env, w.tok("usr2"), "POST", PROJECTS, {"name": f"P{i}"})
        assert r.status_code == 201, (i, r.text)
    r = await send(env, w.tok("usr2"), "POST", PROJECTS, {"name": "Сверх лимита"})
    assert error(r) == (422, "limit_reached")


async def test_027_business_admin_has_no_project_limit(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for i in range(31):
        r = await send(env, w.tok("ba2"), "POST", PROJECTS, {"name": f"BA{i}"})
        assert r.status_code == 201, (i, r.text)


# --- FR-2: задачи в своём проекте ---------------------------------------------------------------


async def test_027_owner_user_assigns_task_to_member(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _new_project(env, w, "usr2")
    await _add_member_by_ba(env, w, pid, "usr")

    r = await send(
        env,
        w.tok("usr2"),
        "POST",
        project_tasks_url(pid),
        _task_body("Для участника", w.uid("usr")),
    )
    assert r.status_code == 201, r.text
    assert r.json()["assignee"]["id"] == str(w.uid("usr"))


async def test_027_owner_user_creates_task_for_self(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _new_project(env, w, "usr2")
    r = await send(env, w.tok("usr2"), "POST", project_tasks_url(pid), _task_body("Себе", None))
    assert r.status_code == 201, r.text


async def test_027_owner_user_edits_member_task(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _new_project(env, w, "usr2")
    await _add_member_by_ba(env, w, pid, "usr")
    created = await send(
        env, w.tok("usr2"), "POST", project_tasks_url(pid), _task_body("Чужая", w.uid("usr"))
    )
    tid = created.json()["id"]

    r = await send(
        env, w.tok("usr2"), "PATCH", task_url(tid), {"title": "Переименована владельцем"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Переименована владельцем"


async def test_027_non_owner_member_cannot_assign_others(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _new_project(env, w, "usr2")
    await _add_member_by_ba(env, w, pid, "usr")
    # usr — участник, не владелец: назначать другим нельзя
    r = await send(
        env, w.tok("usr"), "POST", project_tasks_url(pid), _task_body("Нельзя", w.uid("usr2"))
    )
    assert error(r) == (403, "forbidden")


async def test_027_non_owner_member_cannot_edit_owner_task(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _new_project(env, w, "usr2")
    await _add_member_by_ba(env, w, pid, "usr")
    created = await send(
        env, w.tok("usr2"), "POST", project_tasks_url(pid), _task_body("Владельца", None)
    )
    tid = created.json()["id"]
    r = await send(env, w.tok("usr"), "PATCH", task_url(tid), {"title": "Чужая правка"})
    assert error(r) == (403, "forbidden")


async def test_027_non_member_user_sees_no_task_of_user_project(api_env: ApiEnv) -> None:
    """Чужой «Пользователь» не видит ни проект, ни задачи (FR-6): usr — не участник."""
    env = api_env
    w = await make_api_world(env)
    pid = await _new_project(env, w, "usr2")
    created = await send(
        env, w.tok("usr2"), "POST", project_tasks_url(pid), _task_body("Личная", None)
    )
    tid = created.json()["id"]
    assert error(await send(env, w.tok("usr"), "GET", pj(pid))) == (403, "forbidden")
    assert error(await send(env, w.tok("usr"), "GET", task_url(tid))) == (403, "forbidden")


# --- FR-11: MCP ---------------------------------------------------------------------------------


async def test_027_mcp_user_creates_project_and_lists_it(api_env: ApiEnv) -> None:
    from tests.api.test_m20_t08_mcp_tools import _agent_token, _call, _payload

    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "usr2")
    created = _payload(await _call(env, token, "create_project", {"name": "Через MCP"}))
    assert created["owner"]["id"] == str(w.uid("usr2"))
    assert created["permissions"]["create_task"] is True
    listed = _payload(await _call(env, token, "list_projects", {}))
    assert created["id"] in [p["id"] for p in listed["items"]]


async def test_027_mcp_create_project_forbidden_for_tech_admin(api_env: ApiEnv) -> None:
    from tests.api.test_m20_t08_mcp_tools import _agent_token, _call, _error_code

    env = api_env
    w = await make_api_world(env)
    token = await _agent_token(env, w, "ta")
    result = await _call(env, token, "create_project", {"name": "Нельзя"})
    assert _error_code(result) == "forbidden"
