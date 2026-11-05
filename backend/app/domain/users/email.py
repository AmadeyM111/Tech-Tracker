"""Нормализация email пользователя (spec 007: FR-1; plan §4.3, PR-1)."""

from __future__ import annotations

from typing import Final

MAX_EMAIL_LENGTH: Final = 254


def normalize_email(value: str) -> str | None:
    r"""Края обрезаются только по пробелам (``\n``/``\t`` -> недопустимо), затем ``lower()``.

    Обрезка только пробелов (``strip(" ")``) выбрана намеренно: пробельные символы вроде
    перевода строки не срезаются, а отвергаются как ``email_invalid``.

    ``None``, если значение пусто или недопустимо.

    Недопустимо: длиннее 254 символов, не ровно один ``@``, пустая локальная часть или домен,
    пробельные и непечатаемые символы. Значение в исключения и логи не попадает.
    """
    normalized = value.strip(" ").lower()
    if not normalized or len(normalized) > MAX_EMAIL_LENGTH:
        return None
    if not normalized.isprintable() or any(ch.isspace() for ch in normalized):
        return None
    local, sep, domain = normalized.partition("@")
    if not sep or not local or not domain or "@" in domain:
        return None
    return normalized
