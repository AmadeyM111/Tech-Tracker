"""R7-T02: ошибки фичи 007 (plan §4.2): формат, статус, код."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings


def _make_app() -> FastAPI:
    from app.core import errors
    from app.main import create_app

    app = create_app(Settings(env="test", cookie_secure=False, expose_api_docs=False))

    async def disabled() -> None:
        raise errors.FeatureDisabled()

    async def token_invalid() -> None:
        raise errors.ResetTokenInvalid()

    async def email_taken() -> None:
        raise errors.EmailTaken()

    async def email_taken_custom() -> None:
        raise errors.EmailTaken("Адрес занят")

    async def email_invalid() -> None:
        raise errors.Unprocessable("Некорректный email", code=errors.ErrorCode.email_invalid)

    for path, fn in (
        ("/_t/disabled", disabled),
        ("/_t/token-invalid", token_invalid),
        ("/_t/email-taken", email_taken),
        ("/_t/email-taken-custom", email_taken_custom),
        ("/_t/email-invalid", email_invalid),
    ):
        app.add_api_route(path, fn, methods=["GET"])
    return app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_make_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_007_ac2_feature_disabled_class_contract() -> None:
    from app.core.errors import AppError, FeatureDisabled

    assert issubclass(FeatureDisabled, AppError)
    assert FeatureDisabled.status_code == 404
    assert FeatureDisabled.code == "feature_disabled"
    assert FeatureDisabled.default_detail == "Функция отключена"


def test_007_ac7_reset_token_invalid_class_contract() -> None:
    from app.core.errors import AppError, ResetTokenInvalid

    assert issubclass(ResetTokenInvalid, AppError)
    assert ResetTokenInvalid.status_code == 400
    assert ResetTokenInvalid.code == "reset_token_invalid"
    assert ResetTokenInvalid.default_detail == "Ссылка для сброса пароля недействительна"


def test_007_ac1_email_taken_class_contract() -> None:
    from app.core.errors import AppError, EmailTaken

    assert issubclass(EmailTaken, AppError)
    assert EmailTaken.status_code == 409
    assert EmailTaken.code == "email_taken"
    assert EmailTaken.default_detail == "Email уже используется"


def test_007_ac1_error_code_email_invalid_member() -> None:
    from enum import StrEnum

    from app.core.errors import ErrorCode

    assert issubclass(ErrorCode, StrEnum)
    assert ErrorCode["email_invalid"].value == "email_invalid"
    assert ErrorCode("email_invalid") == "email_invalid"


@pytest.mark.parametrize(
    ("path", "status", "code", "detail"),
    [
        ("/_t/disabled", 404, "feature_disabled", "Функция отключена"),
        (
            "/_t/token-invalid",
            400,
            "reset_token_invalid",
            "Ссылка для сброса пароля недействительна",
        ),
        ("/_t/email-taken", 409, "email_taken", "Email уже используется"),
        ("/_t/email-taken-custom", 409, "email_taken", "Адрес занят"),
        ("/_t/email-invalid", 422, "email_invalid", "Некорректный email"),
    ],
)
async def test_007_errors_api_response_format(
    client: httpx.AsyncClient, path: str, status: int, code: str, detail: str
) -> None:
    r = await client.get(path)
    assert r.status_code == status
    body: Any = r.json()
    assert set(body) == {"detail", "code"}
    assert body == {"detail": detail, "code": code}
