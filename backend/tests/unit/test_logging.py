"""T09: логирование без секретов (FR-57, FR-51, D-31, plan §4.2).

Контракт:
- ``app.core.logging.configure_logging(level)``: JSON-строки (одна запись = одна строка) в stdout;
- фильтр заменяет значения ключей ``(?i)password|secret|token|cookie|authorization`` на ``"***"``
  в ``extra`` и dict-аргументах (в том числе вложенных); форматтер чистит текст исключений;
- чистый ASGI access-лог: метод, путь без query, статус, длительность, user_id;
- ``uvicorn.access`` отключён, дубль трассировки через ``uvicorn.error`` подавлен.

Имена полей записи допускают типовые варианты (см. ``_pick``), значения проверяются строго.
stdout перехватывается ``capsys``; ``configure_logging`` вызывается уже под перехватом.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from app.core.config import Settings

# Значения живут в константах модуля: строки исходников в трассировке не содержат литералов.
LOCAL_VALUE = "LOCALVALUE-9f3c1a"
ARG_VALUE = "ARGVALUE-77d2be"
UNICODE_PASSWORD = "pw-\udcff-" + "TOPSECRETVALUE42"
BOOM_MARKER = "boom-marker-4f81c"

_TIME_KEYS = ("timestamp", "time", "ts", "asctime")
_LEVEL_KEYS = ("level", "levelname", "severity")
_LOGGER_KEYS = ("logger", "name", "logger_name")
_MESSAGE_KEYS = ("message", "msg")
_STATUS_KEYS = ("status", "status_code")

_RESTORED_LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "app", "app.errors")


# --------------------------------------------------------------------------- инфраструктура


def _snapshot(name: str) -> dict[str, Any]:
    lg = logging.getLogger(name)
    return {
        "handlers": list(lg.handlers),
        "filters": list(lg.filters),
        "level": lg.level,
        "propagate": lg.propagate,
        "disabled": lg.disabled,
    }


def _restore(name: str, snap: dict[str, Any]) -> None:
    lg = logging.getLogger(name)
    for h in list(lg.handlers):
        if h not in snap["handlers"]:
            lg.removeHandler(h)
    for h in snap["handlers"]:
        if h not in lg.handlers:
            lg.addHandler(h)
    for f in list(lg.filters):
        if f not in snap["filters"]:
            lg.removeFilter(f)
    lg.setLevel(snap["level"])
    lg.propagate = snap["propagate"]
    lg.disabled = snap["disabled"]


@pytest.fixture(autouse=True)
def _isolated_logging() -> Iterator[None]:
    snaps = {name: _snapshot(name) for name in _RESTORED_LOGGERS}
    try:
        yield
    finally:
        for name, snap in snaps.items():
            _restore(name, snap)


class LogReader:
    """Накопительно читает JSON-записи из stdout (``capsys``)."""

    def __init__(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._capsys = capsys
        self.raw = ""

    def lines(self) -> list[str]:
        self.raw += self._capsys.readouterr().out
        return [ln for ln in self.raw.splitlines() if ln.strip()]

    def records(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ln in self.lines():
            try:
                rec = json.loads(ln)
            except ValueError as exc:  # каждая строка stdout обязана быть JSON
                pytest.fail(f"строка stdout не JSON: {ln[:200]!r} ({exc})")
            assert isinstance(rec, dict), ln
            out.append(rec)
        return out

    def text(self) -> str:
        self.lines()
        return self.raw


@pytest.fixture
def logs(capsys: pytest.CaptureFixture[str]) -> LogReader:
    from app.core.logging import configure_logging

    configure_logging("DEBUG")
    reader = LogReader(capsys)
    reader.lines()  # сбросить возможный вывод самой настройки
    reader.raw = ""
    return reader


def _pick(rec: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in rec:
            return rec[k]
    pytest.fail(f"в записи нет ни одного из полей {keys}: {sorted(rec)}")


def _by_logger(recs: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [r for r in recs if _pick(r, _LOGGER_KEYS) == name]


def _access_records(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in recs if "method" in r and "path" in r]


def _make_app() -> FastAPI:
    from app.main import create_app

    app: FastAPI = create_app(Settings(env="test", cookie_secure=False, expose_api_docs=False))
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def app_client() -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = _make_app()

    async def boom() -> None:
        raise RuntimeError(BOOM_MARKER)

    async def echo(request: Request) -> dict[str, str]:
        await request.body()
        request.state.user_id = "user-id-7c1e"
        return {"ok": "1"}

    app.add_api_route("/_t/boom", boom, methods=["GET"])
    app.add_api_route("/_t/echo", echo, methods=["POST"])
    async with _client(app) as client:
        yield app, client


# --------------------------------------------------------------------------- формат записей


def test_every_record_is_valid_json_with_required_fields(logs: LogReader) -> None:
    """FR-57/D-31: JSON-строка со временем (UTC ISO 8601), уровнем, логгером, сообщением."""
    before = datetime.now(UTC) - timedelta(seconds=5)
    logging.getLogger("tests.fmt").warning("hello %s", "world")
    logging.getLogger("tests.fmt").info("second")

    recs = logs.records()
    mine = _by_logger(recs, "tests.fmt")
    assert [_pick(r, _MESSAGE_KEYS) for r in mine] == ["hello world", "second"]
    assert str(_pick(mine[0], _LEVEL_KEYS)).upper() == "WARNING"
    assert str(_pick(mine[1], _LEVEL_KEYS)).upper() == "INFO"
    for r in mine:
        ts = datetime.fromisoformat(str(_pick(r, _TIME_KEYS)))
        assert ts.tzinfo is not None and ts.utcoffset() == timedelta(0)
        assert before <= ts <= datetime.now(UTC) + timedelta(seconds=5)


def test_cyrillic_message_roundtrips_and_multiline_stays_one_line(logs: LogReader) -> None:
    """Кириллица не портится; многострочное сообщение остаётся одной физической строкой."""
    text = "Привет, мир: проект «Ёлка»\nвторая строка"
    logging.getLogger("tests.cyr").info(text)

    lines = logs.lines()
    mine = [ln for ln in lines if "tests.cyr" in ln]
    assert len(mine) == 1
    rec = json.loads(mine[0])
    assert _pick(rec, _MESSAGE_KEYS) == text


def test_configure_logging_respects_level(logs: LogReader) -> None:
    from app.core.logging import configure_logging

    configure_logging("WARNING")
    logging.getLogger("tests.lvl").info("quiet-info")
    logging.getLogger("tests.lvl").warning("loud-warning")

    msgs = [_pick(r, _MESSAGE_KEYS) for r in _by_logger(logs.records(), "tests.lvl")]
    assert msgs == ["loud-warning"]


# --------------------------------------------------------------------------- маскирование


def test_extra_secret_keys_are_masked(logs: LogReader) -> None:
    """FR-57: значения ключей password/secret/token/cookie/authorization в extra -> ***."""
    logging.getLogger("tests.extra").info(
        "event",
        extra={
            "password": "pw-VALUE-aaa1",
            "new_password": "pw-VALUE-aaa2",
            "client_secret": "sec-VALUE-bbb1",
            "access_token": "tok-VALUE-ccc1",
            "Set-Cookie": "cook-VALUE-ddd1",
            "Authorization": "Bearer auth-VALUE-eee1",
            "PASSWORD": "pw-VALUE-aaa3",
            "login": "alice-visible",
        },
    )
    text = logs.text()
    for leaked in ("aaa1", "aaa2", "aaa3", "bbb1", "ccc1", "ddd1", "eee1"):
        assert leaked not in text
    assert "***" in text
    assert "alice-visible" in text  # не секретные поля не затираются
    json.loads(text.strip().splitlines()[-1])


def test_dict_args_masked_and_not_leaked_into_message(logs: LogReader) -> None:
    """FR-57: logger.info("x %s", {...}) — значение не попадает в message."""
    logging.getLogger("tests.dictarg").info(
        "payload %s", {"password": "pw-DICTARG-1", "name": "visible-name"}
    )
    logging.getLogger("tests.dictarg").info(
        "%s / %s", "first", {"Token": "tok-DICTARG-2", "other": "visible-other"}
    )

    recs = _by_logger(logs.records(), "tests.dictarg")
    assert len(recs) == 2
    blob = json.dumps(recs, ensure_ascii=False)
    assert "DICTARG" not in blob
    assert "***" in str(_pick(recs[0], _MESSAGE_KEYS))
    assert "visible-name" in str(_pick(recs[0], _MESSAGE_KEYS))
    assert "***" in str(_pick(recs[1], _MESSAGE_KEYS))
    assert "visible-other" in str(_pick(recs[1], _MESSAGE_KEYS))


def test_nested_dict_and_list_values_masked(logs: LogReader) -> None:
    payload = {
        "user": {"login": "bob-visible", "password": "pw-NESTED-1"},
        "items": [{"api_token": "tok-NESTED-2"}, {"keep": "kept-value"}, "plain-string"],
        "deep": [[{"cookie": "cook-NESTED-3"}]],
        1: "int-key-ok",
    }
    logging.getLogger("tests.nested").info("data %s", payload, extra={"ctx": payload})

    text = logs.text()
    assert "NESTED" not in text
    for visible in ("bob-visible", "kept-value", "plain-string"):
        assert visible in text
    recs = _by_logger(logs.records(), "tests.nested")
    assert len(recs) == 1


def test_masking_does_not_mutate_caller_objects(logs: LogReader) -> None:
    payload = {"password": "pw-MUTATE-1", "nested": {"token": "tok-MUTATE-2"}}
    logging.getLogger("tests.mut").info("x %s", payload, extra={"ctx": payload})
    logs.records()
    assert payload == {"password": "pw-MUTATE-1", "nested": {"token": "tok-MUTATE-2"}}


# --------------------------------------------------------------------------- исключения


def test_exception_text_with_password_is_redacted(logs: LogReader) -> None:
    """FR-57 (ревью T04): RuntimeError("password=...") не попадает в лог как есть."""
    try:
        raise RuntimeError("login failed: password=hunter2xyz for user alice")
    except RuntimeError:
        logging.getLogger("tests.exc").exception("operation failed")

    text = logs.text()
    assert "hunter2xyz" not in text
    assert "RuntimeError" in text
    assert "Traceback" in text
    assert "alice" in text  # маскируется значение, а не вся запись
    assert len([ln for ln in text.splitlines() if ln.strip()]) == 1


def test_exception_text_with_token_and_cookie_is_redacted(logs: LogReader) -> None:
    try:
        raise ValueError("bad token=tok-EXC-9a8b and cookie: sess-EXC-7c6d; secret=sec-EXC-5e4f")
    except ValueError as exc:
        logging.getLogger("tests.exc2").error("failed", exc_info=exc)

    text = logs.text()
    for leaked in ("tok-EXC-9a8b", "sess-EXC-7c6d", "sec-EXC-5e4f"):
        assert leaked not in text
    assert "ValueError" in text


def test_exception_text_with_authorization_bearer_is_redacted(logs: LogReader) -> None:
    """Authorization: Bearer <tok> — токен не должен остаться после схемы."""
    try:
        raise ValueError("upstream said Authorization: Bearer tok-BEARER-1a2b3c")
    except ValueError:
        logging.getLogger("tests.exc3").exception("failed")

    assert "tok-BEARER-1a2b3c" not in logs.text()


def test_exception_message_also_redacted_when_exception_chained(logs: LogReader) -> None:
    """Цепочка исключений (__cause__/__context__) тоже чистится."""
    try:
        try:
            raise KeyError("password=inner-CHAIN-77")
        except KeyError as inner:
            raise RuntimeError("wrapper failure") from inner
    except RuntimeError:
        logging.getLogger("tests.chain").exception("chained")

    text = logs.text()
    assert "inner-CHAIN-77" not in text
    assert "wrapper failure" in text


def _inner_with_locals(pwd_arg: str) -> None:
    local_secret = LOCAL_VALUE
    assert local_secret
    raise RuntimeError("neutral failure")


def test_traceback_has_no_locals_or_argument_values(logs: LogReader) -> None:
    """Ревью T08: f_locals и значения аргументов не выводятся (нет show_locals)."""
    try:
        _inner_with_locals(ARG_VALUE)
    except RuntimeError:
        logging.getLogger("tests.locals").exception("failed")

    text = logs.text()
    assert LOCAL_VALUE not in text
    assert ARG_VALUE not in text
    assert "neutral failure" in text
    assert "_inner_with_locals" in text  # трассировка на месте


def _encode_password() -> bytes:
    return UNICODE_PASSWORD.encode("utf-8")


def test_unicode_error_args_do_not_leak_password(logs: LogReader) -> None:
    """Ревью T08: у UnicodeEncodeError args[1] — исходная строка (пароль); в лог не попадает."""
    try:
        _encode_password()
    except UnicodeEncodeError as exc:
        assert UNICODE_PASSWORD in exc.args  # предпосылка теста
        logging.getLogger("tests.unicode").exception("encode failed")
        logging.getLogger("tests.unicode").error("encode failed again", exc_info=exc)

    text = logs.text()
    assert "TOPSECRETVALUE42" not in text
    assert "UnicodeEncodeError" in text
    for ln in text.splitlines():
        json.loads(ln)


def test_unicode_error_repr_in_message_args_does_not_leak_password(logs: LogReader) -> None:
    """Ревью T08: repr(UnicodeError) содержит args[1]; форматирование %r/%s его не выдаёт."""
    try:
        _encode_password()
    except UnicodeEncodeError as exc:
        logging.getLogger("tests.unicode2").error("failed: %r / %s", exc, exc)

    assert "TOPSECRETVALUE42" not in logs.text()


# --------------------------------------------------------------------------- 500 и дубли


async def test_unhandled_500_logs_exactly_one_traceback_record(
    logs: LogReader, app_client: tuple[FastAPI, httpx.AsyncClient]
) -> None:
    """Ревью T04: одна необработанная ошибка -> одна запись с трассировкой."""
    _, client = app_client
    r = await client.get("/_t/boom")

    assert r.status_code == 500
    assert BOOM_MARKER not in r.text
    recs = logs.records()
    with_marker = [r_ for r_ in recs if BOOM_MARKER in json.dumps(r_, ensure_ascii=False)]
    assert len(with_marker) == 1, [_pick(r_, _LOGGER_KEYS) for r_ in with_marker]
    only = with_marker[0]
    assert _pick(only, _LOGGER_KEYS) == "app.errors"
    assert str(_pick(only, _LEVEL_KEYS)).upper() == "ERROR"
    assert "Traceback" in json.dumps(only, ensure_ascii=False)
    assert "boom" in json.dumps(only, ensure_ascii=False)


def test_uvicorn_error_traceback_duplicate_is_suppressed(logs: LogReader) -> None:
    """Дубль «Exception in ASGI application» от uvicorn.error не доходит до stdout."""
    try:
        raise RuntimeError("dup-trace-marker-2d9")
    except RuntimeError as exc:
        logging.getLogger("uvicorn.error").error("Exception in ASGI application", exc_info=exc)
    logging.getLogger("uvicorn.error").info("Started server process [1]")

    text = logs.text()
    assert "dup-trace-marker-2d9" not in text
    assert "Exception in ASGI application" not in text
    # обычные сообщения uvicorn.error сохраняются
    assert "Started server process [1]" in text


def test_uvicorn_access_logger_is_disabled(logs: LogReader) -> None:
    """D-31: uvicorn.access отключён (свой access-лог)."""
    lg = logging.getLogger("uvicorn.access")
    lg.info('127.0.0.1:1 - "GET /uvicorn-access-marker HTTP/1.1" 200')
    lg.warning("uvicorn-access-warning-marker")

    text = logs.text()
    assert "uvicorn-access-marker" not in text
    assert "uvicorn-access-warning-marker" not in text


# --------------------------------------------------------------------------- access-лог


async def test_access_log_has_method_path_status_duration(
    logs: LogReader, app_client: tuple[FastAPI, httpx.AsyncClient]
) -> None:
    _, client = app_client
    r = await client.get("/api/v1/no-such-route-for-access-log")
    assert r.status_code == 404

    path = "/api/v1/no-such-route-for-access-log"
    recs = [x for x in _access_records(logs.records()) if x["path"] == path]
    assert len(recs) == 1  # не-health запрос логируется ровно один раз
    rec = recs[0]
    assert rec["method"] == "GET"
    assert _pick(rec, _STATUS_KEYS) == 404
    duration_keys = [k for k in rec if k.startswith("duration")]
    assert duration_keys, sorted(rec)
    duration = rec[duration_keys[0]]
    assert isinstance(duration, int | float) and 0 <= duration < 60_000
    assert str(_pick(rec, _LEVEL_KEYS)).upper() == "INFO"
    assert "user_id" not in rec or rec["user_id"] in (None, "")


async def test_access_log_strips_query_string(
    logs: LogReader, app_client: tuple[FastAPI, httpx.AsyncClient]
) -> None:
    """FR-57: query (там может быть пароль) не попадает в лог."""
    _, client = app_client
    await client.get(
        "/api/v1/no-such-route-for-access-log?password=QUERYPASSWORDVAL&token=QUERYTOKENVAL"
    )

    recs = _access_records(logs.records())
    assert [x["path"] for x in recs] == ["/api/v1/no-such-route-for-access-log"]
    text = logs.text()
    assert "QUERYPASSWORDVAL" not in text
    assert "QUERYTOKENVAL" not in text


async def test_access_log_has_no_headers_or_bodies(
    logs: LogReader, app_client: tuple[FastAPI, httpx.AsyncClient]
) -> None:
    _, client = app_client
    r = await client.post(
        "/_t/echo",
        json={"login": "carol", "password": "BODYPASSWORDVAL"},
        headers={
            "Authorization": "Bearer AUTHTOKENVALUE",
            "Cookie": "gt_session=COOKIESESSIONVAL",
        },
    )
    assert r.status_code == 200

    recs = [x for x in _access_records(logs.records()) if x["path"] == "/_t/echo"]
    assert len(recs) == 1
    assert recs[0]["method"] == "POST"
    text = logs.text()
    for leaked in ("BODYPASSWORDVAL", "AUTHTOKENVALUE", "COOKIESESSIONVAL"):
        assert leaked not in text


async def test_access_log_includes_user_id_from_request_state(
    logs: LogReader, app_client: tuple[FastAPI, httpx.AsyncClient]
) -> None:
    _, client = app_client
    await client.post("/_t/echo", json={})

    recs = [x for x in _access_records(logs.records()) if x["path"] == "/_t/echo"]
    assert len(recs) == 1
    assert recs[0]["user_id"] == "user-id-7c1e"


async def test_access_log_records_500_status(
    logs: LogReader, app_client: tuple[FastAPI, httpx.AsyncClient]
) -> None:
    _, client = app_client
    r = await client.get("/_t/boom?password=BOOMQUERYVAL")
    assert r.status_code == 500

    recs = [x for x in _access_records(logs.records()) if x["path"] == "/_t/boom"]
    assert len(recs) == 1
    assert _pick(recs[0], _STATUS_KEYS) == 500
    assert "Traceback" not in json.dumps(recs[0], ensure_ascii=False)
    assert "BOOMQUERYVAL" not in logs.text()


# --------------------------------------------------------------------------- идемпотентность


def test_configure_logging_is_idempotent(logs: LogReader) -> None:
    """Повторный вызов не плодит обработчики: одна запись = одна строка."""
    from app.core.logging import configure_logging

    root = logging.getLogger()
    handlers_after_first = list(root.handlers)
    configure_logging("DEBUG")
    configure_logging("DEBUG")
    assert len(root.handlers) == len(handlers_after_first)

    logging.getLogger("tests.idem").info("only-once-marker")
    lines = [ln for ln in logs.lines() if "only-once-marker" in ln]
    assert len(lines) == 1


def test_configure_logging_keeps_foreign_handlers_and_caplog(
    caplog: pytest.LogCaptureFixture, logs: LogReader
) -> None:
    """Повторная настройка не снимает чужие обработчики (caplog, pytest)."""
    from app.core.logging import configure_logging

    foreign = logging.Handler()
    foreign.emit = lambda record: None  # type: ignore[method-assign]
    logging.getLogger().addHandler(foreign)
    try:
        configure_logging("INFO")
        configure_logging("INFO")
        assert foreign in logging.getLogger().handlers
        caplog.set_level(logging.INFO)
        logging.getLogger("tests.caplog").info("caplog-still-works")
        assert "caplog-still-works" in caplog.text
    finally:
        logging.getLogger().removeHandler(foreign)


def test_configure_logging_writes_to_current_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-51: вывод в stdout (для драйвера Docker), не в stderr."""
    from app.core.logging import configure_logging

    configure_logging("INFO")
    capsys.readouterr()
    logging.getLogger("tests.stdout").info("to-stdout-marker")
    captured = capsys.readouterr()
    assert "to-stdout-marker" in captured.out
    assert "to-stdout-marker" not in captured.err


