"""Описание ответов об ошибках в OpenAPI (plan §4.2, §4.14, D-32, D-33, FR-45).

Тело любой ошибки — одна схема ``ErrorResponse`` ``{detail, code}``. Роутеры объявляют ответы
``400/401/403/404/422`` через ``error_responses`` (параметр ``responses`` FastAPI), поэтому схема
``HTTPValidationError`` в OpenAPI не появляется: у неё нет ``code``. Какие статусы объявлять:

* 400 — есть тело запроса (синтаксически невалидный JSON, ``bad_request``);
* 401 — маршрут требует вход (``get_actor``), у входа — ``invalid_credentials``;
* 403 — гейты ``password_change_required``/``no_role``/``forbidden`` или ``origin_mismatch``
  (``check_origin``, небезопасные методы);
* 404 — объект по идентификатору в пути;
* 422 — есть параметры запроса или тело (в том числе параметр пути).

Полноту объявлений проверяет ``tests/cli/test_openapi.py``.
"""

from __future__ import annotations

from typing import Any, Final

from app.core.errors import ErrorResponse

ErrorResponses = dict[int | str, dict[str, Any]]

_DESCRIPTIONS: Final[dict[int, str]] = {
    400: "Некорректный JSON в теле запроса (code: bad_request)",
    401: "Не выполнен вход или сессия недействительна (code: not_authenticated)",
    403: ("Доступ запрещён (code: forbidden, password_change_required, no_role, origin_mismatch)"),
    404: "Объект не найден или принадлежит другому пространству (code: not_found)",
    422: "Ошибка валидации или бизнес-правила (code: validation_error или код из каталога)",
}


def error_response(status: int, description: str | None = None) -> ErrorResponses:
    """Один ответ об ошибке со схемой ``ErrorResponse``; ``description`` уточняет текст."""
    return {
        status: {
            "model": ErrorResponse,
            "description": description if description is not None else _DESCRIPTIONS[status],
        }
    }


def error_responses(*statuses: int) -> ErrorResponses:
    """Ответы об ошибках для ``responses=`` роутера или маршрута."""
    merged: ErrorResponses = {}
    for status in statuses:
        merged.update(error_response(status))
    return merged
