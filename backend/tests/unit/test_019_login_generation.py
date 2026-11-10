"""Генерация логина «фамилия.имя» (spec 019 v0.5, RG-7, RG-8): транслитерация по таблице
загранпаспорта РФ, очистка, длина, суффиксы кандидатов, соответствие шаблону БД.

Тесты чистые: без БД. Занятость (app_user, заявки) проверяется в домене и API.
"""

from __future__ import annotations

import itertools

import pytest

from app.domain.auth.login_generation import (
    BASE_MAX_LENGTH,
    LOGIN_SUFFIX_LIMIT,
    TRANSLIT,
    login_base,
    login_candidates,
    name_slug,
)
from app.domain.auth.provider import normalize_login

# Таблица из решения оркестратора 2026-11-09 (паспорт РФ, ICAO/ГОСТ 52535.1). Ъ и Ь опускаются.
PASSPORT_TABLE = {
    "А": "a", "Б": "b", "В": "v", "Г": "g", "Д": "d", "Е": "e", "Ё": "e", "Ж": "zh", "З": "z",
    "И": "i", "Й": "i", "К": "k", "Л": "l", "М": "m", "Н": "n", "О": "o", "П": "p", "Р": "r",
    "С": "s", "Т": "t", "У": "u", "Ф": "f", "Х": "kh", "Ц": "ts", "Ч": "ch", "Ш": "sh",
    "Щ": "shch", "Ы": "y", "Э": "e", "Ю": "iu", "Я": "ia",
}  # fmt: skip


def test_019_table_matches_passport_rules() -> None:
    assert len(PASSPORT_TABLE) == 31
    assert {k.lower() for k in PASSPORT_TABLE} == set(TRANSLIT)
    for letter, expected in PASSPORT_TABLE.items():
        assert TRANSLIT[letter.lower()] == expected, letter


@pytest.mark.parametrize(("letter", "expected"), sorted(PASSPORT_TABLE.items()))
def test_019_each_cyrillic_letter_transliterates(letter: str, expected: str) -> None:
    assert name_slug(letter) == expected
    assert name_slug(letter.lower()) == expected


@pytest.mark.parametrize("letter", ["Ъ", "Ь", "ъ", "ь"])
def test_019_hard_and_soft_sign_are_dropped(letter: str) -> None:
    assert name_slug(letter) is None
    assert name_slug(f"Иван{letter}") == "ivan"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Суриков", "surikov"),
        ("Антон", "anton"),
        ("Ёлкин", "elkin"),
        ("Йогуртов", "iogurtov"),
        ("Щукин", "shchukin"),
        ("Жуков", "zhukov"),
        ("Храмов", "khramov"),
        ("Чехов", "chekhov"),
        ("Шубин", "shubin"),
        ("Юрьев", "iurev"),
        ("Яковлев", "iakovlev"),
        ("Эдуард", "eduard"),
        ("Ильин", "ilin"),
    ],
)
def test_019_words_transliterate_as_in_passport(value: str, expected: str) -> None:
    assert name_slug(value) == expected


def test_019_surname_and_name_build_login() -> None:
    assert login_base("surikov", "anton") == "surikov.anton"


def test_019_latin_input_is_kept_in_lowercase() -> None:
    assert name_slug("Anton") == "anton"
    assert name_slug("SURIKOV") == "surikov"
    assert name_slug("Ivan2") == "ivan2"


def test_019_hyphen_is_kept_inside_double_surname() -> None:
    assert name_slug("Петрова-Иванова") == "petrova-ivanova"
    assert login_base("petrova-ivanova", "anna") == "petrova-ivanova.anna"


@pytest.mark.parametrize(
    "value",
    ["Де ла Крус", "Де-ла Крус", "О'Нил", "Иван.Петров", "  Анна  ", "Анна\tМария", "Анна!"],
)
def test_019_spaces_apostrophes_dots_and_other_symbols_are_removed(value: str) -> None:
    slug = name_slug(value)
    assert slug is not None
    assert slug == slug.lower()
    assert all(c.isascii() and (c.isalnum() or c == "-") for c in slug)