# --- ревью T09-1: производительность ---


_PERF_LIMIT_S = 1.0  # линейный код укладывается в миллисекунды; квадратичный — секунды


@pytest.mark.parametrize(
    "text",
    [
        "token." * 10000,
        "password" * 12500,
        "token=" * 10000,
        "password: " * 6500,
        "cookie=a;" * 7000,
        "a.token:" * 8000,
    ],
    ids=["token-dots", "password-run", "token-eq", "password-colon", "cookie-semicolons", "mixed"],
)
def test_redact_text_is_linear_on_adversarial_input(text: str) -> None:
    """Ревью T09-1: ~64 КБ повторов ключей не вызывают квадратичный бэктрекинг."""
    import time

    from app.core.logging import redact_text

    started = time.perf_counter()
    redact_text(text)
    elapsed = time.perf_counter() - started
    assert elapsed < _PERF_LIMIT_S, f"redact_text занял {elapsed:.2f} с"


async def test_long_path_request_is_fast_and_does_not_block_health(
    logs: LogReader, app_client: tuple[FastAPI, httpx.AsyncClient]
) -> None:
    """Путь ~60 КБ обрабатывается быстро; параллельный health не ждёт."""
    import asyncio
    import time

    _, client = app_client
    long_path = "/" + "token." * 10000

    started = time.perf_counter()
    long_resp, health = await asyncio.gather(client.get(long_path), client.get("/api/v1/health"))
    elapsed = time.perf_counter() - started
    assert health.status_code == 200
    assert long_resp.status_code == 404
    assert elapsed < _PERF_LIMIT_S, f"запросы заняли {elapsed:.2f} с"
    assert len(logs.records()) >= 2


