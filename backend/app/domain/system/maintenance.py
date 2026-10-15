"""Служебная очистка (plan §4.13; ревью T11, T16a): удаление истёкших сессий.

Истёкшей считается сессия, как в ``SessionStore.resolve``: ``now - last_activity_at >=
idle_timeout`` или ``now >= absolute_expires_at``. Удаление идёт пакетами по
``FOR UPDATE SKIP LOCKED`` и фиксируется после каждого пакета: строки, занятые
параллельными запросами пользователей, пропускаются, а не ожидаются, поэтому взаимных
блокировок и долгих транзакций нет. События в журнал не пишутся.

``dry_run=True`` (T31, FR-25b) только считает ``count(*)`` тем же предикатом и ничего не
удаляет.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy import delete, func, or_, select

from app.domain.auth.models import UserSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DEFAULT_BATCH_SIZE: Final = 1000


async def purge_expired_sessions(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    idle_timeout: timedelta,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> int:
    """Удаляет истёкшие сессии пользователей; возвращает число удалённых строк.

    При ``dry_run`` ничего не удаляется, возвращается число сессий, которые были бы удалены.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    idle_cutoff = now - idle_timeout
    if dry_run:
        async with sessionmaker() as session, session.begin():
            counted = await session.execute(
                select(func.count())
                .select_from(UserSession)
                .where(
                    or_(
                        UserSession.last_activity_at <= idle_cutoff,
                        UserSession.absolute_expires_at <= now,
                    )
                )
            )
            return int(counted.scalar_one())
    total = 0
    while True:
        expired = (
            select(UserSession.id)
            .where(
                or_(
                    UserSession.last_activity_at <= idle_cutoff,
                    UserSession.absolute_expires_at <= now,
                )
            )
            .order_by(UserSession.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        async with sessionmaker() as session, session.begin():
            result = await session.execute(
                delete(UserSession).where(UserSession.id.in_(expired)).returning(UserSession.id)
            )
            deleted = len(result.all())
        total += deleted
        if deleted < batch_size:
            return total
