"""002/R3-T04: несколько ТА и последний администратор, AC-3...AC-9 (FR-3, FR-5, FR-6, FR-7).

Шаги повторяют критерии приёмки spec 002 §6 буквально. Журнал проверяется по числу записей и
полям ``action``, ``actor_id``, ``entity_id``, ``details.role_from/role_to``. Тесты проходят на
текущем сервисе (plan §4.4, D-4): код ТА уже реализует FR-7. Красный тест означает расхождение
плана с кодом (PLAN_ISSUE), сервис здесь не правится.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.admin_support import (
    ADMIN_USERS,
    OTP,
    OTP_FIELD,
    PW,
    active_ta_count,
    admin_call,
    code_of,
    events,
    member_role,
    new_workspace,
    seed,
)
from tests.conftest import ApiEnv
from tests.roles002_support import make_world_002

AUDIT = "/api/v1/admin/audit"
PROJECTS = "/api/v1/projects"


async def _put_role(env: ApiEnv, token: str, user_id: Any, role: Any) -> Any:
    return await env.client.put(
        f"{ADMIN_USERS}/{user_id}/role", json={"role": role}, headers=env.auth(token)
    )


async def _post(env: ApiEnv, token: str, user_id: Any, suffix: str) -> Any:
    return await env.client.post(f"{ADMIN_USERS}/{user_id}/{suffix}", headers=env.auth(token))


async def _journal_len(env: ApiEnv, ws_id: uuid.UUID) -> int:
    return len(await events(env, workspace_id=ws_id))


# --- AC-3: любой активный ТА имеет все права ТА, включая назначение роли ТА ----------------------


async def test_002_ac3_ta_assigns_ta_role_and_new_ta_has_all_ta_rights(api_env: ApiEnv) -> None:
    """002/AC-3 (FR-5, FR-6, FR-3). Замена test_fr42_mixed_role_has_access_to_admin_section."""
    env = api_env
    ws = await new_workspace(env)
    ta1, (tok1,) = await seed(env, ws, "tech_admin", login="ac3.ta1")
    x, _ = await seed(env, ws, None, password=PW, login="ac3.x")
    y, _ = await seed(env, ws, None, login="ac3.y")

    r = await _put_role(env, tok1, x.id, "tech_admin")

    assert r.status_code == 200, r.text
    assert r.json()["role"] == "tech_admin"
    assert await member_role(env, x.id) == "tech_admin"
    log = await events(env, workspace_id=ws.id)
    assert len(log) == 1
    assert log[0].action == "user.role_assigned"
    assert log[0].actor_id == ta1.id
    assert log[0].entity_id == x.id
    assert log[0].details["role_to"] == "tech_admin"

    login = await env.login("ac3.x", PW)
    assert login.status_code == 200, login.text
    tok_x = env.token_from(login)
    assert tok_x

    # создать, заблокировать, разблокировать, сбросить пароль, завершить сессии, читать журнал
    created = await env.client.post(
        ADMIN_USERS, json={"login": "ac3.created", OTP_FIELD: OTP}, headers=env.auth(tok_x)
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert (await _post(env, tok_x, cid, "block")).status_code == 204
    assert (await _post(env, tok_x, cid, "unblock")).status_code == 204
    reset = await env.client.post(
        f"{ADMIN_USERS}/{cid}/reset-password",
        json={OTP_FIELD: "Other-Pa55phrase-xyz-778"},
        headers=env.auth(tok_x),
    )
    assert reset.status_code == 204, reset.text
    assert (await _post(env, tok_x, cid, "revoke-sessions")).status_code == 204
    audit = await env.client.get(AUDIT, headers=env.auth(tok_x))
    assert audit.status_code == 200, audit.text
    api_entries = sorted((i["action"], i["actor"]["id"]) for i in audit.json()["items"])
    db_entries = sorted((e.action, str(e.actor_id)) for e in await events(env, workspace_id=ws.id))
    assert api_entries == db_entries
    expected_actions = sorted(
        [
            "user.role_assigned",
            "user.created",
            "user.blocked",
            "user.unblocked",
            "user.password_reset",
            "user.sessions_revoked",
        ]
    )
    assert [a for a, _ in api_entries] == expected_actions
    assert {actor for _, actor in api_entries} == {str(ta1.id), str(x.id)}
    users = await env.client.get(ADMIN_USERS, headers=env.auth(tok_x))
    assert users.status_code == 200, users.text

    # роль ТА назначает не только ta1, но и x
    before = await _journal_len(env, ws.id)
    r = await _put_role(env, tok_x, y.id, "tech_admin")
    assert r.status_code == 200, r.text
    assert await member_role(env, y.id) == "tech_admin"
    new = (await events(env, workspace_id=ws.id))[before:]
    assert [(e.action, e.actor_id, e.entity_id) for e in new] == [
        ("user.role_assigned", x.id, y.id)
    ]

    # раздел проектов закрыт для ТА
    assert (await env.client.get(PROJECTS, headers=env.auth(tok_x))).status_code == 403


async def test_002_ac3_fr5_number_of_tech_admins_is_not_limited(api_env: ApiEnv) -> None:
    """002/AC-3, FR-5: ТА назначается без верхней границы, все активны."""
    env = api_env
    ws = await new_workspace(env)
    _, (tok,) = await seed(env, ws, "tech_admin")
    targets = [(await seed(env, ws, "user"))[0] for _ in range(6)]
    for t in targets:
        assert (await _put_role(env, tok, t.id, "tech_admin")).status_code == 200
    assert await active_ta_count(env, ws.id) == 7


# --- AC-4: ТА назначает/меняет/снимает любые роли, потом меняет свою на БА -----------------------


async def test_002_ac4_ta_manages_all_roles_then_switches_own_role_to_ba(
    api_env: ApiEnv,
) -> None:
    """002/AC-4 (FR-6, FR-7). Замена смены своей роли на mixed (001/AC-64)."""
    env = api_env
    ws = await new_workspace(env)
    ta1, (tok1,) = await seed(env, ws, "tech_admin", login="ac4.ta1")
    await seed(env, ws, "tech_admin", login="ac4.ta2")
    n_ba, _ = await seed(env, ws, None)
    n_user, _ = await seed(env, ws, None)
    n_ta, _ = await seed(env, ws, None)

    steps: list[tuple[Any, Any, str, str | None, str | None]] = [
        # (цель, роль, действие журнала, role_from, role_to)
        (n_ba, "business_admin", "user.role_assigned", None, "business_admin"),
        (n_user, "user", "user.role_assigned", None, "user"),
        (n_ta, "tech_admin", "user.role_assigned", None, "tech_admin"),
        (n_ba, "user", "user.role_changed", "business_admin", "user"),
        (n_user, "business_admin", "user.role_changed", "user", "business_admin"),
        (n_ta, "business_admin", "user.role_changed", "tech_admin", "business_admin"),
        (n_ba, None, "user.role_removed", "user", None),
        (n_user, None, "user.role_removed", "business_admin", None),
        (n_ta, "tech_admin", "user.role_changed", "business_admin", "tech_admin"),
        (n_ta, None, "user.role_removed", "tech_admin", None),
        (ta1, "business_admin", "user.role_changed", "tech_admin", "business_admin"),
    ]
    for target, role, action, role_from, role_to in steps:
        before = await _journal_len(env, ws.id)
        r = await _put_role(env, tok1, target.id, role)
        assert r.status_code == 200, (action, r.text)
        new = (await events(env, workspace_id=ws.id))[before:]
        assert len(new) == 1, (action, [e.action for e in new])
        assert (new[0].action, new[0].actor_id, new[0].entity_id) == (
            action,
            ta1.id,
            target.id,
        )
        assert new[0].details.get("role_from") == role_from
        assert new[0].details.get("role_to") == role_to

    assert await member_role(env, ta1.id) == "business_admin"
    denied = await admin_call(env, tok1, "create", ta1.id)
    assert denied.status_code == 403
    project = await env.client.post(PROJECTS, json={"name": "P"}, headers=env.auth(tok1))
    assert project.status_code == 201, project.text


# --- AC-5: БА и П не имеют прав ТА --------------------------------------------------------------


@pytest.mark.parametrize("actor_role", ["business_admin", "user"])
async def test_002_ac5_non_ta_gets_403_on_every_ta_action(api_env: ApiEnv, actor_role: str) -> None:
    """002/AC-5 (FR-3, FR-6). Замена test_ac26_non_admins_... без mixed."""
    env = api_env
    w = await make_world_002(env)  # ta1, ta2, ba.owner, ba.member, u1, u2 ... (spec 002 §6)
    ws = w.ws
    actor_name = "ba.owner" if actor_role == "business_admin" else "u1"
    actor = w.people[actor_name].user
    token = w.tok(actor_name)
    target = w.people["u2"].user
    target_token = w.tok("u2")
    blocked_target, _ = await seed(env, ws, "user", blocked=True)

    state_before = (
        await member_role(env, actor.id),
        await member_role(env, target.id),
        await env.session_ids(target.id),
        await env.session_ids(actor.id),
        (await env.user_row(target.id)).password_hash,
        await _journal_len(env, ws.id),
    )
    calls: list[tuple[str, uuid.UUID]] = []
    for victim in (target.id, actor.id):
        for action in ("role_ta", "role_ba", "role_user", "role_none", "block", "revoke"):
            calls.append((action, victim))
    calls += [("unblock", blocked_target.id), ("reset", target.id), ("create", target.id)]
    for action, victim in calls:
        r = await admin_call(env, token, action, victim)
        assert r.status_code == 403, (action, victim, r.text)
    for url in (AUDIT, ADMIN_USERS):
        assert (await env.client.get(url, headers=env.auth(token))).status_code == 403

    state_after = (
        await member_role(env, actor.id),
        await member_role(env, target.id),
        await env.session_ids(target.id),
        await env.session_ids(actor.id),
        (await env.user_row(target.id)).password_hash,
        await _journal_len(env, ws.id),
    )
    assert state_after == state_before
    assert (await env.user_row(blocked_target.id)).is_blocked is True
    assert (await env.me(target_token)).status_code == 200


# --- AC-6: единственный активный ТА -------------------------------------------------------------


async def test_002_ac6_sole_active_ta_cannot_lose_ta_role_or_block_self(
    api_env: ApiEnv,
) -> None:
    """002/AC-6 (FR-7). Заменяет 001 ``test_ac78_last_admin_may_switch_between_admin_roles``.

    Также принимает покрытие удалённого параметра ``("mixed", "business_admin")`` из
    ``test_ac78_last_admin_cannot_switch_to_role_without_manage_accounts`` (NFR-3): единственный
    ТА не меняет роль на БА, П и не снимает её.
    """
    env = api_env
    ws = await new_workspace(env)
    ta1, (tok1,) = await seed(env, ws, "tech_admin")
    await seed(env, ws, "tech_admin", blocked=True)

    for action in ("role_none", "role_ba", "role_user", "block"):
        r = await admin_call(env, tok1, action, ta1.id)
        assert r.status_code == 422, (action, r.text)
        assert code_of(r) == "last_account_admin", action

    assert await member_role(env, ta1.id) == "tech_admin"
    assert (await env.user_row(ta1.id)).is_blocked is False
    assert len(await env.session_ids(ta1.id)) == 1
    assert (await env.me(tok1)).status_code == 200
    assert await _journal_len(env, ws.id) == 0


# --- AC-7: при двух активных ТА один может уйти; второй уже защищён -----------------------------


async def test_002_ac7_ta_switches_own_role_to_user_then_other_is_protected(
    api_env: ApiEnv,
) -> None:
    """002/AC-7 (FR-7). Заменяет 001 ``test_fr12_ta_and_mixed_may_change_own_role``."""
    env = api_env
    ws = await new_workspace(env)
    ta1, (tok1,) = await seed(env, ws, "tech_admin")
    ta2, (tok2,) = await seed(env, ws, "tech_admin")

    r = await _put_role(env, tok1, ta1.id, "user")

    assert r.status_code == 200, r.text
    assert r.json()["role"] == "user"
    log = await events(env, workspace_id=ws.id)
    assert len(log) == 1
    assert (log[0].action, log[0].actor_id, log[0].entity_id) == (
        "user.role_changed",
        ta1.id,
        ta1.id,
    )
    assert log[0].details["role_from"] == "tech_admin"
    assert log[0].details["role_to"] == "user"

    r = await _put_role(env, tok2, ta2.id, None)
    assert r.status_code == 422, r.text
    assert code_of(r) == "last_account_admin"
    assert await member_role(env, ta2.id) == "tech_admin"
    assert await _journal_len(env, ws.id) == 1


async def test_002_ac7_ta_blocks_self_sessions_end_other_ta_stays_active(
    api_env: ApiEnv,
) -> None:
    """002/AC-7 (FR-7, 001/FR-5): блокировка себя при втором активном ТА."""
    env = api_env
    ws = await new_workspace(env)
    ta1, (tok1a, tok1b) = await seed(env, ws, "tech_admin", sessions=2)
    ta2, (tok2,) = await seed(env, ws, "tech_admin")

    r = await _post(env, tok1a, ta1.id, "block")

    assert r.status_code == 204, r.text
    for tok in (tok1a, tok1b):
        assert (await env.me(tok)).status_code == 401
    assert (await env.user_row(ta1.id)).is_blocked is True
    assert await env.session_ids(ta1.id) == []
    assert await active_ta_count(env, ws.id) == 1
    assert (await env.me(tok2)).status_code == 200
    log = await events(env, workspace_id=ws.id)
    assert [(e.action, e.actor_id, e.entity_id) for e in log] == [("user.blocked", ta1.id, ta1.id)]


# --- AC-8: действия над другим ТА ---------------------------------------------------------------


async def test_002_ac8_ta_removes_role_of_other_ta_then_cannot_remove_own(
    api_env: ApiEnv,
) -> None:
    """002/AC-8 (FR-7): снятие роли с другого ТА, затем снятие с себя -> 422."""
    env = api_env
    ws = await new_workspace(env)
    ta1, (tok1,) = await seed(env, ws, "tech_admin")
    ta2, _ = await seed(env, ws, "tech_admin")

    r = await _put_role(env, tok1, ta2.id, None)

    assert r.status_code == 200, r.text
    assert await member_role(env, ta2.id) is None
    log = await events(env, workspace_id=ws.id)
    assert [(e.action, e.actor_id, e.entity_id) for e in log] == [
        ("user.role_removed", ta1.id, ta2.id)
    ]
    assert log[0].details["role_from"] == "tech_admin"

    r = await _put_role(env, tok1, ta1.id, None)
    assert (r.status_code, code_of(r)) == (422, "last_account_admin")
    assert await member_role(env, ta1.id) == "tech_admin"
    assert await _journal_len(env, ws.id) == 1


async def test_002_ac8_ta_blocks_other_ta_then_cannot_remove_own_role(api_env: ApiEnv) -> None:
    """002/AC-8 (FR-7): блокировка другого ТА, затем снятие роли с себя -> 422."""
    env = api_env
    ws = await new_workspace(env)
    ta1, (tok1,) = await seed(env, ws, "tech_admin")
    ta2, (tok2,) = await seed(env, ws, "tech_admin")

    r = await _post(env, tok1, ta2.id, "block")

    assert r.status_code == 204, r.text
    assert (await env.user_row(ta2.id)).is_blocked is True
    assert (await env.me(tok2)).status_code == 401
    log = await events(env, workspace_id=ws.id)
    assert [(e.action, e.actor_id, e.entity_id) for e in log] == [("user.blocked", ta1.id, ta2.id)]

    r = await _put_role(env, tok1, ta1.id, None)
    assert (r.status_code, code_of(r)) == (422, "last_account_admin")
    assert await member_role(env, ta1.id) == "tech_admin"
    assert await _journal_len(env, ws.id) == 1


# --- AC-9: ТА с одноразовым паролем считается активным -----------------------------------------


async def test_002_ac9_ta_with_one_time_password_counts_as_active(api_env: ApiEnv) -> None:
    """002/AC-9 (FR-7, граничный): ta2 не сменил одноразовый пароль, ta1 меняет роль на БА."""
    env = api_env
    ws = await new_workspace(env)
    ta1, (tok1,) = await seed(env, ws, "tech_admin")
    ta2, _ = await seed(env, ws, "tech_admin", must_change_password=True)

    r = await _put_role(env, tok1, ta1.id, "business_admin")

    assert r.status_code == 200, r.text
    assert r.json()["role"] == "business_admin"
    assert await member_role(env, ta2.id) == "tech_admin"
    log = await events(env, workspace_id=ws.id)
    assert [(e.action, e.actor_id, e.entity_id) for e in log] == [
        ("user.role_changed", ta1.id, ta1.id)
    ]
    assert log[0].details["role_to"] == "business_admin"
    assert await active_ta_count(env, ws.id) == 1
