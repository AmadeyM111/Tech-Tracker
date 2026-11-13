"""Регулярное обслуживание (plan §4.13, §4.3, §10.4; D-42, FR-25b, NFR-9).

``run_maintenance`` собирает отчёт о выполненных (или, при ``dry_run``, только подсчитанных)
действиях: истёкшие сессии (T31), заявки регистрации (R8-T12) и вложения — корзина и
файлы-сироты (spec 011). Корзина проектов, задач и комментариев — R3, их счётчики равны 0. События
в журнал не пишутся.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.db import transaction
from app.domain.attachments.purge import purge_attachments
from app.domain.notifications.due import purge_notifications
from app.domain.oauth.service import purge as purge_oauth
from app.domain.system.maintenance import (
    purge_expired_registration_requests,
    purge_expired_sessions,
)

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
    registration_requests_expired: int = 0
    notifications_purged: int = 0  # spec 012 FR-9: старше 90 дней
    oauth_purged: int = 0  # spec 028 FR-13: неиспользуемые клиенты, просроченные коды и токены


async def run_maintenance(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    clock: Clock,
    dry_run: bool,
) -> MaintenanceReport:
    """Выполняет обслуживание на момент ``clock.now()``; при ``dry_run`` только считает."""
    now = clock.now()
    sessions_expired = await purge_expired_sessions(
        sessionmaker,
        now=now,
        idle_timeout=settings.session_idle_timeout,
        dry_run=dry_run,
    )
    registration_requests_expired = await purge_expired_registration_requests(
        sessionmaker,
        now=now,
        dry_run=dry_run,
    )
    files = await purge_attachments(sessionmaker, settings, now=clock.now(), dry_run=dry_run)
    notes = await purge_notifications(sessionmaker, now=clock.now(), dry_run=dry_run)
    async with transaction(sessionmaker) as db:
        oauth = await purge_oauth(db, clock.now(), dry_run=dry_run)
    return MaintenanceReport(
        dry_run=dry_run,
        sessions_expired=sessions_expired,
        registration_requests_expired=registration_requests_expired,
        attachments_purged=files.attachments_purged,
        files_removed=files.files_removed,
        orphan_files_removed=files.orphan_files_removed,
        notifications_purged=notes,
        oauth_purged=sum(oauth.values()),
    )
