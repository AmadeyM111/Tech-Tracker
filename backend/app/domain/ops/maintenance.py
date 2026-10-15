"""Регулярное обслуживание (plan §4.13, §10.4; D-42, FR-25b).

``run_maintenance`` собирает отчёт о выполненных (или, при ``dry_run``, только подсчитанных)
действиях. В T31 заполняется только ``sessions_expired``; счётчики корзины и файлов (T54)
пока равны 0. События в журнал не пишутся.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.system.maintenance import purge_expired_sessions

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.clock import Clock
    from app.core.config import Settings


@dataclass(frozen=True)
class MaintenanceReport:
    """Итог обслуживания; порядок полей совпадает с порядком строк в stdout команды."""

    dry_run: bool = False
    sessions_expired: int = 0
    projects_purged: int = 0
    tasks_purged: int = 0
    comments_purged: int = 0
    attachments_purged: int = 0
    files_removed: int = 0
    orphan_files_removed: int = 0


async def run_maintenance(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    clock: Clock,
    dry_run: bool,
) -> MaintenanceReport:
    """Выполняет обслуживание на момент ``clock.now()``; при ``dry_run`` только считает."""
    sessions_expired = await purge_expired_sessions(
        sessionmaker,
        now=clock.now(),
        idle_timeout=settings.session_idle_timeout,
        dry_run=dry_run,
    )
    return MaintenanceReport(dry_run=dry_run, sessions_expired=sessions_expired)
