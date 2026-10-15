"""T72: 404 или 403 для объектов проекта (FR-45a, OI-35, D-45, AC-94, AC-21).

- несуществующий, мягко удалённый и чужого пространства проект -> 404 для БА и СМ (тела
  совпадают: не отличить друг от друга);
- существующий проект, не видимый «Пользователю»-неучастнику -> 403 (карточка, участники,
  исключение участника: ``can_view_project`` проверяется раньше «цель не участник», решение
  архитектора по T71);
- ТА: 403 на любой id, в том числе несуществующий (AC-94).

Маршруты задач и доски проекта появятся в T77: проверки по ним пропускаются, пока маршрута
нет в приложении, и становятся обязательными с его появлением.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest

from tests.api.test_route_guards import _api_operations
from tests.conftest import ApiEnv
from tests.projects_api_support import (
    SOME_ID,
    add_project,
    error,
    make_api_world,
    make_foreign,
    members_url,
    pj,
    send,
)


def _calls(project_id: Any, user_id: Any) -> list[tuple[str, str, str, Any]]:
    """(метка, метод, URL, тело) всех маршрутов с проектом в пути."""
    return [
        ("card", "GET", pj(project_id), None),
        ("patch", "PATCH", pj(project_id), {"name": "x"}),
        ("owner", "PUT", f"{pj(project_id)}/owner", {"user_id": str(user_id)}),
        ("delete", "DELETE", pj(project_id), None),
        ("members", "GET", members_url(project_id), None),
        ("add", "POST", members_url(project_id), {"user_id": str(user_id)}),
        ("remove", "DELETE", members_url(project_id, user_id), None),
    ]


def _task_calls(env: ApiEnv, project_id: Any) -> list[tuple[str, str]]:
    present = {(m, re.sub(r"\{[^}]+\}", "{}", p)) for m, p in _api_operations(env)}
    out = []
    for suffix in ("tasks", "board"):
        if ("GET", f"/api/v1/projects/{{}}/{suffix}") in present:
            out.append(("GET", f"{pj(project_id)}/{suffix}"))
    return out


async def _foreign_project(env: ApiEnv) -> uuid.UUID:
    return (await make_foreign(env)).project_id


@pytest.mark.parametrize("who", ["ba", "ba2", "ba3", "sm", "sm_m"])
async def test_ac94_unknown_deleted_and_foreign_project_is_404_for_ba_and_sm(
    api_env: ApiEnv, who: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    deleted = await add_project(env, w.ws, w.people["ba"].user, name="Удалён", deleted=True)
    foreign = await _foreign_project(env)
    target = w.uid("usr")
    own = await send(env, w.tok(who), "GET", pj(w.project_id))
    assert own.status_code == 200, own.text  # маршруты существуют

    for label, project in (
        ("unknown", uuid.uuid4()),
        ("deleted", deleted),
        ("foreign", foreign),
    ):
        reference: dict[str, Any] | None = None
        for name, method, url, body in _calls(project, target):
            r = await send(env, w.tok(who), method, url, body)
            assert error(r) == (404, "not_found"), (label, name, r.text)
            if reference is None:
                reference = r.json()
            assert r.json() == reference  # одинаковое тело: объекты неразличимы


async def test_ac94_user_gets_404_for_unknown_deleted_and_foreign_project(api_env: ApiEnv) -> None:
    """Несуществующий проект «Пользователю»: 404; 403 — только у существующих."""
    env = api_env
    w = await make_api_world(env)
    deleted = await add_project(env, w.ws, w.people["ba"].user, name="Удалён", deleted=True)
    foreign = await _foreign_project(env)
    assert (await send(env, w.tok("usr"), "GET", pj(w.project_id))).status_code == 200

    for who in ("usr", "usr2"):
        for project in (uuid.uuid4(), deleted, foreign):
            for name, method, url, body in _calls(project, w.uid("usr")):
                r = await send(env, w.tok(who), method, url, body)
                assert error(r) == (404, "not_found"), (who, name, r.text)


async def test_ac94_tech_admin_gets_403_on_any_id(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    deleted = await add_project(env, w.ws, w.people["ba"].user, name="Удалён", deleted=True)
    foreign = await _foreign_project(env)

    for project in (w.project_id, uuid.uuid4(), deleted, foreign):
        for name, method, url, body in _calls(project, w.uid("usr")):
            r = await send(env, w.tok("ta"), method, url, body)
            assert error(r) == (403, "forbidden"), (project, name, r.text)


async def test_ac94_ta_unknown_id_card_is_403_not_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("ta"), "GET", pj(SOME_ID))
    assert error(r) == (403, "forbidden")


async def test_d45_user_non_member_gets_403_on_card_members_and_remove_not_404(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = w.project_id

    for name, method, url, body in _calls(pid, w.uid("usr")):
        r = await send(env, w.tok("usr2"), method, url, body)
        assert error(r) == (403, "forbidden"), (name, r.text)
    # исключение: и участника, и не участника, и случайный id — одинаково 403
    for target in (w.uid("usr"), w.uid("usr2"), uuid.uuid4()):
        r = await send(env, w.tok("usr2"), "DELETE", members_url(pid, target))
        assert error(r) == (403, "forbidden"), target


async def test_d45_user_non_member_403_body_is_same_for_every_route(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    bodies = []
    for _name, method, url, body in _calls(w.project_id, w.uid("usr")):
        r = await send(env, w.tok("usr2"), method, url, body)
        assert error(r) == (403, "forbidden"), (_name, r.text)
        bodies.append(r.json())
    assert all(b == bodies[0] for b in bodies)
    assert "Основной" not in str(bodies)
    assert w.login("ba") not in str(bodies)


async def test_d45_user_non_member_gets_403_on_tasks_and_board_when_routes_exist(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    calls = _task_calls(env, w.project_id)
    if not calls:
        pytest.skip("маршруты задач и доски проекта — T77")
    for method, url in calls:
        r = await send(env, w.tok("usr2"), method, url)
        assert error(r) == (403, "forbidden"), (method, url)
        r = await send(env, w.tok("ba3"), method, url)  # БА-неучастник: содержимое закрыто (AC-55)
        assert error(r) == (403, "forbidden"), (method, url)
        r = await send(env, w.tok("ba"), method, url)
        assert r.status_code == 200, (method, url, r.text)
        gone = await send(env, w.tok("ba"), method, url.replace(str(w.project_id), SOME_ID))
        assert error(gone) == (404, "not_found")


async def test_ac55_ba_non_member_card_is_200_but_content_routes_are_closed(
    api_env: ApiEnv,
) -> None:
    """Карточка и участники видны БА-неучастнику (D-45), изменения — нет."""
    env = api_env
    w = await make_api_world(env)
    assert (await send(env, w.tok("ba3"), "GET", pj(w.project_id))).status_code == 200
    assert (await send(env, w.tok("ba3"), "GET", members_url(w.project_id))).status_code == 200


async def test_ac21_other_workspace_project_is_404_not_403_even_for_user_and_ba(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)
    missing = uuid.uuid4()
    assert (await send(env, w.tok("usr"), "GET", pj(w.project_id))).status_code == 200

    for who in ("ba", "usr", "usr2", "sm"):
        for name, method, url, body in _calls(foreign.project_id, w.uid("usr")):
            r = await send(env, w.tok(who), method, url, body)
            ref = await send(
                env, w.tok(who), method, url.replace(str(foreign.project_id), str(missing)), body
            )
            assert error(r) == (404, "not_found"), (who, name)
            assert r.json() == ref.json()


# --- T77: задачи (AC-11, AC-94, AC-21, D-45) -------------------------------------------------


def _task_routes(task_id: Any, project_id: Any) -> list[tuple[str, str, str, Any]]:
    base = f"/api/v1/tasks/{task_id}"
    return [
        ("card", "GET", base, None),
        ("patch", "PATCH", base, {"title": "x"}),
        ("delete", "DELETE", base, None),
        ("subtask", "POST", f"{base}/subtasks", {"title": "x"}),
        ("list", "GET", f"{pj(project_id)}/tasks", None),
        ("create", "POST", f"{pj(project_id)}/tasks", {"title": "x"}),
    ]


async def test_t77_ac94_unknown_deleted_foreign_task_is_404_with_same_body(
    api_env: ApiEnv,
) -> None:
    from tests.tasks_api_support import mk

    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)
    deleted_task = await mk(env, w, deleted=True)
    dead_project = await add_project(env, w.ws, w.people["ba"].user, name="Удалён", deleted=True)
    in_dead = await mk(env, w, project_id=dead_project)
    foreign_task = (
        await send(env, foreign.ba_token, "POST", f"{pj(foreign.project_id)}/tasks", {"title": "Ч"})
    ).json()["id"]

    for who in ("ba", "ba2", "ba3", "sm", "sm_m", "usr", "usr2"):
        reference: Any = None
        for task_id in (uuid.uuid4(), deleted_task, in_dead, foreign_task):
            for name, method, url, body in _task_routes(task_id, w.project_id)[:4]:
                r = await send(env, w.tok(who), method, url, body)
                assert error(r) == (404, "not_found"), (who, task_id, name)
                reference = reference or r.json()
                assert r.json() == reference


async def test_t77_ac94_ta_gets_403_on_any_task_id(api_env: ApiEnv) -> None:
    from tests.tasks_api_support import mk

    env = api_env
    w = await make_api_world(env)
    real = await mk(env, w)
    for task_id in (real, uuid.uuid4()):
        for name, method, url, body in _task_routes(task_id, w.project_id):
            r = await send(env, w.tok("ta"), method, url, body)
            assert error(r) == (403, "forbidden"), name


async def test_t77_ac11_non_member_gets_403_for_existing_task_same_body(api_env: ApiEnv) -> None:
    from tests.tasks_api_support import mk

    env = api_env
    w = await make_api_world(env)
    real = await mk(env, w, title="Секрет-название")
    bodies = []
    for who in ("usr2", "ba3", "sm"):
        for name, method, url, body in _task_routes(real, w.project_id):
            r = await send(env, w.tok(who), method, url, body)
            assert error(r) == (403, "forbidden"), (who, name)
            bodies.append(r.json())
    assert all(b == bodies[0] for b in bodies)
    assert "Секрет-название" not in str(bodies)


async def test_t77_ac21_foreign_project_tasks_routes_are_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)
    for who in ("ba", "usr", "sm"):
        for _n, method, url, body in _task_routes(uuid.uuid4(), foreign.project_id)[4:]:
            r = await send(env, w.tok(who), method, url, body)
            assert error(r) == (404, "not_found"), (who, method)
