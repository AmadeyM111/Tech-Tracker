"""R3-T02: БА-участник удаляет любые комментарии проекта (spec 002: AC-13, AC-15, FR-9, FR-10).

Шаги критериев повторяются буквально на фикстуре spec 002 §6 (``roles002_support``). Здесь только
комментарии; задачи и подзадачи (остаток AC-13, AC-14, AC-15) добавит R3-T03.
"""

from __future__ import annotations

from typing import Any

from tests.conftest import ApiEnv
from tests.projects_api_support import rows
from tests.roles002_support import (
    World002,
    error,
    make_world_002,
    members_url,
    send,
    snapshot,
)

TASKS = "/api/v1/tasks"
COMMENTS = "/api/v1/comments"


def _list_url(w: World002, task: str) -> str:
    return f"{TASKS}/{w.tasks[task]}/comments"


async def _comment(env: ApiEnv, w: World002, name: str) -> Any:
    found = await rows(
        env,
        "SELECT body, deleted_at, deleted_batch_id FROM comment WHERE id = :c",
        c=w.comments[name],
    )
    assert len(found) == 1
    return found[0]


# --- AC-13 -------------------------------------------------------------------------------


async def test_002_ac13_ba_member_deletes_foreign_comment_c1(api_env: ApiEnv) -> None:
    """AC-13 (FR-9): ba.member (участник P, не владелец, не автор) удаляет c1 (автор u1) -> 204,
    комментарий удалён мягко; c2 не тронут; в списке c1 - заглушка без текста."""
    env = api_env
    w = await make_world_002(env)
    before = await snapshot(env, w)
    assert (await _comment(env, w, "c1")).deleted_at is None

    r = await send(env, w.tok("ba.member"), "DELETE", f"{COMMENTS}/{w.comments['c1']}")

    assert r.status_code == 204, r.text
    c1 = await _comment(env, w, "c1")
    assert c1.deleted_at is not None
    assert c1.deleted_batch_id is not None
    assert (await _comment(env, w, "c2")).deleted_at is None
    assert (await _comment(env, w, "c3")).deleted_at is None
    after = await snapshot(env, w)
    assert after["events"] == before["events"]  # комментарии журнал не пишут (D-55)
    assert after["tasks"] == before["tasks"]

    r = await send(env, w.tok("u1"), "GET", _list_url(w, "T1"))
    assert r.status_code == 200, r.text
    items = {i["id"]: i for i in r.json()["items"]}
    assert items[str(w.comments["c1"])]["is_deleted"] is True
    assert items[str(w.comments["c1"])]["body"] is None
    assert items[str(w.comments["c2"])]["is_deleted"] is False


async def test_002_ac13_ba_member_comment_permissions_flag_delete_true(api_env: ApiEnv) -> None:
    """AC-13, FR-21: в списке комментариев T1 для ba.member delete=True у чужих c1 и c2,
    edit=False (правка только у автора); у u1 на чужой c2 delete=False (AC-16)."""
    env = api_env
    w = await make_world_002(env)

    r = await send(env, w.tok("ba.member"), "GET", _list_url(w, "T1"))
    assert r.status_code == 200, r.text
    perms = {i["id"]: i["permissions"] for i in r.json()["items"]}
    assert perms == {
        str(w.comments["c1"]): {"edit": False, "delete": True},
        str(w.comments["c2"]): {"edit": False, "delete": True},
    }

    r = await send(env, w.tok("u1"), "GET", _list_url(w, "T1"))
    perms = {i["id"]: i["permissions"] for i in r.json()["items"]}
    assert perms[str(w.comments["c1"])] == {"edit": True, "delete": True}
    assert perms[str(w.comments["c2"])] == {"edit": False, "delete": False}


async def test_002_ac13_ba_member_cannot_edit_foreign_comment_c1(api_env: ApiEnv) -> None:
    """FR-9: правка комментария остаётся за автором; ba.member правит c1 (автор u1) -> 403,
    данные не изменены."""
    env = api_env
    w = await make_world_002(env)
    before = await snapshot(env, w)

    r = await send(
        env, w.tok("ba.member"), "PATCH", f"{COMMENTS}/{w.comments['c1']}", {"body": "правка"}
    )

    assert error(r) == (403, "forbidden")
    assert await snapshot(env, w) == before


async def test_002_ac13_ba_owner_still_deletes_foreign_comment(api_env: ApiEnv) -> None:
    """AC-13 (регресс): владелец-БА по-прежнему удаляет чужой комментарий c2 (автор u2)."""
    env = api_env
    w = await make_world_002(env)

    r = await send(env, w.tok("ba.owner"), "DELETE", f"{COMMENTS}/{w.comments['c2']}")

    assert r.status_code == 204, r.text
    assert (await _comment(env, w, "c2")).deleted_at is not None


# --- AC-15 -------------------------------------------------------------------------------


async def test_002_ac15_ba_out_comments_denied_then_self_add_allows_reading(
    api_env: ApiEnv,
) -> None:
    """AC-15 (FR-10): ba.out не участник P - удаление c1 и чтение комментариев T1 -> 403, данные
    не изменены, журнал не пополнен. После самодобавления в P чтение комментариев T1 -> 200."""
    env = api_env
    w = await make_world_002(env)
    before = await snapshot(env, w)

    r = await send(env, w.tok("ba.out"), "DELETE", f"{COMMENTS}/{w.comments['c1']}")
    assert error(r) == (403, "forbidden")
    r = await send(env, w.tok("ba.out"), "GET", _list_url(w, "T1"))
    assert error(r) == (403, "forbidden")
    r = await send(
        env, w.tok("ba.out"), "PATCH", f"{COMMENTS}/{w.comments['c1']}", {"body": "правка"}
    )
    assert error(r) == (403, "forbidden")
    r = await send(env, w.tok("ba.out"), "POST", _list_url(w, "T1"), {"body": "новый"})
    assert error(r) == (403, "forbidden")
    assert await snapshot(env, w) == before
    assert (await _comment(env, w, "c1")).deleted_at is None

    r = await send(
        env, w.tok("ba.out"), "POST", members_url(w.project_id), {"user_id": str(w.uid("ba.out"))}
    )
    assert r.status_code == 204, r.text
    r = await send(env, w.tok("ba.out"), "GET", _list_url(w, "T1"))
    assert r.status_code == 200, r.text
    assert {i["id"] for i in r.json()["items"]} == {
        str(w.comments["c1"]),
        str(w.comments["c2"]),
    }


async def test_002_ac15_ba_out_deletes_comment_after_self_add(api_env: ApiEnv) -> None:
    """FR-9, FR-10: самодобавленный в P ba.out получает право участника - удаляет c1 -> 204."""
    env = api_env
    w = await make_world_002(env)
    r = await send(
        env, w.tok("ba.out"), "POST", members_url(w.project_id), {"user_id": str(w.uid("ba.out"))}
    )
    assert r.status_code == 204, r.text

    r = await send(env, w.tok("ba.out"), "DELETE", f"{COMMENTS}/{w.comments['c1']}")

    assert r.status_code == 204, r.text
    assert (await _comment(env, w, "c1")).deleted_at is not None
