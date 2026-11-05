"""R7-T04: SMTP-адаптер `app.core.mail` (plan §4.2, PR-12).

AC-5 (письмо уходит через SMTP), NFR-1 (в логах нет адреса и текста), NFR-2 (отправка в потоке),
NFR-6 (без сети: smtplib подменён). БД не нужна.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import Settings

TO = "victim.person@example.test"
BODY = "Секретное тело письма https://tracker.example.test/password-reset/confirm#token=TOK123"
SUBJECT = "Сброс пароля"
SMTP_PASSWORD = "smtp-pass-Zq81"
SMTP_LOGIN = "smtp-login-user"


class FakeSMTP:
    """Подмена `smtplib.SMTP`: фиксирует вызовы, сети не касается."""

    instances: list[FakeSMTP] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.init_args = args
        self.init_kwargs = kwargs
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.sent: list[EmailMessage] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        self.calls.append(("starttls", args, kwargs))
        return (220, b"ok")

    def login(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        self.calls.append(("login", args, kwargs))
        return (235, b"ok")

    def send_message(self, msg: EmailMessage, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("send_message", (msg, *args), kwargs))
        self.sent.append(msg)
        return {}

    def quit(self) -> tuple[int, bytes]:
        return (221, b"bye")

    def close(self) -> None:
        return None

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "env": "test",
        "cookie_secure": False,
        "smtp_host": "smtp.invalid",
        "smtp_port": 2525,
        "smtp_from": "tracker@example.test",
        "public_base_url": "https://tracker.example.test",
    }
    base.update(over)
    return Settings(**base)


def _message() -> Any:
    from app.core.mail import MailMessage

    return MailMessage(to=TO, subject=SUBJECT, body=BODY)


def test_007_mailmessage_repr_hides_to_and_body() -> None:
    msg = _message()
    text = repr(msg)
    assert TO not in text
    assert "TOK123" not in text
    assert "Секретное" not in text
    assert SUBJECT in text


def test_007_mailmessage_is_frozen() -> None:
    msg = _message()
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg.to = "other@example.test"  # type: ignore[misc]


def test_007_smtp_connects_with_host_port_timeout(fake_smtp: type[FakeSMTP]) -> None:
    from app.core.mail import SmtpMailer

    SmtpMailer(_settings()).send(_message())
    assert len(fake_smtp.instances) == 1
    smtp = fake_smtp.instances[0]
    assert smtp.init_args[:2] == ("smtp.invalid", 2525) or (
        smtp.init_kwargs.get("host") == "smtp.invalid" and smtp.init_kwargs.get("port") == 2525
    )
    assert smtp.init_kwargs.get("timeout") == 10


def test_007_smtp_starttls_enabled_uses_default_ssl_context(fake_smtp: type[FakeSMTP]) -> None:
    from app.core.mail import SmtpMailer

    SmtpMailer(_settings(smtp_starttls=True)).send(_message())
    smtp = fake_smtp.instances[0]
    assert "starttls" in smtp.names()
    starttls = next(c for c in smtp.calls if c[0] == "starttls")
    ctx = starttls[2].get("context") or (starttls[1][0] if starttls[1] else None)
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert smtp.names().index("starttls") < smtp.names().index("send_message")


def test_007_smtp_starttls_disabled_skips_starttls(fake_smtp: type[FakeSMTP]) -> None:
    from app.core.mail import SmtpMailer

    SmtpMailer(_settings(smtp_starttls=False)).send(_message())
    assert "starttls" not in fake_smtp.instances[0].names()
    assert "send_message" in fake_smtp.instances[0].names()


def test_007_smtp_login_only_when_user_set(fake_smtp: type[FakeSMTP]) -> None:
    from app.core.mail import SmtpMailer

    SmtpMailer(_settings()).send(_message())
    assert "login" not in fake_smtp.instances[0].names()

    SmtpMailer(_settings(smtp_user=SMTP_LOGIN, smtp_password=SecretStr(SMTP_PASSWORD))).send(
        _message()
    )
    smtp = fake_smtp.instances[1]
    names = smtp.names()
    assert "login" in names
    login = next(c for c in smtp.calls if c[0] == "login")
    assert SMTP_LOGIN in login[1] or login[2].get("user") == SMTP_LOGIN
    assert SMTP_PASSWORD in login[1] or login[2].get("password") == SMTP_PASSWORD
    assert names.index("login") < names.index("send_message")


def test_007_smtp_message_headers_and_plain_utf8_body(fake_smtp: type[FakeSMTP]) -> None:
    from app.core.mail import SmtpMailer

    SmtpMailer(_settings()).send(_message())
    sent = fake_smtp.instances[0].sent
    assert len(sent) == 1
    email = sent[0]
    assert email["From"] == "tracker@example.test"
    assert email["To"] == TO
    assert email["Subject"] == SUBJECT
    assert email.get_content_type() == "text/plain"
    assert email.get_content_charset() == "utf-8"
    assert email.get_content().strip() == BODY


async def test_007_deliver_sends_via_mailer_in_worker_thread() -> None:
    from app.core.mail import deliver

    seen: list[int] = []

    class ThreadMailer:
        def send(self, message: Any) -> None:
            seen.append(threading.get_ident())

    await deliver(ThreadMailer(), _message())
    assert len(seen) == 1
    assert seen[0] != threading.get_ident()


async def test_007_deliver_does_not_block_event_loop() -> None:
    from app.core.mail import deliver

    gate = threading.Event()

    class SlowMailer:
        def send(self, message: Any) -> None:
            gate.wait(5)

    task = asyncio.create_task(deliver(SlowMailer(), _message()))
    await asyncio.sleep(0.05)
    assert not task.done()  # цикл жив, пока SMTP «думает»
    gate.set()
    await asyncio.wait_for(task, 5)


@pytest.mark.parametrize("exc_type", [RuntimeError, smtplib.SMTPException, OSError, ValueError])
async def test_007_deliver_swallows_exception_and_logs_only_type(
    exc_type: type[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    from app.core.mail import deliver

    class BoomMailer:
        def send(self, message: Any) -> None:
            raise exc_type(f"boom {TO} {BODY} {SMTP_PASSWORD}")

    with caplog.at_level(logging.DEBUG):
        await deliver(BoomMailer(), _message())  # не бросает

    mail_records = [r for r in caplog.records if r.name == "app.mail"]
    assert len(mail_records) == 1
    assert mail_records[0].levelno == logging.WARNING
    assert exc_type.__name__ in caplog.text
    for secret in (TO, "victim.person", "TOK123", BODY, SMTP_PASSWORD, SUBJECT):
        assert secret not in caplog.text
    assert all(r.exc_info is None and r.exc_text is None for r in mail_records)


async def test_007_deliver_success_logs_no_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.core.mail import deliver
    from tests.mail_support import RecordingMailer

    mailer = RecordingMailer()
    with caplog.at_level(logging.DEBUG):
        await deliver(mailer, _message())
    assert len(mailer.sent) == 1
    for secret in (TO, "TOK123", BODY):
        assert secret not in caplog.text


async def test_007_smtp_failure_through_deliver_hides_credentials(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.core.mail import SmtpMailer, deliver

    class FailingSMTP(FakeSMTP):
        def login(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
            raise smtplib.SMTPAuthenticationError(535, f"bad {SMTP_LOGIN} {SMTP_PASSWORD}".encode())

    monkeypatch.setattr(smtplib, "SMTP", FailingSMTP)
    mailer = SmtpMailer(_settings(smtp_user=SMTP_LOGIN, smtp_password=SecretStr(SMTP_PASSWORD)))
    with caplog.at_level(logging.DEBUG):
        await deliver(mailer, _message())
    assert "SMTPAuthenticationError" in caplog.text
    for secret in (SMTP_LOGIN, SMTP_PASSWORD, TO, "TOK123"):
        assert secret not in caplog.text