# --- ревью T09-1: значения ---


def test_escaped_quotes_in_json_text_do_not_leave_value_tail(logs: LogReader) -> None:
    """JSON-текст с экранированной кавычкой в пароле заменяется целиком."""
    payload = json.dumps({"password": 'ab"S3cr', "user": "dave-visible"})
    logging.getLogger("tests.esc").info(payload)
    try:
        raise ValueError(payload)
    except ValueError:
        logging.getLogger("tests.esc").exception("failed")

    for rec in logs.records():
        blob = json.dumps(rec, ensure_ascii=False)
        assert "S3cr" not in blob
    assert "dave-visible" in logs.text()


def test_escaped_quotes_in_python_repr_do_not_leave_value_tail(logs: LogReader) -> None:
    """repr словаря с ``\\'`` и ``"`` внутри значения заменяется целиком."""
    payload = repr({"password": "a'b\"c", "user": "erin-visible"})
    logging.getLogger("tests.esc2").info(payload)
    try:
        raise ValueError(payload)
    except ValueError:
        logging.getLogger("tests.esc2").exception("failed")

    for rec in logs.records():
        decoded = json.dumps(rec, ensure_ascii=False)
        assert 'b"c' not in decoded
        assert 'b\\"c' not in decoded
        assert "b\\'c" not in decoded
    assert "erin-visible" in logs.text()


