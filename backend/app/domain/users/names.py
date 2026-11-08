"""Нормализация имени и фамилии человека (spec 019: FR-3a, AC-29; plan §4.3, RG-3)."""

from __future__ import annotations

from typing import Final

NAME_MAX_LENGTH: Final = 100


def normalize_person_name(value: str) -> str | None:
    """``strip()``; ``None``, если пусто, длиннее 100 или есть непечатаемые символы.

    Написание сохраняется. Значение в исключения и логи не попадает.
    """
    stripped = value.strip()
    if not stripped or len(stripped) > NAME_MAX_LENGTH or not stripped.isprintable():
        return None
    return stripped
