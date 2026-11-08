"""Лимиты самостоятельной регистрации (spec 019: FR-10, AC-18, AC-38; plan §4.3, RG-4, RG-5, RG-6).

Области: ``request_ip`` (заявки с одного IP: 10 в час), ``confirm_ip`` (подтверждения
с одного IP: 20 в час), ``confirm_token`` (подтверждения по одной ссылке: 5 в час; окно
больше срока ссылки в 30 минут). IP и токен в БД не пишутся: ключ счётчика —
``HMAC-SHA256(secret_key, "<scope>:<значение>")``, для токена значение — hex SHA-256 токена.
Отклонённые попытки строк не добавляют, поэтому окно их не продлевает. Транзакцию ведёт
вызывающий слой (``registration.py``).
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Literal

from sqlalchemy import delete, func, insert, select

from app.domain.auth.models import RegistrationAttempt

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

REQUEST_IP_LIMIT: Final = 10
CONFIRM_IP_LIMIT: Final = 20
CONFIRM_TOKEN_LIMIT: Final = 5
LIMIT_WINDOW: Final = timedelta(hours=1)

Scope = Literal["request_ip", "confirm_ip", "confirm_token"]

_LIMITS: Final[dict[Scope, int]] = {
    "request_ip": REQUEST_IP_LIMIT,
    "confirm_ip": CONFIRM_IP_LIMIT,
    "confirm_token": CONFIRM_TOKEN_LIMIT,
}

# Пространство ключей advisory-блокировок лимитов регистрации (ASCII «regi»). Двухключевая форма
# ``pg_advisory_xact_lock(int4, int4)`` не пересекается с ``0x726C696D`` (reset_limits.py) и
# ``0x75736572`` (users/service.py).
_REGI_LOCK_NAMESPACE: Final = 0x72656769


def limit_key_hash(key: bytes, scope: Scope, value: str) -> bytes:
    """HMAC-SHA256(key, ``<scope>:<значение>``): 32 байта, открытого значения нет."""
    return hmac.new(key, f"{scope}:{value}".encode(), hashlib.sha256).digest()


def _lock_id(key_hash: bytes) -> int:
    return int.from_bytes(key_hash[:4], "big", signed=True)


async def _lock_keys(db: AsyncSession, key_hashes: set[bytes]) -> None:
    # Порядок по возрастанию номера лока исключает взаимную блокировку при совпадении номеров.
    for lock_id in sorted({_lock_id(key_hash) for key_hash in key_hashes}):
        await db.execute(select(func.pg_advisory_xact_lock(_REGI_LOCK_NAMESPACE, lock_id)))


async def _used(db: AsyncSession, scope: Scope, key_hash: bytes, since: datetime) -> int:
    used = await db.scalar(
        select(func.count())
        .select_from(RegistrationAttempt)
        .where(
            RegistrationAttempt.scope == scope,
            RegistrationAttempt.key_hash == key_hash,
            RegistrationAttempt.created_at >= since,
        )
    )
    return used or 0


async def register_attempt(
    db: AsyncSession,
    key: bytes,
    checks: Sequence[tuple[Scope, str]],
    *,
    now: datetime,
) -> bool:
    """Допускает попытку (True) и пишет строку на каждую область; иначе отказ (False), без записи.

    Порядок: удалить строки старше окна; взять advisory-блокировки по возрастанию номера;
    проверить счётчики всех областей; только если все в пределах лимита, добавить строки.
    Пустой ``checks`` — True.
    """
    since = now - LIMIT_WINDOW
    await db.execute(delete(RegistrationAttempt).where(RegistrationAttempt.created_at <= since))

    hashed = [(scope, limit_key_hash(key, scope, value)) for scope, value in checks]
    await _lock_keys(db, {key_hash for _, key_hash in hashed})
    for scope, key_hash in hashed:
        if await _used(db, scope, key_hash, since) >= _LIMITS[scope]:
            return False

    for scope, key_hash in hashed:
        await db.execute(
            insert(RegistrationAttempt).values(scope=scope, key_hash=key_hash, created_at=now)
        )
    return True
