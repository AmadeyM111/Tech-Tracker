"""T05: слой БД, базовые миксины, Alembic и тестовая БД.

Покрытие: FR-13 (WorkspaceMixin), FR-46/D-4 (метки времени из utcnow()), D-2 (UUID v4),
D-3/D-26 (FK DEFERRABLE INITIALLY IMMEDIATE, RESTRICT на app_user), plan §4.2 (create_engine,
get_db, lifespan), plan §5 (защита имени тестовой БД, alembic upgrade/downgrade/check).

Модули ``app.core.db``, ``app.core.models``, ``app.domain.registry`` импортируются внутри
тестов и фикстур: пока их нет, каждый тест падает отдельно с понятной причиной.
Файл намеренно без ``from __future__ import annotations``: FastAPI разбирает аннотации
зависимостей локальных маршрутов.
"""

import ast
import asyncio
import configparser
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import CheckConstraint, Column, Index, Integer, String, Table, Uuid, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.clock import FixedClock
from app.core.config import Settings
from tests.db_support import (
    ALEMBIC_INI,
    BACKEND_DIR,
    DEFAULT_TEST_DATABASE_URL,
    UnsafeTestDatabaseError,
    assert_test_database_url,
    database_url_from_env,
    run_alembic,
)

APP_DIR = BACKEND_DIR / "app"
FIXED_NOW = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
SECRET = "s3cr3t-value-xyz-9141"


