"""Лимиты частоты запросов сброса пароля (spec 007: FR-9, AC-10; plan §4.3, PR-7, Q-7).

Email и IP в БД не пишутся: ключ счётчика — ``HMAC-SHA256(secret_key, "<scope>:<значение>")``.
Отклонённые запросы строк не добавляют, поэтому окно они не продлевают. Транзакцию ведёт
вызывающий слой.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Literal

from sqlalchemy import delete, func, insert, select

from app.domain.auth.models import PasswordResetAttempt

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

EMAIL_LIMIT: Final = 3
IP_LIMIT: Final = 10
LIMIT_WINDOW: Final = timedelta(hours=1)

# Пространство ключей advisory-блокировок лимитов сброса (ASCII «rlim»); двухключевая форма
# ``pg_advisory_xact_lock(int4, int4)`` не пересекается с ``0x75736572`` в users/service.py.
_LIMIT_LOCK_NAMESPACE: Final = 0x726C696D

Scope = Literal["email", "ip"]


def limit_key_hash(key: bytes, scope: Scope, value: str) -> bytes:
    """HMAC-SHA256(key, ``<scope>:<value>``)."""
    return hmac.new(key, f"{scope}:{value}".encode(), hashlib.sha256).digest()


def _lock_id(key_hash: bytes) -> int:
    return int.from_bytes(key_hash[:4], "big", signed=True)


async def register_request(
    db: AsyncSession, key: bytes, *, email: str | None, ip: str | None, now: datetime
) -> bool:
    """Допускает запрос и записывает его (True) либо отказывает, ничего не записывая (False).

    ``email=None`` (невалидный адрес, PR-21): область ``email`` не проверяется и не пишется.
    """
    since = now - LIMIT_WINDOW
    await db.execute(delete(PasswordResetAttempt).where(PasswordResetAttempt.created_at <= since))

    checks: list[tuple[Scope, bytes, int]] = []
    if email is not None:
        checks.append(
            ("email", limit_key_hash(key, "email", email.strip(" ").lower()), EMAIL_LIMIT)
        )
    if ip is not None:
        checks.append(("ip", limit_key_hash(key, "ip", ip), IP_LIMIT))

    # Порядок по возрастанию номера лока исключает взаимную блокировку при совпадении номеров.
    for lock_id in sorted({_lock_id(key_hash) for _, key_hash, _ in checks}):
        await db.execute(select(func.pg_advisory_xact_lock(_LIMIT_LOCK_NAMESPACE, lock_id)))

    for scope, key_hash, limit in checks:
        used = await db.scalar(
            select(func.count())
            .select_from(PasswordResetAttempt)
            .where(
                PasswordResetAttempt.scope == scope,
                PasswordResetAttempt.key_hash == key_hash,
                PasswordResetAttempt.created_at >= since,
            )
        )
        if (used or 0) >= limit:
            return False

    for scope, key_hash, _ in checks:
        await db.execute(
            insert(PasswordResetAttempt).values(scope=scope, key_hash=key_hash, created_at=now)
        )
    return True
