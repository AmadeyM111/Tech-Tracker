"""Пароли: политика, Argon2id, генерация (plan §4.2, ADR-0004; FR-2, FR-52, FR-53, FR-57).

Пароль не попадает ни в сообщения исключений, ни в их атрибуты (FR-57).
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import string
from typing import Final, Literal

from argon2 import PasswordHasher as _Argon2Hasher
from argon2 import Type
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.security.common_passwords import is_common_password

MIN_PASSWORD_LENGTH: Final = 12

_ALPHABET: Final = string.ascii_letters + string.digits

_MESSAGES: Final[dict[str, str]] = {
    "password_too_short": f"Пароль слишком короткий: минимум {MIN_PASSWORD_LENGTH} символов",
    "password_too_common": "Пароль входит в список частых паролей",
}


class PasswordPolicyError(Exception):
    """Пароль не соответствует политике. ``code`` — код ошибки 422; значения пароля нет."""

    code: Literal["password_too_short", "password_too_common"]

    def __init__(self, code: Literal["password_too_short", "password_too_common"]) -> None:
        super().__init__(_MESSAGES[code])
        self.code = code


def validate_new_password(password: str) -> None:
    """Проверяет новый пароль: длина (FR-52), затем список частых (FR-53).

    Длина считается в символах Unicode; правил состава нет.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError("password_too_short")
    if is_common_password(password):
        raise PasswordPolicyError("password_too_common")


def generate_password(length: int = 20) -> str:
    """Случайный пароль из ASCII-букв и цифр (``secrets``); проходит политику."""
    if length < MIN_PASSWORD_LENGTH:
        raise ValueError(f"length must be >= {MIN_PASSWORD_LENGTH}")
    while True:
        value = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if not is_common_password(value):
            return value


class PasswordHasher:
    """Argon2id; параметры задаются аргументами (ARGON2_* из настроек)."""

    def __init__(self, *, time_cost: int, memory_cost_kib: int, parallelism: int) -> None:
        self._hasher = _Argon2Hasher(
            time_cost=time_cost,
            memory_cost=memory_cost_kib,
            parallelism=parallelism,
            type=Type.ID,
        )
        # Хеш случайного пароля с теми же параметрами — для выравнивания времени.
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def hash(self, password: str) -> str:
        """Хеш ``$argon2id$...`` со случайной солью."""
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """True, если пароль совпал; хеш с любыми параметрами Argon2 проверяется."""
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def dummy_verify(self, password: str) -> None:
        """Проверка по фиктивному хешу: время как у реального входа; результат отбрасывается."""
        with contextlib.suppress(VerificationError):
            self._hasher.verify(self._dummy_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        """True, если параметры хеша отличаются от параметров этого хешера."""
        return self._hasher.check_needs_rehash(password_hash)


async def hash_in_thread(hasher: PasswordHasher, password: str) -> str:
    """``hasher.hash`` в пуле потоков, чтобы не блокировать цикл событий."""
    return await asyncio.to_thread(hasher.hash, password)


async def verify_in_thread(hasher: PasswordHasher, password_hash: str, password: str) -> bool:
    """``hasher.verify`` в пуле потоков."""
    return await asyncio.to_thread(hasher.verify, password_hash, password)
