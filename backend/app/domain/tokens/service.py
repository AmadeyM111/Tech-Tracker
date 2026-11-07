"""Персональные токены агентов: выдача, список, отзыв, проверка (ADR-0018, PN-1, PN-3, PN-4, PN-5).

Токен — ``gtrk_`` + 32 байта случайности. В БД хранится только SHA-256 (PN-1). Выдача и отзыв
пишутся в журнал как действия с учётной записью (PN-5). Проверка ``resolve_token`` отвечает
одинаково для неизвестного, отозванного, истёкшего токена и заблокированного пользователя;
отказ при ``must_change_password`` или без роли решает слой MCP (PN-3).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.errors import AppError, NotFound, Unprocessable
from app.domain.access.roles import Actor, Role
from app.domain.events.catalog import EventAction
from app.domain.events.writer import record_event
from app.domain.tokens.models import ApiToken
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

TOKEN_PREFIX = "gtrk_"
TOKEN_LIFETIME = timedelta(days=90)
MAX_ACTIVE_TOKENS = 10
NAME_MAX_LENGTH = 64
LAST_USED_GRANULARITY = timedelta(minutes=1)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class TokenLimitReached(AppError):
    status_code = 409
    code = "token_limit_reached"
    default_detail = "Достигнут лимит активных токенов"


@dataclass(frozen=True)
class TokenView:
    id: UUID
    name: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True)
class CreatedToken:
    view: TokenView
    token: str  # показывается один раз; в БД не хранится


@dataclass(frozen=True)
class ResolvedToken:
    token_id: UUID
    user_id: UUID
    workspace_id: UUID
    login: str
    role: Role | None
    must_change_password: bool
    name: str


def hash_token(raw: str) -> bytes:
    """SHA-256 токена (32 байта); именно хеш хранится и ищется (PN-1)."""
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not 1 <= len(cleaned) <= NAME_MAX_LENGTH:
        raise Unprocessable("Имя токена: от 1 до 64 символов", code="validation_error")
    if _CONTROL_CHARS.search(cleaned):
        raise Unprocessable("Имя токена содержит управляющие символы", code="validation_error")
    return cleaned


def _view(row: ApiToken) -> TokenView:
    return TokenView(
        id=row.id,
        name=row.name,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
    )


async def create_token(db: AsyncSession, actor: Actor, name: str) -> CreatedToken:
    """Выдаёт токен текущему пользователю; лимит активных — ``MAX_ACTIVE_TOKENS`` (PN-1)."""
    clean = _clean_name(name)
    # Блокировка строки пользователя: два одновременных выпуска не обходят лимит.
    await db.execute(select(AppUser.id).where(AppUser.id == actor.user_id).with_for_update())
    now = utcnow()
    active = await db.execute(
        select(ApiToken.id).where(
            ApiToken.user_id == actor.user_id,
            ApiToken.workspace_id == actor.workspace_id,
            ApiToken.revoked_at.is_(None),
            ApiToken.expires_at > now,
        )
    )
    if len(active.all()) >= MAX_ACTIVE_TOKENS:
        raise TokenLimitReached()
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(
        id=uuid4(),
        workspace_id=actor.workspace_id,
        user_id=actor.user_id,
        name=clean,
        token_hash=hash_token(raw),
        created_at=now,
        expires_at=now + TOKEN_LIFETIME,
    )
    db.add(row)
    await db.flush()
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_TOKEN_CREATED,
        entity_id=actor.user_id,
    )
    return CreatedToken(view=_view(row), token=raw)


async def list_tokens(db: AsyncSession, actor: Actor) -> list[TokenView]:
    """Токены текущего пользователя в его пространстве, без хеша и значения токена."""
    rows = await db.execute(
        select(ApiToken)
        .where(ApiToken.user_id == actor.user_id, ApiToken.workspace_id == actor.workspace_id)
        .order_by(ApiToken.created_at.desc(), ApiToken.id)
    )
    return [_view(row) for row in rows.scalars().all()]


async def revoke_token(db: AsyncSession, actor: Actor, token_id: UUID) -> None:
    """Отзывает свой токен; повторный отзыв — без ошибки и без события. Чужой — 404."""
    row = (
        await db.execute(
            select(ApiToken).where(
                ApiToken.id == token_id,
                ApiToken.user_id == actor.user_id,
                ApiToken.workspace_id == actor.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound()
    if row.revoked_at is not None:
        return
    row.revoked_at = utcnow()
    await db.flush()
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_TOKEN_REVOKED,
        entity_id=actor.user_id,
    )


async def revoke_all_for_user(db: AsyncSession, *, workspace_id: UUID, user_id: UUID) -> int:
    """Отзывает все активные токены пользователя (PN-4, при блокировке); возвращает число."""
    result = await db.execute(
        update(ApiToken)
        .where(
            ApiToken.user_id == user_id,
            ApiToken.workspace_id == workspace_id,
            ApiToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def resolve_token(db: AsyncSession, raw: str) -> ResolvedToken | None:
    """Токен → субъект, или ``None`` для неизвестного, отозванного, истёкшего, заблокированного.

    ``last_used_at`` обновляется не чаще раза в ``LAST_USED_GRANULARITY``, чтобы не писать
    в БД на каждый вызов инструмента.
    """
    if not raw.startswith(TOKEN_PREFIX):
        return None
    now = utcnow()
    row = (
        await db.execute(
            select(
                ApiToken.id,
                ApiToken.name,
                ApiToken.last_used_at,
                ApiToken.user_id,
                ApiToken.workspace_id,
                AppUser.login_display,
                AppUser.is_blocked,
                AppUser.must_change_password,
                WorkspaceMember.role,
            )
            .join(AppUser, AppUser.id == ApiToken.user_id)
            .join(
                WorkspaceMember,
                (WorkspaceMember.user_id == ApiToken.user_id)
                & (WorkspaceMember.workspace_id == ApiToken.workspace_id),
            )
            .where(
                ApiToken.token_hash == hash_token(raw),
                ApiToken.revoked_at.is_(None),
                ApiToken.expires_at > now,
            )
        )
    ).one_or_none()
    if row is None or row.is_blocked:
        return None
    if row.last_used_at is None or now - row.last_used_at >= LAST_USED_GRANULARITY:
        await db.execute(
            update(ApiToken)
            .where(ApiToken.id == row.id)
            .values(last_used_at=now)
            .execution_options(synchronize_session=False)
        )
    return ResolvedToken(
        token_id=row.id,
        user_id=row.user_id,
        workspace_id=row.workspace_id,
        login=row.login_display,
        role=None if row.role is None else Role(row.role),
        must_change_password=row.must_change_password,
        name=row.name,
    )
