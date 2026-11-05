"""Тестовая инфраструктура почты (feature 007, plan §4.6): запись писем вместо отправки."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.mail import MailMessage


class RecordingMailer:
    """Заглушка `Mailer`: складывает письма в `sent`, сети не касается."""

    def __init__(self) -> None:
        self.sent: list[MailMessage] = []

    def send(self, message: MailMessage) -> None:
        self.sent.append(message)
