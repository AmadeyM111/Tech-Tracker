"""R8-T13: экспорт и импорт имён, без заявок и попыток регистрации (spec 019, AC-37, plan §4.5).

Покрытие: архив содержит ``first_name``, ``last_name`` и ``self_registered`` учётной записи,
созданной регистрацией, и не содержит её ``email``; ``registration_request`` и
``registration_attempt`` не выгружаются даже при наличии строк; импорт в пустую БД восстанавливает
имя и фамилию, ``email`` остаётся NULL; импорт очищает заявки и попытки приёмника; цикл
экспорт → импорт → экспорт идентичен (ADR-0010, ADR-0019).
"""

from __future__ import annotations

import tarfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.cli.commands.export import schema_head
from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.models import Base
from app.domain.ops import archive, importer
from app.domain.ops.archive import (
    DATA_MEMBER,
    ImportRefused,
    exported_columns,
    payload_bytes,
    tables_in_order,
    write_archive,
)
from app.domain.ops.demo import load_demo_data
from app.domain.ops.export import build_payload
from app.domain.ops.importer import import_archive, parse_rows
from app.domain.system.bootstrap import run_bootstrap
from tests.conftest import FIXED_NOW, _reset_schema
from tests.factories import WorkspaceRow, make_user

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

pytestmark = pytest.mark.committed

FIRST_ADMIN_PASSWORD = "Zq7Lm2Vx9FirstAdminPw"
ANNA_EMAIL = "anna.petrova@example.ru"
ANNA_FIRST = "Анна"
ANNA_LAST = "Петрова-Иванова"
PENDING_EMAIL = "pending@example.ru"
PENDING_LAST = "Сидоров"
REGISTRATION_TABLES = ("registration_request", "registration_attempt")


async def _bootstrap(sm: async_sessionmaker[Any], settings: Settings) -> None:
    await run_bootstrap(
        sm, settings, clock=FixedClock(FIXED_NOW), generate=lambda: FIRST_ADMIN_PASSWORD
    )


async def _scalar(engine: AsyncEngine, sql: str, params: dict[str, Any] | None = None) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params or {})).scalar_one()


async def _export_payload(engine: AsyncEngine) -> dict[str, Any]:
    return await build_payload(engine, schema_version=schema_head(), exported_at=FIXED_NOW)


def _strip_timestamp(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "exported_at"}


def _data_member_text(path: Path) -> str:
    with tarfile.open(path) as tar:
        member = tar.extractfile(DATA_MEMBER)
        assert member is not None
        return member.read().decode("utf-8")


async def _add_anna(sm: async_sessionmaker[Any]) -> UUID:
    """Учётная запись, созданная самостоятельной регистрацией: имя, фамилия, email, флаг."""
    async with sm() as db:
        workspace_id = (
            await db.execute(text("SELECT id FROM workspace ORDER BY created_at LIMIT 1"))
        ).scalar_one()
        user = await make_user(
            db,
            workspace=WorkspaceRow(id=workspace_id, created_at=FIXED_NOW),
            login="anna.petrova",
            email=ANNA_EMAIL,
            first_name=ANNA_FIRST,
            last_name=ANNA_LAST,
            self_registered=True,
        )
        await db.commit()
    return user.id


