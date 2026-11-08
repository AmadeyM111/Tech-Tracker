"""``gtrack export`` / ``gtrack import`` (plan §4.10, FR-40, AC-17, AC-93, ADR-0010).

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
    assert first["format"] == "gtrack-export"
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
        {DATA_MEMBER: b"{}", "files/../0123456789abcdef0123456789abcdef": b"x"},
        {DATA_MEMBER: b"{}", "files/NOT-A-KEY": b"x"},
        {"../evil.json": b"{}"},
        {"other.json": b"{}"},
    ],
    ids=["file-traversal", "file-bad-key", "path-traversal", "wrong-name"],
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


def test_parse_rows_accepts_legacy_gostracker_format_id() -> None:
    # Архив, созданный до переименования, проходит проверку формата (дальше падает на таблицах).
    from app.domain.ops.archive import ACCEPTED_FORMATS, LEGACY_FORMAT

    assert LEGACY_FORMAT == "gostracker-export"
    assert LEGACY_FORMAT in ACCEPTED_FORMATS
    raw = json.dumps({"format": LEGACY_FORMAT, "schema_version": "x", "tables": {}}).encode()
    with pytest.raises(ImportRefused) as exc:
        parse_rows(raw, schema_version="x")
    assert "неизвестный формат" not in str(exc.value)


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


# --- [007] email и служебные таблицы сброса пароля не переносятся (plan PR-14, Q-9) ----------

SOURCE_EMAIL = "owner@example.ru"
RESET_TABLES = ("password_reset_token", "password_reset_attempt")


async def _seed_reset_data(engine: AsyncEngine, *, set_email: bool = True) -> None:
    """Задаёт email всем пользователям и добавляет токен и попытку сброса."""
    async with engine.begin() as conn:
        if set_email:
            await conn.execute(
                text("UPDATE app_user SET email = 'user-' || id::text || '@example.ru'")
            )
        user_id = (
            await conn.execute(text("SELECT id FROM app_user ORDER BY created_at, id LIMIT 1"))
        ).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO password_reset_token (id, user_id, token_hash, created_at, expires_at)"
                " VALUES (gen_random_uuid(), :u, :h, now(), now() + interval '1 hour')"
            ),
            {"u": user_id, "h": b"\x01" * 32},
        )
        await conn.execute(
            text(
                "INSERT INTO password_reset_attempt (id, scope, key_hash, created_at)"
                " VALUES (gen_random_uuid(), 'email', :h, now())"
            ),
            {"h": b"\x02" * 32},
        )


async def _scalar(engine: AsyncEngine, sql: str) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql))).scalar_one()


def test_007_archive_constants_describe_exclusions() -> None:
    from app.domain.ops import archive, importer

    assert set(RESET_TABLES) <= set(archive.EXCLUDED_TABLES)
    assert "user_session" in archive.EXCLUDED_TABLES
    assert {"app_user": frozenset({"email"})} == archive.EXCLUDED_COLUMNS
    assert tuple(importer.AUTO_TABLES[:2]) == RESET_TABLES
    assert {"user_session", "workspace_member", "app_user", "workspace"} <= set(
        importer.AUTO_TABLES
    )


def test_007_tables_in_order_skips_reset_tables() -> None:
    from app.domain.ops.archive import tables_in_order

    names = {table.name for table in tables_in_order()}
    assert names.isdisjoint(RESET_TABLES)
    assert "app_user" in names


def test_007_exported_columns_drop_only_email() -> None:
    from app.core.models import Base
    from app.domain.ops.archive import exported_columns

    app_user = Base.metadata.tables["app_user"]
    names = [column.name for column in exported_columns(app_user)]
    assert "email" in app_user.c
    assert "email" not in names
    assert set(names) == {column.name for column in app_user.columns} - {"email"}
    workspace = Base.metadata.tables["workspace"]
    assert [c.name for c in exported_columns(workspace)] == [c.name for c in workspace.columns]


async def test_007_export_has_no_email_and_no_reset_tables(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
    tmp_path: Path,
) -> None:
    _sm, engine, _settings = filled
    await _seed_reset_data(engine)
    assert await _scalar(engine, "SELECT count(*) FROM app_user WHERE email IS NOT NULL") > 0

    payload = await _export_payload(engine)
    assert payload["tables"]["app_user"]
    for row in payload["tables"]["app_user"]:
        assert "email" not in row
    for name in RESET_TABLES:
        assert name not in payload["tables"]

    archive = tmp_path / "export.tar"
    write_archive(payload_bytes(payload), archive)
    with tarfile.open(archive) as tar:
        member = tar.extractfile(DATA_MEMBER)
        assert member is not None
        raw = member.read().decode("utf-8")
    assert "@example.ru" not in raw
    assert '"email"' not in raw
    for name in RESET_TABLES:
        assert name not in raw


async def test_007_import_leaves_email_null(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
    test_database_url: str,
    tmp_path: Path,
) -> None:
    sm, engine, settings = filled
    await _seed_reset_data(engine)
    archive = tmp_path / "export.tar"
    first = await _export_payload(engine)
    write_archive(payload_bytes(first), archive)

    await _reset_schema(engine, test_database_url)
    await _bootstrap(sm, settings)
    await import_archive(settings, archive, schema_version=schema_head())

    assert await _scalar(engine, "SELECT count(*) FROM app_user") == len(
        first["tables"]["app_user"]
    )
    assert await _scalar(engine, "SELECT count(*) FROM app_user WHERE email IS NOT NULL") == 0
    for name in RESET_TABLES:
        assert await _scalar(engine, f"SELECT count(*) FROM {name}") == 0


async def test_007_roundtrip_identical_with_email_in_source(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
    test_database_url: str,
    tmp_path: Path,
) -> None:
    sm, engine, settings = filled
    before_seed = await _export_payload(engine)
    await _seed_reset_data(engine)
    first = await _export_payload(engine)
    # email и токены не влияют на содержимое архива
    assert _strip_timestamp(first) == _strip_timestamp(before_seed)

    archive = tmp_path / "export.tar"
    write_archive(payload_bytes(first), archive)
    await _reset_schema(engine, test_database_url)
    await _bootstrap(sm, settings)
    await import_archive(settings, archive, schema_version=schema_head())

    second = await _export_payload(engine)
    assert payload_bytes(_strip_timestamp(second)) == payload_bytes(_strip_timestamp(first))


async def test_007_import_succeeds_when_receiver_first_admin_has_reset_token(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
    test_database_url: str,
    tmp_path: Path,
) -> None:
    sm, engine, settings = filled
    archive = tmp_path / "export.tar"
    first = await _export_payload(engine)
    write_archive(payload_bytes(first), archive)

    await _reset_schema(engine, test_database_url)
    await _bootstrap(sm, settings)
    await _seed_reset_data(engine)  # у первого ТА приёмника есть email, токен и попытка
    assert await _scalar(engine, "SELECT count(*) FROM password_reset_token") == 1

    await import_archive(settings, archive, schema_version=schema_head())

    assert await _scalar(engine, "SELECT count(*) FROM password_reset_token") == 0
    assert await _scalar(engine, "SELECT count(*) FROM password_reset_attempt") == 0
    assert await _scalar(engine, "SELECT count(*) FROM app_user WHERE email IS NOT NULL") == 0
    assert await _scalar(engine, "SELECT count(*) FROM app_user") == len(
        first["tables"]["app_user"]
    )


async def test_007_archive_with_email_key_is_refused(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
) -> None:
    _sm, engine, _settings = filled
    payload = await _export_payload(engine)
    payload["tables"]["app_user"][0]["email"] = SOURCE_EMAIL
    with pytest.raises(ImportRefused, match="не соответствуют схеме"):
        parse_rows(payload_bytes(payload), schema_version=schema_head())


async def test_007_archive_without_other_app_user_column_is_refused(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
) -> None:
    """Сверка колонок остаётся строгой: исключён только email, остальное обязательно."""
    _sm, engine, _settings = filled
    payload = await _export_payload(engine)
    del payload["tables"]["app_user"][0]["login"]
    with pytest.raises(ImportRefused, match="не соответствуют схеме"):
        parse_rows(payload_bytes(payload), schema_version=schema_head())


@pytest.mark.parametrize("name", RESET_TABLES)
async def test_007_archive_with_reset_table_is_refused(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings], name: str
) -> None:
    _sm, engine, _settings = filled
    payload = await _export_payload(engine)
    payload["tables"][name] = []
    with pytest.raises(ImportRefused, match="набор таблиц"):
        parse_rows(payload_bytes(payload), schema_version=schema_head())


async def test_007_archive_of_schema_0007_is_refused_by_version(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
) -> None:
    _sm, engine, _settings = filled
    payload = await _export_payload(engine)
    assert schema_head() != "0007"
    payload["schema_version"] = "0007"
    with pytest.raises(ImportRefused, match="версия схемы"):
        parse_rows(payload_bytes(payload), schema_version=schema_head())


# --- 011/AC-10: вложения в экспорте и импорте ------------------------------------------------


def test_011_unreferenced_or_missing_files_are_refused() -> None:
    """Файл без живого вложения или вложение без файла — отказ (``files/`` = ``data.json``)."""
    from app.domain.ops.archive import match_files

    key = "0123456789abcdef0123456789abcdef"
    with pytest.raises(ImportRefused, match="не совпадают"):
        match_files({}, {key: 1})  # бывший случай «extra-file»
    with pytest.raises(ImportRefused, match="не совпадают"):
        match_files({key: ("a" * 64, 1)}, {})
    with pytest.raises(ImportRefused, match="размер"):
        match_files({key: ("a" * 64, 1)}, {key: 2})


async def _add_attachment(sm: Any, settings: Settings, body: bytes) -> str:
    import hashlib
    import uuid

    from app.domain.attachments.models import Attachment
    from app.domain.attachments.storage import final_path
    from app.domain.projects.models import Project
    from app.domain.tasks.models import Task

    async with sm() as s:
        task = (await s.execute(select(Task).limit(1))).scalar_one()
        project = (
            await s.execute(select(Project).where(Project.id == task.project_id))
        ).scalar_one()
        key = uuid.uuid4().hex
        s.add(
            Attachment(
                workspace_id=task.workspace_id,
                task_id=task.id,
                project_id=project.id,
                created_by=project.owner_id,
                original_name="протокол.pdf",
                kind="pdf",
                content_type="application/pdf",
                size_bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
                storage_key=key,
                created_at=FIXED_NOW,
                updated_at=FIXED_NOW,
            )
        )
        await s.commit()
    path = final_path(settings.attachments_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return key


async def test_011_ac10_roundtrip_keeps_attachment_files(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
    test_database_url: str,
    tmp_path: Path,
) -> None:
    import hashlib

    from app.domain.attachments.storage import final_path
    from app.domain.ops.export import export_archive

    sm, engine, settings = filled
    body = b"%PDF-1.4 synthetic attachment"
    key = await _add_attachment(sm, settings, body)
    archive = tmp_path / "export.tar"
    await export_archive(settings, archive, schema_version=schema_head(), exported_at=FIXED_NOW)
    with tarfile.open(archive) as tar:
        assert f"files/{key}" in tar.getnames()
    first = await _export_payload(engine)

    await _reset_schema(engine, test_database_url)
    fresh = settings.model_copy(update={"data_dir": tmp_path / "fresh-data"})
    await _bootstrap(sm, fresh)
    await import_archive(fresh, archive, schema_version=schema_head())
    restored = final_path(fresh.attachments_dir, key)
    assert hashlib.sha256(restored.read_bytes()).hexdigest() == hashlib.sha256(body).hexdigest()
    second = await _export_payload(engine)
    assert _strip_timestamp(second) == _strip_timestamp(first)


async def test_011_ac10_tampered_file_is_refused_before_db(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings],
    test_database_url: str,
    tmp_path: Path,
) -> None:
    from app.domain.ops.export import export_archive

    sm, engine, settings = filled
    key = await _add_attachment(sm, settings, b"%PDF-original")
    archive = tmp_path / "export.tar"
    await export_archive(settings, archive, schema_version=schema_head(), exported_at=FIXED_NOW)
    with tarfile.open(archive) as tar:
        members = {m.name: tar.extractfile(m).read() for m in tar.getmembers()}  # type: ignore[union-attr]
    members[f"files/{key}"] = b"%PDF-changed!"  # тот же размер, другое содержимое
    bad = _tar_with(members, tmp_path / "bad.tar")

    await _reset_schema(engine, test_database_url)
    fresh = settings.model_copy(update={"data_dir": tmp_path / "fresh-data"})
    await _bootstrap(sm, fresh)
    users_before = await _count(engine, AppUser)
    with pytest.raises(ImportRefused, match="контрольная сумма"):
        await import_archive(fresh, bad, schema_version=schema_head())
    assert await _count(engine, AppUser) == users_before
    leftovers = list((fresh.attachments_dir / ".incoming").glob("*"))
    assert leftovers == []


async def test_011_export_fails_when_attachment_file_is_missing(
    filled: tuple[async_sessionmaker[Any], AsyncEngine, Settings], tmp_path: Path
) -> None:
    from app.domain.attachments.storage import final_path
    from app.domain.ops.export import ExportError, export_archive

    sm, _engine, settings = filled
    key = await _add_attachment(sm, settings, b"%PDF-x")
    final_path(settings.attachments_dir, key).unlink()
    with pytest.raises(ExportError, match=key):
        await export_archive(
            settings, tmp_path / "e.tar", schema_version=schema_head(), exported_at=FIXED_NOW
        )
