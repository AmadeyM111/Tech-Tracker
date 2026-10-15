"""Часы приложения (plan §4.2, FR-46, BR-12).

Все моменты времени — aware UTC. Текущие часы лежат в ``ContextVar``: по умолчанию
``SystemClock``; тесты и middleware подменяют их через ``use_clock``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from typing import Final, Protocol
from zoneinfo import ZoneInfo

MOSCOW_TZ: Final = ZoneInfo("Europe/Moscow")


def _to_utc(at: datetime) -> datetime:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("naive datetime не допускается: нужен aware datetime")
    return at.astimezone(UTC)


class Clock(Protocol):
    def now(self) -> datetime:
        """Текущий момент: aware, UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, at: datetime) -> None:
        self._at = _to_utc(at)

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = _to_utc(at)

    def advance(self, delta: timedelta) -> None:
        self._at = self._at + delta


_DEFAULT_CLOCK: Final[Clock] = SystemClock()  # без состояния, разделяется безопасно
_current_clock: ContextVar[Clock] = ContextVar("current_clock", default=_DEFAULT_CLOCK)


def utcnow() -> datetime:
    return _current_clock.get().now()


@contextmanager
def use_clock(clock: Clock) -> Iterator[None]:
    token = _current_clock.set(clock)
    try:
        yield
    finally:
        _current_clock.reset(token)


def today_msk(now: datetime | None = None) -> date:
    """Календарная дата в Europe/Moscow для момента ``now`` (по умолчанию ``utcnow()``)."""
    moment = utcnow() if now is None else _to_utc(now)
    return moment.astimezone(MOSCOW_TZ).date()
