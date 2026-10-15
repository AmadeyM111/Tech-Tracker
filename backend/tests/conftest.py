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
from typing import TYPE_CHECKING, Any

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

    from tests.factories import UserRow

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


# --- T13: HTTP-окружение входа (хелперы «войти») ------------------------------------------


class ApiEnv:
    """Приложение с запущенным lifespan, httpx-клиент и хелперы входа.

    ``sessionmaker`` — та же фабрика, что подставлена в ``app.state.sessionmaker``: в обычном
    режиме сессии внешней транзакции теста (откат), в режиме ``committed`` — реальные
    фиксации. Тестовые данные создаются в отдельной сессии с ``commit()``: в обоих режимах
    они видны запросам приложения.

    Cookie-jar клиента отключён: cookie передаёт тест явно (``auth``), чтобы не зависеть от
    правил ``Secure``/домена httpx.
    """

    def __init__(
        self,
        *,
        app: FastAPI,
        client: httpx.AsyncClient,
        settings: Settings,
        clock: FixedClock,
        sessionmaker: async_sessionmaker[AsyncSession],
        base_url: str,
    ) -> None:
        self.app = app
        self.client = client
        self.settings = settings
        self.clock = clock
        self.sessionmaker = sessionmaker
        self.base_url = base_url

    # --- данные ---

    async def new_user(self, **kwargs: Any) -> UserRow:
        """``tests.factories.make_user`` в отдельной сессии с фиксацией (по умолчанию без роли)."""
        from tests.factories import make_user

        async with self.sessionmaker() as session:
            user = await make_user(session, **kwargs)
            await session.commit()
        return user

    async def execute(self, statement: Any) -> list[Any] | None:
        """Выполняет Core-выражение в отдельной сессии с фиксацией; возвращает результат."""
        async with self.sessionmaker() as session:
            result = await session.execute(statement)
            rows = result.all() if result.returns_rows else None
            await session.commit()
        return rows

    async def user_row(self, user_id: Any) -> Any:
        """Строка ``app_user`` (failed_login_count, login_locked_until, …) свежей сессией."""
        from sqlalchemy import select

        from tests.factories import get_table

        table = get_table("app_user")
        async with self.sessionmaker() as session:
            row = (await session.execute(select(table).where(table.c.id == user_id))).one()
        return row

    async def session_ids(self, user_id: Any) -> list[bytes]:
        from sqlalchemy import select

        from tests.factories import get_table

        table = get_table("user_session")
        async with self.sessionmaker() as session:
            rows = (
                await session.execute(select(table.c.id).where(table.c.user_id == user_id))
            ).all()
        return [bytes(r[0]) for r in rows]

    def token_id(self, token: str) -> bytes:
        from app.core.secrets import ensure_secret_key
        from app.domain.auth.sessions import SessionStore

        store = SessionStore(
            ensure_secret_key(self.settings),
            idle_timeout=self.settings.session_idle_timeout,
            absolute_timeout=self.settings.session_absolute_timeout,
        )
        return store.token_id(token)

    # --- HTTP ---

    @property
    def cookie_name(self) -> str:
        return self.settings.cookie_name

    def auth(self, token: str, **extra: str) -> dict[str, str]:
        """Заголовки с cookie сессии (+ дополнительные заголовки)."""
        return {"Cookie": f"{self.cookie_name}={token}", **extra}

    async def login(
        self,
        login: str,
        password: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.client.post(
            "/api/v1/auth/login",
            json={"login": login, "password": password},
            headers=headers,
        )

    def token_from(self, response: httpx.Response) -> str | None:
        """Значение cookie сессии из ``Set-Cookie`` ответа; ``None`` — cookie не ставится."""
        for raw in response.headers.get_list("set-cookie"):
            name, _, rest = raw.partition("=")
            if name.strip() == self.cookie_name:
                return rest.split(";", 1)[0].strip().strip('"')
        return None

    async def login_ok(self, user: UserRow) -> str:
        """Вход пользователя из ``new_user`` по HTTP; возвращает сырой токен."""
        response = await self.login(user.login, user.password)
        assert response.status_code == 200, response.text
        token = self.token_from(response)
        assert token, "вход не поставил cookie сессии"
        return token

    async def me(self, token: str, **extra: str) -> httpx.Response:
        return await self.client.get("/api/v1/me", headers=self.auth(token, **extra))


def _block_cookie_jar(client: httpx.AsyncClient) -> None:
    from http.cookiejar import DefaultCookiePolicy

    client.cookies.jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))


async def _open_api_env(
    app: FastAPI,
    settings: Settings,
    clock: FixedClock,
    sessionmaker: async_sessionmaker[AsyncSession],
    base_url: str,
) -> AsyncIterator[ApiEnv]:
    import httpx

    async with app.router.lifespan_context(app):
        app.state.sessionmaker = sessionmaker
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as c:
            _block_cookie_jar(c)
            yield ApiEnv(
                app=app,
                client=c,
                settings=settings,
                clock=clock,
                sessionmaker=sessionmaker,
                base_url=base_url,
            )


@pytest_asyncio.fixture
async def api_env(
    app: FastAPI,
    settings: Settings,
    fixed_clock: FixedClock,
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ApiEnv]:
    """``cookie_secure=False``, http; запросы в транзакции теста (откат в конце)."""
    async for env in _open_api_env(
        app, settings, fixed_clock, db_sessionmaker, "http://testserver"
    ):
        yield env


@pytest_asyncio.fixture
async def api_env_secure(
    settings: Settings,
    fixed_clock: FixedClock,
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ApiEnv]:
    """``cookie_secure=True`` (поставляемая конфигурация), запросы по https."""
    from app.main import create_app

    secure = settings.model_copy(update={"cookie_secure": True})
    application = create_app(secure, clock=fixed_clock)
    async for env in _open_api_env(
        application, secure, fixed_clock, db_sessionmaker, "https://testserver"
    ):
        yield env


@pytest_asyncio.fixture
async def committed_api_env(
    app: FastAPI,
    settings: Settings,
    fixed_clock: FixedClock,
    committed: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ApiEnv]:
    """Реальные фиксации и отдельные соединения на запрос (параллельность, FR-61)."""
    async for env in _open_api_env(app, settings, fixed_clock, committed, "http://testserver"):
        yield env


def parse_set_cookie(response: httpx.Response, name: str) -> Any:
    """``http.cookies.Morsel`` для cookie ``name`` из ``Set-Cookie`` ответа или ``None``."""
    from http.cookies import SimpleCookie

    for raw in response.headers.get_list("set-cookie"):
        jar: SimpleCookie = SimpleCookie()
        jar.load(raw)
        if name in jar:
            return jar[name]
    return None
