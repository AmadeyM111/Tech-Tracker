"""B09-T02/T03: копия и восстановление с настоящим ``pg_dump``/``pg_restore`` 16.

AC-1, AC-5 (журнал запусков), AC-9 (круг export → backup → restore в чистую БД → export),
AC-10 (непустая БД). Деструктивно только для БД ``*_test`` (отдельная ``…_restore_test``).
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.cli.commands.export import schema_head
from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.db import transaction
from app.domain.ops.backup import (
    BackupRunRecord,
    RestoreRefused,
    create_backup,
    public_tables,
    record_run,
    restore_backup,
)
from app.domain.ops.demo import load_demo_data
from app.domain.ops.export import build_payload
from app.domain.ops.models import BackupRun
from app.domain.system.bootstrap import run_bootstrap
from tests.backup_support import requires_pg16, with_pg
from tests.conftest import FIXED_NOW
from tests.db_support import assert_test_database_url

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

pytestmark = [pytest.mark.committed, requires_pg16]


@pytest_asyncio.fixture
async def filled(
    committed: async_sessionmaker[Any], db_engine: AsyncEngine, settings: Settings
) -> AsyncIterator[tuple[async_sessionmaker[Any], AsyncEngine, Settings]]:
    await run_bootstrap(
        committed, settings, clock=FixedClock(FIXED_NOW), generate=lambda: "Zq7Lm2Vx9BackupPw"
    )
    await load_demo_data(committed, settings, clock=FixedClock(FIXED_NOW), seed=7)
    (settings.data_dir / "attachments").mkdir(exist_ok=True)
    (settings.data_dir / "attachments" / "a1").write_bytes(b"\x00\x01payload")
    yield committed, db_engine, settings


@pytest_asyncio.fixture
async def restore_url(test_database_url: str) -> AsyncIterator[str]:
    """Пустая БД ``<имя>_restore_test`` на том же сервере; удаляется после теста."""
    base = assert_test_database_url(test_database_url)
    name = f"{str(base.database).removesuffix('_test')}_restore_test"
    url = base.set(database=name)
    assert_test_database_url(url.render_as_string(hide_password=False))
    admin = create_async_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


def _strip(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k != "exported_at"}


def _tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "exports" not in p.relative_to(root).parts
    }


async def test_009_ac1_ac5_real_backup_and_run_record(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings], tmp_path: Path
) -> None:
    sm, _engine, settings = filled
    cfg = with_pg(settings)
    result = create_backup(
        cfg,
        tmp_path / "b",
        schema_revision=schema_head(),
        app_version="0.0.1",
        now=FIXED_NOW,
        keep=14,
    )
    assert result.size_bytes > 0
    async with transaction(sm) as s:
        await record_run(
            s,
            BackupRunRecord(
                started_at=FIXED_NOW,
                finished_at=FIXED_NOW,
                size_bytes=result.size_bytes,
                schema_revision=result.schema_revision,
                file_name=result.path.name,
            ),
        )
    async with sm() as s:
        row = (await s.execute(select(BackupRun))).scalar_one()
    assert (row.status, row.size_bytes, row.file_name) == (
        "ok",
        result.size_bytes,
        result.path.name,
    )
    assert row.error_code is None


async def test_009_ac9_restore_into_clean_db_gives_identical_export(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
    restore_url: str,
    tmp_path: Path,
) -> None:
    _sm, engine, settings = filled
    cfg = with_pg(settings)
    before = await build_payload(engine, schema_version=schema_head(), exported_at=FIXED_NOW)
    files_before = _tree(settings.data_dir)
    result = create_backup(
        cfg,
        tmp_path / "b",
        schema_revision=schema_head(),
        app_version="0.0.1",
        now=FIXED_NOW,
        keep=14,
    )

    target = cfg.model_copy(update={"database_url": restore_url, "data_dir": tmp_path / "fresh"})
    restored = create_async_engine(make_url(restore_url), hide_parameters=True)
    try:
        async with restored.connect() as conn:
            assert await public_tables(conn) == []
        manifest = restore_backup(target, result.path, db_tables=[])
        assert manifest.schema_revision == schema_head()
        after = await build_payload(restored, schema_version=schema_head(), exported_at=FIXED_NOW)
        async with restored.connect() as conn:
            assert "backup_run" in await public_tables(conn)
    finally:
        await restored.dispose()
    assert len(before["tables"]["task"]) > 0
    assert _strip(after) == _strip(before)
    assert _tree(tmp_path / "fresh") == files_before


async def test_009_ac10_restore_refused_into_non_empty_db(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings], tmp_path: Path
) -> None:
    _sm, engine, settings = filled
    cfg = with_pg(settings)
    result = create_backup(
        cfg,
        tmp_path / "b",
        schema_revision=schema_head(),
        app_version="0.0.1",
        now=FIXED_NOW,
        keep=14,
    )
    async with engine.connect() as conn:
        tables = await public_tables(conn)
    assert "task" in tables
    with pytest.raises(RestoreRefused, match="БД не пуста"):
        restore_backup(
            cfg.model_copy(update={"data_dir": tmp_path / "empty"}), result.path, db_tables=tables
        )
