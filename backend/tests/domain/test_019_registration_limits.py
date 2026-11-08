"""R8-T08: лимиты регистрации (spec 019: FR-10, AC-18, AC-38; plan §4.3, RG-4, RG-5, RG-6).

Публичный интерфейс: ``app.domain.auth.registration_limits`` (``limit_key_hash``,
``register_attempt``, ``REQUEST_IP_LIMIT``, ``CONFIRM_IP_LIMIT``, ``CONFIRM_TOKEN_LIMIT``,
``LIMIT_WINDOW``). Время — ``fixed_clock``.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

from app.domain.auth import registration_limits as rl

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.clock import FixedClock
    from app.domain.auth.registration_limits import Scope

KEY = b"k" * 32
REGI_LOCK_NS = 0x72656769  # registration_limits.py: ключ «regi»
IP = "203.0.113.10"
OTHER_IP = "203.0.113.11"
TOKEN = "token-plain-value-for-tests"
TOKEN_HEX = hashlib.sha256(TOKEN.encode()).hexdigest()  # RG-4: value = hex SHA-256 токена


async def attempt(
    db: AsyncSession,
    clock: FixedClock,
    checks: Sequence[tuple[Scope, str]],
    key: bytes = KEY,
) -> bool:
    return await rl.register_attempt(db, key, checks, now=clock.now())


async def ask_request(db: AsyncSession, clock: FixedClock, ip: str = IP) -> bool:
    return await attempt(db, clock, [("request_ip", ip)])


async def ask_confirm_ip(db: AsyncSession, clock: FixedClock, ip: str = IP) -> bool:
    return await attempt(db, clock, [("confirm_ip", ip)])


async def ask_confirm_token(
    db: AsyncSession, clock: FixedClock, token_hex: str = TOKEN_HEX
) -> bool:
    return await attempt(db, clock, [("confirm_token", token_hex)])


async def rows(db: AsyncSession) -> list[tuple[str, bytes]]:
    res = await db.execute(text("SELECT scope, key_hash FROM registration_attempt"))
    return [(r[0], bytes(r[1])) for r in res.all()]


async def count(db: AsyncSession) -> int:
    return len(await rows(db))


def test_019_constants() -> None:
    assert rl.REQUEST_IP_LIMIT == 10
    assert rl.CONFIRM_IP_LIMIT == 20
    assert rl.CONFIRM_TOKEN_LIMIT == 5
    assert rl.LIMIT_WINDOW.total_seconds() == 3600


def test_019_limit_key_hash_is_hmac_sha256_of_scope_and_value() -> None:
    got = rl.limit_key_hash(KEY, "request_ip", IP)
    assert got == hmac.new(KEY, f"request_ip:{IP}".encode(), hashlib.sha256).digest()
    assert len(got) == 32
    assert got != rl.limit_key_hash(KEY, "confirm_ip", IP)
    assert got != rl.limit_key_hash(b"z" * 32, "request_ip", IP)


async def test_019_ac18_tenth_request_ip_accepted_eleventh_denied(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(10):
        assert await ask_request(db, fixed_clock) is True
    assert await ask_request(db, fixed_clock) is False


async def test_019_ac38_twentieth_confirm_ip_accepted_twenty_first_denied(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(20):
        assert await ask_confirm_ip(db, fixed_clock) is True
    assert await ask_confirm_ip(db, fixed_clock) is False


async def test_019_ac38_fifth_confirm_token_accepted_sixth_denied(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(5):
        assert await ask_confirm_token(db, fixed_clock) is True
    assert await ask_confirm_token(db, fixed_clock) is False


async def test_019_denied_attempt_is_not_written(db: AsyncSession, fixed_clock: FixedClock) -> None:
    for _ in range(10):
        assert await ask_request(db, fixed_clock) is True
    assert await count(db) == 10
    for _ in range(5):
        assert await ask_request(db, fixed_clock) is False
    assert await count(db) == 10


async def test_019_denied_multi_scope_attempt_writes_no_scope(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(5):
        assert await ask_confirm_token(db, fixed_clock) is True
    before = await count(db)
    # confirm_ip свободна, но confirm_token исчерпана: ни одна область не должна получить строку.
    assert (
        await attempt(db, fixed_clock, [("confirm_ip", IP), ("confirm_token", TOKEN_HEX)]) is False
    )
    assert await count(db) == before
    assert {s for s, _ in await rows(db)} == {"confirm_token"}


async def test_019_window_not_yet_elapsed_at_59_minutes(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(10):
        await ask_request(db, fixed_clock)
    fixed_clock.advance(timedelta(minutes=59))
    assert await ask_request(db, fixed_clock) is False


async def test_019_allowed_again_after_61_minutes(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(10):
        assert await ask_request(db, fixed_clock) is True
    assert await ask_request(db, fixed_clock) is False
    fixed_clock.advance(timedelta(minutes=61))
    assert await ask_request(db, fixed_clock) is True


async def test_019_old_rows_are_purged(db: AsyncSession, fixed_clock: FixedClock) -> None:
    for _ in range(10):
        await ask_request(db, fixed_clock)
    assert await count(db) == 10
    fixed_clock.advance(timedelta(minutes=61))
    assert await ask_request(db, fixed_clock, ip=OTHER_IP) is True
    assert await count(db) == 1


async def test_019_denied_attempts_do_not_extend_window(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(10):
        await ask_request(db, fixed_clock)
    fixed_clock.advance(timedelta(minutes=40))
    assert await ask_request(db, fixed_clock) is False
    fixed_clock.advance(timedelta(minutes=21))  # 61 минута после принятых
    assert await ask_request(db, fixed_clock) is True


async def test_019_other_ip_is_not_affected(db: AsyncSession, fixed_clock: FixedClock) -> None:
    for _ in range(10):
        await ask_request(db, fixed_clock)
    assert await ask_request(db, fixed_clock) is False
    for _ in range(10):
        assert await ask_request(db, fixed_clock, ip=OTHER_IP) is True


async def test_019_other_token_is_not_affected(db: AsyncSession, fixed_clock: FixedClock) -> None:
    other_hex = hashlib.sha256(b"another-token").hexdigest()
    for _ in range(5):
        await ask_confirm_token(db, fixed_clock)
    assert await ask_confirm_token(db, fixed_clock) is False
    for _ in range(5):
        assert await ask_confirm_token(db, fixed_clock, token_hex=other_hex) is True


async def test_019_scopes_do_not_share_counters(db: AsyncSession, fixed_clock: FixedClock) -> None:
    for _ in range(10):
        await ask_request(db, fixed_clock)
    assert await ask_request(db, fixed_clock) is False
    # Тот же IP в области confirm_ip имеет собственный счётчик.
    assert await ask_confirm_ip(db, fixed_clock) is True


async def test_019_other_secret_key_has_own_counters(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(10):
        await attempt(db, fixed_clock, [("request_ip", IP)])
    assert await attempt(db, fixed_clock, [("request_ip", IP)]) is False
    assert await attempt(db, fixed_clock, [("request_ip", IP)], key=b"z" * 32) is True


async def test_019_key_hash_is_32_bytes_and_not_plaintext(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    assert await attempt(db, fixed_clock, [("request_ip", IP), ("confirm_token", TOKEN_HEX)])
    got = await rows(db)
    assert sorted(got) == sorted(
        [
            ("request_ip", rl.limit_key_hash(KEY, "request_ip", IP)),
            ("confirm_token", rl.limit_key_hash(KEY, "confirm_token", TOKEN_HEX)),
        ]
    )
    for _, key_hash in got:
        assert len(key_hash) == 32
        assert key_hash != IP.encode()
        assert key_hash != TOKEN_HEX.encode()
        assert IP.encode() not in key_hash
        assert TOKEN_HEX.encode() not in key_hash


async def test_019_no_plaintext_ip_or_token_in_any_column(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await attempt(db, fixed_clock, [("request_ip", "198.51.100.9"), ("confirm_token", TOKEN_HEX)])
    res = await db.execute(text("SELECT t::text FROM registration_attempt t"))
    dump = "\n".join(r[0] for r in res.all())
    assert "198.51.100.9" not in dump
    assert TOKEN_HEX not in dump
    assert TOKEN not in dump


async def test_019_empty_checks_accepted_and_nothing_written(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    assert await attempt(db, fixed_clock, []) is True
    assert await count(db) == 0


async def test_019_advisory_locks_use_own_namespace(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await attempt(db, fixed_clock, [("request_ip", IP), ("confirm_ip", IP)])
    res = await db.execute(
        text(
            "SELECT classid::bigint FROM pg_locks "
            "WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND objsubid = 2"
        )
    )
    classes = [int(r[0]) for r in res.all()]
    assert len(classes) == 2  # по одной блокировке на область
    assert classes == [REGI_LOCK_NS, REGI_LOCK_NS]
