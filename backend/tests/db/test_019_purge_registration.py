"""R8-T12: очистка истёкших заявок на регистрацию (spec 019, NFR-9, RG-18, plan §4.3).

Заявка с ``expires_at <= now`` удаляется, действующая (``expires_at > now``) остаётся.
``dry_run=True`` только считает тем же предикатом и ничего не удаляет. Учётные записи и сессии
очистка не трогает.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.domain.auth.models import RegistrationRequest
from app.domain.system.maintenance import purge_expired_registration_requests
from tests.factories import get_table, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.committed

NOW = datetime(2026, 11, 8, 9, 0, 0, tzinfo=UTC)
MICRO = timedelta(microseconds=1)


async def _insert(sm: async_sessionmaker[AsyncSession], *, expires_at: datetime) -> uuid.UUID:
    rid = uuid.uuid4()
    async with sm() as session:
        session.add(
            RegistrationRequest(
                id=rid,
                email=f"{rid.hex}@example.test",
                login=f"u{rid.hex[:12]}",
                login_display=f"U{rid.hex[:12]}",
                first_name="Иван",
                last_name="Петров",
                password_hash="hash",
                token_hash=os.urandom(32),
                created_at=expires_at - timedelta(days=1),
                expires_at=expires_at,
            )
        )
        await session.commit()
    return rid


async def _ids(sm: async_sessionmaker[AsyncSession]) -> set[uuid.UUID]:
    async with sm() as session:
        return set((await session.execute(select(RegistrationRequest.id))).scalars().all())


async def test_019_nfr9_expired_requests_are_deleted_and_active_kept(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    expired = {
        await _insert(committed, expires_at=NOW - timedelta(minutes=1)),
        await _insert(committed, expires_at=NOW - timedelta(days=2)),
        await _insert(committed, expires_at=NOW),  # граница: expires_at <= now
    }
    live = {
        await _insert(committed, expires_at=NOW + MICRO),
        await _insert(committed, expires_at=NOW + timedelta(minutes=30)),
    }
    assert await _ids(committed) == expired | live

    assert await purge_expired_registration_requests(committed, now=NOW) == 3
    assert await _ids(committed) == live


async def test_019_nfr9_request_expiring_one_microsecond_later_is_kept(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    rid = await _insert(committed, expires_at=NOW + MICRO)
    assert await purge_expired_registration_requests(committed, now=NOW) == 0
    assert rid in await _ids(committed)


async def test_019_nfr9_dry_run_counts_and_deletes_nothing(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    dead = {
        await _insert(committed, expires_at=NOW - timedelta(hours=1)),
        await _insert(committed, expires_at=NOW),
    }
    live = {await _insert(committed, expires_at=NOW + timedelta(hours=1))}
    before = dead | live

    dry = await purge_expired_registration_requests(committed, now=NOW, dry_run=True)
    assert dry == 2
    assert await _ids(committed) == before, "dry_run ничего не удаляет"
    again = await purge_expired_registration_requests(committed, now=NOW, dry_run=True)
    assert again == 2, "dry_run повторяем"

    real = await purge_expired_registration_requests(committed, now=NOW)
    assert real == dry
    assert await _ids(committed) == live


async def test_019_nfr9_purge_does_not_touch_accounts_or_sessions(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    async with committed() as session:
        user = await make_user(session, role="tech_admin")
        await session.commit()
    user_id = user.id
    await _insert(committed, expires_at=NOW - timedelta(minutes=1))

    assert await purge_expired_registration_requests(committed, now=NOW) == 1

    users = get_table("app_user")
    async with committed() as session:
        ids = set((await session.execute(select(users.c.id))).scalars().all())
    assert user_id in ids


async def test_019_nfr9_purge_on_empty_table_returns_zero(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    assert await purge_expired_registration_requests(committed, now=NOW) == 0
    assert await purge_expired_registration_requests(committed, now=NOW, dry_run=True) == 0
