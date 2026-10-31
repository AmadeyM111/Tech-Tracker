"""Ключ агента: формат, генерация, дайджест (007: FR-6, AC-41, NFR-3; plan §4.2, PD-1, PD-11).

Ключ — ``gtk_`` + base64url(``secrets.token_bytes(32)``) без ``=`` (47 символов).
Хранится и сравнивается только SHA-256 ключа; само значение не попадает ни в тексты
исключений, ни в их атрибуты.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from typing import Final

API_KEY_PREFIX: Final = "gtk_"
API_KEY_RANDOM_BYTES: Final = 32
API_KEY_FORMAT: Final = re.compile(r"gtk_[A-Za-z0-9_-]{43}", re.ASCII)  # fullmatch
API_KEY_LEAK_PATTERN: Final = re.compile(r"""gtk_[^\s"'`<>&;,()\[\]{}|]{8,}""")  # для логов

_INVALID_FORMAT_MESSAGE: Final = "API key has invalid format"


def generate_api_key() -> str:
    """Новый ключ: ``gtk_`` + base64url(32 случайных байт из ``secrets``) без ``=``."""
    raw = secrets.token_bytes(API_KEY_RANDOM_BYTES)
    return API_KEY_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def is_api_key_format(value: str) -> bool:
    """Строка целиком соответствует формату ключа."""
    return isinstance(value, str) and API_KEY_FORMAT.fullmatch(value) is not None


def api_key_digest(value: str) -> bytes:
    """SHA-256 ключа (32 байта); не по формату -> ``ValueError`` без значения в тексте."""
    if not is_api_key_format(value):
        raise ValueError(_INVALID_FORMAT_MESSAGE)
    return hashlib.sha256(value.encode("ascii")).digest()
