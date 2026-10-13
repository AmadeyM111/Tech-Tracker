"""Общие фикстуры тестов backend (T05, plan §5).

Правила БД:
- адрес берётся из ``TEST_DATABASE_URL``; имя базы обязано оканчиваться на ``_test``;
- база создаётся при отсутствии, на сессию выполняется один ``alembic upgrade head``;
- обычный тест получает сессию во внешней транзакции (``join_transaction_mode=
  "create_savepoint"``), откат в конце;
- тесты с ``@pytest.mark.committed`` используют фикстуру ``committed``: чистая схема на тест.

Импорты ``sqlalchemy.ext.asyncio`` и ``app.core.db`` — внутри фикстур, чтобы тесты без БД
не требовали драйверов.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

from app.core.clock import FixedClock, use_clock
from app.core.config import Settings
from tests.db_support import (
    assert_test_database_url,
    database_url_from_env,
    run_alembic,
)

if TYPE_CHECKING:
    import httpx
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import (
        AsyncConnection,
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
    )

FIXED_NOW = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
SESSION_LOOP = pytest.mark.asyncio(loop_scope="session")

# Дешёвые параметры Argon2 для тестов (tasks.md, «Общие условия»).
CHEAP_ARGON2 = {"argon2_time_cost": 1, "argon2_memory_cost_kib": 1024, "argon2_parallelism": 1}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Все async-тесты идут в одном session-цикле событий.

    Движок БД живёт на session-фикстуре; без общего цикла asyncpg-соединения «прикреплены к
    другому циклу». Эквивалент ``asyncio_default_test_loop_scope = "session"`` в pyproject.
    """
    for item in items:
        func = getattr(item, "obj", None)
        if inspect.iscoroutinefunction(func):
            # append=False: наш маркер «ближе» автоматически добавленного pytest-asyncio
            item.add_marker(SESSION_LOOP, append=False)


# --- часы и настройки -------------------------------------------------------------------


@pytest.fixture
def fixed_clock() -> Iterator[FixedClock]:
    """FixedClock на 2026-10-13T09:00:00Z; установлен как текущие часы процесса."""
    clock = FixedClock(FIXED_NOW)
    with use_clock(clock):
        yield clock


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """URL тестовой БД; отказывается работать, если имя базы не оканчивается на ``_test``."""
    return database_url_from_env()


@pytest.fixture
def settings(test_database_url: str, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return Settings(
        env="test",
        database_url=test_database_url,
        data_dir=tmp_path_factory.mktemp("data"),
        cookie_secure=False,
        expose_api_docs=False,
        **CHEAP_ARGON2,
    )


# --- БД ---------------------------------------------------------------------------------


async def _create_database_if_missing(url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    parsed = assert_test_database_url(url)
    admin = create_async_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": parsed.database},
                )
            ).scalar()
            if not exists:
                quoted = '"' + str(parsed.database).replace('"', '""') + '"'
                await conn.execute(text(f"CREATE DATABASE {quoted}"))
    finally:
        await admin.dispose()


async def _upgrade_head(url: str) -> None:
    result = await asyncio.to_thread(run_alembic, url, "upgrade", "head")
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head завершился с кодом {result.returncode}:\n"
            f"{result.stdout}\n{result.stderr}"
        )


@pytest_asyncio.fixture(scope="session")
async def db_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Создаёт БД при отсутствии, один раз на сессию применяет миграции, отдаёт движок."""
    from sqlalchemy.ext.asyncio import create_async_engine

    await _create_database_if_missing(test_database_url)
    await _upgrade_head(test_database_url)
    engine = create_async_engine(test_database_url, hide_parameters=True, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_connection(db_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Соединение с внешней транзакцией, которая откатывается в конце теста."""
    async with db_engine.connect() as conn:
        outer = await conn.begin()
        try:
            yield conn
        finally:
            if outer.is_active:
                await outer.rollback()


@pytest_asyncio.fixture
async def db_sessionmaker(db_connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(
        bind=db_connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )


@pytest_asyncio.fixture
async def db(db_sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Сессия теста: ``commit()`` внутри освобождает SAVEPOINT, внешняя транзакция откатится."""
    async with db_sessionmaker() as session:
        yield session


async def _reset_schema(engine: AsyncEngine, url: str) -> None:
    from sqlalchemy import text

    await engine.dispose()
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    await _upgrade_head(url)


@pytest_asyncio.fixture
async def committed(
    db_engine: AsyncEngine, test_database_url: str
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Реальные фиксации: чистая схема (DROP SCHEMA + upgrade head) до и после теста.

    Отдаёт ``async_sessionmaker`` поверх движка тестовой БД (``expire_on_commit=False``).
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    await _reset_schema(db_engine, test_database_url)
    try:
        yield async_sessionmaker(db_engine, expire_on_commit=False)
    finally:
        await _reset_schema(db_engine, test_database_url)


# --- приложение -------------------------------------------------------------------------


@pytest.fixture
def app(settings: Settings, fixed_clock: FixedClock) -> FastAPI:
    """Приложение с FixedClock в ``app.state.clock``. БД не подключена (lifespan не запущен)."""
    from app.main import create_app

    return create_app(settings, clock=fixed_clock)


@pytest_asyncio.fixture
async def client(
    app: FastAPI, db_sessionmaker: async_sessionmaker[AsyncSession]
) -> AsyncIterator[httpx.AsyncClient]:
    """httpx-клиент к приложению; запросы идут в сессиях внешней транзакции теста (откат)."""
    import httpx

    app.state.sessionmaker = db_sessionmaker
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
