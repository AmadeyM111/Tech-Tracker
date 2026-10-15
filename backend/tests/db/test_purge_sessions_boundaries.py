"""T31 (FR-59, FR-25b): границы истечения сессий в ``purge_expired_sessions`` с явным ``now``.

Истёкшая: ``last_activity_at <= now - 8 ч`` или ``absolute_expires_at <= now``.
``dry_run=True`` только считает тем же предикатом и ничего не удаляет.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.domain.system.maintenance import purge_expired_sessions
from tests.factories import get_table, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.committed

NOW = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
IDLE = timedelta(hours=8)
MICRO = timedelta(microseconds=1)
FAR = timedelta(days=3)


async def _insert(
    sm: async_sessionmaker[AsyncSession],
    *,
    last: datetime,
    absolute: datetime,
    user: object | None = None,
) -> bytes:
    sid = os.urandom(32)
    async with sm() as session:
        u = user or await make_user(session, role="tech_admin")
        await session.execute(
            get_table("user_session")
            .insert()
            .values(
                id=sid,
                user_id=u.id,  # type: ignore[attr-defined]
                workspace_id=u.workspace_id,  # type: ignore[attr-defined]
                created_at=NOW - timedelta(days=1),
                last_activity_at=last,
                absolute_expires_at=absolute,
            )
        )
        await session.commit()
    return sid


async def _ids(sm: async_sessionmaker[AsyncSession]) -> set[bytes]:
    table = get_table("user_session")
    async with sm() as session:
        return {bytes(r[0]) for r in (await session.execute(select(table.c.id))).all()}


async def _purge(sm: async_sessionmaker[AsyncSession], *, dry_run: bool = False) -> int:
    if dry_run:
        return await purge_expired_sessions(sm, now=NOW, idle_timeout=IDLE, dry_run=True)
    return await purge_expired_sessions(sm, now=NOW, idle_timeout=IDLE)


async def test_fr59_idle_exactly_8h_is_deleted(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    sid = await _insert(committed, last=NOW - IDLE, absolute=NOW + FAR)
    assert await _purge(committed) == 1
    assert sid not in await _ids(committed)


async def test_fr59_idle_8h_minus_one_microsecond_is_kept(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    sid = await _insert(committed, last=NOW - IDLE + MICRO, absolute=NOW + FAR)
    assert await _purge(committed) == 0
    assert sid in await _ids(committed)


async def test_fr59_absolute_exactly_now_is_deleted(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    sid = await _insert(committed, last=NOW - timedelta(minutes=1), absolute=NOW)
    assert await _purge(committed) == 1
    assert sid not in await _ids(committed)


async def test_fr59_absolute_now_plus_one_microsecond_is_kept(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    sid = await _insert(committed, last=NOW - timedelta(minutes=1), absolute=NOW + MICRO)
    assert await _purge(committed) == 0
    assert sid in await _ids(committed)


async def test_fr25b_dry_run_deletes_nothing_and_matches_real_count(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    dead = {
        await _insert(committed, last=NOW - IDLE, absolute=NOW + FAR),
        await _insert(committed, last=NOW - timedelta(minutes=1), absolute=NOW),
        await _insert(committed, last=NOW - timedelta(days=2), absolute=NOW + FAR),
    }
    live = {
        await _insert(committed, last=NOW - IDLE + MICRO, absolute=NOW + FAR),
        await _insert(committed, last=NOW, absolute=NOW + MICRO),
    }
    before = await _ids(committed)
    assert before == dead | live

    dry = await _purge(committed, dry_run=True)
    assert dry == 3
    assert await _ids(committed) == before, "dry_run ничего не удаляет"
    assert await _purge(committed, dry_run=True) == 3, "dry_run повторяем"

    real = await _purge(committed)
    assert real == dry
    assert await _ids(committed) == live


async def test_fr59_other_users_and_workspaces_untouched_unless_expired(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    async with committed() as session:
        u1 = await make_user(session, role="tech_admin")
        u2 = await make_user(session, role="tech_admin")  # другое пространство
        u1b = await make_user(session, role="tech_admin")
        await session.commit()
    dead1 = await _insert(committed, last=NOW - IDLE, absolute=NOW + FAR, user=u1)
    live1 = await _insert(committed, last=NOW, absolute=NOW + FAR, user=u1)
    live2 = await _insert(committed, last=NOW, absolute=NOW + FAR, user=u2)
    dead2 = await _insert(committed, last=NOW, absolute=NOW, user=u2)
    live3 = await _insert(committed, last=NOW - timedelta(hours=1), absolute=NOW + FAR, user=u1b)

    assert await _purge(committed) == 2
    assert await _ids(committed) == {live1, live2, live3}
    assert dead1 not in await _ids(committed)
    assert dead2 not in await _ids(committed)


async def test_fr59_rerun_is_idempotent(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    await _insert(committed, last=NOW - IDLE, absolute=NOW + FAR)
    live = await _insert(committed, last=NOW, absolute=NOW + FAR)
    assert await _purge(committed) == 1
    assert await _purge(committed) == 0
    assert await _ids(committed) == {live}
