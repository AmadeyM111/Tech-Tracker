"""``gostracker export`` / ``gostracker import`` (plan §4.10, FR-40, AC-17, AC-93, ADR-0010).

Покрытие: цикл экспорт → импорт → экспорт даёт идентичный ``data.json`` (метка ``exported_at``
не сравнивается); файл архива с режимом 0600; сброс файла с паролем первого ТА; синхронизация
последовательности ``domain_event.id``; отказ при непустой системе, другой версии схемы и
небезопасном архиве (отказ = код 2, БД не меняется); коды выхода CLI.
"""

from __future__ import annotations

import asyncio
import io
import json
import stat
import tarfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from app.cli.commands.export import schema_head
from app.core.clock import FixedClock
from app.core.config import Settings, get_settings
from app.domain.ops.archive import DATA_MEMBER, ImportRefused, payload_bytes, write_archive
from app.domain.ops.demo import load_demo_data
from app.domain.ops.export import build_payload
from app.domain.ops.importer import import_archive, parse_rows
from app.domain.system.bootstrap import INITIAL_ADMIN_FILE, run_bootstrap
from app.domain.users.models import AppUser
from tests.conftest import FIXED_NOW, _reset_schema
from tests.db_support import ALEMBIC_INI

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

pytestmark = pytest.mark.committed

FIRST_ADMIN_PASSWORD = "Zq7Lm2Vx9FirstAdminPw"


async def _bootstrap(sm: async_sessionmaker[Any], settings: Settings) -> None:
    await run_bootstrap(
        sm, settings, clock=FixedClock(FIXED_NOW), generate=lambda: FIRST_ADMIN_PASSWORD
    )


async def _count(engine: AsyncEngine, model: type[Any]) -> int:
    async with engine.connect() as conn:
        table = model.__table__
        return int((await conn.execute(select(func.count()).select_from(table))).scalar_one())


async def _export_payload(engine: AsyncEngine) -> dict[str, Any]:
    return await build_payload(engine, schema_version=schema_head(), exported_at=FIXED_NOW)


def _strip_timestamp(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "exported_at"}


@pytest_asyncio.fixture
async def filled(
    committed: async_sessionmaker[Any], db_engine: AsyncEngine, settings: Settings
) -> AsyncIterator[tuple[async_sessionmaker[Any], AsyncEngine, Settings]]:
    """Система с первым ТА и демо-данными (проекты, задачи, комментарии, события)."""
    await _bootstrap(committed, settings)
    await load_demo_data(committed, settings, clock=FixedClock(FIXED_NOW), seed=1)
    yield committed, db_engine, settings


async def test_roundtrip_export_import_export_is_identical(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
    test_database_url: str,
    tmp_path: Path,
) -> None:
    sm, engine, settings = filled
    first = await _export_payload(engine)
    assert first["format"] == "gostracker-export"
    assert len(first["tables"]["task"]) > 0
    assert len(first["tables"]["domain_event"]) > 0
    assert "user_session" not in first["tables"]

    archive = tmp_path / "export.tar"
    write_archive(payload_bytes(first), archive)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600

    # Пустая установка: сбрасываем схему и заново создаём только первого ТА.
    await _reset_schema(engine, test_database_url)
    await _bootstrap(sm, settings)
    assert (settings.secrets_dir / INITIAL_ADMIN_FILE).exists()

    counts = await import_archive(settings, archive, schema_version=schema_head())
    assert counts["task"] == len(first["tables"]["task"])

    second = await _export_payload(engine)
    assert _strip_timestamp(second) == _strip_timestamp(first)
    assert payload_bytes(_strip_timestamp(second)) == payload_bytes(_strip_timestamp(first))
    # файл с паролем первого ТА удалён после фиксации
    assert not (settings.secrets_dir / INITIAL_ADMIN_FILE).exists()


async def test_import_syncs_domain_event_sequence(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
    test_database_url: str,
    tmp_path: Path,
) -> None:
    sm, engine, settings = filled
    archive = tmp_path / "export.tar"
    payload = await _export_payload(engine)
    write_archive(payload_bytes(payload), archive)
    max_id = max(row["id"] for row in payload["tables"]["domain_event"])

    await _reset_schema(engine, test_database_url)
    await _bootstrap(sm, settings)
    await import_archive(settings, archive, schema_version=schema_head())

    async with engine.begin() as conn:
        seq = (
            await conn.execute(text("SELECT pg_get_serial_sequence('domain_event', 'id')"))
        ).scalar_one()
        next_id = (await conn.execute(text(f"SELECT nextval('{seq}')"))).scalar_one()
    assert next_id > max_id