async def _seed_registration_rows(engine: AsyncEngine) -> None:
    """Неподтверждённая заявка с email и попытка регистрации (строки есть в БД)."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO registration_request (id, email, login, login_display, first_name,"
                " last_name, password_hash, token_hash, created_at, expires_at)"
                " VALUES (gen_random_uuid(), :email, 'ivan.sidorov', 'Ivan.Sidorov', 'Иван',"
                " :last, 'hash', :th, now(), now() + interval '30 minutes')"
            ),
            {"email": PENDING_EMAIL, "last": PENDING_LAST, "th": b"\x03" * 32},
        )
        await conn.execute(
            text(
                "INSERT INTO registration_attempt (id, scope, key_hash, created_at)"
                " VALUES (gen_random_uuid(), 'request_ip', :h, now())"
            ),
            {"h": b"\x04" * 32},
        )


@pytest_asyncio.fixture
async def anna_system(
    committed: async_sessionmaker[Any], db_engine: AsyncEngine, settings: Settings
) -> AsyncIterator[tuple[async_sessionmaker[Any], AsyncEngine, Settings, UUID]]:
    """Система с первым ТА, демо-данными и учётной записью «Анна» (зарегистрирована)."""
    await _bootstrap(committed, settings)
    await load_demo_data(committed, settings, clock=FixedClock(FIXED_NOW), seed=1)
    anna_id = await _add_anna(committed)
    yield committed, db_engine, settings, anna_id


async def test_019_archive_keeps_names_and_self_registered_without_email(
    anna_system: tuple[async_sessionmaker[Any], AsyncEngine, Settings, UUID],
    tmp_path: Path,
) -> None:
    _sm, engine, _settings, anna_id = anna_system
    assert await _scalar(engine, "SELECT email FROM app_user WHERE id = :id", {"id": anna_id}) == (
        ANNA_EMAIL
    )

    payload = await _export_payload(engine)
    rows = [row for row in payload["tables"]["app_user"] if row["id"] == str(anna_id)]
    assert len(rows) == 1
    anna = rows[0]
    assert anna["first_name"] == ANNA_FIRST
    assert anna["last_name"] == ANNA_LAST
    assert anna["self_registered"] is True
    assert "email" not in anna

    archive_path = tmp_path / "export.tar"
    write_archive(payload_bytes(payload), archive_path)
    raw = _data_member_text(archive_path)
    assert ANNA_EMAIL not in raw
    assert '"email"' not in raw
    assert ANNA_FIRST in raw
    assert ANNA_LAST in raw


async def test_019_archive_excludes_registration_tables_even_with_rows(
    anna_system: tuple[async_sessionmaker[Any], AsyncEngine, Settings, UUID],
    tmp_path: Path,
) -> None:
    _sm, engine, _settings, _anna_id = anna_system
    await _seed_registration_rows(engine)
    assert await _scalar(engine, "SELECT count(*) FROM registration_request") == 1
    assert await _scalar(engine, "SELECT count(*) FROM registration_attempt") == 1

    payload = await _export_payload(engine)
    for name in REGISTRATION_TABLES:
        assert name not in payload["tables"]

    archive_path = tmp_path / "export.tar"
    write_archive(payload_bytes(payload), archive_path)
    raw = _data_member_text(archive_path)
    assert PENDING_EMAIL not in raw
    assert PENDING_LAST not in raw
    for name in REGISTRATION_TABLES:
        assert name not in raw


async def test_019_import_into_empty_db_restores_names_and_leaves_email_null(
    anna_system: tuple[async_sessionmaker[Any], AsyncEngine, Settings, UUID],
    test_database_url: str,
    tmp_path: Path,
) -> None:
    sm, engine, settings, anna_id = anna_system
    archive_path = tmp_path / "export.tar"
    write_archive(payload_bytes(await _export_payload(engine)), archive_path)

    await _reset_schema(engine, test_database_url)
    await _bootstrap(sm, settings)
    await import_archive(settings, archive_path, schema_version=schema_head())

    async with engine.connect() as conn:
        restored = (
            await conn.execute(
                text(
                    "SELECT first_name, last_name, self_registered, email"
                    " FROM app_user WHERE id = :id"
                ),
                {"id": anna_id},
            )
        ).one()
    assert tuple(restored) == (ANNA_FIRST, ANNA_LAST, True, None)


async def test_019_import_clears_receiver_registration_rows(
    anna_system: tuple[async_sessionmaker[Any], AsyncEngine, Settings, UUID],
    test_database_url: str,
    tmp_path: Path,
) -> None:
    sm, engine, settings, _anna_id = anna_system
    archive_path = tmp_path / "export.tar"
    write_archive(payload_bytes(await _export_payload(engine)), archive_path)

    await _reset_schema(engine, test_database_url)
    await _bootstrap(sm, settings)
    await _seed_registration_rows(engine)  # у приёмника есть заявка и попытка
    assert await _scalar(engine, "SELECT count(*) FROM registration_request") == 1

    await import_archive(settings, archive_path, schema_version=schema_head())

    for name in REGISTRATION_TABLES:
        assert await _scalar(engine, f"SELECT count(*) FROM {name}") == 0


async def test_019_roundtrip_with_names_and_pending_requests_is_identical(
    anna_system: tuple[async_sessionmaker[Any], AsyncEngine, Settings, UUID],
    test_database_url: str,
    tmp_path: Path,
) -> None:
    sm, engine, settings, anna_id = anna_system
    await _seed_registration_rows(engine)
    first = await _export_payload(engine)
    archive_path = tmp_path / "export.tar"
    write_archive(payload_bytes(first), archive_path)

    await _reset_schema(engine, test_database_url)
    await _bootstrap(sm, settings)
    await import_archive(settings, archive_path, schema_version=schema_head())

    second = await _export_payload(engine)
    assert payload_bytes(_strip_timestamp(second)) == payload_bytes(_strip_timestamp(first))
    anna = next(row for row in second["tables"]["app_user"] if row["id"] == str(anna_id))
    assert anna["first_name"] == ANNA_FIRST
    assert anna["last_name"] == ANNA_LAST


@pytest.mark.parametrize("name", REGISTRATION_TABLES)
async def test_019_archive_with_registration_table_is_refused(
    anna_system: tuple[async_sessionmaker[Any], AsyncEngine, Settings, UUID], name: str
) -> None:
    _sm, engine, _settings, _anna_id = anna_system
    payload = await _export_payload(engine)
    payload["tables"][name] = []
    with pytest.raises(ImportRefused, match="набор таблиц"):
        parse_rows(payload_bytes(payload), schema_version=schema_head())


def test_019_registration_tables_are_excluded_and_names_exported() -> None:
    assert set(REGISTRATION_TABLES) <= set(archive.EXCLUDED_TABLES)
    assert {table.name for table in tables_in_order()}.isdisjoint(REGISTRATION_TABLES)
    assert tuple(importer.AUTO_TABLES[:2]) == REGISTRATION_TABLES

    app_user = Base.metadata.tables["app_user"]
    names = {column.name for column in exported_columns(app_user)}
    assert {"first_name", "last_name", "self_registered"} <= names
    assert "email" not in names
