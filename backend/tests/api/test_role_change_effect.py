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
