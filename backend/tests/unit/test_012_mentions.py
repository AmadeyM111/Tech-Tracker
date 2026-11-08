"""N12-T01: разбор ``@логин`` (spec 012 FR-1; AC-2)."""

from __future__ import annotations

import pytest

from app.domain.notifications.mentions import parse_mentions


@pytest.mark.parametrize(
    ("text", "logins"),
    [
        ("@Ivanov посмотри", {"ivanov"}),
        ("Привет, @ivanov.petr и @sidorova!", {"ivanov.petr", "sidorova"}),
        ("Конец предложения @petrov.", {"petrov.", "petrov"}),
        ("@ivan- в конце логина дефис", {"ivan-", "ivan"}),
        ("почта x@ivanov.ru не упоминание", set()),
        ("@ab слишком короткий", set()),
        ("@-bad и @_bad", set()),
        ("(@user_1) и @user-2,", {"user_1", "user-2"}),
        ("@@double", set()),
        ("", set()),
    ],
)
def test_012_ac2_parse_mentions(text: str, logins: set[str]) -> None:
    assert parse_mentions(text) == logins
