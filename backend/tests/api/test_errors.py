"""T04: единый формат ошибок и фабрика приложения (FR-45, FR-57, FR-7, D-32, plan §4.2)."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.core.clock import FixedClock, SystemClock, utcnow
from app.core.config import Settings

FIXED_AT = datetime(2031, 3, 4, 12, 30, 0, tzinfo=UTC)
SECRET_VALUE = "hunter2-secret-value"
BOOM_TEXT = "boom-internal-detail-xyz"


def _settings(**kwargs: Any) -> Settings:
    kwargs.setdefault("env", "test")
    kwargs.setdefault("cookie_secure", False)
    kwargs.setdefault("expose_api_docs", False)
    return Settings(**kwargs)


def _make_app(**kwargs: Any) -> FastAPI:
    from app.main import create_app

    clock = kwargs.pop("clock", None)
    return create_app(_settings(**kwargs), clock=clock)


class LoginBody(BaseModel):
    login: str = Field(min_length=3)
    password: str = Field(min_length=20)


def _add_test_routes(app: FastAPI) -> None:
    from app.core import errors

    async def raise_not_found() -> None:
        raise errors.NotFound("Объект не найден")

    async def raise_not_found_custom_code() -> None:
        raise errors.NotFound("Пользователь не найден", code="user_not_found")

    async def raise_forbidden_subclass() -> None:
        raise errors.PasswordChangeRequired("Смените пароль")

    async def raise_archived() -> None:
        raise errors.ProjectArchived("Проект в архиве")

    async def raise_too_large() -> None:
        raise errors.PayloadTooLarge("Файл слишком большой")

    async def raise_unprocessable() -> None:
        raise errors.Unprocessable("Логин занят", code=errors.ErrorCode.login_taken)

    async def raise_unauthenticated() -> None:
        raise errors.NotAuthenticated("Нужен вход")

    async def raise_unexpected() -> None:
        raise RuntimeError(BOOM_TEXT)

    async def post_login(body: LoginBody) -> dict[str, str]:
        return {"login": body.login}

    async def query_int(n: int) -> dict[str, int]:
        return {"n": n}

    async def clock_now() -> dict[str, str]:
        return {"now": utcnow().isoformat()}

    async def only_get() -> dict[str, str]:
        return {"ok": "yes"}

    routes: list[tuple[str, str, Callable[..., Any]]] = [
        ("/_t/not-found", "GET", raise_not_found),
        ("/_t/not-found-code", "GET", raise_not_found_custom_code),
        ("/_t/pwd-change", "GET", raise_forbidden_subclass),
        ("/_t/archived", "GET", raise_archived),
        ("/_t/too-large", "GET", raise_too_large),
        ("/_t/unprocessable", "GET", raise_unprocessable),
        ("/_t/unauth", "GET", raise_unauthenticated),
        ("/_t/boom", "GET", raise_unexpected),
        ("/_t/login", "POST", post_login),
        ("/_t/query", "GET", query_int),
        ("/_t/clock", "GET", clock_now),
        ("/_t/only-get", "GET", only_get),
    ]
    for path, method, fn in routes:
        app.add_api_route(path, fn, methods=[method])


@pytest.fixture
def app() -> FastAPI:
    application = _make_app()
    _add_test_routes(application)
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _assert_error_shape(body: Any, code: str) -> None:
    assert isinstance(body, dict)
    assert set(body) == {"detail", "code"}
    assert body["code"] == code


# --- FR-45: формат ошибок ---------------------------------------------------------------


async def test_fr45_unknown_path_is_404_not_found(client: httpx.AsyncClient) -> None:
    r = await client.get("/no/such/path")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    _assert_error_shape(r.json(), "not_found")
    assert isinstance(r.json()["detail"], str)


async def test_fr45_wrong_method_is_405_method_not_allowed(client: httpx.AsyncClient) -> None:
    r = await client.post("/_t/only-get")
    assert r.status_code == 405
    _assert_error_shape(r.json(), "method_not_allowed")


async def test_fr45_health_wrong_method_is_405(client: httpx.AsyncClient) -> None:
    r = await client.delete("/api/v1/health")
    assert r.status_code == 405
    _assert_error_shape(r.json(), "method_not_allowed")


async def test_fr45_validation_error_is_422_with_list_detail(client: httpx.AsyncClient) -> None:
    r = await client.post("/_t/login", json={"login": "ab", "password": "short"})
    assert r.status_code == 422
    body = r.json()
    _assert_error_shape(body, "validation_error")
    assert isinstance(body["detail"], list)
    assert body["detail"], "список ошибок не должен быть пустым"
    for item in body["detail"]:
        assert set(item) == {"loc", "msg", "type"}
        assert isinstance(item["loc"], list)
        assert isinstance(item["msg"], str)
        assert isinstance(item["type"], str)
    locs = [tuple(item["loc"]) for item in body["detail"]]
    assert ("body", "login") in locs
    assert ("body", "password") in locs


async def test_fr45_validation_query_error_is_422(client: httpx.AsyncClient) -> None:
    r = await client.get("/_t/query", params={"n": "not-a-number"})
    assert r.status_code == 422
    body = r.json()
    _assert_error_shape(body, "validation_error")
    assert [tuple(i["loc"]) for i in body["detail"]] == [("query", "n")]
    assert "not-a-number" not in r.text


async def test_fr45_unhandled_exception_is_500_internal_error(client: httpx.AsyncClient) -> None:
    r = await client.get("/_t/boom")
    assert r.status_code == 500
    assert r.json() == {"detail": "Внутренняя ошибка", "code": "internal_error"}


async def test_fr45_500_body_has_no_traceback_or_exception_text(client: httpx.AsyncClient) -> None:
    r = await client.get("/_t/boom")
    assert r.status_code == 500
    for needle in (BOOM_TEXT, "Traceback", "RuntimeError", ".py", 'File "'):
        assert needle not in r.text


@pytest.mark.parametrize(
    ("path", "status", "code", "detail"),
    [
        ("/_t/not-found", 404, "not_found", "Объект не найден"),
        ("/_t/not-found-code", 404, "user_not_found", "Пользователь не найден"),
        ("/_t/pwd-change", 403, "password_change_required", "Смените пароль"),
        ("/_t/archived", 409, "project_archived", "Проект в архиве"),
        ("/_t/too-large", 413, "attachment_too_large", "Файл слишком большой"),
        ("/_t/unprocessable", 422, "login_taken", "Логин занят"),
        ("/_t/unauth", 401, "not_authenticated", "Нужен вход"),
    ],
)
async def test_fr45_app_error_status_code_and_detail(
    client: httpx.AsyncClient, path: str, status: int, code: str, detail: str
) -> None:
    r = await client.get(path)
    assert r.status_code == status
    assert r.json() == {"detail": detail, "code": code}


# --- FR-57: 422 не возвращает введённое -------------------------------------------------


async def test_fr57_validation_response_has_no_input_ctx_url(client: httpx.AsyncClient) -> None:
    r = await client.post("/_t/login", json={"login": "ab", "password": SECRET_VALUE})
    assert r.status_code == 422
    body = r.json()
    for item in body["detail"]:
        assert "input" not in item
        assert "ctx" not in item
        assert "url" not in item
    # min_length даёт ctx в стандартном ответе Pydantic: значит, обработчик его удалил
    assert '"ctx"' not in r.text
    assert '"input"' not in r.text
    assert '"url"' not in r.text


async def test_fr57_validation_response_does_not_echo_password(client: httpx.AsyncClient) -> None:
    r = await client.post("/_t/login", json={"login": "ab", "password": SECRET_VALUE})
    assert r.status_code == 422
    assert SECRET_VALUE not in r.text
    assert "hunter2" not in r.text


async def test_fr57_validation_response_does_not_echo_non_dict_body(
    client: httpx.AsyncClient,
) -> None:
    r = await client.post("/_t/login", content=SECRET_VALUE, headers={"content-type": "text/plain"})
    assert r.status_code == 422
    assert SECRET_VALUE not in r.text
    _assert_error_shape(r.json(), "validation_error")


async def test_t68_broken_json_is_400_bad_request_without_echo(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/_t/login",
        content=('{"login": "abcd", "password": "' + SECRET_VALUE).encode(),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json() == {"detail": "Некорректный JSON в теле запроса", "code": "bad_request"}
    assert SECRET_VALUE not in r.text
    assert "abcd" not in r.text


async def test_t68_valid_json_with_wrong_fields_stays_422(client: httpx.AsyncClient) -> None:
    r = await client.post("/_t/login", json={"login": "ab"})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


# --- FR-7 / D-32 -------------------------------------------------------------------------


async def test_fr7_health_is_public(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_d32_docs_disabled_by_default(path: str) -> None:
    application = _make_app(expose_api_docs=False)
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(path)
    assert r.status_code == 404
    _assert_error_shape(r.json(), "not_found")


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_d32_docs_enabled_when_expose_api_docs(path: str) -> None:
    application = _make_app(expose_api_docs=True)
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(path)
    assert r.status_code == 200


async def test_d32_openapi_operation_id_equals_function_name() -> None:
    application = _make_app(expose_api_docs=True)
    _add_test_routes(application)
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert paths["/api/v1/health"]["get"]["operationId"] == "health"
    assert paths["/_t/clock"]["get"]["operationId"] == "clock_now"
    assert paths["/_t/login"]["post"]["operationId"] == "post_login"


def test_t04_debug_is_off() -> None:
    assert _make_app().debug is False
    assert _make_app(env="local", expose_api_docs=True).debug is False


# --- Часы и фабрика ----------------------------------------------------------------------


async def test_t04_clock_from_factory_is_active_inside_request() -> None:
    clock = FixedClock(FIXED_AT)
    application = _make_app(clock=clock)
    _add_test_routes(application)
    assert application.state.clock is clock
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/_t/clock")
    assert r.status_code == 200
    assert datetime.fromisoformat(r.json()["now"]) == FIXED_AT


async def test_t04_replacing_state_clock_takes_effect_on_next_request(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.clock = FixedClock(FIXED_AT)
    first = await client.get("/_t/clock")
    assert datetime.fromisoformat(first.json()["now"]) == FIXED_AT
    later = datetime(2032, 1, 1, tzinfo=UTC)
    app.state.clock = FixedClock(later)
    second = await client.get("/_t/clock")
    assert datetime.fromisoformat(second.json()["now"]) == later


async def test_t04_default_clock_is_system_clock(app: FastAPI, client: httpx.AsyncClient) -> None:
    assert isinstance(app.state.clock, SystemClock)
    before = datetime.now(UTC)
    r = await client.get("/_t/clock")
    after = datetime.now(UTC)
    assert before <= datetime.fromisoformat(r.json()["now"]) <= after


async def test_t04_clock_does_not_leak_outside_request() -> None:
    application = _make_app(clock=FixedClock(FIXED_AT))
    _add_test_routes(application)
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.get("/_t/clock")
    assert utcnow() != FIXED_AT


def test_t04_create_app_returns_independent_fastapi_instances() -> None:
    a = _make_app()
    b = _make_app()
    assert isinstance(a, FastAPI)
    assert a is not b


def test_t04_create_app_does_not_open_network_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("create_app не должен открывать сетевые соединения")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)
    application = _make_app(database_url="postgresql+asyncpg://u:p@127.0.0.1:1/none")
    assert isinstance(application, FastAPI)


def test_t04_module_level_app_exists() -> None:
    from app.main import app as module_app

    assert isinstance(module_app, FastAPI)
    assert module_app.debug is False


def test_t04_import_main_does_not_open_network_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    import app.main

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("импорт app.main не должен открывать сетевые соединения")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)
    importlib.reload(app.main)


# --- Иерархия ошибок (plan §4.2) ----------------------------------------------------------


def test_t04_error_hierarchy_status_and_codes() -> None:
    from app.core import errors

    expected = {
        errors.NotAuthenticated: (401, "not_authenticated"),
        errors.InvalidCredentials: (401, "invalid_credentials"),
        errors.Forbidden: (403, "forbidden"),
        errors.PasswordChangeRequired: (403, "password_change_required"),
        errors.NoRole: (403, "no_role"),
        errors.OriginMismatch: (403, "origin_mismatch"),
        errors.NotFound: (404, "not_found"),
        errors.ProjectArchived: (409, "project_archived"),
        errors.PayloadTooLarge: (413, "attachment_too_large"),
    }
    for cls, (status, code) in expected.items():
        assert issubclass(cls, errors.AppError)
        assert cls.status_code == status, cls
        assert cls.code == code, cls
    assert issubclass(errors.PasswordChangeRequired, errors.Forbidden)
    assert issubclass(errors.NoRole, errors.Forbidden)
    assert issubclass(errors.OriginMismatch, errors.Forbidden)
    assert issubclass(errors.AppError, Exception)
    assert errors.Unprocessable.status_code == 422


def test_t04_error_code_is_str_enum_with_catalog() -> None:
    from enum import StrEnum

    from app.core.errors import ErrorCode

    assert issubclass(ErrorCode, StrEnum)
    names = {
        "validation_error",
        "password_too_short",
        "password_too_common",
        "password_reused",
        "invalid_current_password",
        "login_invalid",
        "login_taken",
        "last_account_admin",
        "user_not_found",
        "user_blocked",
        "recipient_wrong_role",
        "not_project_member",
        "owner_cannot_be_removed",
        "subtask_depth_exceeded",
        "label_not_found",
        "too_many_labels",
        "label_name_taken",
        "too_many_attachments",
        "attachment_type_not_allowed",
        "parent_task_deleted",
        "project_deleted",
        "invalid_neighbors",
        "inn_taken",
        "contacts_attached",
        "contact_wrong_account",
        "stage_archived",
        "stage_has_deals",
        "pipeline_invariant",
        "stage_name_taken",
        "deal_already_linked",
        "project_already_linked",
        "project_linked_to_deleted_deal",
        "account_has_deals",
        "account_deleted",
        "permanent_delete_not_allowed",
        "search_query_too_short",
        "due_date_in_past",  # 006/D-5, plan PD-9
    }
    for name in names:
        assert ErrorCode[name].value == name
        assert ErrorCode(name) == name


def test_t04_app_error_code_override_and_detail() -> None:
    from app.core.errors import NotFound

    err = NotFound("текст", code="user_not_found")
    assert err.code == "user_not_found"
    assert err.status_code == 404
    assert NotFound.code == "not_found"  # переопределение не меняет класс
    assert NotFound("x").code == "not_found"
