"""M20-T03: домен токенов агентов (ADR-0018, PN-1, PN-3, PN-4, PN-5).

Покрытие: AC-1 (показ один раз, в БД хеш), AC-3 (отзыв), NFR-1 (хеш, формат, без значения в
логах не проверяется здесь), NFR-2 (фильтр по пространству), лимит 10 и срок 90 дней,
проверка токена (неизвестный, отозванный, истёкший, заблокированный), троттлинг last_used_at.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update

from app.core.clock import use_clock, utcnow
from app.core.errors import NotFound, Unprocessable
from app.domain.access.roles import Actor, Role
from app.domain.events.models import DomainEvent
from app.domain.tokens import service
from app.domain.tokens.models import ApiToken
from app.domain.users.models import AppUser
from tests.factories import WorkspaceRow, make_user, make_workspace

SESSION_ID = b"\x00" * 32


def _actor(user: Any, workspace_id: uuid.UUID, role: Role = Role.BUSINESS_ADMIN) -> Actor:
    return Actor(
        user_id=user.id,
        workspace_id=workspace_id,
        login=user.login,
        role=role,
        must_change_password=False,
        session_id=SESSION_ID,
    )


async def _user_actor(db: Any, role: Role = Role.BUSINESS_ADMIN) -> Actor:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role=role.value)
    return _actor(user, ws.id, role)


async def _peer_actor(db: Any, like: Actor, role: Role) -> Actor:
    """Второй пользователь в том же пространстве, что и ``like``."""
    ws = WorkspaceRow(id=like.workspace_id, created_at=utcnow())
    user = await make_user(db, workspace=ws, role=role.value)
    return _actor(user, like.workspace_id, role)


async def _count_events(db: Any, action: str, workspace_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(DomainEvent)
                .where(DomainEvent.action == action, DomainEvent.workspace_id == workspace_id)
            )
        ).scalar_one()
    )


async def test_m20_ac1_create_returns_token_once_and_stores_only_hash(
    db: Any, fixed_clock: Any
) -> None:
    actor = await _user_actor(db)
    created = await service.create_token(db, actor, "Claude Code")

    assert created.token.startswith(service.TOKEN_PREFIX)
    assert len(created.token) >= len(service.TOKEN_PREFIX) + 43
    assert created.view.name == "Claude Code"

    row = (await db.execute(select(ApiToken).where(ApiToken.id == created.view.id))).scalar_one()
    assert bytes(row.token_hash) == service.hash_token(created.token)
    assert created.token not in (row.name, row.token_hash.hex())
    assert row.expires_at - row.created_at == service.TOKEN_LIFETIME


async def test_m20_ac1_create_writes_audit_event(db: Any, fixed_clock: Any) -> None:
    actor = await _user_actor(db)
    await service.create_token(db, actor, "agent")
    assert await _count_events(db, "user.token_created", actor.workspace_id) == 1


@pytest.mark.parametrize("name", ["", "   ", "x" * 65, "bad\nname"])
async def test_m20_name_validation_rejects_bad_names(db: Any, fixed_clock: Any, name: str) -> None:
    actor = await _user_actor(db)
    with pytest.raises(Unprocessable) as exc:
        await service.create_token(db, actor, name)
    assert exc.value.status_code == 422


async def test_m20_limit_is_ten_active_tokens(db: Any, fixed_clock: Any) -> None:
    actor = await _user_actor(db)
    created = [
        await service.create_token(db, actor, f"agent-{i}")
        for i in range(service.MAX_ACTIVE_TOKENS)
    ]
    with pytest.raises(service.TokenLimitReached):
        await service.create_token(db, actor, "one-too-many")

    await service.revoke_token(db, actor, created[0].view.id)
    again = await service.create_token(db, actor, "after-revoke")
    assert again.view.name == "after-revoke"


async def test_m20_list_returns_only_own_tokens(db: Any, fixed_clock: Any) -> None:
    actor = await _user_actor(db)
    other = await _peer_actor(db, actor, Role.USER)
    mine = await service.create_token(db, actor, "mine")
    await service.create_token(db, other, "theirs")

    listed = await service.list_tokens(db, actor)
    assert [t.id for t in listed] == [mine.view.id]


async def test_m20_ac3_revoke_makes_token_unusable_and_is_idempotent(
    db: Any, fixed_clock: Any
) -> None:
    actor = await _user_actor(db)
    created = await service.create_token(db, actor, "agent")
    assert await service.resolve_token(db, created.token) is not None

    await service.revoke_token(db, actor, created.view.id)
    assert await service.resolve_token(db, created.token) is None

    await service.revoke_token(db, actor, created.view.id)  # повтор: без ошибки
    assert await _count_events(db, "user.token_revoked", actor.workspace_id) == 1


async def test_m20_revoke_other_users_token_is_not_found(db: Any, fixed_clock: Any) -> None:
    actor = await _user_actor(db)
    intruder = await _peer_actor(db, actor, Role.BUSINESS_ADMIN)
    created = await service.create_token(db, actor, "agent")
    with pytest.raises(NotFound):
        await service.revoke_token(db, intruder, created.view.id)
    assert await service.resolve_token(db, created.token) is not None


async def test_m20_resolve_returns_subject_for_valid_token(db: Any, fixed_clock: Any) -> None:
    actor = await _user_actor(db, role=Role.USER)
    created = await service.create_token(db, actor, "agent")
    resolved = await service.resolve_token(db, created.token)
    assert resolved is not None
    assert resolved.user_id == actor.user_id
    assert resolved.workspace_id == actor.workspace_id
    assert resolved.role is Role.USER
    assert resolved.must_change_password is False
    assert resolved.name == "agent"


async def test_m20_resolve_rejects_unknown_and_foreign_prefix(db: Any, fixed_clock: Any) -> None:
    assert await service.resolve_token(db, "gtrk_" + "a" * 43) is None
    assert await service.resolve_token(db, "not-a-token") is None


async def test_m20_expired_token_is_rejected(db: Any, fixed_clock: Any) -> None:
    actor = await _user_actor(db)
    created = await service.create_token(db, actor, "agent")
    fixed_clock.advance(service.TOKEN_LIFETIME)
    assert await service.resolve_token(db, created.token) is None


async def test_m20_blocked_user_token_is_rejected(db: Any, fixed_clock: Any) -> None:
    actor = await _user_actor(db)
    created = await service.create_token(db, actor, "agent")
    await db.execute(update(AppUser).where(AppUser.id == actor.user_id).values(is_blocked=True))
    assert await service.resolve_token(db, created.token) is None


async def test_m20_last_used_is_throttled(db: Any, fixed_clock: Any) -> None:
    actor = await _user_actor(db)
    created = await service.create_token(db, actor, "agent")

    await service.resolve_token(db, created.token)
    first = (
        await db.execute(select(ApiToken.last_used_at).where(ApiToken.id == created.view.id))
    ).scalar_one()
    assert first is not None

    fixed_clock.advance(timedelta(seconds=30))
    await service.resolve_token(db, created.token)
    same = (
        await db.execute(select(ApiToken.last_used_at).where(ApiToken.id == created.view.id))
    ).scalar_one()
    assert same == first

    fixed_clock.advance(timedelta(minutes=2))
    await service.resolve_token(db, created.token)
    later = (
        await db.execute(select(ApiToken.last_used_at).where(ApiToken.id == created.view.id))
    ).scalar_one()
    assert later > first


async def test_m20_revoke_all_for_user_revokes_only_active(db: Any, fixed_clock: Any) -> None:
    actor = await _user_actor(db)
    a = await service.create_token(db, actor, "a")
    await service.create_token(db, actor, "b")
    await service.revoke_token(db, actor, a.view.id)

    count = await service.revoke_all_for_user(
        db, workspace_id=actor.workspace_id, user_id=actor.user_id
    )
    assert count == 1
    assert await service.resolve_token(db, a.token) is None
    listed = await service.list_tokens(db, actor)
    assert all(t.revoked_at is not None for t in listed)


async def test_m20_clock_helper_is_used(db: Any, fixed_clock: Any) -> None:
    """Смоук: сервис читает часы процесса (``use_clock``), поэтому тесты детерминированы."""
    actor = await _user_actor(db)
    with use_clock(fixed_clock):
        created = await service.create_token(db, actor, "agent")
    assert created.view.created_at == fixed_clock.now()
