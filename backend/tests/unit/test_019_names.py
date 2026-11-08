"""R8-T03: normalize_person_name (spec 019: FR-3a, AC-29; plan §4.3, RG-3)."""

from __future__ import annotations

import pytest


def test_019_ac29_max_length_is_100() -> None:
    from app.domain.users.names import NAME_MAX_LENGTH

    assert NAME_MAX_LENGTH == 100


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Анна", "Анна"),
        ("  Анна ", "Анна"),
        ("\tАнна\n", "Анна"),
        ("Анна-Мария", "Анна-Мария"),
        ("Иван Петрович", "Иван Петрович"),
        ("о'Брайен", "о'Брайен"),
        ("x", "x"),
        ("ёЁ", "ёЁ"),
    ],
)
def test_019_ac29_normalize_strips_and_keeps_spelling(raw: str, expected: str) -> None:
    from app.domain.users.names import normalize_person_name

    assert normalize_person_name(raw) == expected


@pytest.mark.parametrize("raw", ["", " ", "   ", "\t\n ", " "])
def test_019_ac29_empty_or_blank_is_none(raw: str) -> None:
    from app.domain.users.names import normalize_person_name

    assert normalize_person_name(raw) is None


def test_019_ac29_boundary_100_ok_101_rejected() -> None:
    from app.domain.users.names import normalize_person_name

    assert normalize_person_name("я" * 100) == "я" * 100
    assert normalize_person_name("я" * 101) is None
    assert normalize_person_name(" " + "я" * 100 + " ") == "я" * 100
    assert normalize_person_name(" " + "я" * 101 + " ") is None


@pytest.mark.parametrize("raw", ["Ан\nна", "Ан\x00на", "Ан\tна", "Анна\x07", "Ан​на "])
def test_019_ac29_unprintable_inside_is_none(raw: str) -> None:
    from app.domain.users.names import normalize_person_name

    assert normalize_person_name(raw) is None
