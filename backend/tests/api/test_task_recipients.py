"""T77: исполнитель задачи — получатель ``TASK_ASSIGNEE`` (AC-56, AC-74, FR-20, FR-70).

Одни и те же коды 422 на трёх входах: создание задачи, создание подзадачи, смена исполнителя.
Порядок проверок получателя: ``user_not_found`` -> ``user_blocked`` -> ``recipient_wrong_role``
-> ``not_project_member``. Данные при отказе не меняются.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    TASK_REQ,
    ApiWorld,
    add_member_row,
    add_project,
    error,
    extra_user,
    make_api_world,
    make_foreign,
    mk,
    project_tasks_url,
    rows,
    send,
    task_db,
    task_url,
)

ENTRIES = ("create", "subtask", "patch")


async def _bad_targets(env: ApiEnv, w: ApiWorld) -> dict[str, tuple[Any, str]]:
    """Получатель -> (UUID, ожидаемый код)."""
    foreign = await make_foreign(env)
    blocked_member = await extra_user(env, w, "user", "rc.blocked_member", blocked=True)
    norole_member = await extra_user(env, w, None, "rc.norole_member")
    ta_member = await extra_user(env, w, "tech_admin", "rc.ta_member")
    return {
        "unknown": (uuid.uuid4(), "user_not_found"),
        "foreign_workspace": (foreign.usr.id, "user_not_found"),
        "blocked_non_member": (w.uid("blocked"), "user_blocked"),
        "blocked_member": (blocked_member.user.id, "user_blocked"),
        "ta": (w.uid("ta"), "recipient_wrong_role"),
        "ta_member_row": (ta_member.user.id, "recipient_wrong_role"),
        "norole": (w.uid("norole"), "recipient_wrong_role"),
        "role_removed_member": (norole_member.user.id, "recipient_wrong_role"),
        "user_non_member": (w.uid("usr2"), "not_project_member"),
        "otp_non_member": (w.uid("otp"), "not_project_member"),
        "ba_non_member": (w.uid("ba3"), "not_project_member"),
    }


async def _call(env: ApiEnv, w: ApiWorld, entry: str, assignee: Any) -> tuple[Any, Any]:
    """Возвращает (ответ, id задачи-цели или None)."""
    token = w.tok("ba")
    value = str(assignee)
    if entry == "create":
        r = await send(
            env,
            token,
            "POST",
            project_tasks_url(w.project_id),
            {"title": "Т", **TASK_REQ, "assignee_id": value},
        )
        return r, None
    target = await mk(env, w, assignee="ba2", title="Цель")
    if entry == "subtask":
        r = await send(
            env, token, "POST", f"{task_url(target)}/subtasks", {"title": "П", "assignee_id": value}
        )
        return r, target
    r = await send(env, token, "PATCH", task_url(target), {"assignee_id": value})
    return r, target


@pytest.mark.parametrize("entry", ENTRIES)
async def test_ac56_ac74_invalid_recipients_give_422_with_distinct_codes(
    api_env: ApiEnv, entry: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    targets = await _bad_targets(env, w)
    failures: list[str] = []

    for label, (user_id, code) in targets.items():
        before = (await rows(env, "SELECT count(*) FROM task WHERE workspace_id = :w", w=w.ws.id))[
            0
        ][0]
        r, target = await _call(env, w, entry, user_id)
        if error(r) != (422, code):
            failures.append(f"{entry}/{label}: {r.status_code} {r.text[:80]} != {code}")
        after = (await rows(env, "SELECT count(*) FROM task WHERE workspace_id = :w", w=w.ws.id))[
            0
        ][0]
        expected_new = 1 if entry != "create" else 0  # цель патча/подзадачи создаётся в _call
        if after != before + expected_new:
            failures.append(f"{entry}/{label}: задача создана при 422")
        if (
            target is not None
            and entry == "patch"
            and (await task_db(env, target)).assignee_id != w.uid("ba2")
        ):
            failures.append(f"{entry}/{label}: исполнитель изменён при 422")
    assert failures == []


@pytest.mark.parametrize("entry", ENTRIES)
@pytest.mark.parametrize("who", ["ba", "ba2", "usr"])
async def test_ac56_members_with_business_roles_are_accepted(
    api_env: ApiEnv, entry: str, who: str
) -> None:
    env = api_env
    w = await make_api_world(env)

    r, _ = await _call(env, w, entry, w.uid(who))

    assert r.status_code in (200, 201), r.text
    assert r.json()["assignee"] == {"id": str(w.uid(who)), "login": w.login(who)}


async def test_ac74_member_whose_role_was_removed_stays_member_but_is_not_assignable(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    person = await extra_user(env, w, None, "rc.member_norole")
    members = await rows(
        env, "SELECT user_id FROM project_member WHERE project_id = :p", p=w.project_id
    )
    assert person.user.id in {m[0] for m in members}

    r, _ = await _call(env, w, "create", person.user.id)

    assert error(r) == (422, "recipient_wrong_role")


async def test_owner_without_member_row_is_a_valid_assignee(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    project = await add_project(
        env, w.ws, w.people["ba2"].user, name="Владелец без строки", owner_is_member=False
    )
    await add_member_row(env, w, w.people["ba"].user, project)

    r = await send(
        env,
        w.tok("ba"),
        "POST",
        project_tasks_url(project),
        {"title": "Владельцу", **TASK_REQ, "assignee_id": str(w.uid("ba2"))},
    )

    assert r.status_code == 201, r.text
    assert r.json()["assignee"]["id"] == str(w.uid("ba2"))


async def test_assignee_error_does_not_leak_foreign_user_data(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)

    r, _ = await _call(env, w, "create", foreign.usr.id)
    ref, _ = await _call(env, w, "create", uuid.uuid4())

    assert error(r) == (422, "user_not_found")
    assert r.json() == ref.json()  # неотличимо от несуществующего
    assert foreign.usr.login not in r.text


async def test_recipient_check_comes_after_permission_403_for_user(api_env: ApiEnv) -> None:
    """«Пользователь» назначает постороннего: сначала 403 (не может назначать других)."""
    env = api_env
    w = await make_api_world(env)

    r = await send(
        env,
        w.tok("usr"),
        "POST",
        project_tasks_url(w.project_id),
        {"title": "Т", **TASK_REQ, "assignee_id": str(w.uid("ta"))},
    )

    assert error(r) == (403, "forbidden")


async def test_assignee_null_is_valid_for_ba_on_subtask_patch_only(api_env: ApiEnv) -> None:
    """006/AC-20 (D-4), AC-27 (R6-T14): явный null исполнителя - 422 при создании задачи и при
    PATCH задачи верхнего уровня (задача не меняется); PATCH подзадачи от БА - 200."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr")
    sub = await mk(env, w, assignee="usr", parent=t)

    created = await send(
        env,
        w.tok("ba"),
        "POST",
        project_tasks_url(w.project_id),
        {"title": "Т", **TASK_REQ, "assignee_id": None},
    )
    patched_top = await send(env, w.tok("ba"), "PATCH", task_url(t), {"assignee_id": None})
    patched_sub = await send(env, w.tok("ba"), "PATCH", task_url(sub), {"assignee_id": None})

    assert error(created) == (422, "validation_error")
    assert error(patched_top) == (422, "validation_error")
    assert (await task_db(env, t)).assignee_id == w.uid("usr")
    assert patched_sub.status_code == 200 and patched_sub.json()["assignee"] is None
