"""Провайдеры аутентификации (plan §4.6, D-10, FR-3, FR-61).

``AuthProvider`` проверяет учётные данные и возвращает идентификатор пользователя или ``None``.
Блокировку учётной записи, членство и создание сессии выполняет ``service.login`` (D-10).

``LocalPasswordProvider`` — Argon2id и защита от перебора: 5 неудач подряд блокируют вход по
логину на 15 минут (значения задаются конструктором). Пароль, хеш и логин в исключения и логи
не попадают.

Защита от перебора устойчива к параллельным запросам (FR-61, AC-37): попытка резервируется
одним атомарным ``UPDATE ... WHERE <нет блокировки> RETURNING`` ДО проверки пароля (медленный
Argon2 выполняется без блокировки строки). Пятая попытка в серии при резервировании сразу
выставляет ``login_locked_until`` и обнуляет счётчик, поэтому проверок пароля между
фиксациями блокировки не больше порога. Успех сбрасывает серию условным ``UPDATE``: если
блокировка зафиксирована параллельным запросом, вход отклоняется. Исключение — попытка,
сама поставившая блокировку (пятая): при верном пароле она её снимает.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import case, or_, update

from app.core.security.passwords import PasswordHasher, hash_in_thread, verify_in_thread
from app.domain.users.models import AppUser

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# FR-73 / D-39: тот же шаблон, что в CHECK таблицы app_user. Сопоставляется целиком
# (fullmatch): ни перевод строки, ни NUL в конце не допускаются.
LOGIN_RE: Final = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")


def normalize_login(raw: str) -> str | None:
    """Приводит введённый логин к нижнему регистру и проверяет шаблон FR-73.

    ``None`` — логин не может принадлежать ни одной учётной записи. Нижний регистр только
    для ASCII: ``str.lower()`` для не-ASCII (например, знак Кельвина U+212A -> ``k``) дал бы
    ложные совпадения с шаблоном.
    """
    if not raw.isascii():
        return None
    login = raw.lower()
    if LOGIN_RE.fullmatch(login) is None:
        return None
    return login


# Вызывается провайдером сразу после резервирования попытки: вызывающий делает занятый слот
# видимым параллельным запросам (фиксация), не дожидаясь медленной проверки пароля.
Checkpoint = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class PasswordCredentials:
    login: str  # уже нормализован (lower)
    password: SecretStr


class AuthProvider(Protocol):
    """Источник проверки учётных данных (FR-3: OIDC добавляется новой реализацией)."""

    name: str

    async def authenticate(
        self,
        db: AsyncSession,
        credentials: PasswordCredentials,
        *,
        now: datetime,
        checkpoint: Checkpoint | None = None,
    ) -> UUID | None:
        """``user_id`` при успехе, иначе ``None`` (причина отказа не различается).

        ``checkpoint`` (необязательный) провайдер ожидает после записи состояния, которое
        должно быть видно параллельным запросам до долгой проверки.
        """
        ...


def _encodable(password: str) -> str | None:
    """Пароль, пригодный для хеширования (UTF-8), либо ``None`` (одиночный суррогат).

    Исключение кодирования не пробрасывается: его ``args`` содержат пароль (ревью T08).
    """
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return password


class LocalPasswordProvider:
    """Пароль в БД (Argon2id) + защита от перебора (FR-61)."""

    name = "local"

    def __init__(
        self, hasher: PasswordHasher, *, max_failures: int, lock_duration: timedelta
    ) -> None:
        self._hasher = hasher
        self._max_failures = max_failures
        self._lock_duration = lock_duration

    async def _equalize_time(self, password: str) -> None:
        """Проверка по фиктивному хешу: время ответа не зависит от причины отказа."""
        safe = _encodable(password)
        await asyncio.to_thread(self._hasher.dummy_verify, safe if safe is not None else "")

    async def authenticate(
        self,
        db: AsyncSession,
        credentials: PasswordCredentials,
        *,
        now: datetime,
        checkpoint: Checkpoint | None = None,
    ) -> UUID | None:
        login = credentials.login
        password = credentials.password.get_secret_value()

        # Логин вне шаблона (в том числе с NUL) не может существовать: в БД не ходим,
        # NUL asyncpg отверг бы исключением.
        if LOGIN_RE.fullmatch(login) is None:
            await self._equalize_time(password)
            return None

        # Резервирование попытки до проверки пароля: один атомарный UPDATE. Нет строки —
        # логина нет либо вход заблокирован: ответ и затраты времени одинаковы (FR-61).
        next_count = AppUser.failed_login_count + 1
        reached = next_count >= self._max_failures
        row = (
            await db.execute(
                update(AppUser)
                .where(
                    AppUser.login == login,
                    or_(AppUser.login_locked_until.is_(None), AppUser.login_locked_until <= now),
                )
                .values(
                    failed_login_count=case((reached, 0), else_=next_count),
                    login_locked_until=case(
                        (reached, now + self._lock_duration), else_=AppUser.login_locked_until
                    ),
                )
                .returning(
                    AppUser.id,
                    AppUser.password_hash,
                    AppUser.failed_login_count,
                    AppUser.login_locked_until,
                )
                .execution_options(synchronize_session=False)
            )
        ).one_or_none()
        if row is None:
            await self._equalize_time(password)
            return None

        user_id: UUID = row.id
        # RETURNING отдаёт новые значения: счётчик 0 после резервирования означает, что эта
        # попытка — пятая в серии и сама поставила блокировку (``own_lock``).
        own_lock: datetime | None = row.login_locked_until if row.failed_login_count == 0 else None
        if checkpoint is not None:
            await checkpoint()

        safe_password = _encodable(password)
        if safe_password is None:
            # Одиночный суррогат не совпадёт ни с одним хешем: обычная неудача.
            await self._equalize_time(password)
            return None
        if not await verify_in_thread(self._hasher, row.password_hash, safe_password):
            return None  # неудача уже учтена резервированием

        # Успех: условный сброс серии (и перехеширование устаревшего хеша). Блокировка,
        # зафиксированная параллельными неудачами, пока проверялся пароль, вход отклоняет.
        if own_lock is not None:
            still_ours = AppUser.login_locked_until == own_lock
        else:
            still_ours = or_(
                AppUser.login_locked_until.is_(None), AppUser.login_locked_until <= now
            )
        values: dict[str, object] = {"failed_login_count": 0, "login_locked_until": None}
        if self._hasher.needs_rehash(row.password_hash):
            values["password_hash"] = await hash_in_thread(self._hasher, safe_password)
        reset = await db.execute(
            update(AppUser)
            .where(AppUser.id == user_id, still_ours)
            .values(**values)
            .returning(AppUser.id)
            .execution_options(synchronize_session=False)
        )
        if reset.scalar_one_or_none() is None:
            return None
        return user_id
