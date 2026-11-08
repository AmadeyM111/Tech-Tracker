"""R8-T08: шаблон письма регистрации `registration_mail.build_registration_mail`.

Spec 019: FR-5, AC-8; plan §4.3, RG-19. В письме только ссылка на подтверждение и три строки
из RG-19. Логина, имени, фамилии и пароля в нём нет.
"""

from __future__ import annotations

import inspect
from datetime import timedelta

from app.core.mail import MailMessage
from app.domain.auth.registration_mail import SUBJECT, build_registration_mail

TO = "ivan.petrov@example.test"
LINK = "https://tracker.example.test/register/confirm#token=abc_DEF-123"
LOGIN = "ivan_petrov_login"
FIRST_NAME = "Иван"
LAST_NAME = "Петров"
PASSWORD = "Sup3r-Secret-Pass!"
TTL_LINE = "Ссылка действует 30 минут."
WARNING_LINE = "Если вы не регистрировались, ничего не делайте: учётная запись не будет создана."


def _build() -> MailMessage:
    return build_registration_mail(to=TO, link=LINK, ttl=timedelta(minutes=30))


def test_019_mail_subject_and_recipient() -> None:
    msg = _build()
    assert isinstance(msg, MailMessage)
    assert SUBJECT == "Подтверждение регистрации"
    assert msg.subject == "Подтверждение регистрации"
    assert msg.to == TO


def test_019_ac8_body_contains_exact_link_with_fragment() -> None:
    body = _build().body
    assert LINK in body
    assert "/register/confirm#token=" in body
    assert "?token=" not in body  # токен только во фрагменте


def test_019_ac8_states_ttl_and_warning() -> None:
    body = _build().body
    assert TTL_LINE in body
    assert WARNING_LINE in body


def test_019_body_has_only_link_and_required_lines() -> None:
    # RG-19: «В письме только ссылка и эти строки.»
    lines = [line for line in _build().body.splitlines() if line.strip()]
    assert lines == [LINK, TTL_LINE, WARNING_LINE]


def test_019_ac8_builder_takes_no_login_name_or_password() -> None:
    params = set(inspect.signature(build_registration_mail).parameters)
    assert params == {"to", "link", "ttl"}


def test_019_ac8_no_login_name_or_password_in_message() -> None:
    msg = _build()
    text = f"{msg.subject}\n{msg.body}"
    for marker in (LOGIN, FIRST_NAME, LAST_NAME, PASSWORD, "$argon2"):
        assert marker not in text
    low = text.lower()
    assert "логин" not in low
    assert "пароль" not in low
    assert "фамилия" not in low
    assert "имя" not in low


def test_019_recipient_address_not_in_body() -> None:
    assert TO not in _build().body


def test_019_message_repr_hides_address_and_link() -> None:
    text = repr(_build())
    assert TO not in text
    assert "abc_DEF-123" not in text
