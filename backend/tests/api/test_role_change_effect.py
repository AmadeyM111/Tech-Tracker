"""T72: смена роли действует со следующего запроса, без повторного входа (AC-76, FR-67, SC-14).

БА с активной сессией создаёт проект (201); ТА или СМ меняет его роль на «Пользователь» —
следующий ``POST /projects`` той же сессии даёт 403; роль возвращена — 201. Права на уже
созданный проект соответствуют новой роли; владелец и членство не меняются (AC-77).
"""

from __future__ import annotations

import pytest

from tests.admin_support import admin_call, new_workspace, seed
from tests.conftest import ApiEnv
from tests.projects_api_support import PROJECTS, error, members_url, pj, send


@pytest.mark.parametrize("changer_role", ["tech_admin", "mixed"])
async def test_ac76_role_change_applies_to_next_request_in_same_session(
    api_env: ApiEnv, changer_role: str
) -> None:
    env = api_env
    ws = await new_workspace(env)
    changer, (changer_token,) = await seed(env, ws, changer_role, login="rc.changer")
    ba, (ba_token,) = await seed(env, ws, "business_admin", login="rc.ba")
    other, _ = await seed(env, ws, "user", login="rc.other")

    first = await send(env, ba_token, "POST", PROJECTS, {"name": "До смены роли"})
    assert first.status_code == 201, first.text
    project_id = first.json()["id"]

    down = await admin_call(env, changer_token, "role_user", ba.id)
    assert down.status_code in (200, 204), down.text

    # та же сессия, без повторного входа
    assert (await env.me(ba_token)).status_code == 200
    denied = await send(env, ba_token, "POST", PROJECTS, {"name": "После смены роли"})
    assert error(denied) == (403, "forbidden")

    # права на уже созданный проект — по новой роли «Пользователь»; владелец и членство целы
    card = await send(env, ba_token, "GET", pj(project_id))
    assert card.status_code == 200, card.text
    assert card.json()["owner"]["id"] == str(ba.id)
    assert card.json()["is_member"] is True
    assert card.json()["permissions"] == {
        "manage": False,
        "manage_members": False,
        "create_task": True,
        "remove_self": False,  # владелец не выходит
    }
    assert error(await send(env, ba_token, "PATCH", pj(project_id), {"name": "Нельзя"})) == (
        403,
        "forbidden",
    )
    assert error(await send(env, ba_token, "DELETE", pj(project_id))) == (403, "forbidden")
    assert error(
        await send(env, ba_token, "POST", members_url(project_id), {"user_id": str(other.id)})
    ) == (403, "forbidden")
    assert error(
        await send(env, ba_token, "PUT", f"{pj(project_id)}/owner", {"user_id": str(ba.id)})
    ) == (403, "forbidden")
    listed = await send(env, ba_token, "GET", PROJECTS)  # как участник проект в списке
    assert [i["id"] for i in listed.json()["items"]] == [project_id]

    up = await admin_call(env, changer_token, "role_ba", ba.id)
    assert up.status_code in (200, 204), up.text

    again = await send(env, ba_token, "POST", PROJECTS, {"name": "После возврата роли"})
    assert again.status_code == 201, again.text
    card = await send(env, ba_token, "GET", pj(project_id))
    assert card.json()["permissions"]["manage"] is True
    renamed = await send(env, ba_token, "PATCH", pj(project_id), {"name": "Переименован"})
    assert renamed.status_code == 200, renamed.text
    assert changer.id != ba.id


async def test_ac76_role_removed_gives_403_no_role_on_projects_in_same_session(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws = await new_workspace(env)
    _, (ta_token,) = await seed(env, ws, "tech_admin", login="rn.ta")
    ba, (ba_token,) = await seed(env, ws, "business_admin", login="rn.ba")
    created = await send(env, ba_token, "POST", PROJECTS, {"name": "П"})
    assert created.status_code == 201

    removed = await admin_call(env, ta_token, "role_none", ba.id)
    assert removed.status_code in (200, 204), removed.text

    for method, url in (("GET", PROJECTS), ("GET", pj(created.json()["id"]))):
        r = await send(env, ba_token, method, url)
        assert error(r) == (403, "no_role")


# --- T77: задачи (AC-77, SC-14, AC-75, AC-76) -----------------------------------------------


async def test_t77_ac77_role_change_keeps_owner_member_assignee_and_mixed_reassigns(
    api_env: ApiEnv,
) -> None:
    from tests.tasks_api_support import make_api_world, mk, project_tasks_url, task_db, task_url

    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, by="ba", assignee="ba", title="Исходное")
    assert (
        await send(env, w.tok("ba"), "PATCH", task_url(t), {"assignee_id": str(w.uid("ba"))})
    ).status_code == 200

    down = await admin_call(env, w.tok("ta"), "role_user", w.uid("ba"))
    assert down.status_code in (200, 204), down.text

    row = await task_db(env, t)
    assert row.assignee_id == w.uid("ba")  # исполнитель не изменился
    card = await send(env, w.tok("ba"), "GET", task_url(t))
    assert card.status_code == 200, card.text
    assert card.json()["assignee"]["id"] == str(w.uid("ba"))
    # права по новой роли: «Пользователь» не меняет исполнителя; своя задача — правится
    assert card.json()["permissions"]["change_assignee"] is False
    assert card.json()["permissions"]["edit"] is True
    assert error(
        await send(env, w.tok("ba"), "PATCH", task_url(t), {"assignee_id": str(w.uid("usr"))})
    ) == (403, "forbidden")
    # СМ находит задачу фильтром по исполнителю и переназначает (SC-14)
    found = await send(
        env, w.tok("sm_m"), "GET", project_tasks_url(w.project_id, f"?assignee_id={w.uid('ba')}")
    )
    assert [i["id"] for i in found.json()["items"]] == [str(t)]
    moved = await send(env, w.tok("sm_m"), "PATCH", task_url(t), {"assignee_id": str(w.uid("usr"))})
    assert moved.status_code == 200, moved.text
    assert (await task_db(env, t)).assignee_id == w.uid("usr")


async def test_t77_ac76_role_effect_on_task_operations_without_relogin(api_env: ApiEnv) -> None:
    from tests.tasks_api_support import make_api_world, mk, task_url

    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, by="ba", assignee="usr", title="Т")
    ok = await send(env, w.tok("ba"), "PATCH", task_url(t), {"title": "Владелец"})
    assert ok.status_code == 200

    assert (await admin_call(env, w.tok("ta"), "role_user", w.uid("ba"))).status_code in (200, 204)
    denied = await send(env, w.tok("ba"), "PATCH", task_url(t), {"title": "Пользователь"})
    assert error(denied) == (403, "forbidden")  # не автор-исполнитель

    assert (await admin_call(env, w.tok("ta"), "role_ba", w.uid("ba"))).status_code in (200, 204)
    again = await send(env, w.tok("ba"), "PATCH", task_url(t), {"title": "Снова владелец"})
    assert again.status_code == 200, again.text

    assert (await admin_call(env, w.tok("ta"), "role_none", w.uid("ba"))).status_code in (200, 204)
    for method, url in (("GET", task_url(t)), ("GET", "/api/v1/me/tasks")):
        r = await send(env, w.tok("ba"), method, url)
        assert error(r) == (403, "no_role")