def test_pydantic_validation_error_does_not_leak_input_value(logs: LogReader) -> None:
    """ValidationError печатает input_value='...' — пароль не попадает в лог."""
    from pydantic import BaseModel, Field, ValidationError

    class Creds(BaseModel):
        password: str = Field(max_length=5)

    try:
        Creds(password="S3cr3tPW!x")
    except ValidationError as exc:
        assert "S3cr3tPW" in str(exc)  # предпосылка теста
        logging.getLogger("tests.pyd").exception("validation failed")
        logging.getLogger("tests.pyd").error("failed: %s", exc)
        logging.getLogger("tests.pyd").error("failed", exc_info=exc)

    text = logs.text()
    assert "S3cr3tPW" not in text
    assert "ValidationError" in text


def test_dsn_password_is_masked_in_message_and_settings_repr(logs: LogReader) -> None:
    dsn = "postgresql+asyncpg://tracker:S3cretPw@db:5432/tracker"
    masked = "postgresql+asyncpg://tracker:***@db:5432/tracker"
    logging.getLogger("tests.dsn").info("connecting to %s", dsn)
    logging.getLogger("tests.dsn").info("settings %r", Settings(env="test", database_url=dsn))
    try:
        raise ConnectionError(f"cannot connect to {dsn}")
    except ConnectionError:
        logging.getLogger("tests.dsn").exception("db down")

    recs = _by_logger(logs.records(), "tests.dsn")
    assert len(recs) == 3
    assert "S3cretPw" not in json.dumps(recs, ensure_ascii=False)
    assert masked in str(_pick(recs[0], _MESSAGE_KEYS))
    assert masked in str(_pick(recs[1], _MESSAGE_KEYS))
    assert "tracker:***@db" in json.dumps(recs[2], ensure_ascii=False)


