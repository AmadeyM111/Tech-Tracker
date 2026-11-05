"""SMTP-адаптер (feature 007, plan §4.2, PR-12): только стандартная библиотека.

В лог не попадают адрес, тема, тело, ссылка и текст исключения: пишется лишь имя типа.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings

logger = logging.getLogger("app.mail")

_SMTP_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class MailMessage:
    """Письмо; адресат и тело скрыты из `repr`."""

    to: str = field(repr=False)
    subject: str
    body: str = field(repr=False)


class Mailer(Protocol):
    def send(self, message: MailMessage) -> None: ...


class SmtpMailer:
    """Отправка через SMTP с необязательными STARTTLS и аутентификацией."""

    def __init__(self, settings: Settings) -> None:
        if settings.smtp_host is None or settings.smtp_from is None:
            raise ValueError("smtp_host and smtp_from are required")
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._user = settings.smtp_user
        self._password = settings.smtp_password
        self._sender = settings.smtp_from
        self._starttls = settings.smtp_starttls

    def send(self, message: MailMessage) -> None:
        email = EmailMessage()
        email["From"] = self._sender
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.body, subtype="plain", charset="utf-8")
        with smtplib.SMTP(self._host, self._port, timeout=_SMTP_TIMEOUT_SECONDS) as smtp:
            if self._starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self._user is not None:
                password = self._password.get_secret_value() if self._password else ""
                smtp.login(self._user, password)
            smtp.send_message(email)


async def deliver(mailer: Mailer, message: MailMessage) -> None:
    """Отправляет письмо в потоке; любая ошибка гасится, в лог идёт только имя типа."""
    try:
        await asyncio.to_thread(mailer.send, message)
    except Exception as exc:
        logger.warning("mail delivery failed: %s", type(exc).__name__)
