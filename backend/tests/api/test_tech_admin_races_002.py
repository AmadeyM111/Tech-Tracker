"""002/R3-T04: AC-10, гонки двух ТА (FR-7, plan §4.4, D-4).

В пространстве ровно два активных ТА (``ta1``, ``ta2``), других ТА нет. Каждый сценарий
(а)-(г) повторяется ``REPEATS`` раз; в каждом повторе фикстура строится заново: новое
пространство, ``ta1`` и ``ta2`` с ролью ``tech_admin``, не заблокированы, свежие сессии.
Запросы стартуют одновременно через ``asyncio.gather`` (без пауз).

Проверки повтора: ровно один запрос выполнен; второй - код из AC либо 503 ``service_busy`` с
``Retry-After`` (FR-7); ровно один активный ТА; в журнале ровно одна новая запись - о
выполненном действии (автор и объект победителя); данные проигравшего не изменены.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from tests.admin_support import (
    active_ta_count,
    admin_call,
    code_of,
    events,
    member_role,
    new_workspace,
    seed,
)
from tests.conftest import ApiEnv

REPEATS = 20


@dataclass(frozen=True)
class Scenario:
    id: str
    action_1: str  # то, что делает ta1
    target_1: str  # над кем: "self" или "other"
    action_2: str
    target_2: str
    loser_codes: frozenset[int]  # допустимые статусы проигравшего (кроме 503)
    loser_code: str | None  # код ошибки в теле (None - не проверяем, 401/403)
    executed_actions: frozenset[str]  # допустимые action записи журнала победителя


SCENARIOS = [
    # (а) оба снимают роль каждый с себя
    Scenario("a", "role_none", "self", "role_none", "self", frozenset({422}),
             "last_account_admin", frozenset({"user.role_removed"})),
    # (б) ta1 блокирует себя, ta2 меняет свою роль на П
    Scenario("b", "block", "self", "role_user", "self", frozenset({422}),
             "last_account_admin", frozenset({"user.blocked", "user.role_changed"})),
    # (в) взаимная блокировка
    Scenario("c", "block", "other", "block", "other", frozenset({401, 403}),
             None, frozenset({"user.blocked"})),
    # (г) взаимное снятие роли
    Scenario("d", "role_none", "other", "role_none", "other", frozenset({403}),
             None, frozenset({"user.role_removed"})),
]  # fmt: skip


async def _call(request: Awaitable[httpx.Response]) -> httpx.Response | BaseException:
    try:
        return await request
    except Exception as exc:  # 500 в ASGI-транспорте приходит исключением
        return exc


def _is_ok(r: httpx.Response) -> bool:
    return 200 <= r.status_code < 300


@pytest.mark.committed
@pytest.mark.parametrize("sc", SCENARIOS, ids=[f"ac10_{s.id}" for s in SCENARIOS])
async def test_002_ac10_parallel_ta_actions_leave_exactly_one_active_ta(
    committed_api_env: ApiEnv, sc: Scenario
) -> None:
    env = committed_api_env
    failures: list[str] = []
    busy_seen = 0

    for i in range(REPEATS):
        ws = await new_workspace(env)
        ta1, (tok1,) = await seed(env, ws, "tech_admin", login=f"r{sc.id}{i}.ta1")
        ta2, (tok2,) = await seed(env, ws, "tech_admin", login=f"r{sc.id}{i}.ta2")
        assert await active_ta_count(env, ws.id) == 2
        journal_before = len(await events(env, workspace_id=ws.id))
        victim_1 = ta1.id if sc.target_1 == "self" else ta2.id
        victim_2 = ta2.id if sc.target_2 == "self" else ta1.id

        results = await asyncio.gather(
            _call(admin_call(env, tok1, sc.action_1, victim_1)),
            _call(admin_call(env, tok2, sc.action_2, victim_2)),
        )
        tag = f"повтор {i}: {results}"

        excs = [r for r in results if isinstance(r, BaseException)]
        if excs:
            failures.append(f"{tag}: исключение {excs!r}")
            continue
        resp: list[httpx.Response] = [r for r in results if isinstance(r, httpx.Response)]
        winners = [k for k, r in enumerate(resp) if _is_ok(r)]
        if len(winners) != 1:
            failures.append(f"{tag}: выполнено запросов {len(winners)}, нужен ровно 1")
            continue
        w_idx, l_idx = winners[0], 1 - winners[0]
        loser = resp[l_idx]
        if loser.status_code == 503:
            busy_seen += 1
            if code_of(loser) != "service_busy" or "retry-after" not in loser.headers:
                failures.append(f"{tag}: 503 без service_busy/Retry-After")
                continue
        else:
            if loser.status_code not in sc.loser_codes:
                failures.append(f"{tag}: проигравший получил {loser.status_code}")
                continue
            if sc.loser_code is not None and code_of(loser) != sc.loser_code:
                failures.append(f"{tag}: код проигравшего {code_of(loser)}")
                continue

        active = await active_ta_count(env, ws.id)
        new = (await events(env, workspace_id=ws.id))[journal_before:]
        win_actor = (ta1.id, ta2.id)[w_idx]
        win_entity = (victim_1, victim_2)[w_idx]
        if active != 1:
            failures.append(f"{tag}: активных ТА {active}")
        elif len(new) != 1:
            failures.append(f"{tag}: новых записей журнала {len(new)}: {[e.action for e in new]}")
        elif (
            new[0].action not in sc.executed_actions
            or new[0].actor_id != win_actor
            or new[0].entity_id != win_entity
        ):
            failures.append(f"{tag}: запись журнала {new[0].action} {new[0].actor_id}")
        else:
            # данные проигравшего не изменены его запросом: проверяем итоговое состояние
            await _check_final_state(env, sc, ta1.id, ta2.id, w_idx, failures, tag)
        if len(failures) >= 3:
            break

    assert not failures, "\n".join(failures)
    # 503 допустим, но не должен быть нормой: большинство повторов даёт коды из AC
    assert busy_seen <= REPEATS // 2, f"слишком много 503: {busy_seen} из {REPEATS}"


async def _check_final_state(
    env: ApiEnv,
    sc: Scenario,
    ta1_id: Any,
    ta2_id: Any,
    winner: int,
    failures: list[str],
    tag: str,
) -> None:
    """Выживший ТА: единственный с ролью ``tech_admin`` и незаблокированный."""
    survivor_roles = {
        "ta1": await member_role(env, ta1_id),
        "ta2": await member_role(env, ta2_id),
    }
    blocked = {
        "ta1": (await env.user_row(ta1_id)).is_blocked,
        "ta2": (await env.user_row(ta2_id)).is_blocked,
    }
    alive = [k for k in ("ta1", "ta2") if survivor_roles[k] == "tech_admin" and not blocked[k]]
    if len(alive) != 1:
        failures.append(f"{tag}: итоговое состояние {survivor_roles} {blocked}")
        return
    # в (в) и (г) победитель действует над соперником, значит выживает именно он;
    # в (а) и (б) победитель убирает себя, значит выживает соперник
    expected = ("ta1", "ta2")[winner] if sc.target_1 == "other" else ("ta2", "ta1")[winner]
    if alive[0] != expected:
        failures.append(f"{tag}: выжил {alive[0]}, ожидался {expected}")
