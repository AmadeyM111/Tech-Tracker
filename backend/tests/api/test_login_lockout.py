"""T13: защита от перебора через HTTP (FR-61, AC-37, AC-30, AC-116).

Счётчик неудач и ``login_locked_until`` переживают откат запроса (``commit_durably``, T11):
проверяется на реальных фиксациях (``committed_api_env``). Параллельность — отдельные
соединения на запрос (``asyncio.gather``). Время — ``FixedClock`` (``env.clock``).
"""

import asyncio
from datetime import timedelta

import httpx

from tests.conftest import FIXED_NOW, ApiEnv

PW = "Sup3r-secret-Pa55phrase-xyz"
BAD = "Wr0ng-Pa55phrase-unique-qq"


def _same_failure(response: httpx.Response, reference: httpx.Response) -> bool:
    return (
        response.status_code == reference.status_code
        and response.json() == reference.json()
        and not response.headers.get_list("set-cookie")
        and {k: v for k, v in response.headers.items() if k != "date"}
        == {k: v for k, v in reference.headers.items() if k != "date"}
    )


async def test_ac37_four_failures_then_correct_password_logs_in(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    user = await env.new_user(role="user", password=PW)
    for _ in range(4):
        assert (await env.login(user.login, BAD)).status_code == 401
    response = await env.login(user.login, PW)
    assert response.status_code == 200
    assert env.token_from(response)


async def test_ac37_success_resets_counter(committed_api_env: ApiEnv) -> None:
    env = committed_api_env
    user = await env.new_user(role="user", password=PW)
    for _ in range(4):
        await env.login(user.login, BAD)
    assert (await env.login(user.login, PW)).status_code == 200
    for _ in range(4):  # снова 4 неудачи — ещё не блокировка
        assert (await env.login(user.login, BAD)).status_code == 401
    assert (await env.login(user.login, PW)).status_code == 200


async def test_ac37_fr61_five_failures_lock_for_fifteen_minutes_then_unlock(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    user = await env.new_user(role="user", password=PW)
    reference = await env.login(user.login, BAD)
    assert reference.status_code == 401
    for _ in range(4):
        assert (await env.login(user.login, BAD)).status_code == 401

    # блокировка: верный пароль отклоняется тем же ответом, cookie нет, сессия не создана
    locked = await env.login(user.login, PW)
    assert locked.status_code == 401
    assert env.token_from(locked) is None
    assert _same_failure(locked, reference)
    assert await env.session_ids(user.id) == []

    env.clock.advance(timedelta(minutes=14, seconds=59))
    still_locked = await env.login(user.login, PW)
    assert still_locked.status_code == 401
    assert _same_failure(still_locked, reference)

    env.clock.advance(timedelta(seconds=1))  # ровно 15 минут с момента блокировки
    response = await env.login(user.login, PW)
    assert response.status_code == 200, response.text
    assert env.token_from(response)


async def test_fr61_attempts_during_lock_do_not_extend_it(committed_api_env: ApiEnv) -> None:
    env = committed_api_env
    user = await env.new_user(role="user", password=PW)
    for _ in range(5):
        await env.login(user.login, BAD)
    env.clock.advance(timedelta(minutes=10))
    for _ in range(3):  # попытки во время блокировки (неверные и верные)
        assert (await env.login(user.login, BAD)).status_code == 401
        assert (await env.login(user.login, PW)).status_code == 401
    env.clock.advance(timedelta(minutes=5))  # 15 мин с начала блокировки
    assert (await env.login(user.login, PW)).status_code == 200


async def test_fr61_failure_counter_survives_request_rollback(committed_api_env: ApiEnv) -> None:
    """401 откатывает транзакцию запроса, но счётчик уже зафиксирован (проверка свежей сессией)."""
    env = committed_api_env
    user = await env.new_user(role="user", password=PW)
    for expected in (1, 2, 3):
        assert (await env.login(user.login, BAD)).status_code == 401
        row = await env.user_row(user.id)
        assert row.failed_login_count == expected
        assert row.login_locked_until is None

    await env.login(user.login, BAD)
    await env.login(user.login, BAD)
    row = await env.user_row(user.id)
    assert row.login_locked_until == FIXED_NOW + timedelta(minutes=15)


async def test_fr61_unknown_login_attempts_are_indistinguishable_and_never_lock_out_others(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    user = await env.new_user(role="user", password=PW)
    reference = await env.login(user.login, BAD)
    for _ in range(8):
        response = await env.login("ghost.user", BAD)
        assert _same_failure(response, reference)
    assert (await env.login(user.login, PW)).status_code == 200


async def test_ac116_fr61_failures_with_upper_case_login_lock_the_normalized_account(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    user = await env.new_user(role="user", login="ivan.petrov", password=PW)
    for variant in ("IVAN.PETROV", "Ivan.Petrov", "ivan.PETROV", "IVAN.petrov", "ivan.petrov"):
        assert (await env.login(variant, BAD)).status_code == 401
    assert (await env.login("ivan.petrov", PW)).status_code == 401
    assert (await env.login("IVAN.PETROV", PW)).status_code == 401
    row = await env.user_row(user.id)
    assert row.login_locked_until is not None


_AC127_VARIANTS = ("ivanov.petr", "IVANOV.PETR", "Ivanov.Petr", "ivanov.PETR", "IvAnOv.PeTr")


async def test_ac127_five_failures_in_mixed_case_lock_one_account_then_unlock_after_15_minutes(
    committed_api_env: ApiEnv,
) -> None:
    """FR-73a, FR-61: счётчик и блокировка — на учётную запись, в каком бы регистре ни вводили."""
    env = committed_api_env
    user = await env.new_user(role="business_admin", login="Ivanov.Petr", password=PW)
    reference = await env.login("ghost.user", BAD)  # несуществующий логин: эталон отказа
    assert reference.status_code == 401

    for variant in _AC127_VARIANTS:
        assert (await env.login(variant, BAD)).status_code == 401
    row = await env.user_row(user.id)
    assert row.login_locked_until == FIXED_NOW + timedelta(minutes=15)

    locked = await env.login("Ivanov.Petr", PW)
    assert locked.status_code == 401
    assert env.token_from(locked) is None
    assert _same_failure(locked, reference)
    assert await env.session_ids(user.id) == []

    env.clock.advance(timedelta(minutes=14, seconds=59))
    assert (await env.login("Ivanov.Petr", PW)).status_code == 401

    env.clock.advance(timedelta(seconds=1))
    response = await env.login("Ivanov.Petr", PW)
    assert response.status_code == 200, response.text
    assert response.json()["user"]["login"] == "Ivanov.Petr"
    assert env.token_from(response)


async def test_ac127_four_failures_in_mixed_case_do_not_lock(committed_api_env: ApiEnv) -> None:
    env = committed_api_env
    user = await env.new_user(role="business_admin", login="Ivanov.Petr", password=PW)
    for variant in _AC127_VARIANTS[:4]:
        assert (await env.login(variant, BAD)).status_code == 401
    row = await env.user_row(user.id)
    assert row.failed_login_count == 4
    assert row.login_locked_until is None
    assert (await env.login("IVANOV.PETR", PW)).status_code == 200


async def test_fr61_lock_is_per_login(committed_api_env: ApiEnv) -> None:
    env = committed_api_env
    first = await env.new_user(role="user", password=PW)
    second = await env.new_user(role="user", password=PW)
    for _ in range(5):
        await env.login(first.login, BAD)
    assert (await env.login(first.login, PW)).status_code == 401
    assert (await env.login(second.login, PW)).status_code == 200


async def test_fr61_parallel_burst_locks_and_correct_password_gets_no_cookie_afterwards(
    committed_api_env: ApiEnv,
) -> None:
    """20 неверных + верный параллельно: блокировка наступает, верный вход после неё отклонён.

    Известное поведение plan §4.6: верная попытка, зарезервированная до порога, может
    пройти (не больше одной сессии), но после фиксации блокировки cookie не выдаётся.
    """
    env = committed_api_env
    user = await env.new_user(role="user", password=PW)

    responses = await asyncio.gather(
        *[env.login(user.login, BAD) for _ in range(20)],
        env.login(user.login, PW),
    )
    wrong, correct = responses[:20], responses[20]
    assert all(r.status_code == 401 for r in wrong)
    assert all(env.token_from(r) is None for r in wrong)
    assert correct.status_code in (200, 401)
    assert len(await env.session_ids(user.id)) <= 1

    row = await env.user_row(user.id)
    assert row.login_locked_until is not None, "блокировка не зафиксирована"
    after = await env.login(user.login, PW)
    assert after.status_code == 401
    assert env.token_from(after) is None
    assert _same_failure(after, wrong[0])


async def test_fr61_parallel_correct_attempts_after_lock_all_rejected(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    user = await env.new_user(role="user", password=PW)
    for _ in range(5):
        await env.login(user.login, BAD)

    responses = await asyncio.gather(*[env.login(user.login, PW) for _ in range(10)])
    assert all(r.status_code == 401 for r in responses)
    assert all(env.token_from(r) is None for r in responses)
    assert await env.session_ids(user.id) == []


async def test_fr61_parallel_wrong_attempts_do_not_exceed_threshold_of_checks(
    committed_api_env: ApiEnv,
) -> None:
    """Параллельные неверные попытки: не больше порога проверок паролей между фиксациями."""
    env = committed_api_env
    user = await env.new_user(role="user", password=PW)
    hasher = env.app.state.password_hasher
    calls = 0
    original = hasher.verify

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    hasher.verify = counting
    try:
        await asyncio.gather(*[env.login(user.login, BAD) for _ in range(20)])
    finally:
        hasher.verify = original

    assert calls <= env.settings.login_max_failures, calls
