"""Единый формат ошибок API (plan §4.2, FR-45, FR-57, D-30).

Тело любой ошибки: ``{"detail": str | list[{"loc", "msg", "type"}], "code": str}``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, ClassVar, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")

INTERNAL_ERROR_DETAIL = "Внутренняя ошибка"


class ErrorDetail(BaseModel):
    """Одна ошибка валидации в ``detail`` 422: без введённого значения (FR-57)."""

    loc: list[str | int]
    msg: str
    type: str


class ErrorResponse(BaseModel):
    """Тело любой ошибки API: ``detail`` — текст или ошибки валидации, ``code`` — машинный код."""

    detail: str | list[ErrorDetail]
    code: str


class ErrorCode(StrEnum):
    """Каталог кодов ошибок 422 (plan §4.2); имя члена совпадает со значением."""

    # [0]
    validation_error = "validation_error"
    password_too_short = "password_too_short"
    password_too_common = "password_too_common"
    password_reused = "password_reused"
    invalid_current_password = "invalid_current_password"
    login_invalid = "login_invalid"
    login_taken = "login_taken"
    last_account_admin = "last_account_admin"
    user_not_found = "user_not_found"
    user_blocked = "user_blocked"
    recipient_wrong_role = "recipient_wrong_role"
    not_project_member = "not_project_member"
    # [1-2]
    owner_cannot_be_removed = "owner_cannot_be_removed"
    subtask_depth_exceeded = "subtask_depth_exceeded"
    label_not_found = "label_not_found"
    too_many_labels = "too_many_labels"
    label_name_taken = "label_name_taken"
    too_many_attachments = "too_many_attachments"
    attachment_type_not_allowed = "attachment_type_not_allowed"
    parent_task_deleted = "parent_task_deleted"
    project_deleted = "project_deleted"
    invalid_neighbors = "invalid_neighbors"
    # [3]
    inn_taken = "inn_taken"
    contacts_attached = "contacts_attached"
    contact_wrong_account = "contact_wrong_account"
    stage_archived = "stage_archived"
    stage_has_deals = "stage_has_deals"
    pipeline_invariant = "pipeline_invariant"
    stage_name_taken = "stage_name_taken"
    deal_already_linked = "deal_already_linked"
    project_already_linked = "project_already_linked"
    project_linked_to_deleted_deal = "project_linked_to_deleted_deal"
    account_has_deals = "account_has_deals"
    account_deleted = "account_deleted"
    permanent_delete_not_allowed = "permanent_delete_not_allowed"
    # [1]
    search_query_too_short = "search_query_too_short"


class AppError(Exception):
    """Базовая прикладная ошибка: HTTP-статус и код задаются классом."""

    status_code: ClassVar[int] = 400
    code: ClassVar[str] = "error"
    default_detail: ClassVar[str] = "Ошибка запроса"

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        self.detail: str = self.default_detail if detail is None else detail
        if code is not None:
            # переопределение только для экземпляра: ClassVar на классе не меняется
            self.__dict__["code"] = str(code)
        super().__init__(self.detail)


class NotAuthenticated(AppError):
    status_code = 401
    code = "not_authenticated"
    default_detail = "Требуется вход в систему"


class InvalidCredentials(AppError):
    """Тело одинаково для всех причин отказа входа (FR-5, FR-61)."""

    status_code = 401
    code = "invalid_credentials"
    default_detail = "Неверный логин или пароль"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    default_detail = "Недостаточно прав"


class PasswordChangeRequired(Forbidden):
    code = "password_change_required"
    default_detail = "Необходимо сменить пароль"


class NoRole(Forbidden):
    code = "no_role"
    default_detail = "Пользователю не назначена роль"


class OriginMismatch(Forbidden):
    code = "origin_mismatch"
    default_detail = "Недопустимый источник запроса"


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    default_detail = "Не найдено"


class ProjectArchived(AppError):
    status_code = 409
    code = "project_archived"
    default_detail = "Проект в архиве"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "attachment_too_large"
    default_detail = "Файл слишком большой"


class ServiceBusy(AppError):
    """Занятая блокировка или взаимоблокировка БД (D-40): состояние временное, можно повторить."""

    status_code = 503
    code = "service_busy"
    default_detail = "Сервер занят, повторите запрос"


class Unprocessable(AppError):
    """422; код обязателен (``ErrorCode`` или строка)."""

    status_code = 422
    code = ErrorCode.validation_error
    default_detail = "Некорректные данные"

    # Намеренно сужаем сигнатуру: у 422 без кода клиенту нечего показать.
    def __init__(self, detail: str | None = None, *, code: str) -> None:
        super().__init__(detail, code=code)


# Starlette-исключения (роутинг, зависимости): статус → (code, detail).
_HTTP_STATUS_MAP: dict[int, tuple[str, str]] = {
    400: ("bad_request", "Некорректный запрос"),
    401: ("not_authenticated", "Требуется вход в систему"),
    403: ("forbidden", "Недостаточно прав"),
    404: ("not_found", "Не найдено"),
    405: ("method_not_allowed", "Метод не поддерживается"),
    409: ("conflict", "Конфликт состояния"),
    413: ("payload_too_large", "Слишком большой запрос"),
    415: ("unsupported_media_type", "Неподдерживаемый тип содержимого"),
    429: ("too_many_requests", "Слишком много запросов"),
}


def _error_response(
    status_code: int,
    detail: str | list[dict[str, Any]],
    code: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"detail": detail, "code": code}, headers=headers
    )


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001  # сигнатура задана фреймворком
    err = cast(AppError, exc)
    return _error_response(err.status_code, err.detail, err.code)


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001  # сигнатура задана фреймворком
    """422 без ``input``, ``ctx``, ``url``: введённое значение (пароль) не возвращается (FR-57)."""
    errors = cast(RequestValidationError, exc).errors()
    detail = [
        {
            "loc": list(e.get("loc", ())),
            "msg": str(e.get("msg", "")),
            "type": str(e.get("type", "")),
        }
        for e in errors
    ]
    return _error_response(422, detail, ErrorCode.validation_error)


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001  # сигнатура задана фреймворком
    http_exc = cast(StarletteHTTPException, exc)
    status = http_exc.status_code
    if status in _HTTP_STATUS_MAP:
        code, detail = _HTTP_STATUS_MAP[status]
    elif status >= 500:
        code, detail = "internal_error", INTERNAL_ERROR_DETAIL
    else:
        code, detail = "http_error", "Ошибка запроса"
    # exc.detail не отдаём: текст исключения не должен попадать в ответ
    return _error_response(status, detail, code, headers=http_exc.headers)


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001  # сигнатура задана фреймворком
    """500 с фиксированным телом; трассировка — только в лог (FR-57)."""
    logger.error("Unhandled exception", exc_info=exc)
    return _error_response(500, INTERNAL_ERROR_DETAIL, "internal_error")


# SQLSTATE: lock_not_available (превышен lock_timeout) и deadlock_detected (D-40).
_BUSY_SQLSTATES = frozenset({"55P03", "40P01"})
_RETRY_AFTER_SECONDS = "5"


def _sqlstate(exc: DBAPIError) -> str | None:
    """SQLSTATE из ``orig.sqlstate``/``orig.pgcode``, затем из ``orig.__cause__`` (asyncpg)."""
    orig = exc.orig
    for source in (orig, getattr(orig, "__cause__", None)):
        for attr in ("sqlstate", "pgcode"):
            value = getattr(source, attr, None)
            if isinstance(value, str) and value:
                return value
    return None


async def _dbapi_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """55P03/40P01 -> 503 ``service_busy``; прочие ошибки БД — как любое необработанное (500).

    В лог идёт только SQLSTATE: текст ``DBAPIError`` содержит SQL (FR-57, NFR-9).
    """
    state = _sqlstate(cast(DBAPIError, exc))
    if state not in _BUSY_SQLSTATES:
        return await _unhandled_exception_handler(request, exc)
    logger.warning("Database is busy: SQLSTATE %s", state)
    busy = ServiceBusy()
    return _error_response(
        busy.status_code, busy.detail, busy.code, headers={"Retry-After": _RETRY_AFTER_SECONDS}
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(DBAPIError, _dbapi_error_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
