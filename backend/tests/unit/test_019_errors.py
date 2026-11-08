"""R8-T02: ошибки фичи 019 (plan §4.2, RG-4, RG-10): формат, статус, код."""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings


def _make_app() -> FastAPI:
    from app.core import errors
    from app.main import create_app

    app = create_app(Settings(env="test", cookie_secure=False, expose_api_docs=False))

    async def rate_limited() -> None:
        raise errors.RateLimited()

    async def token_invalid() -> None:
        raise errors.RegistrationTokenInvalid()

    async def login_taken() -> None:
        raise errors.LoginTakenConflict()

    async def first_name_invalid() -> None:
        raise errors.Unprocessable("Укажите имя", code=errors.ErrorCode.first_name_invalid)

    async def last_name_invalid() -> None:
        raise errors.Unprocessable("Укажите фамилию", code=errors.ErrorCode.last_name_invalid)

    for path, fn in (
        ("/_t/rate-limited", rate_limited),
        ("/_t/token-invalid", token_invalid),
        ("/_t/login-taken", login_taken),
        ("/_t/first-name-invalid", first_name_invalid),
        ("/_t/last-name-invalid", last_name_invalid),
    ):
        app.add_api_route(path, fn, methods=["GET"])
    return app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_make_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_019_ac18_rate_limited_class_contract() -> None:
    from app.core.errors import AppError, RateLimited

    assert issubclass(RateLimited, AppError)
    assert RateLimited.status_code == 429
    assert RateLimited.code == "rate_limited"
    assert RateLimited.default_detail == "Слишком много запросов. Попробуйте позже"


def test_019_ac19_registration_token_invalid_class_contract() -> None:
    from app.core.errors import AppError, RegistrationTokenInvalid

    assert issubclass(RegistrationTokenInvalid, AppError)
    assert RegistrationTokenInvalid.status_code == 400
    assert RegistrationTokenInvalid.code == "registration_token_invalid"
    assert RegistrationTokenInvalid.default_detail == "Ссылка подтверждения недействительна"


def test_019_ac28_login_taken_conflict_class_contract() -> None:
    from app.core.errors import AppError, LoginTakenConflict

    assert issubclass(LoginTakenConflict, AppError)
    assert LoginTakenConflict.status_code == 409
    assert LoginTakenConflict.code == "login_taken"
    assert LoginTakenConflict.default_detail == "Логин уже занят"


@pytest.mark.parametrize("name", ["first_name_invalid", "last_name_invalid"])
def test_019_ac29_error_code_name_members(name: str) -> None:
    from app.core.errors import ErrorCode

    assert issubclass(ErrorCode, StrEnum)
    assert ErrorCode[name].value == name
    assert ErrorCode(name) == name


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/_t/rate-limited", 429, "rate_limited"),
        ("/_t/token-invalid", 400, "registration_token_invalid"),
        ("/_t/login-taken", 409, "login_taken"),
        ("/_t/first-name-invalid", 422, "first_name_invalid"),
        ("/_t/last-name-invalid", 422, "last_name_invalid"),
    ],
)
async def test_019_errors_api_response_format(
    client: httpx.AsyncClient, path: str, status: int, code: str
) -> None:
    r = await client.get(path)
    assert r.status_code == status
    body = r.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == code
    assert isinstance(body["detail"], str)
    assert body["detail"]


async def test_019_errors_default_details_in_body(client: httpx.AsyncClient) -> None:
    assert (await client.get("/_t/rate-limited")).json()["detail"] == (
        "Слишком много запросов. Попробуйте позже"
    )
    assert (await client.get("/_t/token-invalid")).json()["detail"] == (
        "Ссылка подтверждения недействительна"
    )
    assert (await client.get("/_t/login-taken")).json()["detail"] == "Логин уже занят"
