"""Список 10 000 частых паролей (plan §7.3, ADR-0004, FR-53, OI-111).

Список поставляется в пакете; сеть не используется (NFR-4). Сравнение — точное, с учётом
регистра: ``Unbelievable`` частым не считается, если в списке есть только ``unbelievable``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Final

COMMON_PASSWORDS_SHA256: Final = "fa1ea0cf2f673458b58be3a7171d2b7fc6f2e704b4691e69c13a9a8511f5cf31"

_DATA_FILE: Final = Path(__file__).resolve().parent / "data" / "common-passwords-10k.txt"


@cache
def _load() -> frozenset[str]:
    """Читает список один раз за процесс (UTF-8, строки разделены ``\\n``)."""
    text = _DATA_FILE.read_text(encoding="utf-8")
    return frozenset(line for line in text.split("\n") if line)


def is_common_password(password: str) -> bool:
    """Точное совпадение пароля с записью списка (с учётом регистра)."""
    return password in _load()
