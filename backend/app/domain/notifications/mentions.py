"""Разбор ``@логин`` в тексте комментария (spec 012 FR-1; plan PN-5). Чистая функция.

Логин — по шаблону FR-73 (``LOGIN_RE``), без учёта регистра. Перед ``@``
не может стоять буква, цифра, ``.``, ``@`` — e-mail ``x@ivanov.ru`` упоминанием не считается.
Точка или дефис в конце дают два кандидата (с ними и без), лишний не найдётся среди логинов.
"""

from __future__ import annotations

import re
from typing import Final

from app.domain.auth.provider import LOGIN_RE

_MENTION: Final = re.compile(r"(?<![\w.@])@([A-Za-z0-9][A-Za-z0-9_.\-]{0,63})")


def parse_mentions(text: str) -> set[str]:
    """Нормализованные логины (нижний регистр) упомянутых в тексте."""
    found: set[str] = set()
    for match in _MENTION.finditer(text):
        raw = match.group(1).lower()
        # точка/дефис в конце — либо конец предложения, либо часть логина: берём оба варианта,
        # лишний отсеется при поиске пользователей (ревью 012, п. 5)
        for login in {raw, raw.rstrip(".-")}:
            if LOGIN_RE.fullmatch(login):
                found.add(login)
    return found