# --- ревью T09-1: прочее ---


def test_uvicorn_error_with_exc_info_other_message_passes_through(logs: LogReader) -> None:
    """Подавляется только дубль «Exception in ASGI application»."""
    try:
        raise RuntimeError("uvicorn-other-failure-5b2")
    except RuntimeError as exc:
        logging.getLogger("uvicorn.error").error("Exception in ASGI application", exc_info=exc)
        logging.getLogger("uvicorn.error").error("Lifespan failed", exc_info=exc)

    recs = _by_logger(logs.records(), "uvicorn.error")
    assert [_pick(r, _MESSAGE_KEYS) for r in recs] == ["Lifespan failed"]
    assert "uvicorn-other-failure-5b2" in json.dumps(recs[0], ensure_ascii=False)


def test_color_message_extra_is_not_in_json(logs: LogReader) -> None:
    """uvicorn кладёт в extra ``color_message`` с ANSI-кодами; в JSON его нет."""
    logging.getLogger("uvicorn.error").info(
        "Started server", extra={"color_message": "\x1b[32mStarted server\x1b[0m"}
    )

    recs = _by_logger(logs.records(), "uvicorn.error")
    assert len(recs) == 1
    assert "color_message" not in recs[0]
    assert "\x1b" not in json.dumps(recs[0])


