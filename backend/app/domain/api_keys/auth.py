"""Аутентификация по ключу агента: проверка, срок, лимит частоты (007 FR-9, FR-13, FR-16, FR-33;
plan 007 §4.7, PD-5).

Ключ ищется по ``sha256`` секрета (дайджест считает вызывающий —
``app.core.security.api_keys.api_key_digest``); секрет сюда не передаётся, а дайджест не попадает
ни в результат, ни в логи, ни в тексты исключений.

Любой исход — действующий, неизвестный, отозванный, истёкший ключ и отказ по лимиту — это ровно
один и тот же оператор ``UPDATE api_key … RETURNING``: по числу и виду запросов причину отказа не
различить, а счётчик окна атомарен и для параллельных соединений (строка блокируется
``UPDATE``, повторная проверка условий идёт по зафиксированному значению).

Лимит — фиксированное окно ``RATE_WINDOW`` от первого запроса окна, не больше
``RATE_LIMIT_PER_MINUTE`` запросов; счётчик не растёт выше ``RATE_LIMIT_PER_MINUTE + 1``.
``last_used_at`` обновляется только у запроса в пределах лимита (FR-16). Состояние входа по паролю
(``failed_login_count``, ``login_locked_until``) не учитывается. Транзакция не фиксируется — это
делает вызывающий (``commit_durably``), чтобы счётчик пережил последующие 4xx/429.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy import DateTime, case, func, literal, or_, update

from app.domain.api_keys.models import ApiKey

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

RATE_LIMIT_PER_MINUTE: Final = 120
RATE_WINDOW: Final = timedelta(seconds=60)


@dataclass(frozen=True)
class KeyPrincipal:
    """Владелец действующего ключа в пределах лимита (только идентификаторы)."""

    key_id: UUID
    user_id: UUID
    workspace_id: UUID


@dataclass(frozen=True)
class RateLimited:
    """Отказ по лимиту частоты: через сколько секунд (не меньше 1) откроется новое окно."""

    retry_after: int


async def authenticate_api_key(
    db: AsyncSession, digest: bytes, *, now: datetime
) -> KeyPrincipal | RateLimited | None:
    """Один ``UPDATE api_key ... RETURNING`` (PD-5).

    ``None`` — ключа нет, он отозван или истёк (``expires_at <= now``); ``RateLimited`` — запрос
    сверх лимита окна; иначе ``KeyPrincipal``. Транзакция не фиксируется.
    """
    # все выражения SET вычисляются по значениям строки до обновления
    new_window = or_(
        ApiKey.rate_window_start.is_(None), ApiKey.rate_window_start <= now - RATE_WINDOW
    )
    at = literal(now, DateTime(timezone=True))
    new_count = case(
        (new_window, 1),
        else_=func.least(ApiKey.rate_count + 1, RATE_LIMIT_PER_MINUTE + 1),
    )
    stmt = (
        update(ApiKey)
        .where(
            ApiKey.secret_digest == digest,
            ApiKey.revoked_at.is_(None),
            ApiKey.expires_at > now,
        )
        .values(
            rate_window_start=case((new_window, at), else_=ApiKey.rate_window_start),
            rate_count=new_count,
            last_used_at=case((new_count <= RATE_LIMIT_PER_MINUTE, at), else_=ApiKey.last_used_at),
        )
        .returning(
            ApiKey.id,
            ApiKey.user_id,
            ApiKey.workspace_id,
            ApiKey.rate_count,
            ApiKey.rate_window_start,
        )
        .execution_options(synchronize_session=False)
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return None
    if row.rate_count > RATE_LIMIT_PER_MINUTE:
        remaining = (row.rate_window_start + RATE_WINDOW - now).total_seconds()
        return RateLimited(retry_after=max(1, math.ceil(remaining)))
    return KeyPrincipal(key_id=row.id, user_id=row.user_id, workspace_id=row.workspace_id)
