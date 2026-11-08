"""spec 016: ``gtrack load-data`` и ``load_synthetic_data`` (FR-1, NFR-2, AC-1, AC-2).

AC-1: два запуска с одним seed дают одинаковый ``gtrack export`` (без ``exported_at``).
AC-2: запуск в непустую систему отказан с кодом 2.
Тесты на тестовой БД (``*_test``), ``committed``: фиксации нужны, чтобы экспорт видел данные.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from app.cli.commands.export import schema_head
from app.core.clock import FixedClock
from app.core.config import Settings, get_settings
from app.core.security.passwords import PasswordHasher
from app.domain.ops.archive import payload_bytes
from app.domain.ops.export import build_payload
from app.domain.ops.load import (
    LOAD_TEST_LOGIN,
    LoadDataRefused,
    LoadReport,
    derive_password,
    load_synthetic_data,
)
from app.domain.system.bootstrap import run_bootstrap
from app.domain.tasks.models import Task
from app.domain.users.models import AppUser
from tests.conftest import FIXED_NOW
from tests.db_support import ALEMBIC_INI

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

pytestmark = pytest.mark.committed

SEED = 16
TASKS = 500
FIRST_ADMIN_PASSWORD = "Zq7Lm2Vx9FirstAdminPw"

# удаляет только строки набора; первый ТА и workspace остаются (их хеши и id фиксированы)
_DELETE_GENERATED = (
    "DELETE FROM comment",
    "DELETE FROM task WHERE parent_id IS NOT NULL",
    "DELETE FROM task",
    "DELETE FROM project_member",
    "DELETE FROM project",
    "DELETE FROM workspace_member WHERE user_id IN "
    "(SELECT id FROM app_user WHERE login LIKE 'load.%')",
    "DELETE FROM app_user WHERE login LIKE 'load.%'",
)


async def _bootstrap(sm: async_sessionmaker[Any], settings: Settings) -> None:
    await run_bootstrap(
        sm, settings, clock=FixedClock(FIXED_NOW), generate=lambda: FIRST_ADMIN_PASSWORD
    )


async def _export(engine: AsyncEngine) -> dict[str, Any]:
    payload = await build_payload(engine, schema_version=schema_head(), exported_at=FIXED_NOW)
    return {key: value for key, value in payload.items() if key != "exported_at"}


async def _delete_generated(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for statement in _DELETE_GENERATED:
            await conn.execute(text(statement))


async def _count(engine: AsyncEngine, model: type[Any]) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(select(func.count()).select_from(model))).scalar_one())


@pytest_asyncio.fixture
async def system(
    committed: async_sessionmaker[Any], settings: Settings
) -> AsyncIterator[async_sessionmaker[Any]]:
    """Пустая установка: пространство и первый ТА (как после ``gtrack bootstrap``)."""
    await _bootstrap(committed, settings)
    yield committed


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_database_url: str
) -> Iterator[Path]:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_MEMORY_COST_KIB", "1024")
    monkeypatch.setenv("ARGON2_PARALLELISM", "1")
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ALEMBIC_INI))
    get_settings.cache_clear()
    yield data_dir
    get_settings.cache_clear()


async def test_same_seed_same_export(
    system: async_sessionmaker[Any], db_engine: AsyncEngine, settings: Settings
) -> None:
    """AC-1: одинаковый seed — одинаковый export (без ``exported_at``)."""
    report = await load_synthetic_data(system, settings, seed=SEED, tasks=TASKS)
    first = await _export(db_engine)
    await _delete_generated(db_engine)

    again = await load_synthetic_data(system, settings, seed=SEED, tasks=TASKS)
    second = await _export(db_engine)

    assert again == report
    assert second == first
    assert payload_bytes(second) == payload_bytes(first)


async def test_different_seed_gives_different_export(
    system: async_sessionmaker[Any], db_engine: AsyncEngine, settings: Settings
) -> None:
    await load_synthetic_data(system, settings, seed=SEED, tasks=TASKS)
    first = await _export(db_engine)
    await _delete_generated(db_engine)

    await load_synthetic_data(system, settings, seed=SEED + 1, tasks=TASKS)
    assert await _export(db_engine) != first


async def test_volume_and_roles(
    system: async_sessionmaker[Any], db_engine: AsyncEngine, settings: Settings
) -> None:
    """FR-1: 12 пользователей, 8 проектов, задачи с подзадачами; учётные записи входят."""
    report = await load_synthetic_data(system, settings, seed=SEED, tasks=TASKS)
    assert report == LoadReport(
        users=12,
        projects=8,
        tasks=TASKS,
        subtasks=TASKS // 10,
        comments=report.comments,
    )
    assert report.comments > 0
    # первый ТА плюс 12 строк набора
    assert await _count(db_engine, AppUser) == 13
    async with db_engine.connect() as conn:
        statuses = {row[0] for row in await conn.execute(text("SELECT DISTINCT status FROM task"))}
        overdue = (
            await conn.execute(
                text("SELECT count(*) FROM task WHERE due_date < current_date AND status <> 'done'")
            )
        ).scalar_one()
        unassigned = (
            await conn.execute(text("SELECT count(*) FROM task WHERE assignee_id IS NULL"))
        ).scalar_one()
    assert statuses == {"todo", "in_progress", "review", "done"}
    assert overdue > 0
    assert unassigned > 0


async def test_load_user_password_matches_hash(
    system: async_sessionmaker[Any], db_engine: AsyncEngine, settings: Settings
) -> None:
    """Синтетический пароль из ``derive_password`` проходит проверку хеша набора."""
    await load_synthetic_data(system, settings, seed=SEED, tasks=TASKS)
    async with system() as session:
        row = (
            await session.execute(
                select(AppUser.password_hash).where(AppUser.login == LOAD_TEST_LOGIN)
            )
        ).scalar_one()
    hasher = PasswordHasher(time_cost=1, memory_cost_kib=1024, parallelism=1)
    assert hasher.verify(row, derive_password(SEED, LOAD_TEST_LOGIN))
    assert not hasher.verify(row, derive_password(SEED + 1, LOAD_TEST_LOGIN))


async def test_nonempty_system_refused(
    system: async_sessionmaker[Any], db_engine: AsyncEngine, settings: Settings
) -> None:
    """AC-2 (домен): второй запуск в заполненную систему отказан, данные не меняются."""
    await load_synthetic_data(system, settings, seed=SEED, tasks=TASKS)
    tasks_before = await _count(db_engine, Task)
    with pytest.raises(LoadDataRefused):
        await load_synthetic_data(system, settings, seed=SEED, tasks=TASKS)
    assert await _count(db_engine, Task) == tasks_before


async def test_cli_exit_codes(
    system: async_sessionmaker[Any],
    db_engine: AsyncEngine,
    cli_env: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-2 (CLI): код 0 на пустой системе, код 2 в непустой; ``ENV=production`` — код 1."""
    from app.cli.main import main

    assert (
        await asyncio.to_thread(main, ["load-data", "--seed", str(SEED), "--tasks", str(TASKS)])
        == 0
    )
    out = capsys.readouterr().out
    assert f"load_login={LOAD_TEST_LOGIN}" in out
    assert "tasks=" in out

    assert (
        await asyncio.to_thread(main, ["load-data", "--seed", str(SEED), "--tasks", str(TASKS)])
        == 2
    )


def test_cli_refuses_production(cli_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cli.main import main

    monkeypatch.setenv("ENV", "production")
    get_settings.cache_clear()
    assert main(["load-data", "--seed", str(SEED), "--tasks", str(TASKS)]) == 1
