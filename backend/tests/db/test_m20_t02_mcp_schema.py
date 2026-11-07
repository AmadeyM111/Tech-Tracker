"""M20-T02: схема MCP-доступа — ``api_token`` и ``domain_event.client_name`` (ADR-0018, PN-1, PN-6).

Покрытие: миграция 0009 вверх/вниз (аддитивно), ограничения длины имени токена и хеша,
уникальность хеша, ограничение длины ``client_name``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.core.clock import utcnow
from app.domain.events.models import DomainEvent
from app.domain.tokens.models import ApiToken
from tests.db_support import run_alembic
from tests.factories import make_domain_event, make_user, make_workspace


@pytest.mark.committed
async def test_m20_t02_migration_0009_upgrade_downgrade_upgrade_and_check(
    committed: Any, test_database_url: str
) -> None:
    async def alembic(*args: str) -> None:
        result = await asyncio.to_thread(run_alembic, test_database_url, *args)
        assert result.returncode == 0, (
            f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
        )

    await alembic("upgrade", "head")
    await alembic("downgrade", "0008")
    await alembic("upgrade", "head")
    await alembic("check")


async def _token_row(
    db: Any,
    *,
    name: str = "Claude Code",
    token_hash: bytes | None = None,
    ws: Any = None,
    user: Any = None,
) -> ApiToken:
    ws = ws or await make_workspace(db)
    user = user or await make_user(db, workspace=ws, role="business_admin")
    now = utcnow()
    token = ApiToken(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        user_id=user.id,
        name=name,
        token_hash=token_hash if token_hash is not None else uuid.uuid4().bytes * 2,
        created_at=now,
        expires_at=now + timedelta(days=90),
    )
    db.add(token)
    await db.flush()
    return token


async def test_m20_t02_api_token_roundtrip_stores_hash_and_defaults(db: Any) -> None:
    token = await _token_row(db)
    await db.refresh(token)
    assert len(token.token_hash) == 32
    assert token.last_used_at is None
    assert token.revoked_at is None


@pytest.mark.parametrize("name", ["", "x" * 65])
async def test_m20_t02_api_token_name_length_is_checked(db: Any, name: str) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await _token_row(db, name=name)


async def test_m20_t02_api_token_name_64_chars_is_allowed(db: Any) -> None:
    token = await _token_row(db, name="x" * 64)
    assert len(token.name) == 64


@pytest.mark.parametrize("size", [31, 33])
async def test_m20_t02_token_hash_must_be_32_bytes(db: Any, size: int) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await _token_row(db, token_hash=b"\x01" * size)


async def test_m20_t02_token_hash_is_unique(db: Any) -> None:
    first = await _token_row(db, token_hash=b"\x07" * 32)
    assert first.id is not None
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await _token_row(db, token_hash=b"\x07" * 32)


async def test_m20_t02_domain_event_client_name_is_nullable_and_checked(db: Any) -> None:
    ws = await make_workspace(db)
    event_id = await make_domain_event(db, workspace_id=ws.id)
    row = await db.get(DomainEvent, event_id)
    assert row is not None
    assert row.client_name is None

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                update(DomainEvent).where(DomainEvent.id == event_id).values(client_name="")
            )
            await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                update(DomainEvent).where(DomainEvent.id == event_id).values(client_name="y" * 65)
            )
            await db.flush()