# --- защита имени тестовой БД (plan §5) --------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://tracker:tracker@localhost:5432/tracker",
        "postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_prod",
        "postgresql+asyncpg://tracker:tracker@localhost:5432/test",
        "postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test_old",
        "postgresql+asyncpg://tracker:tracker@localhost:5432/",
        "postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test?database=tracker",
        "postgresql+asyncpg://tracker:tracker@localhost:5432/?database=tracker_prod",
    ],
)
def test_plan5_guard_rejects_non_test_database_names(url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        assert_test_database_url(url)


@pytest.mark.parametrize(
    "url",
    [
        DEFAULT_TEST_DATABASE_URL,
        "postgresql+asyncpg://u:p@db.internal:5432/gostracker_ci_test",
    ],
)
def test_plan5_guard_accepts_test_database_names(url: str) -> None:
    assert assert_test_database_url(url).database is not None


def test_plan5_env_url_with_non_test_name_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://tracker:tracker@h:5432/tracker")
    with pytest.raises(UnsafeTestDatabaseError):
        database_url_from_env()


def test_plan5_default_url_is_tracker_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    assert database_url_from_env() == (
        "postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test"
    )


# --- Alembic: статическая конфигурация (D-26, T05) ---------------------------------------


def test_t05_alembic_ini_exists_and_script_location_is_here_migrations() -> None:
    assert ALEMBIC_INI.is_file(), "нет backend/alembic.ini"
    raw = configparser.RawConfigParser()
    raw.read(ALEMBIC_INI)
    assert raw.get("alembic", "script_location").replace("\\", "/") == "%(here)s/migrations"
    cfg = Config(str(ALEMBIC_INI))
    location = cfg.get_main_option("script_location")
    assert location is not None
    assert Path(location).resolve() == (BACKEND_DIR / "migrations").resolve()


def test_t05_alembic_env_is_async_and_uses_registry() -> None:
    env_py = BACKEND_DIR / "migrations" / "env.py"
    assert env_py.is_file(), "нет backend/migrations/env.py"
    assert (BACKEND_DIR / "migrations" / "script.py.mako").is_file()
    source = env_py.read_text(encoding="utf-8")
    assert "async_engine_from_config" in source or "create_async_engine" in source
    assert "run_sync" in source
    assert "app.domain.registry" in source, "env.py обязан импортировать registry (autogenerate)"
    assert "Base.metadata" in source or "Base" in source and "metadata" in source


def test_t05_registry_importable_and_exposes_base_metadata() -> None:
    import app.domain.registry  # noqa: F401
    from app.core.models import Base

    assert Base.metadata is not None


# --- Alembic: прогон на тестовой БД ------------------------------------------------------


@pytest.mark.committed
async def test_t05_upgrade_downgrade_upgrade_and_check(
    committed: Any, test_database_url: str
) -> None:
    async def alembic(*args: str) -> None:
        result = await asyncio.to_thread(run_alembic, test_database_url, *args)
        assert result.returncode == 0, (
            f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
        )

    await alembic("upgrade", "head")
    await alembic("downgrade", "base")
    await alembic("upgrade", "head")
    await alembic("check")


async def test_t05_alembic_url_falls_back_to_settings_without_x_arg(
    db_engine: Any, test_database_url: str
) -> None:
    result = await asyncio.to_thread(run_alembic, test_database_url, "current", x_dburl=False)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


# --- Base: naming convention (D-26) ------------------------------------------------------


def test_t05_base_has_naming_convention_keys() -> None:
    from app.core.models import Base

    convention = Base.metadata.naming_convention
    for key in ("ix", "uq", "ck", "fk", "pk"):
        assert key in convention, f"нет ключа {key!r} в naming_convention"
        assert isinstance(convention[key], str)
        assert "%(" in convention[key]


def test_t05_base_convention_yields_deterministic_constraint_names() -> None:
    from app.core.models import Base

    table = Table(
        "t05_names_probe",
        Base.metadata,
        Column("id", Integer, primary_key=True),
        Column("code", String(10), unique=True),
        Column("label", String(10), index=True),
        Column("qty", Integer),
        CheckConstraint("qty >= 0", name="qty_non_negative"),
    )
    try:
        pk = table.primary_key.name
        uq = next(c.name for c in table.constraints if c.__class__.__name__ == "UniqueConstraint")
        ix = next(i.name for i in table.indexes if isinstance(i, Index))
        ck = next(c.name for c in table.constraints if isinstance(c, CheckConstraint))
    finally:
        Base.metadata.remove(table)
    assert str(pk).startswith("pk_") and "t05_names_probe" in str(pk)
    assert str(uq).startswith("uq_") and "t05_names_probe" in str(uq) and "code" in str(uq)
    assert str(ix).startswith("ix_") and "t05_names_probe" in str(ix) and "label" in str(ix)
    assert str(ck).startswith("ck_") and "t05_names_probe" in str(ck)


# --- Миксины: модель на отдельной metadata ----------------------------------------------


@pytest.fixture(scope="module")
def models() -> SimpleNamespace:
    """Тестовая модель ``thing`` со всеми миксинами на собственной DeclarativeBase.

    ``Base`` приложения не затрагивается (иначе ``alembic check`` увидел бы лишнюю таблицу).
    Таблицы-цели FK (``workspace``, ``app_user``) объявлены в той же metadata.
    """
    from sqlalchemy import MetaData
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    from app.core import models as core

    class TBase(DeclarativeBase):
        metadata = MetaData(naming_convention=dict(core.Base.metadata.naming_convention))

    workspace = Table("workspace", TBase.metadata, Column("id", Uuid, primary_key=True))
    app_user = Table("app_user", TBase.metadata, Column("id", Uuid, primary_key=True))

    class Thing(
        core.UUIDPkMixin,
        core.TimestampMixin,
        core.WorkspaceMixin,
        core.AuthoredMixin,
        core.SoftDeleteMixin,
        TBase,
    ):
        __tablename__ = "thing"
        name: Mapped[str] = mapped_column(String(50))

    return SimpleNamespace(Base=TBase, Thing=Thing, workspace=workspace, app_user=app_user)


def test_ac_d4_timestamp_columns_are_timestamptz_without_server_default(
    models: SimpleNamespace,
) -> None:
    table = models.Thing.__table__
    for name in ("created_at", "updated_at"):
        column = table.c[name]
        assert column.type.timezone is True, f"{name}: нужен timestamptz (D-4)"
        assert column.server_default is None, f"{name}: серверного DEFAULT now() быть не должно"
        assert column.nullable is False


def test_fr13_workspace_mixin_gives_not_null_indexed_fk_to_workspace(
    models: SimpleNamespace,
) -> None:
    table = models.Thing.__table__
    column = table.c.workspace_id
    assert column.nullable is False
    targets = {fk.target_fullname for fk in column.foreign_keys}
    assert targets == {"workspace.id"}
    assert (
        any([c.name for c in ix.columns] == ["workspace_id"] for ix in table.indexes)
        or column.index
    ), "workspace_id должен быть проиндексирован"


def test_d26_all_mixin_fks_deferrable_initially_immediate(models: SimpleNamespace) -> None:
    fks = list(models.Thing.__table__.foreign_keys)
    assert {fk.target_fullname for fk in fks} == {"workspace.id", "app_user.id"}
    for fk in fks:
        assert fk.deferrable is True, fk.target_fullname
        assert fk.initially == "IMMEDIATE", fk.target_fullname


def test_d26_created_by_is_nullable_restrict(models: SimpleNamespace) -> None:
    column = models.Thing.__table__.c.created_by
    assert column.nullable is True
    (fk,) = column.foreign_keys
    assert fk.target_fullname == "app_user.id"
    assert (fk.ondelete or "").upper() == "RESTRICT"


def test_soft_delete_mixin_columns_are_nullable(models: SimpleNamespace) -> None:
    table = models.Thing.__table__
    assert table.c.deleted_at.nullable is True
    assert table.c.deleted_at.type.timezone is True
    assert table.c.deleted_batch_id.nullable is True


@pytest_asyncio.fixture
async def thing_db(
    models: SimpleNamespace, db_connection: Any, db_sessionmaker: Any
) -> AsyncIterator[Any]:
    """Сессия и тестовые таблицы во временной схеме внутри откатываемой транзакции."""
    from sqlalchemy import insert

    await db_connection.execute(text("CREATE SCHEMA t05_probe"))
    await db_connection.execute(text("SET LOCAL search_path TO t05_probe"))
    await db_connection.run_sync(models.Base.metadata.create_all)
    async with db_sessionmaker() as session:
        await session.execute(insert(models.workspace).values(id=uuid.uuid4()))
        yield session


async def _workspace_id(session: Any, models: SimpleNamespace) -> uuid.UUID:
    from sqlalchemy import select

    return (await session.execute(select(models.workspace.c.id))).scalar_one()


async def test_fr46_timestamps_come_from_utcnow_clock(
    thing_db: Any, models: SimpleNamespace, fixed_clock: FixedClock
) -> None:
    ws = await _workspace_id(thing_db, models)
    thing = models.Thing(name="a", workspace_id=ws)
    thing_db.add(thing)
    await thing_db.flush()

    assert thing.created_at == FIXED_NOW
    assert thing.updated_at == FIXED_NOW
    assert thing.created_at.utcoffset() == timedelta(0)

    fixed_clock.advance(timedelta(minutes=5))
    thing.name = "b"
    await thing_db.flush()
    assert thing.created_at == FIXED_NOW
    assert thing.updated_at == FIXED_NOW + timedelta(minutes=5)

    await thing_db.refresh(thing)
    assert thing.created_at == FIXED_NOW
    assert thing.updated_at == FIXED_NOW + timedelta(minutes=5)
    assert thing.updated_at.tzinfo is not None
    assert thing.updated_at.utcoffset() == timedelta(0)


async def test_d2_uuid_pk_is_generated_uuid4(thing_db: Any, models: SimpleNamespace) -> None:
    ws = await _workspace_id(thing_db, models)
    first = models.Thing(name="a", workspace_id=ws)
    second = models.Thing(name="b", workspace_id=ws)
    thing_db.add_all([first, second])
    await thing_db.flush()
    assert isinstance(first.id, uuid.UUID)
    assert first.id.version == 4
    assert second.id.version == 4
    assert first.id != second.id


async def test_fr13_workspace_id_is_required_and_fk_checked_immediately(
    thing_db: Any, models: SimpleNamespace
) -> None:
    thing_db.add(models.Thing(name="no-workspace"))
    with pytest.raises(IntegrityError):
        await thing_db.flush()


async def test_d26_unknown_workspace_fails_at_flush_not_at_commit(
    thing_db: Any, models: SimpleNamespace
) -> None:
    thing_db.add(models.Thing(name="x", workspace_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await thing_db.flush()


async def test_d26_database_constraints_deferrable_initially_immediate(
    thing_db: Any, models: SimpleNamespace
) -> None:
    ws = await _workspace_id(thing_db, models)
    thing_db.add(models.Thing(name="a", workspace_id=ws))
    await thing_db.flush()
    rows = (
        await thing_db.execute(
            text(
                "SELECT conname, condeferrable, condeferred, confdeltype::text AS deltype, "
                "confrelid::regclass::text AS target "
                "FROM pg_constraint WHERE conrelid = 't05_probe.thing'::regclass AND contype = 'f'"
            )
        )
    ).all()
    assert len(rows) == 2
    for row in rows:
        assert row.condeferrable is True, row.conname
        assert row.condeferred is False, row.conname
    assert {r.deltype for r in rows if r.target.endswith("app_user")} == {"r"}
    assert all(r.conname.startswith("fk_") for r in rows)


# --- create_engine (plan §4.2) -----------------------------------------------------------


def test_create_engine_sets_hide_parameters_and_pre_ping(settings: Settings) -> None:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from app.core.db import create_engine

    engine = create_engine(settings)
    assert isinstance(engine, AsyncEngine)
    assert engine.sync_engine.hide_parameters is True
    assert engine.sync_engine.pool._pre_ping is True  # type: ignore[attr-defined]
    assert engine.url.drivername == "postgresql+asyncpg"
    assert engine.url.database == "tracker_test"


async def test_create_engine_hides_parameters_in_errors(db_engine: Any, settings: Settings) -> None:
    from app.core.db import create_engine

    engine = create_engine(settings)
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError) as info:
                await conn.execute(
                    text("SELECT CAST(:s AS text), 1 / CAST(:z AS integer)"),
                    {"s": SECRET, "z": 0},
                )
    finally:
        await engine.dispose()
    assert SECRET not in str(info.value)


# --- get_db (plan §4.2): одна транзакция на запрос ---------------------------------------


@pytest_asyncio.fixture
async def probe_client(
    committed: Any, settings: Settings, fixed_clock: FixedClock
) -> AsyncIterator[httpx.AsyncClient]:
    from app.core import errors
    from app.core.db import DbSession
    from app.main import create_app

    async with committed() as setup, setup.begin():
        await setup.execute(text("CREATE TABLE t05_probe (id serial PRIMARY KEY, v text)"))
        await setup.execute(text("CREATE TABLE t05_parent (id integer PRIMARY KEY)"))
        await setup.execute(
            text(
                "CREATE TABLE t05_child (id serial PRIMARY KEY, parent_id integer "
                "REFERENCES t05_parent (id) DEFERRABLE INITIALLY IMMEDIATE)"
            )
        )

    application: FastAPI = create_app(settings, clock=fixed_clock)
    application.state.sessionmaker = committed

    async def insert_ok(db: DbSession) -> dict[str, Any]:
        await db.execute(text("INSERT INTO t05_probe (v) VALUES ('ok')"))
        return {"in_tx": db.in_transaction()}

    async def two_statements(db: DbSession) -> dict[str, Any]:
        first = (await db.execute(text("SELECT txid_current()"))).scalar_one()
        await db.execute(text("INSERT INTO t05_probe (v) VALUES ('x')"))
        second = (await db.execute(text("SELECT txid_current()"))).scalar_one()
        return {"first": first, "second": second}

    async def boom(db: DbSession) -> None:
        await db.execute(text("INSERT INTO t05_probe (v) VALUES ('boom-1')"))
        await db.execute(text("INSERT INTO t05_probe (v) VALUES ('boom-2')"))
        raise RuntimeError("boom")

    async def app_error(db: DbSession) -> None:
        await db.execute(text("INSERT INTO t05_probe (v) VALUES ('nf')"))
        raise errors.NotFound("нет такого")

    async def commit_fails(db: DbSession) -> dict[str, bool]:
        await db.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        await db.execute(text("INSERT INTO t05_child (parent_id) VALUES (999)"))
        await db.execute(text("INSERT INTO t05_probe (v) VALUES ('commit-fails')"))
        return {"ok": True}

    application.add_api_route("/probe/commit-fails", commit_fails, methods=["POST"])
    application.add_api_route("/probe/ok", insert_ok, methods=["POST"])
    application.add_api_route("/probe/two", two_statements, methods=["POST"])
    application.add_api_route("/probe/boom", boom, methods=["POST"])
    application.add_api_route("/probe/app-error", app_error, methods=["POST"])

    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def _probe_count(committed: Any) -> int:
    async with committed() as s:
        return int((await s.execute(text("SELECT count(*) FROM t05_probe"))).scalar_one())


@pytest.mark.committed
async def test_get_db_commits_once_at_request_end(
    probe_client: httpx.AsyncClient, committed: Any
) -> None:
    response = await probe_client.post("/probe/ok")
    assert response.status_code == 200
    assert response.json() == {"in_tx": True}
    assert await _probe_count(committed) == 1


@pytest.mark.committed
async def test_get_db_uses_single_transaction_per_request(
    probe_client: httpx.AsyncClient, committed: Any
) -> None:
    response = await probe_client.post("/probe/two")
    assert response.status_code == 200
    body = response.json()
    assert body["first"] == body["second"]
    assert await _probe_count(committed) == 1


@pytest.mark.committed
async def test_get_db_rolls_back_on_unhandled_exception(
    probe_client: httpx.AsyncClient, committed: Any
) -> None:
    response = await probe_client.post("/probe/boom")
    assert response.status_code == 500
    assert await _probe_count(committed) == 0


@pytest.mark.committed
async def test_get_db_rolls_back_on_app_error(
    probe_client: httpx.AsyncClient, committed: Any
) -> None:
    response = await probe_client.post("/probe/app-error")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert await _probe_count(committed) == 0


@pytest.mark.committed
async def test_get_db_commit_failure_returns_500_and_rolls_back(
    probe_client: httpx.AsyncClient, committed: Any
) -> None:
    """COMMIT выполняется до отправки ответа: сбой фиксации -> 500, а не 200 (scope=function)."""
    response = await probe_client.post("/probe/commit-fails")
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert await _probe_count(committed) == 0
    async with committed() as s:
        assert (await s.execute(text("SELECT count(*) FROM t05_child"))).scalar_one() == 0


def test_dbsession_is_used_instead_of_bare_depends_get_db() -> None:
    """Вне ``app/core/db.py`` нет ``Depends(get_db...)``: только ``DbSession`` (scope=function)."""
    offenders: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        rel = path.relative_to(APP_DIR).as_posix()
        if rel == "core/db.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Depends"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "get_db"
            ):
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


def test_get_db_no_commit_calls_outside_core_db() -> None:
    """Сервисы, API и модели не вызывают ``commit()`` (план §4.2; CLI вне проверки)."""
    offenders: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        rel = path.relative_to(APP_DIR).as_posix()
        if rel == "core/db.py" or rel.startswith("cli/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "commit"
            ):
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


# --- lifespan (plan §4.2, T05) -----------------------------------------------------------


async def test_lifespan_puts_engine_and_sessionmaker_into_app_state(
    db_engine: Any, settings: Settings, fixed_clock: FixedClock
) -> None:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from app.main import create_app

    application = create_app(settings, clock=fixed_clock)
    async with application.router.lifespan_context(application):
        engine = application.state.engine
        sessionmaker = application.state.sessionmaker
        assert isinstance(engine, AsyncEngine)
        assert isinstance(sessionmaker, async_sessionmaker)
        assert engine.url.database == "tracker_test"
        async with sessionmaker() as session:
            assert isinstance(session, AsyncSession)
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1


def test_commit_durably_used_only_by_auth_service() -> None:
    """T11 (ревью): единственное санкционированное исключение из «сервисы не фиксируют» —
    ``commit_durably``; определён в core/db.py, вызывается только из domain/auth/service.py
    и (T16a) api/deps.py (``get_actor`` фиксирует активность сессии до обработчика)."""
    required_users = {"domain/auth/service.py"}
    allowed_users = required_users | {"api/deps.py"}
    definition = "core/db.py"
    users: set[str] = set()
    defined_in: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        rel = path.relative_to(APP_DIR).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                if node.name == "commit_durably":
                    defined_in.add(rel)
                continue
            hit = (
                (isinstance(node, ast.Name) and node.id == "commit_durably")
                or (isinstance(node, ast.Attribute) and node.attr == "commit_durably")
                or (
                    isinstance(node, ast.ImportFrom)
                    and any(a.name == "commit_durably" for a in node.names)
                )
            )
            if hit and rel != definition:
                users.add(rel)
    assert defined_in == {definition}, f"commit_durably определён в {sorted(defined_in)}"
    assert required_users <= users, (
        f"commit_durably не вызывается из {sorted(required_users - users)}"
    )
    assert users <= allowed_users, f"commit_durably используется в {sorted(users - allowed_users)}"
