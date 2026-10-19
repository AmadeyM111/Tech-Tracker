"""T17: ``PUT /api/v1/admin/users/{id}/role`` и защита последнего администратора (plan §4.6).

AC-26, AC-75, AC-78, AC-121 (назначение — отдельное действие); FR-12 (ADR-0003), FR-66, FR-67,
FR-69. Заметки ревью T16a: (a) параллельно заблокированный актор не доводит действие до 2xx,
(b) ``change_own_password`` заблокированного — не 204, (c) реальные админ-эндпоинты в
дедлок-сценариях T16a (HTTP-стресс, 100 итераций, без 5xx).

Конкурентные тесты: ``committed_api_env`` (чистая схема, соединение на запрос). Удержание
запроса «после ``get_actor``, до протокола блокировок» — подмена ``_lock_for_account_change``
сервиса (имя из plan §4.6) обёрткой, ждущей ``Event``.
"""

import asyncio
import itertools
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from tests.admin_support import (
    ADMIN_USERS,
    OTP,
    OTP_FIELD,
    PW,
    active_admin_count,
    admin_call,
    admin_in_new_workspace,
    code_of,
    events,
    member_role,
    new_workspace,
    seed,
)
from tests.conftest import ApiEnv

ITERATIONS_RACE = 36
ITERATIONS_STALE = 30
ITERATIONS_DEADLOCK = 100
MAX_FAILURES = 3


async def _put_role(
    env: ApiEnv, token: str, user_id: Any, role: Any, **extra: str
) -> httpx.Response:
    return await env.client.put(
        f"{ADMIN_USERS}/{user_id}/role", json={"role": role}, headers=env.auth(token, **extra)
    )


# --- назначение, смена, снятие (AC-75, AC-121) --------------------------------------------------


