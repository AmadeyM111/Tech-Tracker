"""Состояние резервных копий для ТА и ``gtrack bootstrap`` (spec 009 FR-6, FR-9; plan PB-6, PB-10).

Только чтение ``backup_run``. «Устарела» (``stale``): успешных копий нет, последняя успешная
старше порога или последний запуск неудачен. Таблицы может не быть (схема до ``0011``) —
тогда данных о копиях нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy import select, text

from app.domain.ops.models import BackupRun, BackupRunStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

BOOTSTRAP_MAX_AGE: Final = timedelta(hours=24)


@dataclass(frozen=True)
class BackupStatus:
    last_success_at: datetime | None
    last_success_size_bytes: int | None
    last_run_at: datetime | None
    last_run_status: BackupRunStatus | None
    stale: bool
    stale_after_hours: int


async def _table_exists(session: AsyncSession) -> bool:
    found = (await session.execute(text("SELECT to_regclass('public.backup_run')"))).scalar()
    return found is not None


async def backup_status(session: AsyncSession, *, now: datetime, stale_hours: int) -> BackupStatus:
    """Последний запуск и последняя успешная копия; ``stale`` по правилу PB-6."""
    last = (
        await session.execute(select(BackupRun).order_by(BackupRun.finished_at.desc()).limit(1))
    ).scalar_one_or_none()
    ok = (
        await session.execute(
            select(BackupRun)
            .where(BackupRun.status == BackupRunStatus.OK)
            .order_by(BackupRun.finished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    stale = (
        ok is None
        or now - ok.finished_at > timedelta(hours=stale_hours)
        or (last is not None and last.status == BackupRunStatus.FAILED)
    )
    return BackupStatus(
        last_success_at=None if ok is None else ok.finished_at,
        last_success_size_bytes=None if ok is None else ok.size_bytes,
        last_run_at=None if last is None else last.finished_at,
        last_run_status=None if last is None else BackupRunStatus(last.status),
        stale=stale,
        stale_after_hours=stale_hours,
    )


async def last_success_at(session: AsyncSession) -> datetime | None:
    """Время последней успешной копии; ``None`` — нет копий или таблицы (схема до 0011)."""
    if not await _table_exists(session):
        return None
    return (
        await session.execute(
            select(BackupRun.finished_at)
            .where(BackupRun.status == BackupRunStatus.OK)
            .order_by(BackupRun.finished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def bootstrap_warning(
    *, current: str | None, head: str, last_ok: datetime | None, now: datetime
) -> str | None:
    """Текст предупреждения перед миграцией (FR-9) или ``None``.

    Чистая установка (``current is None``) и схема без неприменённых миграций — без предупреждения.
    """
    if current is None or current == head:
        return None
    if last_ok is None:
        return (
            "ВНИМАНИЕ: перед миграцией нет данных об успешной резервной копии. "
            "Снимите копию: gtrack backup"
        )
    if now - last_ok > BOOTSTRAP_MAX_AGE:
        return (
            "ВНИМАНИЕ: последняя резервная копия старше 24 часов "
            f"({last_ok.strftime('%Y-%m-%d %H:%M')} UTC). Снимите копию: gtrack backup"
        )
    return None
