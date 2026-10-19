"""R3-T01: БА управляет любым проектом (spec 002: AC-11, AC-12, AC-16, AC-17, AC-18, AC-19).

Тесты повторяют шаги критериев буквально на фикстуре spec 002 §6 (``roles002_support``).
При отказах проверяется «данные не изменены, новых записей журнала нет».
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import ApiEnv
from tests.projects_api_support import member_ids, rows
from tests.roles002_support import (
    World002,
    error,
    make_world_002,
    members_url,
    owner_url,
    pj,
    send,
    snapshot,
)

TASKS = "/api/v1/tasks"
COMMENTS = "/api/v1/comments"


async def _project(env: ApiEnv, w: World002, project_id: Any = None) -> Any:
    found = await rows(
        env,
        "SELECT name, description, owner_id, deleted_at FROM project WHERE id = :p",
        p=project_id or w.project_id,
    )
    assert len(found) == 1
    return found[0]


async def _transfer_events(env: ApiEnv, w: World002) -> list[Any]:
    return await rows(
        env,
        "SELECT actor_id, entity_id, action FROM domain_event "
        "WHERE workspace_id = :w AND action = 'project.ownership_transferred' ORDER BY id",
        w=w.ws.id,
    )


# --- AC-11 -------------------------------------------------------------------------------


async def test_002_ac11_ba_outside_manages_name_members_and_himself(api_env: ApiEnv) -> None:
    """AC-11 (FR-8): ba.out не участник P - правка названия и описания, добавление u3,
    исключение u2 (u2 получает 403 на T1, исполнитель T1.1 пуст), добавление себя."""
    env = api_env
    w = await make_world_002(env)
    assert w.uid("ba.out") not in await member_ids(env, w.project_id)

    r = await send(
        env,
        w.tok("ba.out"),
        "PATCH",
        pj(w.project_id),
        {"name": "Новое название", "description": "Новое описание"},
    )
    assert r.status_code == 200, r.text
    row = await _project(env, w)
    assert (row.name, row.description) == ("Новое название", "Новое описание")

    r = await send(
        env, w.tok("ba.out"), "POST", members_url(w.project_id), {"user_id": str(w.uid("u3"))}
    )
    assert r.status_code == 204, r.text
    assert w.uid("u3") in await member_ids(env, w.project_id)

    r = await send(env, w.tok("ba.out"), "DELETE", members_url(w.project_id, w.uid("u2")))
    assert r.status_code == 204, r.text
    assert w.uid("u2") not in await member_ids(env, w.project_id)
    r = await send(env, w.tok("u2"), "GET", f"{TASKS}/{w.tasks['T1']}")
    assert error(r) == (403, "forbidden")
    sub = await rows(env, "SELECT assignee_id FROM task WHERE id = :t", t=w.tasks["T1.1"])
    assert sub[0][0] is None  # исполнитель T1.1 пуст
    r = await send(env, w.tok("ba.owner"), "GET", f"{TASKS}/{w.tasks['T1.1']}")
    assert r.status_code == 200, r.text
    assert r.json()["assignee"] is None

    # ba.out по-прежнему не участник: 403 на T1
    r = await send(env, w.tok("ba.out"), "GET", f"{TASKS}/{w.tasks['T1']}")
    assert error(r) == (403, "forbidden")

    r = await send(
        env, w.tok("ba.out"), "POST", members_url(w.project_id), {"user_id": str(w.uid("ba.out"))}
    )
    assert r.status_code == 204, r.text
    assert w.uid("ba.out") in await member_ids(env, w.project_id)


# --- AC-12 -------------------------------------------------------------------------------


async def test_002_ac12_ba_outside_transfers_ownership_with_audit_entry(api_env: ApiEnv) -> None:
    """AC-12 (FR-8, FR-11), часть 1: ba.out передаёт владение P участнику ba.member."""
    env = api_env
    w = await make_world_002(env)

    r = await send(
        env, w.tok("ba.out"), "PUT", owner_url(w.project_id), {"user_id": str(w.uid("ba.member"))}
    )

    assert r.status_code == 200, r.text
    assert r.json()["owner"]["id"] == str(w.uid("ba.member"))
    assert (await _project(env, w)).owner_id == w.uid("ba.member")
    entries = await _transfer_events(env, w)
    assert len(entries) == 1
    assert entries[0].actor_id == w.uid("ba.out")
    assert entries[0].entity_id == w.project_id


async def test_002_ac12_ba_outside_deletes_p2_softly_with_children(api_env: ApiEnv) -> None:
    """AC-12, часть 2: ba.out (не участник P2) удаляет P2; P2, T5, подзадача и комментарий
    для ba.owner и u1 - 404."""
    env = api_env
    w = await make_world_002(env, with_p2=True)
    assert w.p2_id is not None

    r = await send(env, w.tok("ba.out"), "DELETE", pj(w.p2_id))

    assert r.status_code == 204, r.text
    assert (await _project(env, w, w.p2_id)).deleted_at is not None  # мягкое удаление
    for who in ("ba.owner", "u1"):
        for url in (
            pj(w.p2_id),
            f"{TASKS}/{w.tasks['T5']}",
            f"{TASKS}/{w.tasks['T5.1']}",
            f"{TASKS}/{w.tasks['T5']}/comments",
        ):
            got = await send(env, w.tok(who), "GET", url)
            assert error(got) == (404, "not_found"), (who, url)
    got = await send(env, w.tok("u1"), "PATCH", f"{COMMENTS}/{w.comments['c5']}", {"body": "x"})
    assert error(got) == (404, "not_found")
    got = await send(env, w.tok("ba.owner"), "DELETE", f"{COMMENTS}/{w.comments['c5']}")
    assert error(got) == (404, "not_found")
    # P не затронут
    assert (await _project(env, w)).deleted_at is None


async def test_002_ac12_former_owner_deletes_project_after_transfer(api_env: ApiEnv) -> None:
    """AC-12, часть 3: после передачи владения ba.member прежний владелец ba.owner удаляет P
    (отмена ограничения 001/AC-52)."""
    env = api_env
    w = await make_world_002(env)
    r = await send(
        env, w.tok("ba.out"), "PUT", owner_url(w.project_id), {"user_id": str(w.uid("ba.member"))}
    )
    assert r.status_code == 200, r.text

    r = await send(env, w.tok("ba.owner"), "DELETE", pj(w.project_id))

    assert r.status_code == 204, r.text
    assert (await _project(env, w)).deleted_at is not None


# --- AC-16 -------------------------------------------------------------------------------


async def test_002_ac16_user_gets_403_everywhere_then_may_remove_himself(api_env: ApiEnv) -> None:
    """AC-16 (FR-12): u1 - участник P. Название, добавление/исключение другого, передача,
    удаление P, смена исполнителя своей T3, удаление c2 - 403, данные не изменены;
    исключение себя - выполнено."""
    env = api_env
    w = await make_world_002(env)
    before = await snapshot(env, w)
    tok = w.tok("u1")

    attempts: list[tuple[str, str, Any]] = [
        ("PATCH", pj(w.project_id), {"name": "Взлом"}),
        ("POST", members_url(w.project_id), {"user_id": str(w.uid("u3"))}),
        ("DELETE", members_url(w.project_id, w.uid("u2")), None),
        ("PUT", owner_url(w.project_id), {"user_id": str(w.uid("ba.member"))}),
        ("DELETE", pj(w.project_id), None),
        ("PATCH", f"{TASKS}/{w.tasks['T3']}", {"assignee_id": str(w.uid("u2"))}),
        ("DELETE", f"{COMMENTS}/{w.comments['c2']}", None),
    ]
    for method, url, body in attempts:
        r = await send(env, tok, method, url, body)
        assert error(r) == (403, "forbidden"), (method, url, r.text)
    assert await snapshot(env, w) == before

    r = await send(env, tok, "DELETE", members_url(w.project_id, w.uid("u1")))
    assert r.status_code == 204, r.text
    assert w.uid("u1") not in await member_ids(env, w.project_id)


@pytest.mark.parametrize("who", ["ta1", "u3"])
async def test_002_ac16_ta_and_non_member_user_get_403_on_project_management(
    api_env: ApiEnv, who: str
) -> None:
    """AC-16 (дополнительно): ТА и П не участник тоже не управляют проектом."""
    env = api_env
    w = await make_world_002(env)
    before = await snapshot(env, w)
    for method, url, body in (
        ("PATCH", pj(w.project_id), {"name": "Взлом"}),
        ("POST", members_url(w.project_id), {"user_id": str(w.uid("u3"))}),
        ("PUT", owner_url(w.project_id), {"user_id": str(w.uid("ba.member"))}),
        ("DELETE", pj(w.project_id), None),
    ):
        r = await send(env, w.tok(who), method, url, body)
        assert error(r) == (403, "forbidden"), (method, url)
    assert await snapshot(env, w) == before


# --- AC-17 -------------------------------------------------------------------------------


async def test_002_ac17_blocked_owner_replaced_by_any_ba_with_recipient_errors(
    api_env: ApiEnv,
) -> None:
    """AC-17 (FR-11): владелец ba.owner заблокирован. ba.out (не участник) передаёт владение
    ba.member - успех. Отдельная фикстура: u1 - 422 «не та роль», ba.blocked - 422
    «заблокирован», ba.free - 422 «не участник», ta1 - 403; владелец не меняется, журнал пуст."""
    env = api_env
    w = await make_world_002(env, with_ba_extra=True)
    from tests.projects_api_support import set_blocked

    await set_blocked(env, w.uid("ba.owner"))
    before = await snapshot(env, w)

    for target, expected in (
        ("u1", (422, "recipient_wrong_role")),
        ("ba.blocked", (422, "user_blocked")),
        ("ba.free", (422, "not_project_member")),
    ):
        r = await send(
            env, w.tok("ba.out"), "PUT", owner_url(w.project_id), {"user_id": str(w.uid(target))}
        )
        assert error(r) == expected, (target, r.text)
        assert (await _project(env, w)).owner_id == w.uid("ba.owner")
    r = await send(
        env, w.tok("ta1"), "PUT", owner_url(w.project_id), {"user_id": str(w.uid("ba.member"))}
    )
    assert error(r) == (403, "forbidden")
    assert (await _project(env, w)).owner_id == w.uid("ba.owner")
    assert await snapshot(env, w) == before
    assert await _transfer_events(env, w) == []

    r = await send(
        env, w.tok("ba.out"), "PUT", owner_url(w.project_id), {"user_id": str(w.uid("ba.member"))}
    )
    assert r.status_code == 200, r.text
    assert (await _project(env, w)).owner_id == w.uid("ba.member")


# --- AC-18 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "owner_role",
    [None, "user", "tech_admin"],
    ids=["role_removed", "role_user", "role_tech_admin"],
)
async def test_002_ac18_owner_without_ba_role_replaced_by_any_ba(
    api_env: ApiEnv, owner_role: str | None
) -> None:
    """AC-18 (FR-11): роль владельца снята / сменена на П / на ТА. ba.out (не участник)
    передаёт владение nr (роль снята) - 422 «не та роль», владелец прежний; ba.member - успех."""
    env = api_env
    w = await make_world_002(env, with_nr=True, owner_role=owner_role)
    before = await snapshot(env, w)

    r = await send(
        env, w.tok("ba.out"), "PUT", owner_url(w.project_id), {"user_id": str(w.uid("nr"))}
    )

    assert error(r) == (422, "recipient_wrong_role"), r.text
    assert (await _project(env, w)).owner_id == w.uid("ba.owner")
    assert await snapshot(env, w) == before
    assert await _transfer_events(env, w) == []

    r = await send(
        env, w.tok("ba.out"), "PUT", owner_url(w.project_id), {"user_id": str(w.uid("ba.member"))}
    )
    assert r.status_code == 200, r.text
    assert (await _project(env, w)).owner_id == w.uid("ba.member")


# --- AC-19 -------------------------------------------------------------------------------


async def test_002_ac19_ba_adds_himself_becomes_owner_and_owner_cannot_be_removed(
    api_env: ApiEnv,
) -> None:
    """AC-19 (FR-11): ba.out добавил себя в P и передал владение себе - владелец ba.out.
    Любой БА, исключающий текущего владельца, получает 422 «сначала передайте владение»."""
    env = api_env
    w = await make_world_002(env)
    r = await send(
        env, w.tok("ba.out"), "POST", members_url(w.project_id), {"user_id": str(w.uid("ba.out"))}
    )
    assert r.status_code == 204, r.text

    r = await send(
        env, w.tok("ba.out"), "PUT", owner_url(w.project_id), {"user_id": str(w.uid("ba.out"))}
    )

    assert r.status_code == 200, r.text
    assert r.json()["owner"]["id"] == str(w.uid("ba.out"))
    assert (await _project(env, w)).owner_id == w.uid("ba.out")

    before = await snapshot(env, w)
    for who in ("ba.member", "ba.owner", "ba.out"):
        r = await send(env, w.tok(who), "DELETE", members_url(w.project_id, w.uid("ba.out")))
        assert error(r) == (422, "owner_cannot_be_removed"), (who, r.text)
        assert "владение" in r.json()["detail"]
    assert await snapshot(env, w) == before
