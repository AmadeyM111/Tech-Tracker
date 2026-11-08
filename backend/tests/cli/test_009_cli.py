"""B09-T04: ``gtrack backup``, ``gtrack restore`` и предупреждение ``gtrack bootstrap``.

AC-1, AC-3, AC-5, AC-10, AC-11 через CLI. Тесты с настоящим ``pg_dump`` требуют клиента 16.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.domain.ops.backup_status import bootstrap_warning
from app.domain.ops.models import BackupRun
from tests.backup_support import pg_bin_dir, requires_pg16
from tests.db_support import ALEMBIC_INI, run_alembic

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_database_url: str
) -> Iterator[Path]:
    data_dir = tmp_path / "data"
    (data_dir / "secrets").mkdir(parents=True)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ALEMBIC_INI))
    found = pg_bin_dir()
    if found is not None:
        monkeypatch.setenv("PG_BIN_DIR", str(found))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _run(argv: list[str]) -> int:
    from app.cli.main import main

    return int(main(argv))


async def _runs(sm: async_sessionmaker[Any]) -> list[BackupRun]:
    async with sm() as s:
        return list((await s.execute(select(BackupRun).order_by(BackupRun.finished_at))).scalars())


def _kv(out: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)


@pytest.mark.committed
@requires_pg16
async def test_009_cli_backup_ok_prints_report_and_records_run(
    committed: async_sessionmaker[Any], cli_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await asyncio.to_thread(_run, ["backup"])
    out, err = capsys.readouterr()
    assert code == 0, err
    report = _kv(out)
    assert set(report) == {
        "path",
        "size_bytes",
        "schema_revision",
        "same_device",
        "removed",
        "rotate_error",
    }
    assert report["rotate_error"] == "0"
    assert Path(report["path"]).parent == cli_env / "backups"
    assert report["same_device"] == "1" and "том же устройстве" in err
    runs = await _runs(committed)
    assert [(r.status, r.file_name) for r in runs] == [("ok", Path(report["path"]).name)]


@pytest.mark.committed
async def test_009_ac3_cli_backup_failure_records_failed_run(
    committed: async_sessionmaker[Any],
    cli_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty = cli_env / "nobin"
    empty.mkdir()
    monkeypatch.setenv("PG_BIN_DIR", str(empty))
    get_settings.cache_clear()
    code = await asyncio.to_thread(_run, ["backup"])
    out, err = capsys.readouterr()
    assert code == 1
    assert "error_code=tool_missing" in out
    assert "pg_dump" in err
    runs = await _runs(committed)
    assert [(r.status, r.error_code) for r in runs] == [("failed", "tool_missing")]
    assert not any((cli_env / "backups").glob("gtrack-backup-*.tar"))


def test_009_cli_restore_requires_yes(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(["restore", str(cli_env / "x.tar")]) == 2
    assert "--yes" in capsys.readouterr().err


@pytest.mark.committed
@requires_pg16
async def test_009_ac10_cli_restore_into_non_empty_db_is_refused(
    committed: async_sessionmaker[Any], cli_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await asyncio.to_thread(_run, ["backup"]) == 0
    path = _kv(capsys.readouterr().out)["path"]
    code = await asyncio.to_thread(_run, ["restore", path, "--yes"])
    assert code == 2
    assert "БД не пуста" in capsys.readouterr().err


@pytest.mark.committed
async def test_009_cli_restore_bad_archive_is_error(
    committed: async_sessionmaker[Any], cli_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = cli_env / "bad.tar"
    bad.write_bytes(b"not a tar")
    assert await asyncio.to_thread(_run, ["restore", str(bad), "--yes"]) == 1
    assert "не является архивом" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("current", "last_ok", "expected"),
    [
        (None, None, None),
        ("0011", None, None),
        ("0009", NOW - timedelta(hours=23, minutes=59), None),
        ("0009", NOW - timedelta(hours=24, minutes=1), "старше 24 часов"),
        ("0009", None, "нет данных"),
    ],
    ids=["fresh-install", "no-pending", "fresh-copy", "old-copy", "no-copy"],
)
def test_009_ac11_bootstrap_warning_rule(
    current: str | None, last_ok: datetime | None, expected: str | None
) -> None:
    message = bootstrap_warning(current=current, head="0011", last_ok=last_ok, now=NOW)
    if expected is None:
        assert message is None
    else:
        assert message is not None and expected in message


@pytest.mark.committed
async def test_009_ac11_bootstrap_warns_before_pending_migration(
    committed: async_sessionmaker[Any],
    cli_env: Path,
    test_database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = await asyncio.to_thread(run_alembic, test_database_url, "downgrade", "0009")
    assert result.returncode == 0, result.stderr
    code = await asyncio.to_thread(_run, ["bootstrap"])
    err = capsys.readouterr().err
    assert code == 0, err
    assert "нет данных об успешной резервной копии" in err
    capsys.readouterr()
    assert await asyncio.to_thread(_run, ["bootstrap"]) == 0
    assert "резервн" not in capsys.readouterr().err, "схема актуальна — без предупреждения"
