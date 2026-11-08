"""Разбор ``@логин`` в тексте комментария (spec 012 FR-1; plan PN-5). Чистая функция.

Логин — по шаблону FR-73 (``^[a-z0-9][a-z0-9._-]{2,63}$``), без учёта регистра. Перед ``@``
не может стоять буква, цифра, ``.``, ``@`` — e-mail ``x@ivanov.ru`` упоминанием не считается.
Точка в конце (конец предложения) в логин не входит.
"""

from __future__ import annotations

import re
from typing import Final

_MENTION: Final = re.compile(r"(?<![\w.@])@([A-Za-z0-9][A-Za-z0-9_.\-]{0,63})")
_LOGIN: Final = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")


def parse_mentions(text: str) -> set[str]:
    """Нормализованные логины (нижний регистр) упомянутых в тексте."""
    found: set[str] = set()
    for match in _MENTION.finditer(text):
        login = match.group(1).rstrip(".-").lower()
        if _LOGIN.fullmatch(login):
            found.add(login)
    return found
