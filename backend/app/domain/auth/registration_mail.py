"""Единственный шаблон письма подтверждения регистрации (spec 019: FR-5, AC-8; plan §4.3, RG-19).

В письме только ссылка и две строки текста. Логина, имени, фамилии и пароля функция
не принимает и в тело не включает.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from app.core.mail import MailMessage

SUBJECT: Final = "Подтверждение регистрации"


def build_registration_mail(*, to: str, link: str, ttl: timedelta) -> MailMessage:
    minutes = int(ttl.total_seconds() // 60)
    body = (
        f"{link}\n\n"
        f"Ссылка действует {minutes} минут.\n\n"
        "Если вы не регистрировались, ничего не делайте: учётная запись не будет создана.\n"
    )
    return MailMessage(to=to, subject=SUBJECT, body=body)
