"""002/R3-T11: значение `mixed` и прочие недопустимые значения роли в запросах, AC-24 (FR-1, FR-18).

Шаги повторяют AC-24 spec 002 буквально: ``ta1`` назначает пользователю ``x`` с ролью П
значения ``mixed``, ``MIXED``, ``admin`` и пустую строку - каждый раз 422 ``validation_error``
(формат 001/FR-45), роль ``x`` остаётся П, новых записей журнала нет; ``ba.owner`` с тем же
запросом получает 403; без сессии - 401 (порядок проверок 001/FR-7: 401, 403, затем 422).
Упоминание `mixed` здесь - отрицательная проверка (допустимо по tasks.md R3-T11).

В «красной» фазе R3-T11 тесты на 422 падают: сервер ещё принимает `mixed` (200).
"""

from __future__ import annotations

import pytest

from tests.admin_support import ADMIN_USERS, member_role
from tests.conftest import ApiEnv
from tests.projects_api_support import event_count
from tests.roles002_support import World002, code_of, make_world_002, send

BAD_VALUES = ["mixed", "MIXED", "admin", ""]


def _role_url(w: World002, who: str) -> str:
    return f"{ADMIN_USERS}/{w.uid(who)}/role"


async def _journal_count(env: ApiEnv, w: World002) -> int:
    return await event_count(env, w.ws.id)


@pytest.mark.parametrize("value", BAD_VALUES)
async def test_002_ac24_ta_invalid_role_value_is_422_and_nothing_changes(
    api_env: ApiEnv, value: str
) -> None:
    """002/AC-24 (FR-18, FR-1): ``ta1`` -> 422 validation_error, роль x - П, журнал без записей."""
    env = api_env
    w = await make_world_002(env)
    before = await _journal_count(env, w)

    r = await send(env, w.tok("ta1"), "PUT", _role_url(w, "u3"), {"role": value})

    assert r.status_code == 422, r.text
    assert code_of(r) == "validation_error"
    assert await member_role(env, w.uid("u3")) == "user"
    assert await _journal_count(env, w) == before


async def test_002_ac24_all_four_values_in_sequence_keep_role_and_journal(
    api_env: ApiEnv,
) -> None:
    """002/AC-24: подряд все четыре значения - каждый раз 422, роль x - П, журнал не растёт."""
    env = api_env
    w = await make_world_002(env)
    before = await _journal_count(env, w)

    for value in BAD_VALUES:
        r = await send(env, w.tok("ta1"), "PUT", _role_url(w, "u3"), {"role": value})
        assert (r.status_code, code_of(r)) == (422, "validation_error"), value
        assert await member_role(env, w.uid("u3")) == "user", value
        assert await _journal_count(env, w) == before, value


async def test_002_ac24_rejected_value_does_not_block_valid_assignment(api_env: ApiEnv) -> None:
    """002/AC-24 (FR-1): после отказов допустимое значение по-прежнему назначается (200)."""
    env = api_env
    w = await make_world_002(env)
    bad = await send(env, w.tok("ta1"), "PUT", _role_url(w, "u3"), {"role": "mixed"})
    assert bad.status_code == 422

    ok = await send(env, w.tok("ta1"), "PUT", _role_url(w, "u3"), {"role": "business_admin"})

    assert ok.status_code == 200, ok.text
    assert ok.json()["role"] == "business_admin"
    assert await member_role(env, w.uid("u3")) == "business_admin"


async def test_002_ac24_business_admin_gets_403_not_422(api_env: ApiEnv) -> None:
    """002/AC-24: ``ba.owner`` с тем же запросом (`mixed`) получает 403; роль и журнал целы."""
    env = api_env
    w = await make_world_002(env)
    before = await _journal_count(env, w)

    r = await send(env, w.tok("ba.owner"), "PUT", _role_url(w, "u3"), {"role": "mixed"})

    assert (r.status_code, code_of(r)) == (403, "forbidden")
    assert await member_role(env, w.uid("u3")) == "user"
    assert await _journal_count(env, w) == before


async def test_002_ac24_user_role_gets_403_not_422(api_env: ApiEnv) -> None:
    """002/AC-24 (порядок 001/FR-7): П с запросом `mixed` - тоже 403, а не 422."""
    env = api_env
    w = await make_world_002(env)

    r = await send(env, w.tok("u1"), "PUT", _role_url(w, "u3"), {"role": "mixed"})

    assert (r.status_code, code_of(r)) == (403, "forbidden")
    assert await member_role(env, w.uid("u3")) == "user"


async def test_002_ac24_no_session_gets_401(api_env: ApiEnv) -> None:
    """002/AC-24: без сессии тот же запрос - 401; роль и журнал не меняются."""
    env = api_env
    w = await make_world_002(env)
    before = await _journal_count(env, w)

    r = await send(env, None, "PUT", _role_url(w, "u3"), {"role": "mixed"})

    assert r.status_code == 401, r.text
    assert code_of(r) == "not_authenticated"
    assert await member_role(env, w.uid("u3")) == "user"
    assert await _journal_count(env, w) == before
