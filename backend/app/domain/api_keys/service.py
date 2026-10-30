"""Ключи агентов: выпуск, перечень, отзыв (spec 007 FR-5…FR-11; plan 007 §4.6, PD-1, PD-6, PD-8).

Секрет ключа существует только в результате ``issue_api_key`` (``IssuedApiKey.secret``, без
``repr``): в БД пишется ``sha256`` секрета, в журнал — id и название ключа; в логи, тексты
исключений и ``details`` секрет не попадает.

Выпуск и отзыв идут по единому протоколу блокировок учётных записей (PD-8): сначала
``users.service.lock_for_account_change``, затем состояние агента читается через
``users.service.load_account``. Так подсчёт действующих ключей и вставка не гонятся между собой,
а параллельная блокировка агента не оставляет ему действующий ключ. Модуль пользователей
вызывается по имени модуля (``accounts.<функция>``), а не импортом функций.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import load_only

from app.core.clock import utcnow
from app.core.errors import ErrorCode, Forbidden, NotFound, Unprocessable
from app.core.pagination import PageParams, paginate
from app.core.security.api_keys import api_key_digest, generate_api_key
from app.domain.access.roles import Actor, Capability
from app.domain.api_keys.models import ApiKey
from app.domain.events.catalog import EventAction
from app.domain.events.writer import UserEventDetails, record_event
from app.domain.users import service as accounts
from app.domain.users.directory import UserRef, user_refs

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

MAX_ACTIVE_KEYS: Final = 5
DEFAULT_TTL_DAYS: Final = 90
MAX_TTL_DAYS: Final = 365
MAX_NAME_LENGTH: Final = 100


class ApiKeyState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


def key_state(*, expires_at: datetime, revoked_at: datetime | None, now: datetime) -> ApiKeyState:
    """PD-6: ``revoked`` (есть ``revoked_at``), иначе ``expired`` (``expires_at <= now``),
    иначе ``active``."""
    if revoked_at is not None:
        return ApiKeyState.REVOKED
    if expires_at <= now:
        return ApiKeyState.EXPIRED
    return ApiKeyState.ACTIVE


@dataclass(frozen=True)
class ApiKeyView:
    """Ключ в перечне и в ответе выпуска; ни секрета, ни его дайджеста нет."""

    id: UUID
    name: str
    created_at: datetime
    created_by: UserRef | None
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    state: ApiKeyState


@dataclass(frozen=True)
class IssuedApiKey:
    """Результат выпуска: секрет показывается один раз и в ``repr`` не попадает."""

    key: ApiKeyView
    secret: str = field(repr=False)


def _require(actor: Actor) -> None:
    if not actor.can(Capability.MANAGE_ACCOUNTS):
        raise Forbidden()


def _validate_issue(name: str, ttl_days: int) -> None:
    """422 ``validation_error``: срок 1…365 суток, название 1…100 символов без NUL."""
    if isinstance(ttl_days, bool) or not 1 <= ttl_days <= MAX_TTL_DAYS:
        raise Unprocessable(
            f"Срок действия ключа — от 1 до {MAX_TTL_DAYS} суток",
            code=ErrorCode.validation_error,
        )
    if not 1 <= len(name) <= MAX_NAME_LENGTH or "\x00" in name:
        raise Unprocessable(
            f"Название ключа — от 1 до {MAX_NAME_LENGTH} символов",
            code=ErrorCode.validation_error,
        )


async def _creator_ref(db: AsyncSession, workspace_id: UUID, user_id: UUID) -> UserRef | None:
    return (await user_refs(db, workspace_id, [user_id])).get(user_id)


async def issue_api_key(
    db: AsyncSession, actor: Actor, user_id: UUID, /, *, name: str, ttl_days: int
) -> IssuedApiKey:
    """403 MANAGE_ACCOUNTS -> 1 <= ttl_days <= 365 и 1 <= len(name) <= 100, без NUL, иначе 422
    validation_error -> lock_for_account_change -> load_account (404) -> не агент: 422 not_an_agent
    -> заблокирован: 422 user_blocked -> действующих >= 5: 422 api_key_limit_reached ->
    generate_api_key, INSERT (expires_at = now + ttl_days суток) -> USER_API_KEY_ISSUED
    (entity_id = агент, details {api_key_id, api_key_name})."""
    _require(actor)
    _validate_issue(name, ttl_days)
    await accounts.lock_for_account_change(db, actor.workspace_id, user_id, actor.user_id)
    target = await accounts.load_account(db, actor.workspace_id, user_id)
    if not target.is_agent:
        raise Unprocessable("Ключ можно выпустить только агенту", code=ErrorCode.not_an_agent)
    if target.is_blocked:
        raise Unprocessable("Учётная запись заблокирована", code=ErrorCode.user_blocked)

    now = utcnow()
    active = (
        await db.execute(
            select(func.count())
            .select_from(ApiKey)
            .where(
                ApiKey.workspace_id == actor.workspace_id,
                ApiKey.user_id == target.id,
                ApiKey.revoked_at.is_(None),
                ApiKey.expires_at > now,
            )
        )
    ).scalar_one()
    if active >= MAX_ACTIVE_KEYS:
        raise Unprocessable(
            f"У агента уже {MAX_ACTIVE_KEYS} действующих ключей",
            code=ErrorCode.api_key_limit_reached,
        )

    secret = generate_api_key()
    expires_at = now + timedelta(days=ttl_days)
    key_id = (
        await db.execute(
            insert(ApiKey)
            .values(
                workspace_id=actor.workspace_id,
                user_id=target.id,
                name=name,
                secret_digest=api_key_digest(secret),
                created_at=now,
                created_by=actor.user_id,
                expires_at=expires_at,
            )
            .returning(ApiKey.id)
        )
    ).scalar_one()
    details: UserEventDetails = {"api_key_id": str(key_id), "api_key_name": name}
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_API_KEY_ISSUED,
        entity_id=target.id,
        details=details,
    )
    view = ApiKeyView(
        id=key_id,
        name=name,
        created_at=now,
        created_by=await _creator_ref(db, actor.workspace_id, actor.user_id),
        expires_at=expires_at,
        last_used_at=None,
        revoked_at=None,
        state=ApiKeyState.ACTIVE,
    )
    return IssuedApiKey(key=view, secret=secret)


async def list_api_keys(
    db: AsyncSession, actor: Actor, user_id: UUID, params: PageParams
) -> tuple[list[ApiKeyView], bool]:
    """403 -> load_account (404) -> ключи агента created_at DESC, id DESC; у не агента — []."""
    _require(actor)
    target = await accounts.load_account(db, actor.workspace_id, user_id)
    if not target.is_agent:
        return [], False
    stmt = (
        select(ApiKey)
        # дайджест секрета и счётчики частоты в выборку не попадают
        .options(
            load_only(
                ApiKey.id,
                ApiKey.name,
                ApiKey.created_at,
                ApiKey.created_by,
                ApiKey.expires_at,
                ApiKey.last_used_at,
                ApiKey.revoked_at,
            )
        )
        .where(ApiKey.workspace_id == actor.workspace_id, ApiKey.user_id == target.id)
        .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
        # строки могли измениться UPDATE-ом без синхронизации сессии (отзыв, блокировка)
        .execution_options(populate_existing=True)
    )
    rows, has_next = await paginate(db, stmt, params)
    if not rows:
        return [], has_next
    now = utcnow()
    refs = await user_refs(db, actor.workspace_id, {row.created_by for row in rows})
    items = [
        ApiKeyView(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            created_by=refs.get(row.created_by),
            expires_at=row.expires_at,
            last_used_at=row.last_used_at,
            revoked_at=row.revoked_at,
            state=key_state(expires_at=row.expires_at, revoked_at=row.revoked_at, now=now),
        )
        for row in rows
    ]
    return items, has_next


async def revoke_api_key(db: AsyncSession, actor: Actor, user_id: UUID, key_id: UUID, /) -> None:
    """403 -> lock -> load_account (404) -> ключ этого пользователя в пространстве (404) ->
    revoked или expired: return (без события) -> UPDATE revoked_at/revoked_by ->
    USER_API_KEY_REVOKED."""
    _require(actor)
    await accounts.lock_for_account_change(db, actor.workspace_id, user_id, actor.user_id)
    target = await accounts.load_account(db, actor.workspace_id, user_id)
    key = (
        await db.execute(
            select(ApiKey.id, ApiKey.name, ApiKey.expires_at, ApiKey.revoked_at).where(
                ApiKey.id == key_id,
                ApiKey.workspace_id == actor.workspace_id,
                ApiKey.user_id == target.id,
            )
        )
    ).one_or_none()
    if key is None:
        raise NotFound()
    now = utcnow()
    if key_state(expires_at=key.expires_at, revoked_at=key.revoked_at, now=now) is not (
        ApiKeyState.ACTIVE
    ):
        return
    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == key.id, ApiKey.revoked_at.is_(None))
        .values(revoked_at=now, revoked_by=actor.user_id)
        .execution_options(synchronize_session=False)
    )
    details: UserEventDetails = {"api_key_id": str(key.id), "api_key_name": key.name}
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_API_KEY_REVOKED,
        entity_id=target.id,
        details=details,
    )
