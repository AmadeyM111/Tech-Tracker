"""T72: ``/api/v1/projects`` — список, создание, карточка, правка, владелец, удаление.

AC-21, AC-51, AC-52, AC-55, AC-72, AC-75, AC-108, AC-110, AC-123, AC-124; FR-14…FR-17;
plan §11.4, D-45, D-46, D-52, D-65. Участники — ``test_project_members.py``.

Контракт ответов: ``ProjectDetail {id, name, description, owner{id, login}, task_count,
is_member, created_at, updated_at, permissions{manage, manage_members, create_task,
remove_self}}``; ``ProjectListItem {id, name, owner, task_count}`` (без ``status``);
``Page[T] {items, page, page_size, has_next}``.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from tests.api.test_route_guards import _api_operations
from tests.conftest import ApiEnv
from tests.db_support import BACKEND_DIR
from tests.projects_api_support import (
    DESC_10000,
    DETAIL_FIELDS,
    LIST_ITEM_FIELDS,
    NAME_255,
    PAGE_FIELDS,
    PERMISSION_FIELDS,
    PROJECTS,
    SOME_ID,
    USER_REF_FIELDS,
    add_member_row,
    add_project,
    add_task,
    error,
    event_count,
    make_api_world,
    make_foreign,
    pj,
    project_db,
    rows,
    send,
    set_blocked,
)

REPO_ROOT = BACKEND_DIR.parent


def _bad_json(token: str | None, env: ApiEnv, method: str, url: str) -> Any:
    return send(env, token, method, url, raw='{"name": "Секрет-проекта'.encode())


# --- GET /projects --------------------------------------------------------------------------


async def test_ac55_list_item_shape_owner_and_task_count_without_status(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    top = await add_task(env, w)
    await add_task(env, w)
    await add_task(env, w, parent_id=top)  # подзадача не считается
    await add_task(env, w, deleted=True)  # удалённая не считается

    r = await send(env, w.tok("ba"), "GET", PROJECTS)

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == PAGE_FIELDS
    assert (body["page"], body["page_size"], body["has_next"]) == (1, 50, False)
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert set(item) == LIST_ITEM_FIELDS  # ни status, ни description, ни задач
    assert item["id"] == str(w.project_id)
    assert item["name"] == "Основной"
    assert item["owner"] == {"id": str(w.uid("ba")), "login": w.login("ba")}
    assert item["task_count"] == 2


async def test_ac55_fr17_ba_and_sm_see_all_user_sees_only_membership_projects(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    other = await add_project(env, w.ws, w.people["ba2"].user, name="Чужой-для-usr")
    gone = await add_project(env, w.ws, w.people["ba2"].user, name="Удалён", deleted=True)

    everything = {str(w.project_id), str(other)}
    for who in ("ba", "ba2", "ba3", "sm", "sm_m"):
        r = await send(env, w.tok(who), "GET", PROJECTS)
        assert r.status_code == 200, (who, r.text)
        assert {i["id"] for i in r.json()["items"]} == everything, who
    r = await send(env, w.tok("usr"), "GET", PROJECTS)
    assert {i["id"] for i in r.json()["items"]} == {str(w.project_id)}
    r = await send(env, w.tok("usr2"), "GET", PROJECTS)
    assert r.json()["items"] == []
    assert str(gone) not in (await send(env, w.tok("sm"), "GET", PROJECTS)).text


async def test_fr17_order_is_lower_name_then_id(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for name in ("b-проект", "A-проект", "C-проект"):
        await add_project(env, w.ws, w.people["ba"].user, name=name)

    r = await send(env, w.tok("sm"), "GET", PROJECTS)

    assert [i["name"] for i in r.json()["items"]] == [
        "A-проект",
        "b-проект",
        "C-проект",
        "Основной",
    ]


async def test_fr47_pagination_has_next_and_second_page(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for n in range(2):
        await add_project(env, w.ws, w.people["ba"].user, name=f"П{n}")  # итого 3

    first = (await send(env, w.tok("ba"), "GET", f"{PROJECTS}?page_size=2")).json()
    second = (await send(env, w.tok("ba"), "GET", f"{PROJECTS}?page_size=2&page=2")).json()

    assert (len(first["items"]), first["has_next"], first["page_size"]) == (2, True, 2)
    assert (len(second["items"]), second["has_next"], second["page"]) == (1, False, 2)
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101", "page=x"])
async def test_fr47_invalid_page_params_are_422(api_env: ApiEnv, query: str) -> None:
    w = await make_api_world(api_env)
    r = await send(api_env, w.tok("ba"), "GET", f"{PROJECTS}?{query}")
    assert error(r) == (422, "validation_error")


async def test_ac75_list_gates(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    assert error(await send(env, w.tok("norole"), "GET", PROJECTS)) == (403, "no_role")
    assert error(await send(env, w.tok("otp"), "GET", PROJECTS)) == (
        403,
        "password_change_required",
    )
    assert error(await send(env, w.tok("ta"), "GET", PROJECTS)) == (403, "forbidden")
    assert error(await send(env, None, "GET", PROJECTS)) == (401, "not_authenticated")


async def test_ac21_list_has_no_projects_of_other_workspace(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)

    r = await send(env, w.tok("sm"), "GET", PROJECTS)
    own = await send(env, foreign.ba_token, "GET", PROJECTS)

    assert str(foreign.project_id) not in r.text
    assert "Чужой-проект" not in r.text
    assert [i["id"] for i in own.json()["items"]] == [str(foreign.project_id)]


# --- POST /projects -------------------------------------------------------------------------


async def test_ac51_create_with_name_only_owner_and_member_is_creator(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(env, w.tok("ba3"), "POST", PROJECTS, {"name": "Новый"})

    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == DETAIL_FIELDS
    assert set(body["permissions"]) == PERMISSION_FIELDS
    assert set(body["owner"]) == USER_REF_FIELDS
    assert body["owner"] == {"id": str(w.uid("ba3")), "login": w.login("ba3")}
    assert (body["name"], body["description"], body["task_count"]) == ("Новый", "", 0)
    assert body["is_member"] is True
    assert body["permissions"] == {
        "manage": True,
        "manage_members": True,
        "create_task": True,
        "remove_self": False,
    }
    members = await send(env, w.tok("ba3"), "GET", f"{PROJECTS}/{body['id']}/members")
    assert [m["user"]["id"] for m in members.json()["items"]] == [str(w.uid("ba3"))]
    assert members.json()["items"][0]["is_owner"] is True
    got = await send(env, w.tok("ba3"), "GET", pj(body["id"]))
    assert got.json() == body  # создание и чтение дают одну и ту же карточку


async def test_ac51_mixed_creates_project_as_owner_and_member(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("sm"), "POST", PROJECTS, {"name": "От СМ", "description": "Описание"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner"]["id"] == str(w.uid("sm"))
    assert body["description"] == "Описание"
    assert body["is_member"] is True


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        ("usr", (403, "forbidden")),
        ("ta", (403, "forbidden")),
        ("norole", (403, "no_role")),
        ("otp", (403, "password_change_required")),
    ],
)
async def test_fr14_create_gates(api_env: ApiEnv, who: str, expected: tuple[int, str]) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await rows(env, "SELECT count(*) FROM project WHERE workspace_id = :w", w=w.ws.id)

    r = await send(env, w.tok(who), "POST", PROJECTS, {"name": "Нельзя"})

    assert error(r) == expected
    after = await rows(env, "SELECT count(*) FROM project WHERE workspace_id = :w", w=w.ws.id)
    assert after == before


async def test_ac4_create_without_session_is_401(api_env: ApiEnv) -> None:
    r = await send(api_env, None, "POST", PROJECTS, {"name": "x"})
    assert error(r) == (401, "not_authenticated")


async def test_ac108_boundary_lengths_created_as_entered(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(
        env, w.tok("ba"), "POST", PROJECTS, {"name": NAME_255, "description": DESC_10000}
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == NAME_255
    assert r.json()["description"] == DESC_10000

    padded = "  Проект с пробелами  "  # D-52: хранится как введено, без обрезки
    r = await send(env, w.tok("ba"), "POST", PROJECTS, {"name": padded})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == padded
    assert (await project_db(env, r.json()["id"])).name == padded


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "\t\n "},
        {"name": "Я" * 256},
        {"name": "ok", "description": "д" * 10_001},
        {"name": None},
        {"name": 123},
        {"name": ["a"]},
    ],
    ids=["no-name", "empty", "spaces", "whitespace", "256", "desc-10001", "null", "int", "list"],
)
async def test_ac108_ac51_d52_invalid_create_is_422_and_nothing_created(
    api_env: ApiEnv, payload: dict[str, Any]
) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(env, w.tok("ba"), "POST", PROJECTS, payload)

    assert error(r) == (422, "validation_error")
    found = await rows(env, "SELECT count(*) FROM project WHERE workspace_id = :w", w=w.ws.id)
    assert found[0][0] == 1  # только исходный проект мира


async def test_ac123_create_broken_json_is_400_without_echo(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for token in (w.tok("ba"), None, w.tok("usr")):  # 400 раньше 401/403 (D-65)
        r = await _bad_json(token, env, "POST", PROJECTS)
        assert error(r) == (400, "bad_request"), token
        assert "Секрет-проекта" not in r.text
    found = await rows(env, "SELECT count(*) FROM project WHERE workspace_id = :w", w=w.ws.id)
    assert found[0][0] == 1


async def test_ac123_valid_json_wrong_fields_without_session_is_401_not_422(
    api_env: ApiEnv,
) -> None:
    r = await send(api_env, None, "POST", PROJECTS, {"name": 1})
    assert error(r) == (401, "not_authenticated")


# --- GET /projects/{id} ---------------------------------------------------------------------

# (is_member, manage, manage_members, create_task, remove_self)
CARD_MATRIX = {
    "ba": (True, True, True, True, False),  # владелец
    "ba2": (True, False, False, True, True),
    "ba3": (False, False, False, False, False),
    "sm": (False, True, True, False, False),
    "sm_m": (True, True, True, True, True),
    "usr": (True, False, False, True, True),
}


@pytest.mark.parametrize("who", sorted(CARD_MATRIX))
async def test_ac55_d45_card_fields_and_permissions_per_role(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    top = await add_task(env, w)
    await add_task(env, w, parent_id=top)
    await add_task(env, w, deleted=True)

    r = await send(env, w.tok(who), "GET", pj(w.project_id))

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == DETAIL_FIELDS
    assert set(body["permissions"]) == PERMISSION_FIELDS
    assert body["id"] == str(w.project_id)
    assert body["name"] == "Основной"
    assert body["owner"] == {"id": str(w.uid("ba")), "login": w.login("ba")}
    assert body["task_count"] == 1
    is_member, manage, manage_members, create_task, remove_self = CARD_MATRIX[who]
    assert body["is_member"] is is_member
    assert body["permissions"] == {
        "manage": manage,
        "manage_members": manage_members,
        "create_task": create_task,
        "remove_self": remove_self,
    }
    assert body["created_at"].endswith("Z") or "+00:00" in body["created_at"]


async def test_d45_user_non_member_gets_403_on_card(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("usr2"), "GET", pj(w.project_id))
    assert error(r) == (403, "forbidden")
    assert w.project_id.hex not in r.text.replace("-", "")
    assert "Основной" not in r.text


async def test_ac75_card_gates(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    url = pj(w.project_id)
    assert error(await send(env, w.tok("ta"), "GET", url)) == (403, "forbidden")
    assert error(await send(env, w.tok("norole"), "GET", url)) == (403, "no_role")
    assert error(await send(env, w.tok("otp"), "GET", url)) == (403, "password_change_required")
    assert error(await send(env, None, "GET", url)) == (401, "not_authenticated")


async def test_fr14_card_invalid_uuid_is_422(api_env: ApiEnv) -> None:
    w = await make_api_world(api_env)
    r = await send(api_env, w.tok("ba"), "GET", f"{PROJECTS}/not-a-uuid")
    assert error(r) == (422, "validation_error")


# --- PATCH /projects/{id} -------------------------------------------------------------------


async def test_ac110_owner_changes_name_and_description(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(
        env,
        w.tok("ba"),
        "PATCH",
        pj(w.project_id),
        {"name": "Новое название", "description": "Новое описание"},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == DETAIL_FIELDS
    assert (body["name"], body["description"]) == ("Новое название", "Новое описание")
    got = await send(env, w.tok("usr"), "GET", pj(w.project_id))
    assert got.json()["name"] == "Новое название"
    assert got.json()["owner"]["id"] == str(w.uid("ba"))


async def test_ac110_partial_patch_changes_only_given_field(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    await send(env, w.tok("ba"), "PATCH", pj(w.project_id), {"description": "Описание"})

    r = await send(env, w.tok("sm"), "PATCH", pj(w.project_id), {"name": "Только имя"})

    assert r.status_code == 200, r.text  # СМ, не участник (AC-110)
    assert (r.json()["name"], r.json()["description"]) == ("Только имя", "Описание")
    assert r.json()["is_member"] is False


@pytest.mark.parametrize("who", ["ba2", "ba3", "usr", "usr2", "ta"])
async def test_ac110_other_roles_get_403_and_project_is_untouched(
    api_env: ApiEnv, who: str
) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(env, w.tok(who), "PATCH", pj(w.project_id), {"name": "Взлом"})

    assert error(r) == (403, "forbidden")
    assert (await project_db(env, w.project_id)).name == "Основной"


async def test_d46_empty_and_same_value_patch_change_nothing(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await project_db(env, w.project_id)
    env.clock.advance(timedelta(hours=1))  # иначе «не изменился» проверяется вхолостую

    for payload in ({}, {"name": "Основной"}, {"name": "Основной", "description": ""}):
        r = await send(env, w.tok("ba"), "PATCH", pj(w.project_id), payload)
        assert r.status_code == 200, (payload, r.text)
        assert r.json()["name"] == "Основной"

    after = await project_db(env, w.project_id)
    assert after.updated_at == before.updated_at
    assert after.name == before.name


async def test_ac108_patch_boundaries_and_rejections(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    url = pj(w.project_id)

    ok = await send(env, w.tok("ba"), "PATCH", url, {"name": NAME_255, "description": DESC_10000})
    assert ok.status_code == 200, ok.text
    assert ok.json()["name"] == NAME_255

    for payload in (
        {"name": "Я" * 256},
        {"description": "д" * 10_001},
        {"name": ""},
        {"name": "   "},
    ):
        r = await send(env, w.tok("ba"), "PATCH", url, payload)
        assert error(r) == (422, "validation_error"), payload
    row = await project_db(env, w.project_id)
    assert (row.name, row.description) == (NAME_255, DESC_10000)  # данные не изменены


async def test_d52_patch_name_stored_as_entered(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("ba"), "PATCH", pj(w.project_id), {"name": "  с пробелами "})
    assert r.status_code == 200
    assert (await project_db(env, w.project_id)).name == "  с пробелами "


async def test_ac123_patch_broken_json_is_400(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for token in (w.tok("ba"), None):
        r = await _bad_json(token, env, "PATCH", pj(w.project_id))
        assert error(r) == (400, "bad_request")
        assert "Секрет-проекта" not in r.text
    assert (await project_db(env, w.project_id)).name == "Основной"


# --- PUT /projects/{id}/owner ---------------------------------------------------------------


def _owner(url_project: Any) -> str:
    return f"{pj(url_project)}/owner"


async def test_ac52_owner_transfers_to_member_ba_and_loses_delete_right(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(env, w.tok("ba"), "PUT", _owner(w.project_id), {"user_id": str(w.uid("ba2"))})

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == DETAIL_FIELDS
    assert body["owner"] == {"id": str(w.uid("ba2")), "login": w.login("ba2")}
    assert body["permissions"]["manage"] is False  # для бывшего владельца
    assert body["permissions"]["remove_self"] is True
    gone = await send(env, w.tok("ba"), "DELETE", pj(w.project_id))
    assert error(gone) == (403, "forbidden")  # AC-52
    assert (await project_db(env, w.project_id)).owner_id == w.uid("ba2")
    # новый владелец может удалить
    assert (await send(env, w.tok("ba2"), "DELETE", pj(w.project_id))).status_code == 204


async def test_ac52_ac72_mixed_non_member_transfers_even_if_owner_blocked(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    await set_blocked(env, w.uid("ba"))  # владелец заблокирован

    r = await send(env, w.tok("sm"), "PUT", _owner(w.project_id), {"user_id": str(w.uid("ba2"))})

    assert r.status_code == 200, r.text
    assert r.json()["owner"]["id"] == str(w.uid("ba2"))
    assert r.json()["is_member"] is False
    assert r.json()["permissions"]["manage"] is True


async def test_ac52_transfer_to_mixed_member_is_allowed(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("ba"), "PUT", _owner(w.project_id), {"user_id": str(w.uid("sm_m"))})
    assert r.status_code == 200, r.text
    assert r.json()["owner"]["id"] == str(w.uid("sm_m"))


async def test_t71_review_transfer_when_owner_has_no_member_row(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    pid = await add_project(
        env,
        w.ws,
        w.people["ba2"].user,
        name="Без строки владельца",
        members=["usr"],
        people=w.people,
        owner_is_member=False,
    )
    await add_member_row(env, w, w.people["ba3"].user, pid)

    r = await send(env, w.tok("ba2"), "PUT", _owner(pid), {"user_id": str(w.uid("ba3"))})

    assert r.status_code == 200, r.text
    assert r.json()["owner"]["id"] == str(w.uid("ba3"))


@pytest.mark.parametrize("who", ["ba2", "ba3", "usr", "usr2", "ta"])
async def test_ac52_non_owner_roles_get_403_on_transfer(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok(who), "PUT", _owner(w.project_id), {"user_id": str(w.uid("ba2"))})
    assert error(r) == (403, "forbidden")
    assert (await project_db(env, w.project_id)).owner_id == w.uid("ba")


async def test_d46_transfer_to_current_owner_is_200_without_event(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    before_events = await event_count(env, w.ws.id)

    r = await send(env, w.tok("ba"), "PUT", _owner(w.project_id), {"user_id": str(w.uid("ba"))})

    assert r.status_code == 200, r.text
    assert r.json()["owner"]["id"] == str(w.uid("ba"))
    assert await event_count(env, w.ws.id) == before_events


async def _extra_user(env: ApiEnv, w: Any, role: str | None, login: str, **kw: Any) -> Any:
    from tests.admin_support import seed

    user, _ = await seed(env, w.ws, role, login=login, **kw)
    return user


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("usr", "recipient_wrong_role"),  # «Пользователь» — участник, но не владелец
        ("ta", "recipient_wrong_role"),
        ("norole_member", "recipient_wrong_role"),
        ("blocked_member", "user_blocked"),
        ("ba3", "not_project_member"),
        ("unknown", "user_not_found"),
        ("foreign", "user_not_found"),
    ],
)
async def test_ac52_ac74_transfer_recipient_errors_are_422_owner_unchanged(
    api_env: ApiEnv, target: str, code: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    if target == "norole_member":
        user = await _extra_user(env, w, None, "m.norole")
        await add_member_row(env, w, user)
        target_id = str(user.id)
    elif target == "blocked_member":
        user = await _extra_user(env, w, "business_admin", "m.blocked", blocked=True)
        await add_member_row(env, w, user)
        target_id = str(user.id)
    elif target == "unknown":
        target_id = SOME_ID
    elif target == "foreign":
        target_id = str((await make_foreign(env)).ba.id)
    else:
        target_id = str(w.uid(target))
    before_events = await event_count(env, w.ws.id)

    r = await send(env, w.tok("ba"), "PUT", _owner(w.project_id), {"user_id": target_id})

    assert error(r) == (422, code), r.text
    assert (await project_db(env, w.project_id)).owner_id == w.uid("ba")
    assert await event_count(env, w.ws.id) == before_events


@pytest.mark.parametrize("payload", [{}, {"user_id": None}, {"user_id": "nope"}, {"user_id": 5}])
async def test_ac52_transfer_invalid_body_is_422(api_env: ApiEnv, payload: dict[str, Any]) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("ba"), "PUT", _owner(w.project_id), payload)
    assert error(r) == (422, "validation_error")


async def test_ac123_transfer_broken_json_is_400(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await _bad_json(w.tok("ba"), env, "PUT", _owner(w.project_id))
    assert error(r) == (400, "bad_request")
    assert (await project_db(env, w.project_id)).owner_id == w.uid("ba")


# --- DELETE /projects/{id} ------------------------------------------------------------------


async def test_ac48_owner_deletes_204_then_404_everywhere_and_cascade(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    task = await add_task(env, w, assignee=w.uid("usr"), with_comment=True)
    sub = await add_task(env, w, parent_id=task)

    r = await send(env, w.tok("ba"), "DELETE", pj(w.project_id))

    assert r.status_code == 204
    assert r.content == b""
    for who in ("ba", "sm", "usr"):
        for method, url in (
            ("GET", pj(w.project_id)),
            ("DELETE", pj(w.project_id)),
            ("GET", f"{pj(w.project_id)}/members"),
        ):
            again = await send(env, w.tok(who), method, url)
            assert error(again) == (404, "not_found"), (who, method, url)
    listed = await send(env, w.tok("ba"), "GET", PROJECTS)
    assert listed.json()["items"] == []
    stamped = await rows(
        env,
        "SELECT t.deleted_at, t.deleted_batch_id, p.deleted_batch_id FROM task t, project p "
        "WHERE p.id = :p AND t.id IN (:a, :b)",
        p=w.project_id,
        a=task,
        b=sub,
    )
    assert len(stamped) == 2
    for task_deleted, task_batch, project_batch in stamped:
        assert task_deleted is not None
        assert task_batch == project_batch  # один пакет D-56
    comments = await rows(env, "SELECT deleted_at FROM comment WHERE task_id = :t", t=task)
    assert comments and all(c[0] is not None for c in comments)


async def test_ac48_mixed_non_member_can_delete(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("sm"), "DELETE", pj(w.project_id))
    assert r.status_code == 204


@pytest.mark.parametrize("who", ["ba2", "ba3", "usr", "usr2", "ta"])
async def test_ac48_other_roles_get_403_on_delete(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok(who), "DELETE", pj(w.project_id))
    assert error(r) == (403, "forbidden")
    assert (await project_db(env, w.project_id)).deleted_at is None


# --- матрица роль x маршрут (все маршруты проектов и участников) ---------------------------

# маршрут -> роль -> код успеха или 403; тело и URL строятся ниже
ROUTES = ("card", "patch", "owner", "delete", "members", "add", "remove")
OK, NO = "ok", "403"
MATRIX: dict[str, dict[str, str]] = {
    #         ba    ba2   ba3   sm    sm_m  usr   usr2  ta
    "card": dict(ba=OK, ba2=OK, ba3=OK, sm=OK, sm_m=OK, usr=OK, usr2=NO, ta=NO),
    "patch": dict(ba=OK, ba2=NO, ba3=NO, sm=OK, sm_m=OK, usr=NO, usr2=NO, ta=NO),
    "owner": dict(ba=OK, ba2=NO, ba3=NO, sm=OK, sm_m=OK, usr=NO, usr2=NO, ta=NO),
    "delete": dict(ba=OK, ba2=NO, ba3=NO, sm=OK, sm_m=OK, usr=NO, usr2=NO, ta=NO),
    "members": dict(ba=OK, ba2=OK, ba3=OK, sm=OK, sm_m=OK, usr=OK, usr2=NO, ta=NO),
    "add": dict(ba=OK, ba2=NO, ba3=NO, sm=OK, sm_m=OK, usr=NO, usr2=NO, ta=NO),
    "remove": dict(ba=OK, ba2=NO, ba3=NO, sm=OK, sm_m=OK, usr=OK, usr2=NO, ta=NO),
}
SUCCESS = {
    "card": 200,
    "patch": 200,
    "owner": 200,
    "delete": 204,
    "members": 200,
    "add": 204,
    "remove": 204,
}


@pytest.mark.parametrize("who", ["ba", "ba2", "ba3", "sm", "sm_m", "usr", "usr2", "ta"])
@pytest.mark.parametrize("route", ROUTES)
async def test_matrix_role_x_route(api_env: ApiEnv, route: str, who: str) -> None:
    """AC-48, AC-52, AC-54, AC-55, AC-73, AC-110, D-45."""
    env = api_env
    w = await make_api_world(env)
    pid = w.project_id
    calls: dict[str, tuple[str, str, Any]] = {
        "card": ("GET", pj(pid), None),
        "patch": ("PATCH", pj(pid), {"name": "Матрица"}),
        "owner": ("PUT", _owner(pid), {"user_id": str(w.uid("ba"))}),
        "delete": ("DELETE", pj(pid), None),
        "members": ("GET", f"{pj(pid)}/members", None),
        "add": ("POST", f"{pj(pid)}/members", {"user_id": str(w.uid("usr2"))}),
        "remove": ("DELETE", f"{pj(pid)}/members/{w.uid('usr')}", None),
    }
    method, url, body = calls[route]

    r = await send(env, w.tok(who), method, url, body)

    if MATRIX[route][who] == OK:
        assert r.status_code == SUCCESS[route], (route, who, r.text)
    else:
        assert error(r) == (403, "forbidden"), (route, who, r.text)


# --- 401/403 гейтов по всем маршрутам ------------------------------------------------------

ROUTE_TABLE: list[tuple[str, str, Any]] = [
    ("GET", PROJECTS, None),
    ("POST", PROJECTS, {"name": "x"}),
    ("GET", f"{PROJECTS}/{SOME_ID}", None),
    ("PATCH", f"{PROJECTS}/{SOME_ID}", {"name": "x"}),
    ("PUT", f"{PROJECTS}/{SOME_ID}/owner", {"user_id": SOME_ID}),
    ("DELETE", f"{PROJECTS}/{SOME_ID}", None),
    ("GET", f"{PROJECTS}/{SOME_ID}/members", None),
    ("POST", f"{PROJECTS}/{SOME_ID}/members", {"user_id": SOME_ID}),
    ("DELETE", f"{PROJECTS}/{SOME_ID}/members/{SOME_ID}", None),
]


@pytest.mark.parametrize(("method", "url", "body"), ROUTE_TABLE)
async def test_ac75_ac4_gates_on_every_project_route(
    api_env: ApiEnv, method: str, url: str, body: Any
) -> None:
    env = api_env
    w = await make_api_world(env)
    assert error(await send(env, None, method, url, body)) == (401, "not_authenticated")
    assert error(await send(env, w.tok("norole"), method, url, body)) == (403, "no_role")
    assert error(await send(env, w.tok("otp"), method, url, body)) == (
        403,
        "password_change_required",
    )
    assert error(await send(env, w.tok("ta"), method, url, body)) == (403, "forbidden")  # AC-94


# --- AC-124: 503 -----------------------------------------------------------------------------


async def test_ac124_busy_project_row_gives_503_service_busy_on_mutations(
    committed_api_env: ApiEnv,
) -> None:
    """Строка проекта занята другой транзакцией: изменяющие маршруты -> 503, ``Retry-After: 5``."""
    env = committed_api_env
    w = await make_api_world(env)
    pid = w.project_id
    engine = env.sessionmaker.kw["bind"]
    async with engine.connect() as conn:
        db_name = (await conn.execute(text("SELECT current_database()"))).scalar_one()
    assert str(db_name).endswith("_test")
    quoted = '"' + str(db_name) + '"'
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"ALTER DATABASE {quoted} SET lock_timeout = '300ms'"))
    await engine.dispose()  # новые соединения подхватят lock_timeout
    try:
        holder = env.sessionmaker()
        await holder.begin()
        await holder.execute(
            text("SELECT id FROM project WHERE id = :p FOR UPDATE").bindparams(p=pid)
        )
        try:
            calls = [
                ("PATCH", pj(pid), {"name": "Занято"}),
                ("PUT", _owner(pid), {"user_id": str(w.uid("ba2"))}),
                ("DELETE", pj(pid), None),
                ("POST", f"{pj(pid)}/members", {"user_id": str(w.uid("usr2"))}),
                ("DELETE", f"{pj(pid)}/members/{w.uid('usr')}", None),
            ]
            for method, url, body in calls:
                r = await send(env, w.tok("ba"), method, url, body)
                assert r.status_code == 503, (method, url, r.text)
                assert r.headers.get("retry-after") == "5"
                assert r.json()["code"] == "service_busy"
        finally:
            await holder.rollback()
            await holder.close()
        row = await project_db(env, pid)
        assert (row.name, row.owner_id, row.deleted_at) == ("Основной", w.uid("ba"), None)
        assert w.uid("usr") in {
            r[0]
            for r in await rows(
                env, "SELECT user_id FROM project_member WHERE project_id = :p", p=pid
            )
        }
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f"ALTER DATABASE {quoted} RESET lock_timeout"))
        await engine.dispose()


# --- контракт: OpenAPI и маршруты -----------------------------------------------------------

EXPECTED_OPERATIONS: set[tuple[str, str]] = {
    ("GET", "/api/v1/projects"),
    ("POST", "/api/v1/projects"),
    ("GET", "/api/v1/projects/{project_id}"),
    ("PATCH", "/api/v1/projects/{project_id}"),
    ("DELETE", "/api/v1/projects/{project_id}"),
    ("PUT", "/api/v1/projects/{project_id}/owner"),
    ("GET", "/api/v1/projects/{project_id}/members"),
    ("POST", "/api/v1/projects/{project_id}/members"),
    ("DELETE", "/api/v1/projects/{project_id}/members/{user_id}"),
    # T77: задачи проекта (подробно — test_tasks.py, test_project_task_list.py)
    ("GET", "/api/v1/projects/{project_id}/tasks"),
    ("POST", "/api/v1/projects/{project_id}/tasks"),
    ("GET", "/api/v1/projects/{project_id}/board"),  # T78
}


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _operations(env: ApiEnv) -> dict[tuple[str, str], dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for path, item in env.app.openapi()["paths"].items():
        if path.startswith("/api/v1/projects"):
            for method, op in item.items():
                found[(method.upper(), _norm(path))] = op
    return found


async def test_t72_openapi_has_exactly_the_project_operations(api_env: ApiEnv) -> None:
    ops = _operations(api_env)
    assert set(ops) == {(m, _norm(p)) for m, p in EXPECTED_OPERATIONS}


async def test_t72_route_walk_sees_project_routes(api_env: ApiEnv) -> None:
    walked = {(m, _norm(p)) for m, p in _api_operations(api_env)}
    assert {(m, _norm(p)) for m, p in EXPECTED_OPERATIONS} <= walked


async def test_t72_declared_errors_follow_the_table(api_env: ApiEnv) -> None:
    ops = _operations(api_env)
    with_body = {
        ("POST", "/api/v1/projects"),
        ("PATCH", "/api/v1/projects/{}"),
        ("PUT", "/api/v1/projects/{}/owner"),
        ("POST", "/api/v1/projects/{}/members"),
        ("POST", "/api/v1/projects/{}/tasks"),
    }
    for key, op in ops.items():
        declared = set(op["responses"])
        assert {"401", "403"} <= declared, key
        if key in with_body:
            assert "400" in declared, key  # D-65
            assert "422" in declared, key
        else:
            assert "400" not in declared, key
    for key, op in ops.items():
        if "{}" in key[1]:
            assert "404" in op["responses"], key
    assert "404" not in ops[("GET", "/api/v1/projects")]["responses"]
    assert "422" in ops[("GET", "/api/v1/projects")]["responses"]
    assert "409" not in str([op["responses"] for op in ops.values()])  # D-57: 409 нет


async def test_t72_operation_ids_unique_and_equal_function_names(api_env: ApiEnv) -> None:
    from tests.api.test_route_guards import _iter_routes

    spec = api_env.app.openapi()
    all_ids = [op["operationId"] for item in spec["paths"].values() for op in item.values()]
    assert len(all_ids) == len(set(all_ids))
    names: dict[tuple[str, str], str] = {}
    for route in _iter_routes(api_env.app.routes):
        if route.path.startswith("/api/v1/projects"):
            for method in set(route.methods) - {"HEAD", "OPTIONS"}:
                names[(method, _norm(route.path))] = route.endpoint.__name__
    ops = _operations(api_env)
    assert {(m, _norm(p)) for m, p in EXPECTED_OPERATIONS} == set(ops)
    assert set(names) == set(ops)
    for key, op in ops.items():
        assert op["operationId"] == names[key], key


async def test_t72_response_schemas_match_plan_11_4(api_env: ApiEnv) -> None:
    schemas = api_env.app.openapi()["components"]["schemas"]
    assert set(schemas["ProjectDetail"]["properties"]) == DETAIL_FIELDS
    assert set(schemas["ProjectListItem"]["properties"]) == LIST_ITEM_FIELDS
    assert set(schemas["ProjectMember"]["properties"]) == {"user", "role", "is_blocked", "is_owner"}
    for name in ("ProjectDetail", "ProjectListItem", "ProjectMember"):
        assert "status" not in schemas[name]["properties"], name
    assert any(n.startswith("Page_ProjectListItem") for n in schemas)
    assert any(n.startswith("Page_ProjectMember") for n in schemas)
    perms = next(s for n, s in schemas.items() if set(s.get("properties", {})) == PERMISSION_FIELDS)
    assert perms["type"] == "object"


async def test_t72_committed_contract_files_contain_project_routes() -> None:
    spec_path = REPO_ROOT / "docs" / "api" / "openapi.json"
    import json

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    committed = {
        (m.upper(), _norm(p))
        for p, item in spec["paths"].items()
        if p.startswith("/api/v1/projects")
        for m in item
    }
    assert committed == {(m, _norm(p)) for m, p in EXPECTED_OPERATIONS}
    dts = (REPO_ROOT / "frontend" / "src" / "shared" / "api" / "schema.d.ts").read_text(
        encoding="utf-8"
    )
    in_dts = {_norm(p) for p in re.findall(r'"(/api/v1/projects[^"]*)"', dts)}
    assert in_dts == {_norm(p) for _, p in EXPECTED_OPERATIONS}
    assert "ProjectDetail" in dts
    assert "ProjectListItem" in dts
    assert "ProjectMember" in dts


async def test_d57_no_archive_routes_unknown_paths_are_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for method, suffix in (("POST", "archive"), ("POST", "unarchive"), ("GET", "history")):
        r = await send(env, w.tok("ba"), method, f"{pj(w.project_id)}/{suffix}")
        assert r.status_code == 404, (method, suffix)


# --- T72 попытка 2: extra="forbid", null, NUL -------------------------------------------------


def _count(env: ApiEnv, ws_id: Any) -> Any:
    return rows(env, "SELECT count(*) FROM project WHERE workspace_id = :w", w=ws_id)


@pytest.mark.parametrize("extra", ["status", "owner_id", "title", "x"])
async def test_t72_create_extra_field_is_422_and_nothing_created(
    api_env: ApiEnv, extra: str
) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(env, w.tok("ba"), "POST", PROJECTS, {"name": "Лишнее", extra: "v"})

    assert error(r) == (422, "validation_error")
    assert (await _count(env, w.ws.id))[0][0] == 1


@pytest.mark.parametrize("extra", ["status", "owner_id", "title", "x"])
async def test_t72_patch_extra_field_is_422_and_project_untouched(
    api_env: ApiEnv, extra: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await project_db(env, w.project_id)

    r = await send(env, w.tok("ba"), "PATCH", pj(w.project_id), {"name": "Новое", extra: "v"})

    assert error(r) == (422, "validation_error")
    after = await project_db(env, w.project_id)
    assert (after.name, after.description, after.owner_id, after.updated_at) == (
        before.name,
        before.description,
        before.owner_id,
        before.updated_at,
    )


@pytest.mark.parametrize("extra", ["status", "owner_id", "title", "x"])
async def test_t72_owner_change_extra_field_is_422_owner_unchanged(
    api_env: ApiEnv, extra: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    before_events = await event_count(env, w.ws.id)

    r = await send(
        env,
        w.tok("ba"),
        "PUT",
        f"{pj(w.project_id)}/owner",
        {"user_id": str(w.uid("ba2")), extra: "v"},
    )

    assert error(r) == (422, "validation_error")
    assert (await project_db(env, w.project_id)).owner_id == w.uid("ba")
    assert await event_count(env, w.ws.id) == before_events


@pytest.mark.parametrize("extra", ["status", "owner_id", "title", "x"])
async def test_t72_member_add_extra_field_is_422_member_not_added(
    api_env: ApiEnv, extra: str
) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(
        env,
        w.tok("ba"),
        "POST",
        f"{pj(w.project_id)}/members",
        {"user_id": str(w.uid("usr2")), extra: "v"},
    )

    assert error(r) == (422, "validation_error")
    found = await rows(
        env,
        "SELECT count(*) FROM project_member WHERE project_id = :p AND user_id = :u",
        p=w.project_id,
        u=w.uid("usr2"),
    )
    assert found[0][0] == 0


@pytest.mark.parametrize("field", ["name", "description"])
async def test_t72_patch_explicit_null_is_422_data_unchanged(api_env: ApiEnv, field: str) -> None:
    env = api_env
    w = await make_api_world(env)
    await send(env, w.tok("ba"), "PATCH", pj(w.project_id), {"description": "Описание"})
    before = await project_db(env, w.project_id)

    r = await send(env, w.tok("ba"), "PATCH", pj(w.project_id), {field: None})

    assert error(r) == (422, "validation_error")
    after = await project_db(env, w.project_id)
    assert (after.name, after.description) == (before.name, before.description)
    assert after.updated_at == before.updated_at


async def test_t72_create_null_name_and_null_description_are_422(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for payload in ({"name": None}, {"name": "Ок", "description": None}):
        r = await send(env, w.tok("ba"), "POST", PROJECTS, payload)
        assert error(r) == (422, "validation_error"), payload
    assert (await _count(env, w.ws.id))[0][0] == 1


async def test_t72_committed_openapi_forbids_extra_and_nulls() -> None:
    import json

    spec = json.loads((REPO_ROOT / "docs" / "api" / "openapi.json").read_text(encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    for name in ("ProjectCreate", "ProjectPatch", "OwnerChange", "MemberAdd"):
        assert schemas[name].get("additionalProperties") is False, name
    for name in ("ProjectCreate", "ProjectPatch"):
        for field in ("name", "description"):
            prop = schemas[name]["properties"][field]
            variants = prop.get("anyOf", []) + prop.get("oneOf", []) + [prop]
            assert all(v.get("type") != "null" for v in variants), (name, field)
            assert prop.get("type") != "null"


async def test_t72_runtime_openapi_forbids_extra_and_nulls(api_env: ApiEnv) -> None:
    schemas = api_env.app.openapi()["components"]["schemas"]
    for name in ("ProjectCreate", "ProjectPatch", "OwnerChange", "MemberAdd"):
        assert schemas[name].get("additionalProperties") is False, name
    for field in ("name", "description"):
        prop = schemas["ProjectPatch"]["properties"][field]
        variants = prop.get("anyOf", []) + prop.get("oneOf", []) + [prop]
        assert all(v.get("type") != "null" for v in variants), field


@pytest.mark.parametrize("field", ["name", "description"])
async def test_t72_nul_char_create_is_422_not_500(api_env: ApiEnv, field: str) -> None:
    env = api_env
    w = await make_api_world(env)
    payload = {"name": "Ок", "description": ""}
    payload[field] = "a\x00b"

    r = await send(env, w.tok("ba"), "POST", PROJECTS, payload)

    assert error(r) == (422, "validation_error")
    assert (await _count(env, w.ws.id))[0][0] == 1


@pytest.mark.parametrize("field", ["name", "description"])
async def test_t72_nul_char_patch_is_422_not_500(api_env: ApiEnv, field: str) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await project_db(env, w.project_id)

    r = await send(env, w.tok("ba"), "PATCH", pj(w.project_id), {field: "a\x00b"})

    assert error(r) == (422, "validation_error")
    after = await project_db(env, w.project_id)
    assert (after.name, after.description) == (before.name, before.description)
