"""R7-T04: шаблон письма сброса пароля `reset_mail.build_reset_mail` (plan §4.3, FR-4, FR-7, NFR-3).

AC-5: ссылка с `#token=`, срок «30 минут», предупреждение; нет логина, пароля, хеша.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pytest

LINK = "https://tracker.example.test/password-reset/confirm#token=abc_DEF-123"
TO = "ivan.petrov@example.test"
LOGIN = "ivan_petrov_login"
PASSWORD = "Sup3r-Secret-Pass!"


def _build(**over: Any) -> Any:
    from app.domain.auth.reset_mail import build_reset_mail

    kwargs: dict[str, Any] = {"to": TO, "link": LINK, "ttl": timedelta(minutes=30)}
    kwargs.update(over)
    return build_reset_mail(**kwargs)


def test_007_reset_mail_subject_and_recipient() -> None:
    from app.core.mail import MailMessage
    from app.domain.auth.reset_mail import SUBJECT

    msg = _build()
    assert isinstance(msg, MailMessage)
    assert SUBJECT == "Сброс пароля"
    assert msg.subject == SUBJECT
    assert msg.to == TO


def test_007_reset_mail_contains_exact_link_with_fragment() -> None:
    body = _build().body
    assert LINK in body
    assert "/password-reset/confirm#token=" in body
    assert "?token=" not in body  # FR-4: токен только во фрагменте


def test_007_reset_mail_states_ttl_and_single_use_in_russian() -> None:
    body = _build().body
    assert "Ссылка действует 30 минут и сработает один раз." in body


def test_007_reset_mail_warns_if_not_you() -> None:
    body = _build().body
    assert "Если это были не вы, ничего не делайте: пароль останется прежним." in body


def test_007_reset_mail_ttl_is_taken_from_argument() -> None:
    body = _build(ttl=timedelta(minutes=30)).body
    assert "30 минут" in body


def test_007_reset_mail_has_no_login_password_or_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGIN", LOGIN)  # логин в окружении теста не должен попасть в письмо
    monkeypatch.setenv("PASSWORD", PASSWORD)
    msg = _build()
    text = f"{msg.subject}\n{msg.body}"
    assert LOGIN not in text
    assert PASSWORD not in text
    assert "$argon2" not in text
    low = text.lower()
    assert "логин" not in low
    assert "пароль:" not in low


def test_007_reset_mail_is_russian_text() -> None:
    body = _build().body
    cyr = sum("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in body)
    assert cyr > 40


def test_007_reset_mail_is_deterministic() -> None:
    assert _build() == _build()


def test_007_reset_mail_repr_hides_address_and_link() -> None:
    text = repr(_build())
    assert TO not in text
    assert "abc_DEF-123" not in text


def test_007_reset_mail_build_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        _build()
    assert "abc_DEF-123" not in caplog.text
    assert TO not in caplog.text
