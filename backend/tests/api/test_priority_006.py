"""R6-T07: три приоритета через API (spec 006 AC-12, AC-13, AC-18; FR-8, FR-9, NFR-1).

plan §4.1, PD-4: ``TaskPriority`` = ``low``/``medium``/``high``, умолчание при создании -
``medium``; ``base`` и прочее - 422 ``validation_error``.

Часы - фикстура ``fixed_clock`` (2026-10-13), а не ``CLOCK`` spec (2026-10-20): сдвиг часов на
неделю вперёд делает сессии мира недействительными (401). Тело ``FULL`` содержит описание и срок
позже «сегодня», поэтому тесты не зависят от R6-T13 (обязательные поля, срок не в прошлом).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    error,
    make_api_world,
    mk,
    project_tasks_url,
    rows,
    send,
    task_db,
    task_url,
)

FULL: dict[str, Any] = {"title": "Задача", "description": "Описание", "due_date": "2026-10-20"}
SUB_FULL: dict[str, Any] = {"title": "Подзадача"}
BAD_PRIORITIES = ["base", "urgent", "", "normal", "HIGH", "Medium"]


async def _create(env: ApiEnv, w: Any, body: dict[str, Any]) -> Any:
    return await send(env, w.tok("ba"), "POST", project_tasks_url(w.project_id), body)


async def _task_count(env: ApiEnv, project_id: Any) -> int:
    found = await rows(env, "SELECT count(*) FROM task WHERE project_id = :p", p=project_id)
    return int(found[0][0])


def _sub_url(task_id: Any) -> str:
    return f"{task_url(task_id)}/subtasks"


# --- AC-12: создание ---------------------------------------------------------------------


async def test_006_ac12_create_without_priority_is_medium(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _create(env, w, FULL)

    assert r.status_code == 201, r.text
    assert r.json()["priority"] == "medium"
    assert (await task_db(env, r.json()["id"])).priority == "medium"


@pytest.mark.parametrize("priority", ["low", "medium", "high"])
async def test_006_ac12_create_keeps_given_priority(api_env: ApiEnv, priority: str) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _create(env, w, {**FULL, "priority": priority})

    assert r.status_code == 201, r.text
    assert r.json()["priority"] == priority
    assert (await task_db(env, r.json()["id"])).priority == priority


@pytest.mark.parametrize("priority", BAD_PRIORITIES)
async def test_006_ac12_create_rejects_unknown_priority_and_creates_nothing(
    api_env: ApiEnv, priority: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _task_count(env, w.project_id)

    r = await _create(env, w, {**FULL, "priority": priority})

    assert error(r) == (422, "validation_error")
    assert await _task_count(env, w.project_id) == before


async def test_006_ac12_subtask_with_title_only_is_medium(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="Родитель", priority="high")

    r = await send(env, w.tok("ba"), "POST", _sub_url(parent), SUB_FULL)

    assert r.status_code == 201, r.text
    assert r.json()["priority"] == "medium"  # не наследует приоритет родителя
    assert (await task_db(env, r.json()["id"])).priority == "medium"


@pytest.mark.parametrize("priority", ["low", "high"])
async def test_006_ac12_subtask_keeps_given_priority(api_env: ApiEnv, priority: str) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="Родитель")

    r = await send(env, w.tok("ba"), "POST", _sub_url(parent), {**SUB_FULL, "priority": priority})

    assert r.status_code == 201, r.text
    assert r.json()["priority"] == priority


@pytest.mark.parametrize("priority", ["base", "urgent", ""])
async def test_006_ac12_subtask_rejects_unknown_priority(api_env: ApiEnv, priority: str) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="Родитель")
    before = await _task_count(env, w.project_id)

    r = await send(env, w.tok("ba"), "POST", _sub_url(parent), {**SUB_FULL, "priority": priority})

    assert error(r) == (422, "validation_error")
    assert await _task_count(env, w.project_id) == before


# --- AC-13: изменение --------------------------------------------------------------------


async def test_006_ac13_patch_sets_low(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Т", priority="high")

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"priority": "low"})

    assert r.status_code == 200, r.text
    assert r.json()["priority"] == "low"
    assert (await task_db(env, t)).priority == "low"


@pytest.mark.parametrize("priority", ["low", "medium", "high"])
async def test_006_ac13_patch_accepts_each_value(api_env: ApiEnv, priority: str) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Т", priority="medium" if priority != "medium" else "high")

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"priority": priority})

    assert r.status_code == 200, r.text
    assert (await task_db(env, t)).priority == priority


@pytest.mark.parametrize("priority", ["base", "urgent", ""])
async def test_006_ac13_patch_rejects_unknown_and_keeps_priority(
    api_env: ApiEnv, priority: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Т", priority="high")
    before = await task_db(env, t)

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"priority": priority})

    assert error(r) == (422, "validation_error")
    after = await task_db(env, t)
    assert (after.priority, after.updated_at) == ("high", before.updated_at)


async def test_006_ac13_patch_without_priority_does_not_change_it(api_env: ApiEnv) -> None:
    """Не переданный приоритет не меняется (умолчание ``medium`` у TaskUpdate - не значение)."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Т", priority="low")

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"title": "Новое"})

    assert r.status_code == 200, r.text
    assert (await task_db(env, t)).priority == "low"


# --- AC-18: OpenAPI ----------------------------------------------------------------------


def _resolve(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in node:
        return _resolve(spec, spec["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]])
    for key in ("allOf", "anyOf", "oneOf"):
        if key in node and len(node[key]) == 1:
            return _resolve(spec, node[key][0])
    return node


async def test_006_ac18_openapi_priority_enum_and_default(api_env: ApiEnv) -> None:
    spec = api_env.app.openapi()
    schemas = spec["components"]["schemas"]

    assert schemas["TaskPriority"]["enum"] == ["low", "medium", "high"]  # порядок FR-8
    create = schemas["TaskCreate"]["properties"]["priority"]
    assert create.get("default") == "medium"
    assert _resolve(spec, create)["enum"] == ["low", "medium", "high"]
    update = schemas["TaskUpdate"]["properties"]["priority"]
    assert _resolve(spec, update)["enum"] == ["low", "medium", "high"]
    assert "default" not in update  # поле необязательно, но «значения по умолчанию» нет
    for name in ("TaskDetail", "TaskListItem", "TaskBrief"):
        if name in schemas:
            prop = schemas[name]["properties"]["priority"]
            assert _resolve(spec, prop)["enum"] == ["low", "medium", "high"], name
