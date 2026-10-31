"""R7-T11: аутентификация по ключу — проверка, срок, лимит частоты (домен; 007, plan §4.7, PD-5).

AC-10, AC-40 (уровень домена); FR-9, FR-13 (домен), FR-16, FR-32, FR-33; PD-9 (``Actor``).

Публичный интерфейс (``app.domain.api_keys.auth``)::

    RATE_LIMIT_PER_MINUTE = 120;  RATE_WINDOW = timedelta(seconds=60)
    KeyPrincipal(key_id, user_id, workspace_id);  RateLimited(retry_after)
    authenticate_api_key(db, digest, *, now) -> KeyPrincipal | RateLimited | None

``Actor.session_id: bytes | None``, ``Actor.api_key_id: UUID | None = None``;
``change_own_password``: ``session_id is None`` -> ``Forbidden`` первым шагом.

Секрет ключа в сообщениях assert не печатается: булево считается до assert.
Блокировка владельца без отзыва ключа, членство и ``is_agent`` проверяются в ``get_actor``
(R7-T12, plan §4.7 ``_actor_from_api_key``) — здесь только путь «блокировка отзывает ключи».
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import event, text

from app.domain.access.roles import Actor, Role
from tests.factories import UserRow, make_api_key, make_user, make_workspace

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from app.core.clock import FixedClock
    from app.core.config import Settings

CLOCK = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
TTL = timedelta(days=90)
LIMIT = 120
PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "brand-new-password-9157"
CHEAP: dict[str, int] = {"time_cost": 1, "memory_cost_kib": 1024, "parallelism": 1}
SECRET_KEY = b"unit-test-secret-key-0123456789ab"


# --- фикстуры и помощники ---------------------------------------------------------------


@pytest.fixture
def auth_mod() -> Any:
    import app.domain.api_keys.auth as auth

    return auth


@pytest.fixture
def clock(fixed_clock: FixedClock) -> FixedClock:
    fixed_clock.set(CLOCK)
    return fixed_clock


def digest_of(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("ascii")).digest()


def fresh_secret() -> str:
    """Секрет формата ``gtk_…`` (не хранится в БД, если не передан в фабрику)."""
    import base64
    import secrets

    return "gtk_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def actor_of(user: UserRow) -> Actor:
    return Actor(
        user_id=user.id,
        workspace_id=user.workspace_id,
        login=user.login,
        role=Role(user.role) if user.role is not None else None,
        must_change_password=False,
        session_id=b"\x01" * 32,
    )


async def world(db: AsyncSession) -> SimpleNamespace:
    ws = await make_workspace(db)
    ta = await make_user(db, workspace=ws, role="tech_admin", login="ta1")
    agent = await make_user(db, workspace=ws, role="user", login="agent.u", is_agent=True)
    agent_ba = await make_user(
        db, workspace=ws, role="business_admin", login="agent.ba", is_agent=True
    )
    key = await make_api_key(
        db, user=agent, created_by=ta, created_at=CLOCK, expires_at=CLOCK + TTL
    )
    key2 = await make_api_key(
        db, user=agent, created_by=ta, created_at=CLOCK, expires_at=CLOCK + TTL, name="второй"
    )
    key_ba = await make_api_key(
        db, user=agent_ba, created_by=ta, created_at=CLOCK, expires_at=CLOCK + TTL, name="ba"
    )
    await db.commit()
    return SimpleNamespace(
        ws=ws, ta=ta, agent=agent, agent_ba=agent_ba, key=key, key2=key2, key_ba=key_ba
    )


async def key_row(db: AsyncSession, key_id: uuid.UUID) -> Any:
    return (
        await db.execute(
            text(
                "SELECT rate_count, rate_window_start, last_used_at, revoked_at "
                "FROM api_key WHERE id = :id"
            ),
            {"id": key_id},
        )
    ).one()


async def authn(
    auth_mod: Any, db: AsyncSession, clock: FixedClock, secret: str, at: datetime
) -> Any:
    """Вызов в момент ``at``: часы процесса и ``now`` совпадают."""
    clock.set(at)
    return await auth_mod.authenticate_api_key(db, digest_of(secret), now=at)


async def call_n(
    auth_mod: Any, db: AsyncSession, clock: FixedClock, secret: str, at: datetime, n: int
) -> list[Any]:
    return [await authn(auth_mod, db, clock, secret, at) for _ in range(n)]


def is_principal(auth_mod: Any, result: Any) -> bool:
    return isinstance(result, auth_mod.KeyPrincipal)


def is_limited(auth_mod: Any, result: Any) -> bool:
    return isinstance(result, auth_mod.RateLimited)


@pytest.fixture
def sql_log(db_engine: AsyncEngine) -> Iterator[list[str]]:
    """Все SQL-операторы, отправленные в БД (кроме SAVEPOINT/RELEASE/ROLLBACK TO)."""
    statements: list[str] = []

    def before(
        conn: Any, cursor: Any, statement: str, params: Any, context: Any, many: bool
    ) -> None:
        head = statement.lstrip().upper()
        if head.startswith(("SAVEPOINT", "RELEASE", "ROLLBACK")):
            return
        statements.append(" ".join(statement.split()))

    event.listen(db_engine.sync_engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", before)


# --- константы и типы результата (PD-5, PD-9, FR-32) ------------------------------------


def test_007_fr33_limit_constants(auth_mod: Any) -> None:
    assert auth_mod.RATE_LIMIT_PER_MINUTE == 120
    assert timedelta(seconds=60) == auth_mod.RATE_WINDOW


def test_007_fr32_principal_carries_no_digest_or_secret(auth_mod: Any) -> None:
    """Дайджест не выходит из слоя: в результатах только идентификаторы и retry_after."""
    names = {f.name for f in dataclasses.fields(auth_mod.KeyPrincipal)}
    assert names == {"key_id", "user_id", "workspace_id"}
    assert {f.name for f in dataclasses.fields(auth_mod.RateLimited)} == {"retry_after"}


async def test_007_fr12_valid_key_returns_principal_of_owner(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    result = await authn(auth_mod, db, clock, w.key.secret, CLOCK)
    assert is_principal(auth_mod, result)
    assert result.key_id == w.key.id
    assert result.user_id == w.agent.id
    assert result.workspace_id == w.ws.id


# --- AC-10, FR-9: срок действия ---------------------------------------------------------


async def test_007_ac10_one_second_before_expiry_is_valid(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    result = await authn(auth_mod, db, clock, w.key.secret, CLOCK + TTL - timedelta(seconds=1))
    assert is_principal(auth_mod, result)
    assert result.key_id == w.key.id


async def test_007_ac10_at_expiry_moment_is_refused(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    assert await authn(auth_mod, db, clock, w.key.secret, CLOCK + TTL) is None
    assert await authn(auth_mod, db, clock, w.key.secret, CLOCK + TTL + timedelta(days=1)) is None


async def test_007_ac10_expired_key_refusal_has_no_side_effects(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    for _ in range(3):
        assert await authn(auth_mod, db, clock, w.key.secret, CLOCK + TTL) is None
    row = await key_row(db, w.key.id)
    assert row.rate_count == 0
    assert row.rate_window_start is None
    assert row.last_used_at is None


# --- FR-13 (домен): единый отказ -------------------------------------------------------


async def test_007_fr13_unknown_digest_is_refused(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    await world(db)
    assert await authn(auth_mod, db, clock, fresh_secret(), CLOCK) is None


async def test_007_fr13_revoked_key_is_refused_without_side_effects(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    revoked = await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        created_at=CLOCK,
        expires_at=CLOCK + TTL,
        revoked_at=CLOCK + timedelta(minutes=1),
        revoked_by=w.ta,
        name="отозванный",
    )
    await db.commit()
    assert await authn(auth_mod, db, clock, revoked.secret, CLOCK + timedelta(minutes=2)) is None
    row = await key_row(db, revoked.id)
    assert row.rate_count == 0
    assert row.last_used_at is None


async def test_007_fr13_one_digit_changed_is_refused(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    original = w.key.secret
    last = original[-1]
    changed = original[:-1] + ("A" if last != "A" else "B")
    assert await authn(auth_mod, db, clock, changed, CLOCK) is None


async def test_007_fr13_same_refusal_value_for_every_reason(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    """Неизвестный, отозванный, истёкший — один и тот же ответ ``None`` (нет оракула по типу)."""
    w = await world(db)
    revoked = await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        created_at=CLOCK,
        expires_at=CLOCK + TTL,
        revoked_at=CLOCK,
        revoked_by=w.ta,
        name="r",
    )
    expired = await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        created_at=CLOCK - TTL,
        expires_at=CLOCK,
        name="e",
    )
    await db.commit()
    results = [
        await authn(auth_mod, db, clock, fresh_secret(), CLOCK),
        await authn(auth_mod, db, clock, revoked.secret, CLOCK),
        await authn(auth_mod, db, clock, expired.secret, CLOCK),
    ]
    assert results == [None, None, None]


async def test_007_fr13_single_update_returning_for_every_outcome(
    auth_mod: Any, db: AsyncSession, clock: FixedClock, sql_log: list[str]
) -> None:
    """PD-5: один ``UPDATE api_key … RETURNING`` на вызов — одинаковый путь для действующего,
    неизвестного, отозванного, истёкшего ключа и для отказа по лимиту (нет раннего выхода,
    по числу/виду запросов нельзя различить причину)."""
    w = await world(db)
    revoked = await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        created_at=CLOCK,
        expires_at=CLOCK + TTL,
        revoked_at=CLOCK,
        revoked_by=w.ta,
        name="r",
    )
    expired = await make_api_key(
        db, user=w.agent, created_by=w.ta, created_at=CLOCK - TTL, expires_at=CLOCK, name="e"
    )
    await db.execute(
        text("UPDATE api_key SET rate_count = 121, rate_window_start = :t WHERE id = :id"),
        {"t": CLOCK, "id": w.key_ba.id},
    )
    await db.commit()

    cases = {
        "valid": w.key.secret,
        "unknown": fresh_secret(),
        "revoked": revoked.secret,
        "expired": expired.secret,
        "limited": w.key_ba.secret,
    }
    shapes: dict[str, list[str]] = {}
    for name, secret in cases.items():
        sql_log.clear()
        await authn(auth_mod, db, clock, secret, CLOCK)
        shapes[name] = list(sql_log)
    for name, statements in shapes.items():
        assert len(statements) == 1, f"{name}: ожидался один оператор, было {len(statements)}"
        stmt = statements[0].upper()
        assert stmt.startswith("UPDATE API_KEY"), f"{name}: не UPDATE api_key"
        assert "RETURNING" in stmt, f"{name}: нет RETURNING"
    assert len({tuple(s) for s in shapes.values()}) == 1, "текст оператора зависит от исхода"


async def test_007_fr13_no_commit_inside_service(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    """Сервис не фиксирует транзакцию (фиксирует вызывающий — ``commit_durably``)."""
    w = await world(db)
    assert is_principal(auth_mod, await authn(auth_mod, db, clock, w.key.secret, CLOCK))
    await db.rollback()
    row = await key_row(db, w.key.id)
    assert row.last_used_at is None
    assert row.rate_count == 0


async def test_007_fr13_login_lock_state_does_not_affect_key(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    """Заметка ревью R7-T07: перебором паролей ключ не блокируется."""
    w = await world(db)
    await db.execute(
        text(
            "UPDATE app_user SET failed_login_count = 4, login_locked_until = :until WHERE id = :id"
        ),
        {"until": CLOCK + timedelta(minutes=15), "id": w.agent.id},
    )
    await db.commit()
    result = await authn(auth_mod, db, clock, w.key.secret, CLOCK)
    assert is_principal(auth_mod, result)
    assert result.user_id == w.agent.id


async def test_007_ac4_block_owner_refuses_key_even_after_unblock(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    """Блокировка владельца (FR-4, PD-7) делает ключ недействительным; разблокировка его не
    возвращает."""
    from app.domain.auth.sessions import SessionStore
    from app.domain.users import service as accounts

    w = await world(db)
    store = SessionStore(SECRET_KEY, idle_timeout=timedelta(hours=8), absolute_timeout=TTL)
    assert is_principal(auth_mod, await authn(auth_mod, db, clock, w.key.secret, CLOCK))
    await db.commit()
    await accounts.block_user(db, actor_of(w.ta), store, w.agent.id)
    await db.commit()
    at = CLOCK + timedelta(minutes=1)
    assert await authn(auth_mod, db, clock, w.key.secret, at) is None
    await accounts.unblock_user(db, actor_of(w.ta), w.agent.id)
    await db.commit()
    assert await authn(auth_mod, db, clock, w.key.secret, at) is None


# --- AC-40, FR-33: лимит частоты ------------------------------------------------------


async def test_007_ac40_120_calls_pass_121st_limited_with_retry_after_60(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    results = await call_n(auth_mod, db, clock, w.key.secret, CLOCK, LIMIT)
    principals = [is_principal(auth_mod, r) for r in results]
    assert all(principals), f"в пределах лимита отказов: {principals.count(False)}"
    over = await authn(auth_mod, db, clock, w.key.secret, CLOCK)
    assert is_limited(auth_mod, over)
    assert over.retry_after == 60
    assert isinstance(over.retry_after, int)
    row = await key_row(db, w.key.id)
    assert row.rate_count == 121
    assert row.rate_window_start == CLOCK


async def test_007_ac40_retry_after_counts_down_and_is_at_least_one(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    await call_n(auth_mod, db, clock, w.key.secret, CLOCK, LIMIT)
    cases = [
        (timedelta(seconds=30), 30),
        (timedelta(milliseconds=400), 60),  # ceil(59.6)
        (timedelta(seconds=59, milliseconds=500), 1),  # ceil(0.5)
        (timedelta(seconds=59, microseconds=999_999), 1),
    ]
    for delta, expected in cases:
        result = await authn(auth_mod, db, clock, w.key.secret, CLOCK + delta)
        assert is_limited(auth_mod, result), f"+{delta}: не RateLimited"
        assert result.retry_after == expected, f"+{delta}: {result.retry_after} != {expected}"


async def test_007_ac40_new_window_after_60s_resets_counter(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    await call_n(auth_mod, db, clock, w.key.secret, CLOCK, LIMIT + 1)
    later = CLOCK + timedelta(seconds=60)
    result = await authn(auth_mod, db, clock, w.key.secret, later)
    assert is_principal(auth_mod, result)
    row = await key_row(db, w.key.id)
    assert row.rate_count == 1
    assert row.rate_window_start == later


async def test_007_ac40_window_is_fixed_not_sliding(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    """Окно отсчитывается от первого запроса окна: вызовы внутри окна его не сдвигают."""
    w = await world(db)
    s = w.key.secret
    await authn(auth_mod, db, clock, s, CLOCK)
    await authn(auth_mod, db, clock, s, CLOCK + timedelta(seconds=30))
    await authn(auth_mod, db, clock, s, CLOCK + timedelta(seconds=59))
    row = await key_row(db, w.key.id)
    assert row.rate_count == 3
    assert row.rate_window_start == CLOCK
    await authn(auth_mod, db, clock, s, CLOCK + timedelta(seconds=60))
    row = await key_row(db, w.key.id)
    assert row.rate_count == 1
    assert row.rate_window_start == CLOCK + timedelta(seconds=60)


async def test_007_ac40_limit_is_per_key_not_per_agent(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    await call_n(auth_mod, db, clock, w.key.secret, CLOCK, LIMIT + 1)
    second = await authn(auth_mod, db, clock, w.key2.secret, CLOCK)  # тот же агент, другой ключ
    other = await authn(auth_mod, db, clock, w.key_ba.secret, CLOCK)
    assert is_principal(auth_mod, second)
    assert second.key_id == w.key2.id
    assert is_principal(auth_mod, other)
    assert (await key_row(db, w.key2.id)).rate_count == 1
    assert (await key_row(db, w.key_ba.id)).rate_count == 1
    assert (await key_row(db, w.key.id)).rate_count == 121


async def test_007_ac40_rate_limited_state_is_written_in_transaction(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    """После отказа по лимиту счётчик записан в транзакцию вызывающего (её фиксирует
    ``commit_durably`` в R7-T12): после фиксации отказ сохраняется."""
    w = await world(db)
    await call_n(auth_mod, db, clock, w.key.secret, CLOCK, LIMIT + 1)
    await db.commit()
    row = await key_row(db, w.key.id)
    assert row.rate_count == 121
    again = await authn(auth_mod, db, clock, w.key.secret, CLOCK + timedelta(seconds=10))
    assert is_limited(auth_mod, again)
    assert again.retry_after == 50


async def test_007_fr33_stream_of_10000_calls_never_exceeds_121(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    principals = 0
    for _ in range(10_000):
        if is_principal(auth_mod, await authn(auth_mod, db, clock, w.key.secret, CLOCK)):
            principals += 1
    assert principals == LIMIT
    row = await key_row(db, w.key.id)
    assert row.rate_count == 121


@pytest.mark.committed
async def test_007_fr33_concurrent_sessions_do_not_bypass_limit(
    auth_mod: Any, committed: async_sessionmaker[AsyncSession], clock: FixedClock
) -> None:
    """Параллельные запросы (отдельные соединения) не обходят лимит: счётчик атомарен."""
    async with committed() as setup:
        w = await world(setup)
        await setup.execute(
            text("UPDATE api_key SET rate_count = 115, rate_window_start = :t WHERE id = :id"),
            {"t": CLOCK, "id": w.key.id},
        )
        await setup.commit()

    gate = asyncio.Event()

    async def one() -> Any:
        async with committed() as session:
            await session.execute(text("SELECT 1"))  # соединение открыто до старта
            await gate.wait()
            result = await auth_mod.authenticate_api_key(
                session, digest_of(w.key.secret), now=CLOCK
            )
            await session.commit()
            return result

    tasks = [asyncio.create_task(one()) for _ in range(12)]
    await asyncio.sleep(0.2)
    gate.set()
    results = await asyncio.gather(*tasks)

    ok = sum(1 for r in results if is_principal(auth_mod, r))
    limited = sum(1 for r in results if is_limited(auth_mod, r))
    assert (ok, limited) == (5, 7)
    async with committed() as check:
        row = await key_row(check, w.key.id)
    assert row.rate_count == 121


# --- FR-16: последнее использование ---------------------------------------------------


async def test_007_fr16_last_used_at_is_last_call_within_limit(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    s = w.key.secret
    await authn(auth_mod, db, clock, s, CLOCK)
    assert (await key_row(db, w.key.id)).last_used_at == CLOCK
    last_ok = CLOCK + timedelta(seconds=20)
    await call_n(auth_mod, db, clock, s, CLOCK + timedelta(seconds=10), LIMIT - 2)
    await authn(auth_mod, db, clock, s, last_ok)  # 120-й
    assert (await key_row(db, w.key.id)).last_used_at == last_ok
    over = await authn(auth_mod, db, clock, s, CLOCK + timedelta(seconds=40))  # 121-й
    assert is_limited(auth_mod, over)
    assert (await key_row(db, w.key.id)).last_used_at == last_ok


async def test_007_fr16_other_key_last_used_untouched(
    auth_mod: Any, db: AsyncSession, clock: FixedClock
) -> None:
    w = await world(db)
    await authn(auth_mod, db, clock, w.key.secret, CLOCK)
    assert (await key_row(db, w.key2.id)).last_used_at is None


# --- FR-32: секрет и дайджест не попадают в логи ----------------------------------------


async def test_007_fr32_no_secret_or_digest_in_logs_or_repr(
    auth_mod: Any, db: AsyncSession, clock: FixedClock, caplog: pytest.LogCaptureFixture
) -> None:
    w = await world(db)
    revoked = await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        created_at=CLOCK,
        expires_at=CLOCK + TTL,
        revoked_at=CLOCK,
        revoked_by=w.ta,
        name="r",
    )
    await db.commit()
    secrets_ = [w.key.secret, revoked.secret, fresh_secret()]
    caplog.set_level(logging.DEBUG)
    reprs: list[str] = []
    for s in secrets_:
        reprs.append(repr(await authn(auth_mod, db, clock, s, CLOCK)))
    reprs += [repr(r) for r in await call_n(auth_mod, db, clock, w.key.secret, CLOCK, LIMIT)]
    logged = caplog.text + "\n".join(str(r.__dict__) for r in caplog.records)
    blob = logged + "\n".join(reprs)
    leaked_secret = any(s in blob or s[4:12] in blob for s in secrets_)
    leaked_digest = any(digest_of(s).hex() in blob for s in secrets_)
    assert not leaked_secret, "секрет в логе или repr"
    assert not leaked_digest, "дайджест в логе или repr"


# --- PD-9: Actor несёт идентификатор ключа -------------------------------------------


def test_007_pd9_actor_carries_api_key_id_and_optional_session() -> None:
    key_id = uuid.uuid4()
    by_key = Actor(
        user_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        login="agent.u",
        role=Role.USER,
        must_change_password=False,
        session_id=None,
        api_key_id=key_id,
        is_agent=True,
    )
    assert by_key.api_key_id == key_id
    assert by_key.session_id is None
    by_cookie = Actor(
        user_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        login="ba1",
        role=Role.BUSINESS_ADMIN,
        must_change_password=False,
        session_id=b"\x02" * 32,
    )
    assert by_cookie.api_key_id is None
    assert by_cookie.is_agent is False


# --- change_own_password без сессии (plan §4.7) -------------------------------------


async def _password_ctx(db: AsyncSession) -> Any:
    user = await make_user(db, password=PASSWORD, role="user", login="agent.pw", is_agent=True)
    await db.commit()
    return user


async def _user_state(db: AsyncSession, user_id: uuid.UUID) -> Any:
    return (
        await db.execute(
            text(
                "SELECT password_hash, failed_login_count, login_locked_until "
                "FROM app_user WHERE id = :id"
            ),
            {"id": user_id},
        )
    ).one()


@pytest.mark.parametrize("current", [PASSWORD, "definitely-wrong-password"])
async def test_007_fr15_change_own_password_without_session_is_forbidden(
    db: AsyncSession, clock: FixedClock, settings: Settings, current: str
) -> None:
    from app.core.errors import Forbidden
    from app.core.security.passwords import PasswordHasher
    from app.domain.auth import service
    from app.domain.auth.sessions import SessionStore

    user = await _password_ctx(db)
    before = await _user_state(db, user.id)
    actor = SimpleNamespace(user_id=user.id, login=user.login, session_id=None)
    store = SessionStore(SECRET_KEY, idle_timeout=timedelta(hours=8), absolute_timeout=TTL)
    with pytest.raises(Forbidden) as info:
        await service.change_own_password(
            db,
            actor,
            PasswordHasher(**CHEAP),
            store,
            settings,
            current=SecretStr(current),
            new=SecretStr(NEW_PASSWORD),
            now=CLOCK,
        )
    assert info.value.status_code == 403
    assert str(info.value.code) == "forbidden"
    await db.rollback()
    after = await _user_state(db, user.id)
    assert after.password_hash == before.password_hash
    assert after.failed_login_count == before.failed_login_count
    assert after.login_locked_until == before.login_locked_until
