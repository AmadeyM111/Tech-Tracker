"""R7-T07: лимиты частоты запросов сброса (spec 007: FR-9, AC-10; plan §4.3, PR-7, Q-7).

Публичный интерфейс: ``app.domain.auth.reset_limits`` (``limit_key_hash``, ``register_request``,
``EMAIL_LIMIT``, ``IP_LIMIT``, ``LIMIT_WINDOW``). Время — ``fixed_clock``.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.clock import FixedClock

KEY = b"k" * 32
USERS_LOCK_NS = 0x75736572  # users/service.py


@pytest.fixture
def rl() -> Any:
    return importlib.import_module("app.domain.auth.reset_limits")


async def ask(
    rl: Any,
    db: AsyncSession,
    clock: FixedClock,
    email: str = "a@x.ru",
    ip: str | None = "10.0.0.1",
    key: bytes = KEY,
) -> bool:
    return bool(await rl.register_request(db, key, email=email, ip=ip, now=clock.now()))


async def rows(db: AsyncSession) -> list[tuple[str, bytes]]:
    res = await db.execute(text("SELECT scope, key_hash FROM password_reset_attempt"))
    return [(r[0], bytes(r[1])) for r in res.all()]


async def count(db: AsyncSession) -> int:
    return len(await rows(db))


def test_007_constants(rl: Any) -> None:
    assert rl.EMAIL_LIMIT == 3
    assert rl.IP_LIMIT == 10
    assert rl.LIMIT_WINDOW.total_seconds() == 3600


def test_007_limit_key_hash_is_hmac_sha256(rl: Any) -> None:
    got = rl.limit_key_hash(KEY, "email", "a@x.ru")
    assert got == hmac.new(KEY, b"email:a@x.ru", hashlib.sha256).digest()
    assert len(got) == 32
    assert got != rl.limit_key_hash(KEY, "ip", "a@x.ru")
    assert got != rl.limit_key_hash(b"z" * 32, "email", "a@x.ru")


async def test_007_ac10_fourth_request_same_email_denied(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(3):
        assert await ask(rl, db, fixed_clock) is True
    assert await ask(rl, db, fixed_clock) is False


async def test_007_ac10_allowed_again_after_61_minutes(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(3):
        assert await ask(rl, db, fixed_clock) is True
    assert await ask(rl, db, fixed_clock) is False
    fixed_clock.advance(timedelta(minutes=61))
    assert await ask(rl, db, fixed_clock) is True


async def test_007_window_not_yet_elapsed_at_59_minutes(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(3):
        assert await ask(rl, db, fixed_clock) is True
    fixed_clock.advance(timedelta(minutes=59))
    assert await ask(rl, db, fixed_clock) is False


async def test_007_old_rows_are_purged(rl: Any, db: AsyncSession, fixed_clock: FixedClock) -> None:
    for _ in range(3):
        await ask(rl, db, fixed_clock)
    assert await count(db) == 6
    fixed_clock.advance(timedelta(minutes=61))
    await ask(rl, db, fixed_clock, email="b@x.ru", ip="10.0.0.2")
    assert await count(db) == 2


async def test_007_ac10_other_email_not_affected(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(3):
        await ask(rl, db, fixed_clock)
    assert await ask(rl, db, fixed_clock) is False
    assert await ask(rl, db, fixed_clock, email="b@x.ru") is True


async def test_007_email_normalized_strip_and_lower(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    variants = ["a@x.ru", " A@X.ru", "a@x.RU  "]
    for v in variants:
        assert await ask(rl, db, fixed_clock, email=v) is True
    assert await ask(rl, db, fixed_clock, email="A@x.ru") is False
    assert await ask(rl, db, fixed_clock, email=" a@x.ru ") is False


async def test_007_ac10_ip_limit_11th_denied(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for i in range(10):
        assert await ask(rl, db, fixed_clock, email=f"u{i}@x.ru", ip="10.0.0.1") is True
    assert await ask(rl, db, fixed_clock, email="u10@x.ru", ip="10.0.0.1") is False


async def test_007_ac10_other_ip_not_affected(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for i in range(10):
        await ask(rl, db, fixed_clock, email=f"u{i}@x.ru", ip="10.0.0.1")
    assert await ask(rl, db, fixed_clock, email="n@x.ru", ip="10.0.0.1") is False
    assert await ask(rl, db, fixed_clock, email="n@x.ru", ip="10.0.0.2") is True


async def test_007_ip_window_resets_after_61_minutes(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for i in range(10):
        await ask(rl, db, fixed_clock, email=f"u{i}@x.ru")
    fixed_clock.advance(timedelta(minutes=61))
    assert await ask(rl, db, fixed_clock, email="u0@x.ru") is True


async def test_007_ip_none_only_email_limit(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for i in range(12):
        assert await ask(rl, db, fixed_clock, email=f"u{i}@x.ru", ip=None) is True
    assert {s for s, _ in await rows(db)} == {"email"}
    for _ in range(3):
        assert await ask(rl, db, fixed_clock, email="a@x.ru", ip=None) is True
    assert await ask(rl, db, fixed_clock, email="a@x.ru", ip=None) is False


async def test_007_ac10_denied_rows_not_written(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(3):
        await ask(rl, db, fixed_clock)
    assert await count(db) == 6
    for _ in range(5):
        assert await ask(rl, db, fixed_clock) is False
    assert await count(db) == 6


async def test_007_denied_by_email_does_not_count_for_ip(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(3):
        await ask(rl, db, fixed_clock, email="a@x.ru", ip="10.0.0.1")
    for _ in range(20):
        assert await ask(rl, db, fixed_clock, email="a@x.ru", ip="10.0.0.1") is False
    # IP has 3 accepted so far: 7 more distinct emails fit, the 8th does not.
    for i in range(7):
        assert await ask(rl, db, fixed_clock, email=f"u{i}@x.ru", ip="10.0.0.1") is True
    assert await ask(rl, db, fixed_clock, email="u7@x.ru", ip="10.0.0.1") is False


async def test_007_denied_by_ip_does_not_count_for_email(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for i in range(10):
        await ask(rl, db, fixed_clock, email=f"u{i}@x.ru", ip="10.0.0.1")
    for _ in range(5):
        assert await ask(rl, db, fixed_clock, email="t@x.ru", ip="10.0.0.1") is False
    # Email t@x.ru has no accepted requests: from another IP it gets all 3.
    for _ in range(3):
        assert await ask(rl, db, fixed_clock, email="t@x.ru", ip="10.0.0.2") is True
    assert await ask(rl, db, fixed_clock, email="t@x.ru", ip="10.0.0.2") is False


async def test_007_denied_does_not_extend_window(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(3):
        await ask(rl, db, fixed_clock)
    fixed_clock.advance(timedelta(minutes=40))
    assert await ask(rl, db, fixed_clock) is False
    fixed_clock.advance(timedelta(minutes=21))  # 61 min after the accepted ones
    assert await ask(rl, db, fixed_clock) is True


async def test_007_attempt_rows_scope_and_hash_only(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    assert await ask(rl, db, fixed_clock, email=" A@x.ru ", ip="203.0.113.7") is True
    got = await rows(db)
    assert sorted(got) == sorted(
        [
            ("email", rl.limit_key_hash(KEY, "email", "a@x.ru")),
            ("ip", rl.limit_key_hash(KEY, "ip", "203.0.113.7")),
        ]
    )
    for _, h in got:
        assert len(h) == 32
        assert b"a@x.ru" not in h
        assert b"203.0.113.7" not in h
    res = await db.execute(
        text("SELECT count(*) FROM password_reset_attempt WHERE created_at = :t"),
        {"t": fixed_clock.now()},
    )
    assert res.scalar_one() == 2


async def test_007_no_plaintext_in_any_column(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await ask(rl, db, fixed_clock, email="secret.person@x.ru", ip="198.51.100.9")
    res = await db.execute(text("SELECT t::text FROM password_reset_attempt t"))
    dump = "\n".join(r[0] for r in res.all())
    assert "secret.person" not in dump
    assert "198.51.100.9" not in dump


async def test_007_different_secret_keys_do_not_share_counters(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(3):
        await ask(rl, db, fixed_clock)
    assert await ask(rl, db, fixed_clock, key=b"z" * 32) is True


async def test_007_advisory_locks_use_own_two_key_namespace(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await ask(rl, db, fixed_clock)
    res = await db.execute(
        text(
            "SELECT classid::bigint, objid::bigint FROM pg_locks "
            "WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND objsubid = 2"
        )
    )
    locks = res.all()
    assert len(locks) == 2  # email and ip
    assert {int(r[0]) for r in locks} != {USERS_LOCK_NS}
    assert all(int(r[0]) != USERS_LOCK_NS for r in locks)
    assert len({(r[0], r[1]) for r in locks}) == 2


async def test_007_ip_none_takes_single_lock(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await ask(rl, db, fixed_clock, ip=None)
    res = await db.execute(
        text(
            "SELECT count(*) FROM pg_locks "
            "WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND objsubid = 2"
        )
    )
    assert res.scalar_one() == 1


async def test_007_pr21_email_none_checks_and_writes_only_ip(
    rl: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(10):
        assert await rl.register_request(db, KEY, email=None, ip="10.0.0.1", now=fixed_clock.now())
    assert [scope for scope, _ in await rows(db)] == ["ip"] * 10
    assert not await rl.register_request(db, KEY, email=None, ip="10.0.0.1", now=fixed_clock.now())
    assert await count(db) == 10