async def test_import_refused_into_non_empty_system(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
    tmp_path: Path,
) -> None:
    _sm, engine, settings = filled
    archive = tmp_path / "export.tar"
    write_archive(payload_bytes(await _export_payload(engine)), archive)
    users_before = await _count(engine, AppUser)

    with pytest.raises(ImportRefused, match="не пуста"):
        await import_archive(settings, archive, schema_version=schema_head())

    assert await _count(engine, AppUser) == users_before


async def test_import_refused_on_other_schema_version(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
) -> None:
    _sm, engine, _settings = filled
    payload = await _export_payload(engine)
    payload["schema_version"] = "0001"
    with pytest.raises(ImportRefused, match="версия схемы"):
        parse_rows(payload_bytes(payload), schema_version=schema_head())


def _tar_with(members: dict[str, bytes], path: Path) -> Path:
    with tarfile.open(path, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


@pytest.mark.parametrize(
    "members",
    [
        {DATA_MEMBER: b"{}", "files/0123456789abcdef0123456789abcdef": b"x"},
        {"../evil.json": b"{}"},
        {"other.json": b"{}"},
    ],
    ids=["extra-file", "path-traversal", "wrong-name"],
)
def test_unsafe_archive_is_refused(tmp_path: Path, members: dict[str, bytes]) -> None:
    from app.domain.ops.archive import read_data_member

    archive = _tar_with(members, tmp_path / "bad.tar")
    with pytest.raises(ImportRefused):
        read_data_member(archive)


def test_non_archive_is_refused(tmp_path: Path) -> None:
    from app.domain.ops.archive import read_data_member

    plain = tmp_path / "plain.tar"
    plain.write_text("not a tar", encoding="utf-8")
    with pytest.raises(ImportRefused, match="не является архивом"):
        read_data_member(plain)


def test_parse_rows_rejects_wrong_format(tmp_path: Path) -> None:
    raw = json.dumps({"format": "other", "schema_version": "x", "tables": {}}).encode()
    with pytest.raises(ImportRefused, match="формат"):
        parse_rows(raw, schema_version="x")


# --- CLI --------------------------------------------------------------------------------


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_database_url: str
) -> Iterator[Path]:
    data_dir = tmp_path / "data"
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_MEMORY_COST_KIB", "1024")
    monkeypatch.setenv("ARGON2_PARALLELISM", "1")
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ALEMBIC_INI))
    get_settings.cache_clear()
    yield data_dir
    get_settings.cache_clear()


def _run(argv: list[str]) -> int:
    from app.cli.main import main

    try:
        return int(main(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)


async def test_cli_export_and_import_exit_codes(
    committed: async_sessionmaker[Any],
    db_engine: AsyncEngine,
    cli_env: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = get_settings()
    await _bootstrap(committed, settings)
    await load_demo_data(committed, settings, clock=FixedClock(FIXED_NOW), seed=1)
    archive = tmp_path / "cli.tar"

    assert await asyncio.to_thread(_run, ["export", "--out", str(archive)]) == 0
    assert archive.exists()
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert f"archive={archive}" in capsys.readouterr().out

    # файл уже есть — экспорт не перезаписывает его
    assert await asyncio.to_thread(_run, ["export", "--out", str(archive)]) == 2

    # непустая система — импорт отказан с кодом 2, данные не тронуты
    users_before = await _count(db_engine, AppUser)
    assert await asyncio.to_thread(_run, ["import", str(archive)]) == 2
    assert await _count(db_engine, AppUser) == users_before

    # нет файла — ошибка выполнения
    missing = tmp_path / "missing.tar"
    assert await asyncio.to_thread(_run, ["import", str(missing)]) == 1


async def test_cli_import_into_empty_system_succeeds(
    committed: async_sessionmaker[Any],
    db_engine: AsyncEngine,
    cli_env: Path,
    tmp_path: Path,
    test_database_url: str,
) -> None:
    settings = get_settings()
    await _bootstrap(committed, settings)
    await load_demo_data(committed, settings, clock=FixedClock(FIXED_NOW), seed=1)
    archive = tmp_path / "cli.tar"
    assert await asyncio.to_thread(_run, ["export", "--out", str(archive)]) == 0

    await _reset_schema(db_engine, test_database_url)
    await _bootstrap(committed, settings)
    assert await asyncio.to_thread(_run, ["import", str(archive)]) == 0
    assert await _count(db_engine, AppUser) > 1
    assert not (settings.secrets_dir / INITIAL_ADMIN_FILE).exists()
