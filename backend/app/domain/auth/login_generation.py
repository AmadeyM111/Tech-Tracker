"""Генерация логина «фамилия.имя» при самостоятельной регистрации (spec 019 v0.5, RG-7, RG-8).

Пример: Суриков Антон → ``surikov.anton``; Петрова-Иванова, Анна → ``petrova-ivanova.anna``.
Кириллица переводится по таблице загранпаспорта РФ (ГОСТ 52535.1, решение владельца 2026-11-09);
Ъ и Ь опускаются. Украинские и белорусские буквы: і→i, ї→i, є→e, ґ→g, ў→u. Латиница с диакритикой
приводится к базовой букве (NFKD: é→e, ü→u; ß→ss, æ→ae, ø→o, ł→l, đ→d, œ→oe). ASCII-буквы и цифры
сохраняются в нижнем регистре, дефис внутри части сохраняется, прочие символы (пробелы, апострофы,
точки, иероглифы) убираются. Ведущие и хвостовые дефисы каждой
части убираются.

Модуль чистый: без БД и без времени. Занятость логина проверяет домен (``registration.py``).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from typing import Final

# Таблица паспорта РФ в нижнем регистре; ключи — кириллица, ъ и ь отсутствуют (опускаются).
TRANSLIT: Final[dict[str, str]] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ы": "y", "э": "e", "ю": "iu", "я": "ia",
}  # fmt: skip

# Длина базы «фамилия.имя» не больше 56: с суффиксом «.999» логин укладывается в 64 (БД).
BASE_MAX_LENGTH: Final = 56
# Наибольший номер суффикса при выборе логина на заявке (base, base.2 … base.999).
LOGIN_SUFFIX_LIMIT: Final = 999

# Дополнение к паспортной таблице (решение 2026-11-10): украинские и белорусские буквы.
TRANSLIT_EXTRA: Final[dict[str, str]] = {"і": "i", "ї": "i", "є": "e", "ґ": "g", "ў": "u"}
# Латинские буквы, которые NFKD не раскладывает.
LATIN_EXTRA: Final[dict[str, str]] = {
    "ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "ł": "l", "đ": "d", "ð": "d", "þ": "th",
}  # fmt: skip

_KEEP: Final = re.compile(r"[a-z0-9-]")


def _char_slug(ch: str) -> str:
    """Латинский вид одного символа; пустая строка — символ убирается."""
    if ch in TRANSLIT:
        return TRANSLIT[ch]
    if ch in TRANSLIT_EXTRA:
        return TRANSLIT_EXTRA[ch]
    if _KEEP.fullmatch(ch) is not None:
        return ch
    if ch in LATIN_EXTRA:
        return LATIN_EXTRA[ch]
    # é→e, ü→u: базовая ASCII-буква после NFKD; остаются только a-z (кириллица и иероглифы — нет).
    return "".join(c for c in unicodedata.normalize("NFKD", ch) if "a" <= c <= "z")


def name_slug(value: str) -> str | None:
    """Латинская часть имени для логина; ``None``, если после очистки ничего не осталось."""
    slug = "".join(_char_slug(ch) for ch in value.lower()).strip("-")
    return slug or None


def login_base(last_slug: str, first_slug: str) -> str:
    """База ``фамилия.имя`` не длиннее ``BASE_MAX_LENGTH``; хвостовые ``-`` и ``.`` убраны."""
    return f"{last_slug}.{first_slug}"[:BASE_MAX_LENGTH].rstrip("-.")


def login_candidates(base: str) -> Iterator[str]:
    """Кандидаты по порядку: ``base``, затем ``base.2`` … ``base.<LOGIN_SUFFIX_LIMIT>``."""
    yield base
    for number in range(2, LOGIN_SUFFIX_LIMIT + 1):
        yield f"{base}.{number}"
