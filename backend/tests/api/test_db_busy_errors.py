"""T29: занятая блокировка БД (55P03) и взаимоблокировка (40P01) -> 503 ``service_busy`` (D-40).

Контракт (tasks.md T29, plan D-40, Q-1 решён владельцем): SQLSTATE ``55P03``/``40P01`` из
``DBAPIError.orig`` (или ``orig.__cause__``) -> 503, тело ``ErrorResponse`` с кодом
``service_busy`` и detail «Сервер занят…», заголовок ``Retry-After: 5``; лог — WARNING с
SQLSTATE без SQL и параметров; прочие ``DBAPIError`` — прежний 500 ``internal_error``;
транзакцию откатывает ``get_db``; 503 в OpenAPI не объявляется.

Реальные ошибки asyncpg: ``committed_api_env`` (соединение на запрос), временные маршруты на
временной таблице ``t29_rows`` (схема сбрасывается фикстурой ``committed``).

Нет ``from __future__ import annotations``: FastAPI разбирает аннотации локальных обработчиков.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import DbSession
from tests.conftest import ApiEnv

SECRET = "S3cret-Param-Value-T29-xyz"
TABLE = "t29_rows"
RETRY_AFTER = "5"
FORBIDDEN_FRAGMENTS = ("select", "update ", "insert", "for update", TABLE, SECRET, "sqlstate")
OPENAPI_JSON = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"


def _mount(app: FastAPI) -> None:
    barrier = asyncio.Barrier(2)

    async def lock(row_id: int, db: DbSession) -> Any:
        await db.execute(text("SET LOCAL lock_timeout = '50ms'"))
        await db.execute(text(f"SELECT id FROM {TABLE} WHERE id = :i FOR UPDATE"), {"i": row_id})
        return {"ok": True}

    async def lock_secret(db: DbSession) -> Any:
        await db.execute(text("SET LOCAL lock_timeout = '50ms'"))
        await db.execute(
            text(f"SELECT id FROM {TABLE} WHERE v = :secret FOR UPDATE"), {"secret": SECRET}
        )
        return {"ok": True}

    async def write_then_lock(db: DbSession) -> Any:
        await db.execute(text(f"INSERT INTO {TABLE} (id, v) VALUES (100, 'written')"))
        await db.execute(text("SET LOCAL lock_timeout = '50ms'"))
        await db.execute(text(f"SELECT id FROM {TABLE} WHERE id = 1 FOR UPDATE"))
        return {"ok": True}

    async def deadlock(first: int, second: int, db: DbSession) -> Any:
        await db.execute(text("SET LOCAL lock_timeout = '10s'"))
        await db.execute(text(f"SELECT id FROM {TABLE} WHERE id = :i FOR UPDATE"), {"i": first})
        await asyncio.wait_for(barrier.wait(), timeout=10)
        await db.execute(text(f"SELECT id FROM {TABLE} WHERE id = :i FOR UPDATE"), {"i": second})
        return {"ok": True}

    async def bad_sql(db: DbSession) -> Any:
        await db.execute(
            text("SELECT x FROM t29_no_such_table WHERE v = :secret"), {"secret": SECRET}
        )
        return {"ok": True}

    async def plain_write(db: DbSession) -> Any:
        await db.execute(text(f"INSERT INTO {TABLE} (id, v) VALUES (200, 'commit-stage')"))
        return {"ok": True}

    async def ping() -> Any:
        return {"ok": True}

    app.add_api_route("/_t/lock/{row_id}", lock, methods=["POST"])
    app.add_api_route("/_t/lock-secret", lock_secret, methods=["POST"])
    app.add_api_route("/_t/write-then-lock", write_then_lock, methods=["POST"])
    app.add_api_route("/_t/deadlock/{first}/{second}", deadlock, methods=["POST"])
    app.add_api_route("/_t/bad-sql", bad_sql, methods=["POST"])
    app.add_api_route("/_t/plain-write", plain_write, methods=["POST"])
    app.add_api_route("/_t/ping", ping, methods=["GET"])


async def _setup_table(env: ApiEnv) -> None:
    async with env.sessionmaker() as s:
        await s.execute(text(f"CREATE TABLE {TABLE} (id int PRIMARY KEY, v text NOT NULL)"))
        await s.execute(
            text(f"INSERT INTO {TABLE} (id, v) VALUES (1, 'a'), (2, 'b'), (3, :sec)"),
            {"sec": SECRET},
        )
        await s.commit()


async def _row_exists(env: ApiEnv, row_id: int) -> bool:
    async with env.sessionmaker() as s:
        res = await s.execute(text(f"SELECT 1 FROM {TABLE} WHERE id = :i"), {"i": row_id})
        return res.first() is not None


class _Holder:
    """Второе соединение: держит ``FOR UPDATE`` строк до ``release``."""

    def __init__(self, env: ApiEnv, ids: list[int]) -> None:
        self._env = env
        self._ids = ids
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "_Holder":
        self._session = self._env.sessionmaker()
        await self._session.begin()
        for i in self._ids:
            await self._session.execute(
                text(f"SELECT id FROM {TABLE} WHERE id = :i FOR UPDATE"), {"i": i}
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._session is not None
        await self._session.rollback()
        await self._session.close()


@pytest.fixture
async def env(committed_api_env: ApiEnv) -> AsyncIterator[ApiEnv]:
    """Окружение с клиентом, не пробрасывающим исключения приложения (как в test_errors)."""
    _mount(committed_api_env.app)
    await _setup_table(committed_api_env)
    transport = httpx.ASGITransport(app=committed_api_env.app, raise_app_exceptions=False)
    original = committed_api_env.client
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        committed_api_env.client = c
        yield committed_api_env
    committed_api_env.client = original


def _assert_service_busy(resp: httpx.Response) -> None:
    assert resp.status_code == 503, resp.text
    assert resp.headers.get("retry-after") == RETRY_AFTER
    body = resp.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == "service_busy"
    assert isinstance(body["detail"], str)
    assert body["detail"].startswith("Сервер занят")
    haystack = (resp.text + json.dumps(dict(resp.headers))).lower()
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment.lower() not in haystack, fragment


def _log_text(records: list[logging.LogRecord]) -> str:
    parts: list[str] = []
    for r in records:
        parts.append(r.getMessage())
        if r.exc_text:
            parts.append(r.exc_text)
        parts.append(repr(r.args))
    return "\n".join(parts)


# --- AC (1): 55P03 -------------------------------------------------------------------------


async def test_t29_lock_not_available_is_503_service_busy(env: ApiEnv) -> None:
    """D-40/FR-45/FR-57: 55P03 на занятой строке -> 503 service_busy, Retry-After: 5, без SQL."""
    async with _Holder(env, [1]):
        resp = await env.client.post("/_t/lock/1")
    _assert_service_busy(resp)


async def test_t29_service_alive_after_busy(env: ApiEnv) -> None:
    """D-40 (5): после 503 соединение вернулось в пул, следующий запрос работает."""
    async with _Holder(env, [1]):
        assert (await env.client.post("/_t/lock/1")).status_code == 503
    assert (await env.client.get("/_t/ping")).status_code == 200
    assert (await env.client.post("/_t/lock/1")).status_code == 200


# --- AC (2): 40P01 -------------------------------------------------------------------------


async def test_t29_deadlock_is_503_for_victim(
    env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """D-40: deadlock_detected (40P01) -> 503 service_busy у жертвы; победитель успешен."""
    caplog.set_level(logging.DEBUG)
    r1, r2 = await asyncio.gather(
        env.client.post("/_t/deadlock/1/2"), env.client.post("/_t/deadlock/2/1")
    )
    statuses = sorted([r1.status_code, r2.status_code])
    assert 500 not in statuses, (r1.text, r2.text)
    assert 503 in statuses
    assert statuses[0] in (200, 503)
    for r in (r1, r2):
        if r.status_code == 503:
            _assert_service_busy(r)
    assert any(r.levelno == logging.WARNING and "40P01" in r.getMessage() for r in caplog.records)
    assert (await env.client.get("/_t/ping")).status_code == 200


# --- AC (3): прочие DBAPIError -------------------------------------------------------------


async def test_t29_other_dbapi_error_is_still_500_internal_error(env: ApiEnv) -> None:
    """Регрессия: не-55P03/40P01 (42P01 undefined_table) -> 500 internal_error без SQL."""
    resp = await env.client.post("/_t/bad-sql")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Внутренняя ошибка", "code": "internal_error"}
    assert "retry-after" not in resp.headers
    low = resp.text.lower()
    assert "t29_no_such_table" not in low
    assert SECRET.lower() not in low
    assert (await env.client.get("/_t/ping")).status_code == 200


# --- AC (4): лог ---------------------------------------------------------------------------


async def test_t29_503_logs_warning_with_sqlstate_without_sql_and_params(
    env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """NFR-9/FR-57: WARNING с 55P03; нет текста запроса, имени таблицы и параметра; нет ERROR."""
    caplog.set_level(logging.DEBUG)
    async with _Holder(env, [3]):
        resp = await env.client.post("/_t/lock-secret")
    _assert_service_busy(resp)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("55P03" in r.getMessage() for r in warnings)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    text_all = _log_text(caplog.records)
    assert SECRET not in text_all
    low = text_all.lower()
    assert "for update" not in low
    assert TABLE not in low
    for r in warnings:
        if "55P03" in r.getMessage():
            assert r.exc_info is None  # текст DBAPIError содержит SQL


async def test_t29_other_dbapi_error_still_logged_as_error_without_secret(
    env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """Прочие DBAPIError: прежнее поведение — ERROR; параметр не попадает в лог."""
    caplog.set_level(logging.DEBUG)
    resp = await env.client.post("/_t/bad-sql")
    assert resp.status_code == 500
    assert any(r.levelno >= logging.ERROR for r in caplog.records)
    assert not any(
        r.levelno == logging.WARNING and "service_busy" in r.getMessage() for r in caplog.records
    )
    assert SECRET not in _log_text(caplog.records)


# --- AC (5): откат ---------------------------------------------------------------------------


async def test_t29_transaction_rolled_back_on_busy(env: ApiEnv) -> None:
    """D-3/D-40: запись до ошибки в том же запросе не сохраняется."""
    async with _Holder(env, [1]):
        resp = await env.client.post("/_t/write-then-lock")
    _assert_service_busy(resp)
    assert not await _row_exists(env, 100)
    assert (await env.client.get("/_t/ping")).status_code == 200


# --- AC (6): ошибка на COMMIT --------------------------------------------------------------


@pytest.mark.parametrize("via_cause", [False, True], ids=["orig.sqlstate", "orig.__cause__"])
async def test_t29_commit_stage_lock_error_is_503(
    env: ApiEnv, monkeypatch: pytest.MonkeyPatch, via_cause: bool
) -> None:
    """Ошибка 55P03 на COMMIT в ``get_db`` -> тот же 503; запись откатывается."""
    pg_error = asyncpg.exceptions.LockNotAvailableError("could not obtain lock")
    assert pg_error.sqlstate == "55P03"
    orig: BaseException = pg_error
    if via_cause:
        orig = Exception("wrapped driver error")
        orig.__cause__ = pg_error
    calls = {"n": 0}

    async def failing_commit(self: AsyncSession) -> None:
        calls["n"] += 1
        raise DBAPIError("COMMIT", {"p": SECRET}, orig)

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    resp = await env.client.post("/_t/plain-write")
    monkeypatch.undo()
    assert calls["n"] >= 1
    _assert_service_busy(resp)
    assert not await _row_exists(env, 200)
    assert (await env.client.get("/_t/ping")).status_code == 200


# --- AC (7): OpenAPI -------------------------------------------------------------------------


def test_t29_openapi_does_not_declare_503(app: FastAPI) -> None:
    """D-40: 503 как и 500 не объявляется ни у одного маршрута; документ в репозитории тоже."""
    schema = app.openapi()
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            assert "503" not in op.get("responses", {}), f"{method} {path}"
    committed = json.loads(OPENAPI_JSON.read_text(encoding="utf-8"))
    for path, ops in committed["paths"].items():
        for method, op in ops.items():
            assert "503" not in op.get("responses", {}), f"{method} {path}"
    assert "service_busy" not in json.dumps(committed)
