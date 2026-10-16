"""T77: задачи заблокированного исполнителя (AC-42, AC-43, FR-5, ADR-0009).

Блокировка не снимает исполнителя и не удаляет задачу; переназначают владелец-БА и СМ-участник;
БА-участник не владелец и «Пользователь» — 403. Задача находится фильтром по исполнителю.
"""

from __future__ import annotations

from tests.admin_support import admin_call
from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    ApiWorld,
    error,
    extra_user,
    make_api_world,
    mk,
    project_tasks_url,
    send,
    task_db,
    task_url,
)


async def _block(env: ApiEnv, w: ApiWorld, who: str) -> None:
    r = await admin_call(env, w.tok("ta"), "block", w.uid(who))
    assert r.status_code in (200, 204), r.text


async def test_ac43_block_keeps_assignee_and_task_found_by_assignee_filter(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", title="Открытая")

    await _block(env, w, "usr")

    row = await task_db(env, t)
    assert (row.assignee_id, row.deleted_at) == (w.uid("usr"), None)
    r = await send(
        env, w.tok("ba"), "GET", project_tasks_url(w.project_id, f"?assignee_id={w.uid('usr')}")
    )
    assert r.status_code == 200, r.text
    assert [i["id"] for i in r.json()["items"]] == [str(t)]
    assert r.json()["items"][0]["assignee"]["id"] == str(w.uid("usr"))


async def test_ac43_ba_member_not_owner_gets_403_mixed_member_reassigns(api_env: ApiEnv) -> None:
    """Обращён по 002/AC-14 (FR-9, 001/FR-5): задачу заблокированного исполнителя переназначает
    БА-участник не владелец (ba2) -> 200, сохранено (раньше 403)."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr")
    await _block(env, w, "usr")
    body = {"assignee_id": str(w.uid("ba2"))}

    ok = await send(env, w.tok("ba2"), "PATCH", task_url(t), body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["assignee"]["id"] == str(w.uid("ba2"))
    assert (await task_db(env, t)).assignee_id == w.uid("ba2")


async def test_ac43_ba_member_reassigns_blocked_task_user_member_gets_403(
    api_env: ApiEnv,
) -> None:
    """002/AC-14: «Пользователь»-участник (второй П) и не участник (ba3) получают 403 при
    переназначении задачи заблокированного исполнителя, исполнитель остаётся прежним."""
    env = api_env
    w = await make_api_world(env)
    second = await extra_user(env, w, "user", "w.second.usr")
    t = await mk(env, w, assignee="usr")
    await _block(env, w, "usr")
    body = {"assignee_id": str(w.uid("ba2"))}

    for token in (second.token, w.tok("ba3")):
        denied = await send(env, token, "PATCH", task_url(t), body)
        assert error(denied) == (403, "forbidden")
        assert (await task_db(env, t)).assignee_id == w.uid("usr")


async def test_ac42_owner_reassigns_task_of_blocked_user_task_not_deleted(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr")
    await _block(env, w, "usr")

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"assignee_id": str(w.uid("ba2"))})

    assert r.status_code == 200, r.text
    row = await task_db(env, t)
    assert (row.assignee_id, row.deleted_at) == (w.uid("ba2"), None)


async def test_ac42_user_cannot_reassign_task_of_blocked_user(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    other = await extra_user(env, w, "user", "rb.other")
    t = await mk(env, w, assignee="usr")
    await _block(env, w, "usr")

    r = await send(env, other.token, "PATCH", task_url(t), {"assignee_id": str(other.user.id)})

    assert error(r) == (403, "forbidden")
    assert (await task_db(env, t)).assignee_id == w.uid("usr")


async def test_ac43_blocked_assignee_cannot_be_chosen_as_new_assignee(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="ba2")
    await _block(env, w, "usr")

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"assignee_id": str(w.uid("usr"))})

    assert error(r) == (422, "user_blocked")
    assert (await task_db(env, t)).assignee_id == w.uid("ba2")


async def test_ac43_other_fields_of_blocked_assignees_task_can_be_edited(api_env: ApiEnv) -> None:
    """Исполнитель остаётся: правка названия при неизменном исполнителе — не получатель."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", title="Было")
    await _block(env, w, "usr")

    r = await send(
        env,
        w.tok("ba"),
        "PATCH",
        task_url(t),
        {"title": "Стало", "assignee_id": str(w.uid("usr"))},  # то же значение — не изменение
    )

    assert r.status_code == 200, r.text
    row = await task_db(env, t)
    assert (row.title, row.assignee_id) == ("Стало", w.uid("usr"))
