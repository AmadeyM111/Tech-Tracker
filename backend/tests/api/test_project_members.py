"""T72: ``/api/v1/projects/{id}/members`` — список, добавление, исключение (plan §11.4).

AC-50, AC-52, AC-53, AC-54, AC-73, AC-74, AC-123; FR-15, FR-15a, FR-70; D-45, D-46, D-47.
Контракт: ``GET`` -> ``Page[ProjectMember {user{id, login}, role, is_blocked, is_owner}]``,
``ORDER BY login, id``; ``POST {user_id}`` -> 204 (повтор — 204 без изменений);
``DELETE /{user_id}`` -> 204; цель не участник -> 404; владелец -> 422 ``owner_cannot_be_removed``.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.admin_support import seed
from tests.conftest import ApiEnv
from tests.projects_api_support import (
    MEMBER_FIELDS,
    PAGE_FIELDS,
    SOME_ID,
    USER_REF_FIELDS,
    add_member_row,
    add_task,
    error,
    make_api_world,
    make_foreign,
    member_ids,
    members_url,
    pj,
    rows,
    send,
    set_blocked,
)


def _owner_url(project_id: Any) -> str:
    return f"{pj(project_id)}/owner"


# --- GET members ----------------------------------------------------------------------------


async def test_ac55_list_members_shape_order_flags(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    blocked, _ = await seed(env, w.ws, "user", login="a.blocked-member", blocked=True)
    norole, _ = await seed(env, w.ws, None, login="z.norole-member")
    await add_member_row(env, w, blocked)
    await add_member_row(env, w, norole)

    r = await send(env, w.tok("usr"), "GET", members_url(w.project_id))

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == PAGE_FIELDS
    items = body["items"]
    for item in items:
        assert set(item) == MEMBER_FIELDS
        assert set(item["user"]) == USER_REF_FIELDS
    assert [i["user"]["login"] for i in items] == sorted(i["user"]["login"] for i in items)
    by_login = {i["user"]["login"]: i for i in items}
    assert set(by_login) == {
        "a.blocked-member",
        "w.ba",
        "w.ba2",
        "w.sm_m",
        "w.usr",
        "z.norole-member",
    }
    assert by_login["w.ba"]["is_owner"] is True
    assert sum(1 for i in items if i["is_owner"]) == 1
    assert by_login["w.ba"]["role"] == "business_admin"
    assert by_login["w.sm_m"]["role"] == "mixed"
    assert by_login["w.usr"]["role"] == "user"
    assert by_login["z.norole-member"]["role"] is None
    assert by_login["a.blocked-member"]["is_blocked"] is True
    assert by_login["w.usr"]["is_blocked"] is False


async def test_fr47_members_pagination(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)  # 4 участника

    first = (await send(env, w.tok("ba"), "GET", members_url(w.project_id) + "?page_size=3")).json()
    second = (
        await send(env, w.tok("ba"), "GET", members_url(w.project_id) + "?page_size=3&page=2")
    ).json()

    assert (len(first["items"]), first["has_next"]) == (3, True)
    assert (len(second["items"]), second["has_next"]) == (1, False)
    logins = [i["user"]["login"] for i in first["items"] + second["items"]]
    assert logins == sorted(logins)
    assert len(set(logins)) == 4


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101"])
async def test_fr47_members_invalid_page_is_422(api_env: ApiEnv, query: str) -> None:
    w = await make_api_world(api_env)
    r = await send(api_env, w.tok("ba"), "GET", f"{members_url(w.project_id)}?{query}")
    assert error(r) == (422, "validation_error")


async def test_d45_members_visible_to_ba_sm_non_members_but_not_to_user_non_member(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    for who in ("ba3", "sm"):
        r = await send(env, w.tok(who), "GET", members_url(w.project_id))
        assert r.status_code == 200, who
    r = await send(env, w.tok("usr2"), "GET", members_url(w.project_id))
    assert error(r) == (403, "forbidden")
    assert "w.ba2" not in r.text


# --- POST members ---------------------------------------------------------------------------


async def test_ac73_owner_adds_member_204_and_member_is_listed(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(
        env, w.tok("ba"), "POST", members_url(w.project_id), {"user_id": str(w.uid("usr2"))}
    )

    assert r.status_code == 204, r.text
    assert r.content == b""
    assert w.uid("usr2") in await member_ids(env, w.project_id)
    # новый участник видит проект
    assert (await send(env, w.tok("usr2"), "GET", pj(w.project_id))).status_code == 200


async def test_d46_repeated_add_is_204_without_changes(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    body = {"user_id": str(w.uid("usr"))}
    before = await rows(
        env,
        "SELECT user_id, created_at, created_by FROM project_member WHERE project_id = :p",
        p=w.project_id,
    )

    for _ in range(2):
        r = await send(env, w.tok("ba"), "POST", members_url(w.project_id), body)
        assert r.status_code == 204, r.text

    after = await rows(
        env,
        "SELECT user_id, created_at, created_by FROM project_member WHERE project_id = :p",
        p=w.project_id,
    )
    assert sorted(map(tuple, before)) == sorted(map(tuple, after))


async def test_ac73_mixed_non_member_adds_other_user_and_himself(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    other = await send(
        env, w.tok("sm"), "POST", members_url(w.project_id), {"user_id": str(w.uid("usr2"))}
    )
    itself = await send(
        env, w.tok("sm"), "POST", members_url(w.project_id), {"user_id": str(w.uid("sm"))}
    )

    assert (other.status_code, itself.status_code) == (204, 204)
    members = await member_ids(env, w.project_id)
    assert {w.uid("usr2"), w.uid("sm")} <= members
    card = await send(env, w.tok("sm"), "GET", pj(w.project_id))
    assert card.json()["is_member"] is True


async def test_ac54_ba_non_member_adding_himself_is_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(
        env, w.tok("ba3"), "POST", members_url(w.project_id), {"user_id": str(w.uid("ba3"))}
    )
    assert error(r) == (403, "forbidden")
    assert w.uid("ba3") not in await member_ids(env, w.project_id)


@pytest.mark.parametrize("who", ["ba2", "usr", "ba3", "usr2", "ta"])
async def test_ac73_ac54_non_managers_get_403_even_for_unknown_target(
    api_env: ApiEnv, who: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await member_ids(env, w.project_id)

    ok_target = await send(
        env, w.tok(who), "POST", members_url(w.project_id), {"user_id": str(w.uid("usr2"))}
    )
    bad_target = await send(
        env, w.tok(who), "POST", members_url(w.project_id), {"user_id": SOME_ID}
    )

    assert error(ok_target) == (403, "forbidden")
    assert error(bad_target) == (403, "forbidden")  # права раньше получателя
    assert await member_ids(env, w.project_id) == before


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("ta", "recipient_wrong_role"),
        ("norole", "recipient_wrong_role"),
        ("blocked", "user_blocked"),
        ("unknown", "user_not_found"),
        ("foreign", "user_not_found"),
    ],
)
async def test_ac74_add_recipient_errors_422_with_distinct_codes(
    api_env: ApiEnv, target: str, code: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    if target == "unknown":
        target_id = SOME_ID
    elif target == "foreign":
        target_id = str((await make_foreign(env)).usr.id)
    else:
        target_id = str(w.uid(target))
    before = await member_ids(env, w.project_id)

    r = await send(env, w.tok("ba"), "POST", members_url(w.project_id), {"user_id": target_id})

    assert error(r) == (422, code), r.text
    assert await member_ids(env, w.project_id) == before


async def test_t71_review_re_add_of_blocked_existing_member_is_422_user_blocked(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    await set_blocked(env, w.uid("usr"))

    r = await send(
        env, w.tok("ba"), "POST", members_url(w.project_id), {"user_id": str(w.uid("usr"))}
    )

    assert error(r) == (422, "user_blocked")
    assert w.uid("usr") in await member_ids(env, w.project_id)


async def test_ac74_role_removed_participant_stays_participant(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    await rows(env, "UPDATE workspace_member SET role = NULL WHERE user_id = :u", u=w.uid("usr"))

    r = await send(env, w.tok("ba"), "GET", members_url(w.project_id))

    by_login = {i["user"]["login"]: i for i in r.json()["items"]}
    assert by_login["w.usr"]["role"] is None


@pytest.mark.parametrize("payload", [{}, {"user_id": None}, {"user_id": "nope"}, {"user_id": 7}])
async def test_ac74_add_invalid_body_is_422(api_env: ApiEnv, payload: dict[str, Any]) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("ba"), "POST", members_url(w.project_id), payload)
    assert error(r) == (422, "validation_error")


async def test_ac123_add_broken_json_is_400(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await member_ids(env, w.project_id)
    for token in (w.tok("ba"), None, w.tok("usr")):
        r = await send(env, token, "POST", members_url(w.project_id), raw=b'{"user_id": "x')
        assert error(r) == (400, "bad_request")
    assert await member_ids(env, w.project_id) == before


async def test_fr14_add_to_missing_project_for_ba_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    own = await send(env, w.tok("ba"), "GET", members_url(w.project_id))
    assert own.status_code == 200, own.text  # маршрут существует
    r = await send(env, w.tok("ba"), "POST", members_url(SOME_ID), {"user_id": str(w.uid("usr2"))})
    assert error(r) == (404, "not_found")


# --- DELETE members/{user_id} ---------------------------------------------------------------


async def test_ac50_owner_removes_member_assignee_cleared_on_all_tasks(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    usr = w.uid("usr")
    t1 = await add_task(env, w, assignee=usr)
    t2 = await add_task(env, w, assignee=usr)
    sub = await add_task(env, w, parent_id=t1, assignee=usr)
    deleted = await add_task(env, w, assignee=usr, deleted=True)
    kept = await add_task(env, w, assignee=w.uid("ba2"))

    r = await send(env, w.tok("ba"), "DELETE", members_url(w.project_id, usr))

    assert r.status_code == 204, r.text
    assert r.content == b""
    assert usr not in await member_ids(env, w.project_id)
    found = await rows(
        env, "SELECT id, assignee_id FROM task WHERE project_id = :p", p=w.project_id
    )
    assignee = {row[0]: row[1] for row in found}
    assert set(assignee) == {t1, t2, sub, deleted, kept}  # задачи существуют
    for task_id in (t1, t2, sub, deleted):
        assert assignee[task_id] is None
    assert assignee[kept] == w.uid("ba2")
    # исключённый теряет доступ к проекту (AC-50, AC-53)
    assert error(await send(env, w.tok("usr"), "GET", pj(w.project_id))) == (403, "forbidden")
    # исключённого второй раз — 404: он не участник
    again = await send(env, w.tok("ba"), "DELETE", members_url(w.project_id, usr))
    assert error(again) == (404, "not_found")


async def test_ac53_removing_owner_is_422_owner_cannot_be_removed(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    for who in ("ba", "sm"):
        r = await send(env, w.tok(who), "DELETE", members_url(w.project_id, w.uid("ba")))
        assert error(r) == (422, "owner_cannot_be_removed"), who
        assert r.json()["detail"]  # пояснение
    assert w.uid("ba") in await member_ids(env, w.project_id)


async def test_ac53_former_owner_can_be_removed_after_transfer(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    moved = await send(
        env, w.tok("ba"), "PUT", _owner_url(w.project_id), {"user_id": str(w.uid("ba2"))}
    )
    assert moved.status_code == 200, moved.text

    r = await send(env, w.tok("ba2"), "DELETE", members_url(w.project_id, w.uid("ba")))

    assert r.status_code == 204, r.text
    assert w.uid("ba") not in await member_ids(env, w.project_id)


async def test_ac53_non_owner_member_removes_himself_and_loses_access(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await send(env, w.tok("usr"), "DELETE", members_url(w.project_id, w.uid("usr")))

    assert r.status_code == 204, r.text
    assert w.uid("usr") not in await member_ids(env, w.project_id)
    assert error(await send(env, w.tok("usr"), "GET", pj(w.project_id))) == (403, "forbidden")
    assert error(await send(env, w.tok("usr"), "GET", members_url(w.project_id))) == (
        403,
        "forbidden",
    )


async def test_ac53_ba_member_self_removal_keeps_ba_card_visibility_not_membership(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("ba2"), "DELETE", members_url(w.project_id, w.uid("ba2")))
    assert r.status_code == 204
    card = await send(env, w.tok("ba2"), "GET", pj(w.project_id))
    assert card.status_code == 200  # БА видит проект (D-45), но не участник
    assert card.json()["is_member"] is False


@pytest.mark.parametrize("who", ["ba2", "usr", "ba3"])
async def test_ac73_non_managers_cannot_remove_others(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    target = w.uid("sm_m")
    r = await send(env, w.tok(who), "DELETE", members_url(w.project_id, target))
    assert error(r) == (403, "forbidden")
    assert target in await member_ids(env, w.project_id)


async def test_ac73_mixed_non_member_removes_member(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("sm"), "DELETE", members_url(w.project_id, w.uid("ba2")))
    assert r.status_code == 204
    assert w.uid("ba2") not in await member_ids(env, w.project_id)


async def test_ac54_tech_admin_cannot_add_or_remove(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await member_ids(env, w.project_id)
    add = await send(
        env, w.tok("ta"), "POST", members_url(w.project_id), {"user_id": str(w.uid("usr2"))}
    )
    rem = await send(env, w.tok("ta"), "DELETE", members_url(w.project_id, w.uid("usr")))
    assert (error(add), error(rem)) == ((403, "forbidden"), (403, "forbidden"))
    assert await member_ids(env, w.project_id) == before


async def test_t71_review_tech_admin_and_no_role_member_rows_cannot_self_remove(
    api_env: ApiEnv,
) -> None:
    """Мутант ``can_remove_self``: строки участника у ТА и «без роли» не дают права выйти."""
    env = api_env
    w = await make_api_world(env)
    await add_member_row(env, w, w.people["ta"].user)
    await add_member_row(env, w, w.people["norole"].user)

    ta = await send(env, w.tok("ta"), "DELETE", members_url(w.project_id, w.uid("ta")))
    nr = await send(env, w.tok("norole"), "DELETE", members_url(w.project_id, w.uid("norole")))

    assert error(ta) == (403, "forbidden")
    assert error(nr) == (403, "no_role")
    members = await member_ids(env, w.project_id)
    assert {w.uid("ta"), w.uid("norole")} <= members


async def test_d45_user_non_member_gets_403_before_404_on_remove(api_env: ApiEnv) -> None:
    """Решение архитектора по T71: ``can_view_project`` первым, состав не раскрывается."""
    env = api_env
    w = await make_api_world(env)
    member_target = await send(
        env, w.tok("usr2"), "DELETE", members_url(w.project_id, w.uid("usr"))
    )
    stranger_target = await send(
        env, w.tok("usr2"), "DELETE", members_url(w.project_id, w.uid("usr2"))
    )
    unknown_target = await send(env, w.tok("usr2"), "DELETE", members_url(w.project_id, SOME_ID))

    assert error(member_target) == (403, "forbidden")
    assert error(stranger_target) == (403, "forbidden")
    assert error(unknown_target) == (403, "forbidden")
    assert member_target.json() == stranger_target.json() == unknown_target.json()


async def test_fr15a_remove_non_member_target_is_404_for_participants_and_managers(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    for who in ("ba", "ba2", "usr", "sm", "ba3"):
        own = await send(env, w.tok(who), "GET", members_url(w.project_id))
        assert own.status_code == 200, own.text  # маршрут существует, проект виден
        r = await send(env, w.tok(who), "DELETE", members_url(w.project_id, w.uid("usr2")))
        assert error(r) == (404, "not_found"), who
        r = await send(env, w.tok(who), "DELETE", members_url(w.project_id, SOME_ID))
        assert error(r) == (404, "not_found"), who


async def test_ac21_remove_foreign_workspace_user_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)
    own = await send(env, w.tok("ba"), "GET", members_url(w.project_id))
    assert own.status_code == 200, own.text
    r = await send(env, w.tok("ba"), "DELETE", members_url(w.project_id, foreign.usr.id))
    assert error(r) == (404, "not_found")


async def test_ac53_invalid_user_uuid_in_path_is_422(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    r = await send(env, w.tok("ba"), "DELETE", f"{members_url(w.project_id)}/nope")
    assert error(r) == (422, "validation_error")


# --- T72 попытка 2: FR-15 / AC-54 (мутант can_add_member -> can_manage_members) --------------


async def test_fr15_ac54_ba_owner_adding_himself_is_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await member_ids(env, w.project_id)

    r = await send(
        env, w.tok("ba"), "POST", members_url(w.project_id), {"user_id": str(w.uid("ba"))}
    )

    assert error(r) == (403, "forbidden")
    assert await member_ids(env, w.project_id) == before


async def test_fr15_ac54_mixed_non_member_adding_himself_is_204(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    assert w.uid("sm") not in await member_ids(env, w.project_id)

    r = await send(
        env, w.tok("sm"), "POST", members_url(w.project_id), {"user_id": str(w.uid("sm"))}
    )

    assert r.status_code == 204, r.text
    assert w.uid("sm") in await member_ids(env, w.project_id)


async def test_fr15_ac54_ba_member_not_owner_adding_other_is_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    assert w.uid("ba2") in await member_ids(env, w.project_id)

    r = await send(
        env, w.tok("ba2"), "POST", members_url(w.project_id), {"user_id": str(w.uid("usr2"))}
    )

    assert error(r) == (403, "forbidden")
    assert w.uid("usr2") not in await member_ids(env, w.project_id)