async def test_ac121_ac75_create_then_assign_role_are_two_separate_events(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _, admin, token = await admin_in_new_workspace(env)
    created = await env.client.post(
        ADMIN_USERS, json={"login": "ivan.petrov", OTP_FIELD: OTP}, headers=env.auth(token)
    )
    assert created.status_code == 201
    new_id = uuid.UUID(created.json()["id"])
    assert created.json()["role"] is None
    assert await member_role(env, new_id) is None

    response = await _put_role(env, token, new_id, "user")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(new_id)
    assert body["role"] == "user"
    assert set(body) == {"id", "login", "role", "is_blocked", "must_change_password", "created_at"}
    assert await member_role(env, new_id) == "user"
    log = await events(env, entity_id=new_id)
    assert [e.action for e in log] == ["user.created", "user.role_assigned"]
    assert all(e.actor_id == admin.id for e in log)
    assert log[1].details["role_to"] == "user"


async def test_ac75_change_and_remove_role_with_events(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")

    changed = await _put_role(env, token, target.id, "business_admin")
    removed = await _put_role(env, token, target.id, None)

    assert (changed.status_code, changed.json()["role"]) == (200, "business_admin")
    assert (removed.status_code, removed.json()["role"]) == (200, None)
    assert await member_role(env, target.id) is None
    log = await events(env, entity_id=target.id)
    assert [e.action for e in log] == ["user.role_changed", "user.role_removed"]
    assert log[0].details["role_from"] == "user"
    assert log[0].details["role_to"] == "business_admin"
    assert log[1].details["role_from"] == "business_admin"


@pytest.mark.parametrize("role", ["tech_admin", "business_admin", "user"])
async def test_fr12_every_role_value_can_be_assigned(api_env: ApiEnv, role: str) -> None:
    """001/FR-12, обращён по 002/FR-1: три значения роли назначаются (200); `mixed` - ниже."""
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, None)
    response = await _put_role(env, token, target.id, role)
    assert response.status_code == 200, response.text
    assert response.json()["role"] == role


async def test_002_ac24_fr1_mixed_role_is_422_and_role_unchanged(api_env: ApiEnv) -> None:
    """002/AC-24, FR-1, FR-18: `mixed` от ТА отклоняется, роль цели не меняется."""
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")

    response = await _put_role(env, token, target.id, "mixed")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"
    assert await member_role(env, target.id) == "user"
    assert await events(env, entity_id=target.id) == []


async def test_ac75_same_role_returns_200_without_new_event(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")

    response = await _put_role(env, token, target.id, "user")
    none_target, _ = await seed(env, ws, None)
    none_response = await _put_role(env, token, none_target.id, None)

    assert response.status_code == 200
    assert response.json()["role"] == "user"
    assert none_response.status_code == 200
    assert none_response.json()["role"] is None
    assert await events(env, entity_id=target.id) == []
    assert await events(env, entity_id=none_target.id) == []


@pytest.mark.parametrize("value", ["superuser", "", "TECH_ADMIN", 5, ["user"], True])
async def test_ac75_invalid_role_value_is_422_and_role_unchanged(
    api_env: ApiEnv, value: Any
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user")

    response = await _put_role(env, token, target.id, value)

    assert response.status_code == 422, response.text
    assert await member_role(env, target.id) == "user"
    assert await events(env, entity_id=target.id) == []


async def test_ac75_role_put_does_not_touch_sessions_or_password(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, (target_token,) = await seed(env, ws, "user", password=PW)

    assert (await _put_role(env, token, target.id, "business_admin")).status_code == 200

    assert len(await env.session_ids(target.id)) == 1
    assert (await env.me(target_token)).status_code == 200
    row = await env.user_row(target.id)
    assert row.password_hash == target.password_hash


async def test_fr67_new_role_takes_effect_on_next_request_without_relogin(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, (target_token,) = await seed(env, ws, None)
    before = await env.me(target_token)
    assert before.status_code == 403
    assert code_of(before) == "no_role"

    assert (await _put_role(env, token, target.id, "business_admin")).status_code == 200
    after = await env.me(target_token)
    assert after.status_code == 200
    assert after.json()["role"] == "business_admin"

    assert (await _put_role(env, token, target.id, "user")).status_code == 200
    again = await env.me(target_token)
    assert again.json()["role"] == "user"
    assert "manage_accounts" not in again.json()["capabilities"]

    assert (await _put_role(env, token, target.id, None)).status_code == 200
    removed = await env.me(target_token)
    assert (removed.status_code, code_of(removed)) == (403, "no_role")


async def test_fr67_promoted_user_gets_admin_access_with_the_same_token(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, (target_token,) = await seed(env, ws, "user")
    assert (await env.client.get(ADMIN_USERS, headers=env.auth(target_token))).status_code == 403

    await _put_role(env, token, target.id, "tech_admin")

    assert (await env.client.get(ADMIN_USERS, headers=env.auth(target_token))).status_code == 200


# --- самоназначение (FR-12, ADR-0003) -----------------------------------------------------------


async def test_fr12_ta_may_change_own_role_when_another_ta_remains(api_env: ApiEnv) -> None:
    """002/AC-4, AC-7: ТА при втором активном ТА меняет свою роль на БА (было: ТА/СМ <-> mixed)."""
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)  # второй активный ТА
    actor, (token,) = await seed(env, ws, "tech_admin")

    response = await _put_role(env, token, actor.id, "business_admin")

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "business_admin"
    log = await events(env, entity_id=actor.id)
    assert [e.action for e in log] == ["user.role_changed"]
    assert log[0].actor_id == actor.id  # самоназначение фиксируется в журнале
    assert log[0].details["role_from"] == "tech_admin"
    assert log[0].details["role_to"] == "business_admin"
    me = await env.me(token)
    assert me.json()["role"] == "business_admin"


async def test_fr12_admin_may_demote_self_when_another_admin_remains(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    actor, (token,) = await seed(env, ws, "tech_admin")

    response = await _put_role(env, token, actor.id, "user")

    assert response.status_code == 200
    assert (await env.client.get(ADMIN_USERS, headers=env.auth(token))).status_code == 403


# --- БА, Пользователь, без роли: 403 (AC-26) ----------------------------------------------------


@pytest.mark.parametrize("role", ["business_admin", "user", None])
async def test_ac26_non_admins_cannot_assign_roles_including_self(
    api_env: ApiEnv, role: str | None
) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    actor, (token,) = await seed(env, ws, role)
    target, _ = await seed(env, ws, "user")

    # 002/AC-5: набор администраторов учётных записей - только ТА (``mixed`` убран)
    for victim, value in (
        (target.id, "business_admin"),
        (target.id, None),
        (actor.id, "tech_admin"),
    ):
        response = await _put_role(env, token, victim, value)
        assert response.status_code == 403, (victim, value, response.text)

    assert await member_role(env, target.id) == "user"
    assert await member_role(env, actor.id) == role
    assert await events(env, entity_id=target.id) == []
    assert await events(env, entity_id=actor.id) == []


async def test_ac26_role_gate_precedes_target_lookup(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, _ = await admin_in_new_workspace(env)
    _, (token,) = await seed(env, ws, "business_admin")
    response = await _put_role(env, token, uuid.uuid4(), "user")
    assert response.status_code == 403


# --- последний администратор (AC-78, FR-69) -----------------------------------------------------


async def test_ac78_last_admin_cannot_remove_own_role(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    other, (other_token,) = await seed(env, ws, "user")

    response = await _put_role(env, token, admin.id, None)

    assert response.status_code == 422, response.text
    assert code_of(response) == "last_account_admin"
    assert await member_role(env, admin.id) == "tech_admin"
    assert await events(env, entity_id=admin.id) == []
    assert (await env.me(token)).status_code == 200
    assert other.id and (await env.me(other_token)).status_code == 200


@pytest.mark.parametrize(
    ("role", "new_role"),
    [("tech_admin", "business_admin"), ("tech_admin", "user")],
)
async def test_ac78_last_admin_cannot_switch_to_role_without_manage_accounts(
    api_env: ApiEnv, role: str, new_role: str
) -> None:
    env = api_env
    _, admin, token = await admin_in_new_workspace(env, role)

    response = await _put_role(env, token, admin.id, new_role)

    assert response.status_code == 422
    assert code_of(response) == "last_account_admin"
    assert await member_role(env, admin.id) == role


# Удалён ``test_ac78_last_admin_may_switch_between_admin_roles`` (ТА -> mixed): по 002/FR-7
# единственный ТА не меняет роль ни на какую другую. Заменители: ``test_002_ac6_*``
# (api/test_tech_admins_002.py) и в R3-T11 ``test_002_ac24_*``. Также удалён параметр
# ``("mixed", "business_admin")`` из ``test_ac78_last_admin_cannot_switch_to_role_without_manage_
# accounts``: покрытие перенесено в ``test_002_ac6_*`` (ТА -> БА/П/без роли -> 422).


async def test_ac78_last_admin_cannot_block_self_and_sessions_survive(api_env: ApiEnv) -> None:
    env = api_env
    _, admin, token = await admin_in_new_workspace(env)

    response = await env.client.post(f"{ADMIN_USERS}/{admin.id}/block", headers=env.auth(token))

    assert response.status_code == 422, response.text
    assert code_of(response) == "last_account_admin"
    assert (await env.user_row(admin.id)).is_blocked is False
    assert len(await env.session_ids(admin.id)) == 1  # откат: сессии не удалены
    assert (await env.me(token)).status_code == 200
    assert await events(env, entity_id=admin.id) == []


async def test_ac78_blocked_admin_does_not_count_as_remaining(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    await seed(env, ws, "tech_admin", blocked=True)

    response = await _put_role(env, token, admin.id, "user")

    assert response.status_code == 422
    assert code_of(response) == "last_account_admin"


async def test_ac78_two_admins_one_may_be_blocked_then_other_is_protected(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, first, token = await admin_in_new_workspace(env)
    second, _ = await seed(env, ws, "tech_admin")

    blocked = await env.client.post(f"{ADMIN_USERS}/{second.id}/block", headers=env.auth(token))
    again = await _put_role(env, token, first.id, None)
    unblock_then = await env.client.post(
        f"{ADMIN_USERS}/{second.id}/unblock", headers=env.auth(token)
    )
    demote = await _put_role(env, token, first.id, "user")

    assert blocked.status_code == 204
    assert (again.status_code, code_of(again)) == (422, "last_account_admin")
    assert unblock_then.status_code == 204
    assert demote.status_code == 200
    assert await active_admin_count(env, ws.id) == 1


async def test_ac78_non_admin_roles_can_be_changed_and_blocked_freely(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "business_admin")
    assert (await _put_role(env, token, target.id, None)).status_code == 200
    assert (
        await env.client.post(f"{ADMIN_USERS}/{target.id}/block", headers=env.auth(token))
    ).status_code == 204


# --- конкурентность: последний администратор (AC-78) -------------------------------------------


async def _call(request: Awaitable[httpx.Response]) -> tuple[str, int | str]:
    """``("status", код)`` или ``("exc", описание)``: 500 в ASGI приходит исключением."""
    try:
        response = await request
    except Exception as exc:
        return "exc", f"{type(exc).__name__}: {str(getattr(exc, 'orig', exc))[:60]}"
    return "status", response.status_code


def _bad(result: tuple[str, int | str], allowed: set[int]) -> bool:
    kind, value = result
    return kind == "exc" or value not in allowed


async def test_ac78_parallel_requests_never_leave_zero_active_admins(
    committed_api_env: ApiEnv,
) -> None:
    """A и B — единственные администраторы; каждый одновременно лишает прав другого."""
    env = committed_api_env
    variants = (
        ("role_user", "role_user"),
        ("block", "block"),
        ("role_none", "block"),
    )
    allowed = {200, 204, 401, 403, 422}
    failures: list[str] = []
    for i in range(ITERATIONS_RACE):
        ws = await new_workspace(env)
        a, (tok_a,) = await seed(env, ws, "tech_admin")
        b, (tok_b,) = await seed(env, ws, "tech_admin")  # 002/AC-10: был СМ -> второй ТА
        act_a, act_b = variants[i % 3]
        results = await asyncio.gather(
            _call(admin_call(env, tok_a, act_a, b.id)),
            _call(admin_call(env, tok_b, act_b, a.id)),
        )
        remaining = await active_admin_count(env, ws.id)
        problems = [r for r in results if _bad(r, allowed)]
        if problems or remaining < 1:
            failures.append(f"итерация {i} {act_a}/{act_b}: {results}, админов {remaining}")
            if len(failures) >= MAX_FAILURES:
                break
        # хотя бы один запрос отклонён (оба 2xx оставили бы ноль администраторов)
        elif all(r[0] == "status" and 200 <= int(r[1]) < 300 for r in results):
            failures.append(f"итерация {i}: оба запроса успешны {results}")
    assert not failures, "\n".join(failures)


async def test_ac78_parallel_demotion_of_one_target_by_two_admins_is_consistent(
    committed_api_env: ApiEnv,
) -> None:
    """Три администратора; два параллельно лишают прав третьего, потом друг друга."""
    env = committed_api_env
    failures: list[str] = []
    for i in range(ITERATIONS_RACE):
        ws = await new_workspace(env)
        a, (tok_a,) = await seed(env, ws, "tech_admin")
        b, (tok_b,) = await seed(env, ws, "tech_admin")
        c, _ = await seed(env, ws, "tech_admin")
        results = await asyncio.gather(
            _call(admin_call(env, tok_a, "role_user", c.id)),
            _call(admin_call(env, tok_b, "role_user", a.id)),
            _call(admin_call(env, tok_a, "block", b.id)),
        )
        remaining = await active_admin_count(env, ws.id)
        if any(_bad(r, {200, 204, 401, 403, 422}) for r in results) or remaining < 1:
            failures.append(f"итерация {i}: {results}, админов {remaining}")
            if len(failures) >= MAX_FAILURES:
                break
    assert not failures, "\n".join(failures)


# --- заметка ревью T16a (a): заблокированный параллельно актор ------------------------------------


@dataclass
class Gate:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    armed: bool = False


def _install_gate(monkeypatch: pytest.MonkeyPatch) -> Gate:
    """Первый вызов протокола блокировок после ``arm`` ждёт ``release`` (актор уже прошёл
    ``get_actor`` и хеширование пароля, блокировок ещё нет)."""
    from app.domain.users import service as users_service

    gate = Gate()
    original = users_service._lock_for_account_change

    async def gated(*args: Any, **kwargs: Any) -> Any:
        if gate.armed:
            gate.armed = False
            gate.entered.set()
            await asyncio.wait_for(gate.release.wait(), timeout=15)
        return await original(*args, **kwargs)

    monkeypatch.setattr(users_service, "_lock_for_account_change", gated, raising=True)
    return gate


async def _wait(event: asyncio.Event, task: "asyncio.Task[Any]") -> None:
    waiter = asyncio.ensure_future(event.wait())
    try:
        await asyncio.wait({waiter, task}, timeout=15, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()


A_ACTIONS = ("create", "reset", "revoke", "block", "unblock", "role_ba")
C_REVOKERS = ("block", "role_user", "role_none")


async def _target_state(env: ApiEnv, target_id: uuid.UUID) -> tuple[Any, ...]:
    row = await env.user_row(target_id)
    return (
        row.is_blocked,
        row.must_change_password,
        row.password_hash,
        await member_role(env, target_id),
        tuple(await env.session_ids(target_id)),
    )


async def test_t16a_note_a_actor_blocked_or_demoted_in_flight_never_reaches_2xx(
    committed_api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Админ A прошёл ``get_actor`` и ждёт; C блокирует A / снимает с A роль; действие A не
    выполняется: 401/403, состояние цели и журнал не изменены."""
    env = committed_api_env
    gate = _install_gate(monkeypatch)
    failures: list[str] = []
    for i in range(ITERATIONS_STALE):
        ws = await new_workspace(env)
        a, (tok_a,) = await seed(env, ws, "tech_admin")
        _, _ = await seed(env, ws, "tech_admin")
        c, (tok_c,) = await seed(env, ws, "tech_admin")
        target, _ = await seed(env, ws, "user", sessions=1, blocked=(A_ACTIONS[i % 6] == "unblock"))
        a_action, c_action = A_ACTIONS[i % len(A_ACTIONS)], C_REVOKERS[i % len(C_REVOKERS)]
        users_before = await env.execute(text("SELECT count(*) FROM app_user"))
        state_before = await _target_state(env, target.id)

        gate.entered.clear()
        gate.release.clear()
        gate.armed = True
        task_a = asyncio.ensure_future(_call(admin_call(env, tok_a, a_action, target.id)))
        await _wait(gate.entered, task_a)
        assert gate.entered.is_set(), f"действие {a_action} не дошло до протокола блокировок"
        c_result = await _call(admin_call(env, tok_c, c_action, a.id))
        gate.release.set()
        a_result = await task_a

        problems: list[str] = []
        if c_result != ("status", 204 if c_action == "block" else 200):
            problems.append(f"действие C {c_action}: {c_result}")
        if a_result[0] != "status" or a_result[1] not in (401, 403):
            problems.append(f"действие A {a_action}: {a_result}, ожидалось 401/403")
        if await _target_state(env, target.id) != state_before:
            problems.append("состояние цели изменено отклонённым действием")
        if await env.execute(text("SELECT count(*) FROM app_user")) != users_before:
            problems.append("создан пользователь отклонённым действием")
        by_a = [e for e in await events(env, workspace_id=ws.id) if e.actor_id == a.id]
        if by_a:
            problems.append(f"события от отклонённого актора: {[e.action for e in by_a]}")
        if problems:
            failures.append(f"итерация {i} A={a_action} C={c_action}: " + "; ".join(problems))
            if len(failures) >= MAX_FAILURES:
                break
        assert c.id
    assert not failures, "\n".join(failures)


async def test_t16a_note_a_race_without_gate_result_is_consistent(
    committed_api_env: ApiEnv,
) -> None:
    """Без удержания: либо действие A зафиксировано ДО блокировки A (его событие раньше
    события блокировки), либо оно отклонено и событий от A нет."""
    env = committed_api_env
    failures: list[str] = []
    actions = ("create", "reset", "revoke")
    for i in range(ITERATIONS_STALE * 2):
        ws = await new_workspace(env)
        a, (tok_a,) = await seed(env, ws, "tech_admin")
        await seed(env, ws, "tech_admin")
        _c, (tok_c,) = await seed(env, ws, "tech_admin")
        target, _ = await seed(env, ws, "user")
        a_action = actions[i % 3]

        async def delayed_block(delay: float = (i % 4) * 0.002) -> httpx.Response:
            await asyncio.sleep(delay)
            return await admin_call(env, tok_c, "block", a.id)  # noqa: B023

        res_a, res_c = await asyncio.gather(
            _call(admin_call(env, tok_a, a_action, target.id)),
            _call(delayed_block()),
        )
        log = await events(env, workspace_id=ws.id)
        block_ids = [e.id for e in log if e.action == "user.blocked" and e.entity_id == a.id]
        by_a = [e for e in log if e.actor_id == a.id]
        problems: list[str] = []
        if res_c != ("status", 204) or len(block_ids) != 1:
            problems.append(f"блокировка A: {res_c}, событий {len(block_ids)}")
        if res_a[0] != "status" or res_a[1] not in (204, 201, 200, 401, 403):
            problems.append(f"действие A: {res_a}")
        elif res_a[1] in (200, 201, 204):
            if not by_a or block_ids and not all(e.id < block_ids[0] for e in by_a):
                problems.append("действие A успешно, но событие не предшествует блокировке")
        elif by_a:
            problems.append(f"отклонённое действие A оставило события {[e.action for e in by_a]}")
        if problems:
            failures.append(f"итерация {i} {a_action}: " + "; ".join(problems))
            if len(failures) >= MAX_FAILURES:
                break
    assert not failures, "\n".join(failures)


# --- заметка ревью T16a (b): change_own_password заблокированного -------------------------------


async def test_t16a_note_b_change_own_password_of_blocked_user_is_not_204(
    committed_api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.auth import service as auth_service

    env = committed_api_env
    original = vars(auth_service)["reserve_attempt"]
    entered = asyncio.Event()
    release = asyncio.Event()
    state = {"armed": False}

    async def gated(*args: Any, **kwargs: Any) -> Any:
        if state["armed"]:
            state["armed"] = False
            entered.set()
            await asyncio.wait_for(release.wait(), timeout=15)
        return await original(*args, **kwargs)

    monkeypatch.setattr(auth_service, "reserve_attempt", gated, raising=True)
    failures: list[str] = []
    for i in range(ITERATIONS_STALE):
        ws = await new_workspace(env)
        _, (tok_admin,) = await seed(env, ws, "tech_admin")
        await seed(env, ws, "tech_admin")
        y, (tok_y, _other) = await seed(env, ws, "user", sessions=2, password=PW)
        entered.clear()
        release.clear()
        state["armed"] = True
        new_password = f"New-Pa55phrase-{i:04d}-qzxw"
        task = asyncio.ensure_future(
            _call(
                env.client.post(
                    "/api/v1/auth/password",
                    json={"current_password": PW, "new_password": new_password},
                    headers=env.auth(tok_y),
                )
            )
        )
        await _wait(entered, task)
        assert entered.is_set(), "смена пароля не дошла до reserve_attempt"
        block = await admin_call(env, tok_admin, "block", y.id)
        release.set()
        result = await task

        row = await env.user_row(y.id)
        problems: list[str] = []
        if block.status_code != 204:
            problems.append(f"блокировка: {block.status_code}")
        if result[0] != "status" or int(result[1]) != 401:  # T27: ровно 401
            problems.append(f"смена пароля заблокированным: {result}")
        if row.password_hash != y.password_hash:
            problems.append("пароль заблокированного изменён")
        if row.must_change_password:
            problems.append("флаг смены пароля изменён")
        if problems:
            failures.append(f"итерация {i}: " + "; ".join(problems))
            if len(failures) >= MAX_FAILURES:
                break
    assert not failures, "\n".join(failures)


# --- заметка ревью T16a (c): реальные админ-эндпоинты в дедлок-сценариях ---------------------

ACTOR_ACTIONS = ("block", "unblock", "reset", "revoke", "role_user")  # A над целью T
OVER_ACTOR_ACTIONS = ("block", "unblock", "reset", "revoke", "role_ba")  # C над A


async def test_t16a_note_c_real_admin_endpoints_have_no_deadlock_under_stress(
    committed_api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A выполняет действие над T, C — над A (T16a: A держал строку сессии и ждал advisory).
    Режимы: A удержан до протокола блокировок / C удержан / без удержания. 100 итераций,
    ни одного 5xx (в ASGI 500 приходит исключением) и всегда есть активный администратор."""
    env = committed_api_env
    gate = _install_gate(monkeypatch)
    combos = list(itertools.product(range(3), ACTOR_ACTIONS, OVER_ACTOR_ACTIONS))
    plan = (combos * 2)[:ITERATIONS_DEADLOCK]
    ok = {200, 204, 401, 403, 422}
    failures: list[str] = []
    for i, (mode, a_action, c_action) in enumerate(plan):
        ws = await new_workspace(env)
        a, (tok_a, _a2) = await seed(env, ws, "tech_admin", sessions=2)
        await seed(env, ws, "tech_admin")
        c, (tok_c,) = await seed(env, ws, "tech_admin")
        t, _ = await seed(env, ws, "user", sessions=1, blocked=(a_action == "unblock"))
        results: list[tuple[str, int | str]]

        def req_a(token: str = tok_a, act: str = a_action, tid: uuid.UUID = t.id) -> Any:
            return _call(admin_call(env, token, act, tid))

        def req_c(token: str = tok_c, act: str = c_action, tid: uuid.UUID = a.id) -> Any:
            return _call(admin_call(env, token, act, tid))

        gate.entered.clear()
        gate.release.clear()
        if mode == 0:  # A удержан после get_actor, C выполняется целиком
            gate.armed = True
            task_a = asyncio.ensure_future(req_a())
            await _wait(gate.entered, task_a)
            task_c = asyncio.ensure_future(req_c())
            await asyncio.sleep(0.05)
            gate.release.set()
            results = [await task_a, await task_c]
        elif mode == 1:  # C удержан, A выполняется целиком
            gate.armed = True
            task_c = asyncio.ensure_future(req_c())
            await _wait(gate.entered, task_c)
            task_a = asyncio.ensure_future(req_a())
            await asyncio.sleep(0.05)
            gate.release.set()
            results = [await task_a, await task_c]
        else:
            gate.armed = False
            results = list(await asyncio.gather(req_a(), req_c()))
        gate.armed = False
        remaining = await active_admin_count(env, ws.id)
        if any(_bad(r, ok) for r in results) or remaining < 1:
            failures.append(
                f"итерация {i} режим {mode} A={a_action} C={c_action}: {results}, админов "
                f"{remaining}"
            )
            if len(failures) >= MAX_FAILURES:
                break
        assert c.id
    assert not failures, f"{len(failures)} итераций с 5xx/исключением:\n" + "\n".join(failures)
