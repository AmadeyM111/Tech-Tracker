"""M20-T05: блокировка учётной записи отзывает её токены агентов (ADR-0018, PN-4, AC-4)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.domain.access.roles import Actor, Role
from app.domain.auth.sessions import SessionStore
from app.domain.tokens import service as tokens
from app.domain.tokens.models import ApiToken
from app.domain.users import service as users_service
from tests.factories import make_user, make_workspace

SECRET_KEY = b"k" * 32
SESSION_ID = b"\x00" * 32


def _actor(user: Any, workspace_id: Any, role: Role) -> Actor:
    return Actor(
        user_id=user.id,
        workspace_id=workspace_id,
        login=user.login,
        role=role,
        must_change_password=False,
        session_id=SESSION_ID,
    )


@pytest.fixture
def sessions() -> SessionStore:
    return SessionStore(
        SECRET_KEY, idle_timeout=timedelta(hours=8), absolute_timeout=timedelta(days=7)
    )


async def test_m20_ac4_blocking_user_revokes_their_tokens(db: Any, sessions: SessionStore) -> None:
    ws = await make_workspace(db)
    admin = _actor(await make_user(db, workspace=ws, role="tech_admin"), ws.id, Role.TECH_ADMIN)
    target_user = await make_user(db, workspace=ws, role="user")
    target = _actor(target_user, ws.id, Role.USER)
    bystander = _actor(await make_user(db, workspace=ws, role="user"), ws.id, Role.USER)

    blocked_token = await tokens.create_token(db, target, "target agent")
    kept_token = await tokens.create_token(db, bystander, "bystander agent")
    assert await tokens.resolve_token(db, blocked_token.token) is not None

    await users_service.block_user(db, admin, sessions, target_user.id)

    assert await tokens.resolve_token(db, blocked_token.token) is None
    row = (
        await db.execute(select(ApiToken.revoked_at).where(ApiToken.id == blocked_token.view.id))
    ).scalar_one()
    assert row is not None
    assert await tokens.resolve_token(db, kept_token.token) is not None


async def test_m20_repeat_block_is_harmless_for_tokens(db: Any, sessions: SessionStore) -> None:
    ws = await make_workspace(db)
    admin = _actor(await make_user(db, workspace=ws, role="tech_admin"), ws.id, Role.TECH_ADMIN)
    target_user = await make_user(db, workspace=ws, role="user")
    target = _actor(target_user, ws.id, Role.USER)
    token = await tokens.create_token(db, target, "agent")

    await users_service.block_user(db, admin, sessions, target_user.id)
    await users_service.block_user(db, admin, sessions, target_user.id)
    assert await tokens.resolve_token(db, token.token) is None
