"""B09-T01: схема ``backup_run`` (spec 009 FR-4, plan PB-5).

Покрытие: миграция 0011 вверх/вниз/вверх и ``alembic check``; ограничения статуса, порядка
времени, размера и связи ``error_code`` со статусом.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.clock import utcnow
from app.domain.ops.models import BackupRun
from tests.db_support import run_alembic


@pytest.mark.committed
async def test_009_migration_0011_upgrade_downgrade_upgrade_and_check(
    committed: Any, test_database_url: str
) -> None:
    async def alembic(*args: str) -> None:
        result = await asyncio.to_thread(run_alembic, test_database_url, *args)
        assert result.returncode == 0, (
            f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
        )

    await alembic("upgrade", "head")
    await alembic("downgrade", "0009")
    await alembic("upgrade", "head")
    await alembic("check")


def _run(**overrides: Any) -> BackupRun:
    now = utcnow()
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "started_at": now - timedelta(seconds=3),
        "finished_at": now,
        "status": "ok",
        "size_bytes": 1024,
        "schema_revision": "0011",
        "file_name": "gtrack-backup-20261108T000000Z.tar",
        "error_code": None,
    }
    values.update(overrides)
    return BackupRun(**values)


async def test_009_backup_run_ok_and_failed_rows_are_stored(db: Any) -> None:
    db.add(_run())
    db.add(_run(status="failed", size_bytes=None, file_name=None, error_code="pg_dump_failed"))
    await db.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "partial"},
        {"status": "ok", "error_code": "pg_dump_failed"},
        {"status": "failed", "error_code": None},
        {"size_bytes": -1},
    ],
    ids=["bad-status", "ok-with-error", "failed-without-error", "negative-size"],
)
async def test_009_backup_run_constraints(db: Any, overrides: dict[str, Any]) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_run(**overrides))
            await db.flush()


async def test_009_backup_run_finished_before_started_is_rejected(db: Any) -> None:
    now = utcnow()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_run(started_at=now, finished_at=now - timedelta(seconds=1)))
            await db.flush()
