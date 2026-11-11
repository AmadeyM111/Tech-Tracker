"""Спека 027, этап 2b: участники проекта у владельца-«Пользователя» (FR-2…FR-4, FR-7, FR-8).

Добавление по точному логину или email, удаление, выход, передача владения, лимиты (100 участников,
20 попыток в час), аудит неудач; отказ не-владельцу на каждом пути.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from tests.conftest import ApiEnv
from tests.projects_api_support import (
    PROJECTS,
    error,
    make_api_world,
    members_url,
    pj,
    send,
)

OWNER_URL = "/owner"


async def _mine(env: ApiEnv, w: Any, who: str = "usr2") -> str:
    r = await send(env, w.tok(who), "POST", PROJECTS, {"name": "Личный"})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _person(env: ApiEnv, w: Any, login: str, role: str | None = "user", **kw: Any) -> Any:
    return await env.new_user(workspace=w.ws, role=role, login=login, **kw)


async def _logins(env: ApiEnv, w: Any, pid: str, who: str = "usr2") -> list[str]:
    r = await send(env, w.tok(who), "GET", members_url(pid) + "?page_size=100")
    assert r.status_code == 200, r.text
    return [m["user"]["login"] for m in r.json()["items"]]


async def _events(env: ApiEnv, action: str) -> list[Any]:
    rows = await env.execute(
        text(
            "SELECT actor_id, entity_id, project_id, in_audit, details, changes "
            "FROM domain_event WHERE action = :a ORDER BY id"
        ).bindparams(a=action)
    )
    return list(rows or [])


# --- FR-4: добавление по логину и email ---------------------------------------------------------


async def test_027_owner_adds_by_login_case_insensitive_and_by_email(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    await _person(env, w, "Anna.K", email="anna.k@example.test")
    await _person(env, w, "boris", email="boris@example.test")

    by_login = await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": " ANNA.k "})
    by_email = await send(
        env, w.tok("usr2"), "POST", members_url(pid), {"email": "Boris@Example.Test"}
    )

    assert by_login.status_code == 204, by_login.text
    assert by_email.status_code == 204, by_email.text
    assert sorted(await _logins(env, w, pid), key=str.lower) == ["Anna.K", "boris", "w.usr2"]
    added = await _events(env, "member.added")
    assert len(added) == 2 and all(e.actor_id == w.uid("usr2") for e in added)


async def test_027_not_registered_is_422_recipient_not_found_and_failure_is_audited(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    before = await _logins(env, w, pid)

    r = await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": "nobody"})
    r2 = await send(env, w.tok("usr2"), "POST", members_url(pid), {"email": "no@example.test"})

    assert error(r) == (422, "recipient_not_found")
    assert error(r2) == (422, "recipient_not_found")
    assert await _logins(env, w, pid) == before
    failed = await _events(env, "user.member_add_failed")  # записаны, несмотря на 422
    assert len(failed) == 2
    assert all(e.actor_id == w.uid("usr2") and e.in_audit and e.project_id for e in failed)
    assert all(e.details is None and e.changes is None for e in failed)  # введённого значения нет


async def test_027_ta_norole_blocked_look_exactly_like_not_found(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    await _person(env, w, "x.blocked", blocked=True)
    await _person(env, w, "x.norole", role=None)
    await _person(env, w, "x.ta", role="tech_admin")
    for login in ("x.blocked", "x.norole", "x.ta", "w.ta", "w.blocked", "w.norole"):
        r = await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": login})
        assert error(r) == (422, "recipient_not_found"), login


async def test_027_other_workspace_user_is_not_found(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    await env.new_user(role="user", login="other.ws.user")  # своё пространство
    pid = await _mine(env, w)
    r = await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": "other.ws.user"})
    assert error(r) == (422, "recipient_not_found")


async def test_027_already_member_is_field_error_and_state_is_unchanged(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    await _person(env, w, "dup.user")
    assert (
        await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": "dup.user"})
    ).status_code == 204

    r = await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": "dup.user"})
    owner = await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": w.login("usr2")})

    assert error(r) == (422, "member_already_added")
    assert error(owner) == (422, "member_already_added")  # владелец уже в проекте
    assert len(await _events(env, "member.added")) == 1


async def test_027_body_needs_exactly_one_key_and_user_cannot_use_user_id(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    for body in (
        {},
        {"login": "a", "email": "a@b.c"},
        {"login": ""},
        {"login": "a", "user_id": str(w.uid("usr"))},
    ):
        r = await send(env, w.tok("usr2"), "POST", members_url(pid), body)
        assert error(r) == (422, "validation_error"), body
    by_id = await send(env, w.tok("usr2"), "POST", members_url(pid), {"user_id": str(w.uid("usr"))})
    assert error(by_id) == (422, "validation_error")
    # БА по-прежнему добавляет по user_id, а повтор — без ошибки (D-46)
    for _ in range(2):
        ok = await send(env, w.tok("ba"), "POST", members_url(pid), {"user_id": str(w.uid("usr"))})
        assert ok.status_code == 204, ok.text


async def test_027_business_admin_can_add_by_login_too(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("ba"), "POST", members_url(w.project_id), {"login": w.login("usr2")})
    assert r.status_code == 204, r.text


# --- FR-3: граница прав -------------------------------------------------------------------------


async def test_027_participant_cannot_manage_but_can_leave(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    await _person(env, w, "p.target")
    assert (
        await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": w.login("usr")})
    ).status_code == 204
    me = w.tok("usr")  # участник, не владелец

    assert error(await send(env, me, "POST", members_url(pid), {"login": "p.target"})) == (
        403,
        "forbidden",
    )
    assert error(await send(env, me, "DELETE", members_url(pid, w.uid("usr2")))) == (
        403,
        "forbidden",
    )
    assert error(await send(env, me, "PATCH", pj(pid), {"name": "Чужое"})) == (403, "forbidden")
    assert error(await send(env, me, "DELETE", pj(pid))) == (403, "forbidden")
    assert error(
        await send(env, me, "PUT", pj(pid) + OWNER_URL, {"user_id": str(w.uid("usr"))})
    ) == (403, "forbidden")
    detail = (await send(env, me, "GET", pj(pid))).json()
    assert (
        detail["permissions"]["manage_members"] is False
        and detail["permissions"]["remove_self"] is True
    )

    leave = await send(env, me, "DELETE", members_url(pid, w.uid("usr")))  # Q-11: выйти самому
    assert leave.status_code == 204, leave.text
    assert error(await send(env, me, "GET", pj(pid))) == (403, "forbidden")


async def test_027_stranger_cannot_touch_the_project_members(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    stranger = w.tok("usr")  # не участник проекта usr2
    assert error(await send(env, stranger, "POST", members_url(pid), {"login": "w.ba"})) == (
        403,
        "forbidden",
    )
    assert (await send(env, stranger, "DELETE", members_url(pid, w.uid("usr2")))).status_code == 403


# --- удаление, владелец, передача ---------------------------------------------------------------


async def test_027_owner_removes_member_and_task_assignee_is_cleared(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    await _person(env, w, "r.member")
    await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": "r.member"})
    uid = next(
        m["user"]["id"]
        for m in (await send(env, w.tok("usr2"), "GET", members_url(pid))).json()["items"]
        if m["user"]["login"] == "r.member"
    )
    task = await send(
        env,
        w.tok("usr2"),
        "POST",
        f"{PROJECTS}/{pid}/tasks",
        {"title": "Т", "description": "Д", "due_date": "2026-12-31", "assignee_id": uid},
    )
    assert task.status_code == 201, task.text

    gone = await send(env, w.tok("usr2"), "DELETE", members_url(pid, uid))

    assert gone.status_code == 204, gone.text
    assert "r.member" not in await _logins(env, w, pid)
    assert len(await _events(env, "member.removed")) == 1
    detail = (await send(env, w.tok("usr2"), "GET", f"/api/v1/tasks/{task.json()['id']}")).json()
    assert detail["assignee"] is None


async def test_027_owner_cannot_be_removed_or_leave_before_transfer(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    r = await send(env, w.tok("usr2"), "DELETE", members_url(pid, w.uid("usr2")))
    assert error(r) == (422, "owner_cannot_be_removed")  # Q-9
    assert w.login("usr2") in await _logins(env, w, pid)


async def test_027_owner_transfers_then_can_leave(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": w.login("usr")})
    ta = await send(env, w.tok("usr2"), "PUT", pj(pid) + OWNER_URL, {"user_id": str(w.uid("ta"))})
    assert error(ta) in {(422, "recipient_wrong_role"), (422, "not_project_member")}  # ТА — нельзя
    outsider = await send(
        env, w.tok("usr2"), "PUT", pj(pid) + OWNER_URL, {"user_id": str(w.uid("ba3"))}
    )
    assert error(outsider) == (422, "not_project_member")  # не участник — нельзя

    done = await send(
        env, w.tok("usr2"), "PUT", pj(pid) + OWNER_URL, {"user_id": str(w.uid("usr"))}
    )

    assert done.status_code == 200, done.text
    assert done.json()["owner"]["id"] == str(w.uid("usr"))
    transfers = await _events(env, "project.ownership_transferred")
    assert len(transfers) == 1 and transfers[0].actor_id == w.uid("usr2")
    # прежний владелец — рядовой участник: управлять не может, но выйти — да
    assert w.login("usr2") in await _logins(env, w, pid, "usr")
    old = (await send(env, w.tok("usr2"), "GET", pj(pid))).json()["permissions"]
    assert old["manage_members"] is False and old["remove_self"] is True
    out = await send(env, w.tok("usr2"), "DELETE", members_url(pid, w.uid("usr2")))
    assert out.status_code == 204, out.text


async def test_027_owner_renames_and_deletes_own_project(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    ren = await send(env, w.tok("usr2"), "PATCH", pj(pid), {"name": "Новое имя"})
    assert ren.status_code == 200 and ren.json()["name"] == "Новое имя"
    assert (await send(env, w.tok("usr2"), "DELETE", pj(pid))).status_code == 204
    assert error(await send(env, w.tok("usr2"), "GET", pj(pid))) in {
        (404, "not_found"),
        (403, "forbidden"),
    }


# --- лимиты (Q-4, Q-7) --------------------------------------------------------------------------


async def test_027_members_limit_is_100(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    async with env.sessionmaker() as session:
        from tests.factories import make_project_member, make_user

        for i in range(99):  # владелец уже 1 из 100
            user = await make_user(session, workspace=_ws(w), role="user", login=f"lim.{i:03d}")
            await make_project_member(
                session, project_id=_uuid(pid), user_id=user.id, workspace_id=w.ws.id
            )
        await session.commit()
    await _person(env, w, "lim.one.more")
    r = await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": "lim.one.more"})
    assert error(r) == (422, "limit_reached")


async def test_027_twenty_attempts_per_hour_for_user_not_for_ba(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await _mine(env, w)
    for i in range(20):  # неудачи тоже считаются: перебор адресов ограничен
        r = await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": f"ghost{i}"})
        assert error(r) == (422, "recipient_not_found")
    limited = await send(env, w.tok("usr2"), "POST", members_url(pid), {"login": "ghost-next"})
    assert limited.status_code == 429, limited.text
    assert limited.json()["code"] == "rate_limited"
    assert 3500 <= int(limited.headers["retry-after"]) <= 3601  # окно — час с первой попытки
    assert len(await _events(env, "user.member_add_failed")) == 20  # 21-я попытка не записана
    # БА лимитом не ограничен
    for i in range(22):
        r = await send(env, w.tok("ba"), "POST", members_url(w.project_id), {"login": f"ghost{i}"})
        assert error(r) == (422, "recipient_not_found")


def _ws(w: Any) -> Any:
    from tests.factories import WorkspaceRow

    return WorkspaceRow(id=w.ws.id, created_at=w.ws.created_at)


def _uuid(value: str) -> Any:
    import uuid

    return uuid.UUID(value)
