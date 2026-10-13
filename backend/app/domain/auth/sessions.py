"""Серверные сессии (plan §4.6, D-13, FR-58, FR-59, FR-62).

Клиент получает случайный токен (32 байта, base64url); в БД хранится только
``HMAC-SHA256(secret_key, token)``: утечка БД не даёт рабочих токенов. Сроки: простой 8 часов
(истекла при ``>=``), абсолютный 7 суток с входа. Фоновые запросы опроса срок простоя не
продлевают (FR-59).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import delete, insert, select, update

from app.domain.auth.models import UserSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

TOKEN_BYTES: Final = 32
MIN_SECRET_KEY_BYTES: Final = 32


@dataclass(frozen=True)
class SessionRecord:
    id: bytes
    user_id: UUID
    workspace_id: UUID
    created_at: datetime
    last_activity_at: datetime


class SessionStore:
    def __init__(
        self, secret_key: bytes, *, idle_timeout: timedelta, absolute_timeout: timedelta
    ) -> None:
        if len(secret_key) < MIN_SECRET_KEY_BYTES:
            # значение ключа в сообщение не попадает
            raise ValueError(
                f"Секретный ключ сессий слишком короткий: минимум {MIN_SECRET_KEY_BYTES} байта"
            )
        self._secret_key = secret_key
        self._idle_timeout = idle_timeout
        self._absolute_timeout = absolute_timeout

    def token_id(self, token: str) -> bytes:
        """``HMAC-SHA256(secret_key, token)`` — идентификатор строки ``user_session``."""
        # surrogatepass: произвольная строка из cookie не должна вызывать исключение;
        # такой токен просто не найдётся.
        data = token.encode("utf-8", errors="surrogatepass")
        return hmac.new(self._secret_key, data, hashlib.sha256).digest()

    async def create(
        self, db: AsyncSession, *, user_id: UUID, workspace_id: UUID, now: datetime
    ) -> str:
        """Создаёт сессию; возвращает сырой токен (в БД его нет)."""
        token = secrets.token_urlsafe(TOKEN_BYTES)
        await db.execute(
            insert(UserSession).values(
                id=self.token_id(token),
                user_id=user_id,
                workspace_id=workspace_id,
                created_at=now,
                last_activity_at=now,
                absolute_expires_at=now + self._absolute_timeout,
            )
        )
        return token

    async def resolve(
        self, db: AsyncSession, token: str, *, now: datetime, background: bool
    ) -> SessionRecord | None:
        """Действующая сессия по токену или ``None``.

        Истекла, если ``now - last_activity_at >= idle_timeout`` или
        ``now >= absolute_expires_at``: строка удаляется. Иначе при ``background=False``
        ``last_activity_at = now``.
        """
        sid = self.token_id(token)
        row = (
            await db.execute(
                select(
                    UserSession.user_id,
                    UserSession.workspace_id,
                    UserSession.created_at,
                    UserSession.last_activity_at,
                    UserSession.absolute_expires_at,
                ).where(UserSession.id == sid)
            )
        ).one_or_none()
        if row is None:
            return None
        if now - row.last_activity_at >= self._idle_timeout or now >= row.absolute_expires_at:
            await db.execute(delete(UserSession).where(UserSession.id == sid))
            return None
        last_activity_at: datetime = row.last_activity_at
        if not background:
            await db.execute(
                update(UserSession).where(UserSession.id == sid).values(last_activity_at=now)
            )
            last_activity_at = now
        return SessionRecord(
            id=sid,
            user_id=row.user_id,
            workspace_id=row.workspace_id,
            created_at=row.created_at,
            last_activity_at=last_activity_at,
        )

    async def delete(self, db: AsyncSession, token: str) -> None:
        """Удаляет сессию по токену; неизвестный токен — не ошибка (идемпотентно)."""
        await db.execute(delete(UserSession).where(UserSession.id == self.token_id(token)))

    async def delete_all_for_user(
        self, db: AsyncSession, user_id: UUID, *, keep_id: bytes | None = None
    ) -> int:
        """Удаляет все сессии пользователя, кроме ``keep_id``; возвращает число удалённых."""
        stmt = delete(UserSession).where(UserSession.user_id == user_id)
        if keep_id is not None:
            stmt = stmt.where(UserSession.id != keep_id)
        result = await db.execute(stmt.returning(UserSession.id))
        return len(result.all())