def test_tuple_pairs_in_extra_are_masked(logs: LogReader) -> None:
    """Список пар (ключ, значение), в т.ч. bytes (сырые заголовки ASGI), маскируется."""
    logging.getLogger("tests.pairs").info(
        "pairs",
        extra={
            "pairs": [("password", "x-PAIRVAL1"), ("login", "frank-visible")],
            "raw": [(b"cookie", b"sid=PAIRVAL2"), (b"authorization", b"Bearer PAIRVAL3")],
        },
    )

    text = logs.text()
    assert "PAIRVAL" not in text
    assert "frank-visible" in text


# --- ревью T09-2: namedtuple/URL, сбой записи, разделители ---


def test_sqlalchemy_url_in_args_does_not_leak_password(logs: LogReader) -> None:
    """engine.url — NamedTuple: str() его маскирует, поэлементная очистка — нет."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("postgresql+asyncpg://tracker:DBPASS123@db:5432/tracker")
    logging.getLogger("tests.url").info("db url %s", engine.url)
    logging.getLogger("tests.url").info("db url %r", engine.url)

    recs = _by_logger(logs.records(), "tests.url")
    assert len(recs) == 2
    assert "DBPASS123" not in json.dumps(recs, ensure_ascii=False)


def test_sqlalchemy_url_in_extra_does_not_leak_password(logs: LogReader) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("postgresql+asyncpg://tracker:DBPASS123@db:5432/tracker")
    logging.getLogger("tests.url2").info("connect", extra={"url": engine.url})

    text = logs.text()
    assert "DBPASS123" not in text
    assert "tests.url2" in text


def test_custom_namedtuple_with_secret_field_is_masked(logs: LogReader) -> None:
    """Собственный namedtuple: поле ``password`` маскируется в args и в extra."""
    from collections import namedtuple

    Cred = namedtuple("Cred", "login password")  # noqa: N806
    cred = Cred("nt-visible-login", "NTPASS")
    logging.getLogger("tests.nt").info("cred %s", cred)
    logging.getLogger("tests.nt").info("cred %r", cred)
    logging.getLogger("tests.nt").info("cred", extra={"cred": cred})

    recs = _by_logger(logs.records(), "tests.nt")
    assert len(recs) == 3
    assert "NTPASS" not in json.dumps(recs, ensure_ascii=False)


def test_plain_tuple_and_set_secret_pairs_still_masked(logs: LogReader) -> None:
    logging.getLogger("tests.coll").info(
        "coll",
        extra={
            "as_tuple": (("password", "TUPVAL1"), ("login", "gina-visible")),
            "as_set": {("cookie", "SETVAL2")},
            "as_list": [["token", "LISTVAL3"]],
        },
    )

    text = logs.text()
    for leaked in ("TUPVAL1", "SETVAL2", "LISTVAL3"):
        assert leaked not in text
    assert "gina-visible" in text


class _BrokenStdout:
    encoding = "utf-8"

    def write(self, data: str) -> int:
        raise BrokenPipeError("stdout closed")

    def flush(self) -> None:
        raise BrokenPipeError("stdout closed")


def test_write_failure_does_not_leak_secrets_to_stderr(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сбой записи в stdout: logging.handleError не печатает сырые Message/Arguments."""
    from app.core.logging import configure_logging

    monkeypatch.setattr(logging, "raiseExceptions", True)
    monkeypatch.setattr(sys, "stdout", _BrokenStdout())
    configure_logging("INFO")
    capsys.readouterr()

    log = logging.getLogger("tests.broken")
    log.info("login failed %s", "password=HEPASS1")
    log.info(f"p=password={'HEPASS2'}")

    err = capsys.readouterr().err
    assert "HEPASS1" not in err
    assert "HEPASS2" not in err
    assert "Arguments:" not in err


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("password => S3cr3tAA", "S3cr3tAA"),
        ("password := S3cr3tBB", "S3cr3tBB"),
        ("password = S3cr3tCC", "S3cr3tCC"),
        ("token => S3cr3tDD", "S3cr3tDD"),
    ],
    ids=["fat-arrow", "walrus", "spaced-equals", "token-arrow"],
)
def test_alternative_separators_are_masked(logs: LogReader, text: str, leaked: str) -> None:
    logging.getLogger("tests.sep").info("event: " + text)
    try:
        raise ValueError(text)
    except ValueError:
        logging.getLogger("tests.sep").exception("failed")

    recs = _by_logger(logs.records(), "tests.sep")
    assert len(recs) == 2
    assert leaked not in json.dumps(recs, ensure_ascii=False)
    assert "event" in str(_pick(recs[0], _MESSAGE_KEYS))