def test_019_specific_removals() -> None:
    assert name_slug("Де ла Крус") == "delakrus"
    assert name_slug("О'Нил") == "onil"
    assert name_slug("Иван.Петров") == "ivanpetrov"
    assert name_slug("Анна!") == "anna"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Müller", "muller"),
        ("René", "rene"),
        ("Dvořák", "dvorak"),
        ("Łukasz", "lukasz"),
        ("Søren", "soren"),
        ("Straße", "strasse"),
        ("Ковалів", "kovaliv"),
        ("Їжак", "izhak"),
        ("Євген", "evgen"),
        ("Ґанна", "ganna"),
        ("Ўладзімір", "uladzimir"),
    ],
)
def test_019_diacritics_and_ukrainian_letters_get_base_letters(value: str, expected: str) -> None:
    # Решение 2026-11-10: диакритика → базовая буква (NFKD), і ї є ґ ў → i i e g u.
    assert name_slug(value) == expected


def test_019_decomposed_cyrillic_input_matches_composed() -> None:
    # й и ё в виде «буква + диакритика» (NFD) дают тот же результат, что составные.
    import unicodedata

    for word in ("Йошкар-Ола", "Ёлкин", "Чайка"):
        assert name_slug(unicodedata.normalize("NFD", word)) == name_slug(word)


@pytest.mark.parametrize("value", ["-Анна-", "--Анна--", "-анна"])
def test_019_leading_and_trailing_hyphens_are_removed(value: str) -> None:
    assert name_slug(value) == "anna"


@pytest.mark.parametrize("value", ["", "   ", "-", "--", "...", "'", "中文", "李", "ъь"])
def test_019_nothing_left_after_cleaning_is_none(value: str) -> None:
    assert name_slug(value) is None


def test_019_login_base_removes_trailing_hyphen_after_truncation() -> None:
    last = "a" * 55 + "-" + "b" * 10
    base = login_base(last, "anna")
    assert len(base) == BASE_MAX_LENGTH - 1
    assert base == "a" * 55


def test_019_long_base_is_truncated_to_56_and_stays_valid() -> None:
    base = login_base("a" * 80, "b" * 80)
    assert len(base) == BASE_MAX_LENGTH
    assert base == "a" * 56


def test_019_truncation_drops_dot_left_at_the_end() -> None:
    base = login_base("a" * 55, "bbb")
    assert base == "a" * 55


def test_019_candidates_start_with_base_then_numbered() -> None:
    assert list(itertools.islice(login_candidates("surikov.anton"), 3)) == [
        "surikov.anton",
        "surikov.anton.2",
        "surikov.anton.3",
    ]


def test_019_candidate_count_and_last_suffix() -> None:
    candidates = list(login_candidates("a.b"))
    assert len(candidates) == LOGIN_SUFFIX_LIMIT
    assert candidates[-1] == f"a.b.{LOGIN_SUFFIX_LIMIT}"
    assert len(set(candidates)) == len(candidates)


def test_019_longest_candidate_fits_db_login_limit() -> None:
    base = login_base("a" * 200, "b" * 200)
    longest = list(login_candidates(base))[-1]
    assert len(longest) <= 64
    assert normalize_login(longest) == longest


@pytest.mark.parametrize(
    ("last", "first"),
    [
        ("Суриков", "Антон"),
        ("Петрова-Иванова", "Анна"),
        ("О'Нил", "Ричард Джон"),
        ("Ёжиков", "Щука"),
        ("Müller", "Ж"),
        ("Ivan", "x"),
        ("a" * 90, "b" * 90),
        ("-a-", "-b-"),
        ("Иван", "Ivan-2"),
    ],
)
def test_019_generated_logins_match_db_pattern(last: str, first: str) -> None:
    last_slug = name_slug(last)
    first_slug = name_slug(first)
    assert last_slug is not None
    assert first_slug is not None
    for login in itertools.islice(login_candidates(login_base(last_slug, first_slug)), 5):
        assert normalize_login(login) == login
        assert 3 <= len(login) <= 64
