"""Импорт архива в «пустую» систему (plan §4.10, FR-40, AC-93, ADR-0010).

Порядок: разбор архива и проверка формата (до обращения к БД) → одна транзакция, в которой
берётся блокировка, проверяется пустота, удаляются автоданные первого ТА, вставляются строки
с исходными идентификаторами и синхронизируется последовательность ``domain_event.id``.
После фиксации удаляется файл с паролем первого ТА. Любой отказ откатывает транзакцию.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.core.db import create_engine
from app.core.models import Base
from app.domain.ops.archive import (
    FORMAT,
    ImportRefused,
    decode_value,
    exported_columns,
    read_data_member,
    tables_in_order,
)
from app.domain.system.bootstrap import INITIAL_ADMIN_FILE

# Таблицы, которые должны быть пустыми (кроме автоданных первого ТА и воронки по умолчанию).
BUSINESS_TABLES: Final = ("project", "project_member", "task", "comment", "domain_event")
# Автоданные установки, которые импорт заменяет; domain_event не трогается (триггер запрещает).
AUTO_TABLES: Final = (
    "password_reset_token",
    "password_reset_attempt",
    "user_session",
    "workspace_member",
    "app_user",
    "workspace",
)


def parse_rows(raw: bytes, *, schema_version: str) -> dict[str, list[dict[str, Any]]]:
    """Разбирает ``data.json``, проверяет формат и типы, возвращает строки для вставки."""
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ImportRefused("data.json не разобран как JSON") from exc
    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise ImportRefused("неизвестный формат архива")
    if payload.get("schema_version") != schema_version:
        raise ImportRefused(
            f"версия схемы архива ({payload.get('schema_version')}) не совпадает с "
            f"текущей ({schema_version})"
        )
    tables = payload.get("tables")
    expected = {table.name: table for table in tables_in_order()}
    if not isinstance(tables, dict) or set(tables) != set(expected):
        raise ImportRefused("набор таблиц архива не совпадает с текущей схемой")
    return {name: _decode_table(name, rows, expected[name]) for name, rows in tables.items()}


def _decode_table(name: str, rows: Any, table: sa.Table) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise ImportRefused(f"таблица {name} задана не списком")
    columns = {column.name for column in exported_columns(table)}
    decoded: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != columns:
            raise ImportRefused(f"строки таблицы {name} не соответствуют схеме")
        try:
            decoded.append({key: decode_value(table.c[key], value) for key, value in row.items()})
        except (ValueError, TypeError) as exc:
            raise ImportRefused(f"некорректное значение в таблице {name}") from exc
    return decoded


async def _check_empty(conn: AsyncConnection) -> None:
    """Система пуста, если нет бизнес-данных и ровно один первый ТА (автор «система»)."""
    for name in BUSINESS_TABLES:
        table = Base.metadata.tables[name]
        count = (await conn.execute(select(func.count()).select_from(table))).scalar_one()
        if count:
            raise ImportRefused(f"система не пуста: в таблице {name} есть строки")
    app_user = Base.metadata.tables["app_user"]
    first_admins = (
        await conn.execute(
            select(func.count()).select_from(app_user).where(app_user.c.created_by.is_(None))
        )
    ).scalar_one()
    if first_admins != 1:
        raise ImportRefused("система не пуста: нет ровно одного пользователя-создателя")


async def _sync_event_sequence(conn: AsyncConnection) -> None:
    sequence = (
        await conn.execute(text("SELECT pg_get_serial_sequence('domain_event', 'id')"))
    ).scalar_one()
    domain_event = Base.metadata.tables["domain_event"]
    maximum = (await conn.execute(select(func.max(domain_event.c.id)))).scalar_one()
    await conn.execute(
        text("SELECT setval(CAST(:seq AS regclass), :value, :called)"),
        {
            "seq": sequence,
            "value": maximum if maximum is not None else 1,
            "called": maximum is not None,
        },
    )


async def restore_rows(
    engine: AsyncEngine, rows: dict[str, list[dict[str, Any]]]
) -> dict[str, int]:
    """Заменяет автоданные строками архива в одной транзакции; возвращает счётчики."""
    async with engine.begin() as conn:
        await conn.execute(
            text("LOCK TABLE workspace, app_user, domain_event IN ACCESS EXCLUSIVE MODE")
        )
        await _check_empty(conn)
        await conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        for name in AUTO_TABLES:
            await conn.execute(delete(Base.metadata.tables[name]))
        for table in tables_in_order():
            batch = rows.get(table.name, [])
            if batch:
                await conn.execute(table.insert(), batch)
        await _sync_event_sequence(conn)
    return {name: len(batch) for name, batch in rows.items()}


def remove_initial_admin_file(settings: Settings) -> bool:
    """Удаляет файл с паролем первого ТА; возвращает True, если файл был."""
    path: Path = settings.secrets_dir / INITIAL_ADMIN_FILE
    if path.exists():
        path.unlink()
        return True
    return False


async def import_archive(
    settings: Settings, archive: Path, *, schema_version: str
) -> dict[str, int]:
    """Импортирует архив в пустую систему; возвращает число строк по таблицам."""
    rows = parse_rows(read_data_member(archive), schema_version=schema_version)
    engine = create_engine(settings)
    try:
        counts = await restore_rows(engine, rows)
    finally:
        await engine.dispose()
    remove_initial_admin_file(settings)
    return counts
