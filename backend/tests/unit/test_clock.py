"""Юнит-тесты app.core.clock (plan §4.2, T03; AC-68, NFR-5, FR-46, BR-12)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

T0 = datetime(2026, 10, 13, 21, 30, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> Any:
    from app.core import clock as module

    return module


# ---- MOSCOW_TZ (BR-12, NFR-5) ----


def test_br12_moscow_tz_is_europe_moscow(clock: Any) -> None:
    assert ZoneInfo("Europe/Moscow") == clock.MOSCOW_TZ
    assert clock.MOSCOW_TZ.key == "Europe/Moscow"


# ---- SystemClock (FR-46) ----


def test_fr46_system_clock_returns_aware_utc(clock: Any) -> None:
    before = datetime.now(UTC)
    value = clock.SystemClock().now()
    after = datetime.now(UTC)
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)
    assert before - timedelta(seconds=1) <= value <= after + timedelta(seconds=1)


def test_fr46_default_utcnow_is_aware_utc(clock: Any) -> None:
    before = datetime.now(UTC)
    value = clock.utcnow()
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)
    assert abs(value - before) < timedelta(seconds=5)


# ---- FixedClock (FR-46) ----


def test_fr46_fixed_clock_returns_given_instant(clock: Any) -> None:
    fixed = clock.FixedClock(T0)
    assert fixed.now() == T0
    assert fixed.now() == T0  # время не идёт само
    assert fixed.now().utcoffset() == timedelta(0)


def test_fr46_fixed_clock_rejects_naive_datetime(clock: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        clock.FixedClock(datetime(2026, 10, 13, 21, 30))  # noqa: DTZ001


def test_fr46_fixed_clock_set_rejects_naive_datetime(clock: Any) -> None:
    fixed = clock.FixedClock(T0)
    with pytest.raises((ValueError, TypeError)):
        fixed.set(datetime(2026, 10, 14, 0, 0))  # noqa: DTZ001
    assert fixed.now() == T0  # состояние не испорчено


def test_fr46_fixed_clock_normalizes_to_utc(clock: Any) -> None:
    msk = timezone(timedelta(hours=3))
    fixed = clock.FixedClock(datetime(2026, 10, 14, 0, 30, tzinfo=msk))
    assert fixed.now() == T0
    assert fixed.now().utcoffset() == timedelta(0)


def test_fr46_fixed_clock_set_and_advance(clock: Any) -> None:
    fixed = clock.FixedClock(T0)
    later = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    fixed.set(later)
    assert fixed.now() == later
    fixed.advance(timedelta(hours=8, seconds=1))
    assert fixed.now() == later + timedelta(hours=8, seconds=1)
    fixed.advance(timedelta(minutes=-30))
    assert fixed.now() == later + timedelta(hours=7, minutes=30, seconds=1)


# ---- utcnow / use_clock ----


def test_nfr5_utcnow_uses_clock_from_use_clock(clock: Any) -> None:
    with clock.use_clock(clock.FixedClock(T0)):
        assert clock.utcnow() == T0


def test_nfr5_utcnow_follows_fixed_clock_changes(clock: Any) -> None:
    fixed = clock.FixedClock(T0)
    with clock.use_clock(fixed):
        fixed.advance(timedelta(minutes=5))
        assert clock.utcnow() == T0 + timedelta(minutes=5)


def test_nfr5_use_clock_restores_previous_clock(clock: Any) -> None:
    outer = clock.FixedClock(T0)
    inner = clock.FixedClock(datetime(2030, 1, 1, tzinfo=UTC))
    with clock.use_clock(outer):
        with clock.use_clock(inner):
            assert clock.utcnow() == datetime(2030, 1, 1, tzinfo=UTC)
        assert clock.utcnow() == T0


def test_nfr5_use_clock_restores_default_after_exit(clock: Any) -> None:
    with clock.use_clock(clock.FixedClock(datetime(2001, 1, 1, tzinfo=UTC))):
        pass
    assert abs(clock.utcnow() - datetime.now(UTC)) < timedelta(seconds=5)


def test_nfr5_use_clock_restores_clock_on_exception(clock: Any) -> None:
    class Boom(Exception):
        pass

    with clock.use_clock(clock.FixedClock(T0)):
        other = clock.FixedClock(datetime(2030, 1, 1, tzinfo=UTC))
        with pytest.raises(Boom), clock.use_clock(other):
            raise Boom
        assert clock.utcnow() == T0


async def test_nfr5_use_clock_is_isolated_between_tasks(clock: Any) -> None:
    t_a = datetime(2026, 1, 1, tzinfo=UTC)
    t_b = datetime(2027, 6, 1, tzinfo=UTC)
    both_set = asyncio.Event()
    ready = 0

    async def worker(at: datetime) -> tuple[datetime, datetime]:
        nonlocal ready
        with clock.use_clock(clock.FixedClock(at)):
            ready += 1
            if ready == 2:
                both_set.set()
            await both_set.wait()  # обе задачи внутри своих контекстов одновременно
            first = clock.utcnow()
            await asyncio.sleep(0)
            return first, clock.utcnow()

    res_a, res_b = await asyncio.gather(worker(t_a), worker(t_b))
    assert res_a == (t_a, t_a)
    assert res_b == (t_b, t_b)
    # родительский контекст не затронут
    assert abs(clock.utcnow() - datetime.now(UTC)) < timedelta(seconds=5)


async def test_nfr5_task_inherits_clock_set_before_creation(clock: Any) -> None:
    async def read() -> datetime:
        return clock.utcnow()

    with clock.use_clock(clock.FixedClock(T0)):
        assert await asyncio.create_task(read()) == T0


# ---- today_msk (AC-68, BR-12) ----


def test_ac68_today_msk_after_utc_evening_is_next_day(clock: Any) -> None:
    assert clock.today_msk(datetime(2026, 10, 13, 21, 30, tzinfo=UTC)) == date(2026, 10, 14)


def test_ac68_today_msk_one_second_before_msk_midnight(clock: Any) -> None:
    assert clock.today_msk(datetime(2026, 10, 13, 20, 59, 59, tzinfo=UTC)) == date(2026, 10, 13)


def test_ac68_today_msk_exactly_at_msk_midnight(clock: Any) -> None:
    assert clock.today_msk(datetime(2026, 10, 13, 21, 0, 0, tzinfo=UTC)) == date(2026, 10, 14)


def test_br12_today_msk_accepts_non_utc_aware_datetime(clock: Any) -> None:
    # 2026-10-14T02:00+05:00 == 2026-10-13T21:00Z == 2026-10-14T00:00 МСК
    yekt = timezone(timedelta(hours=5))
    assert clock.today_msk(datetime(2026, 10, 14, 2, 0, tzinfo=yekt)) == date(2026, 10, 14)
    # 2026-10-14T00:30+05:00 == 2026-10-13T19:30Z == 2026-10-13T22:30 МСК
    assert clock.today_msk(datetime(2026, 10, 14, 0, 30, tzinfo=yekt)) == date(2026, 10, 13)


def test_br12_today_msk_returns_plain_date(clock: Any) -> None:
    result = clock.today_msk(T0)
    assert type(result) is date


def test_ac68_today_msk_without_argument_uses_utcnow(clock: Any) -> None:
    with clock.use_clock(clock.FixedClock(T0)):
        assert clock.today_msk() == date(2026, 10, 14)
    with clock.use_clock(clock.FixedClock(datetime(2026, 10, 13, 20, 59, 59, tzinfo=UTC))):
        assert clock.today_msk() == date(2026, 10, 13)


def test_ac68_today_msk_tracks_fixed_clock_advance(clock: Any) -> None:
    fixed = clock.FixedClock(datetime(2026, 10, 13, 20, 59, 59, tzinfo=UTC))
    with clock.use_clock(fixed):
        assert clock.today_msk() == date(2026, 10, 13)
        fixed.advance(timedelta(seconds=1))
        assert clock.today_msk() == date(2026, 10, 14)
