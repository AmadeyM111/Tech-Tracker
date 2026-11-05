"""Единственный шаблон письма сброса пароля (feature 007, plan §4.3, FR-4, FR-7, NFR-3)."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from app.core.mail import MailMessage

SUBJECT: Final = "Сброс пароля"


def build_reset_mail(*, to: str, link: str, ttl: timedelta) -> MailMessage:
    minutes = int(ttl.total_seconds() // 60)
    body = (
        "Здравствуйте!\n\n"
        "Для вашей учётной записи в трекере запрошен сброс пароля. "
        "Чтобы задать новый пароль, перейдите по ссылке:\n\n"
        f"{link}\n\n"
        f"Ссылка действует {minutes} минут и сработает один раз.\n\n"
        "Если это были не вы, ничего не делайте: пароль останется прежним.\n"
    )
    return MailMessage(to=to, subject=SUBJECT, body=body)
