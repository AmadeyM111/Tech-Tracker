"""Экспорт рабочего пространства в архив (plan §4.10, FR-40, AC-17).

Все строки читаются в одной транзакции ``REPEATABLE READ``, чтобы архив был согласован.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings
from app.core.db import create_engine
from app.domain.attachments.storage import final_path
from app.domain.ops.archive import (
    FORMAT,
    encode_value,
    expected_files,
    exported_columns,
    iso_utc,
    payload_bytes,
    tables_in_order,
    write_archive,
)


async def _read_table(conn: AsyncConnection, table: Any) -> list[dict[str, Any]]:
    primary_key = list(table.primary_key.columns)
    result = await conn.execute(select(*exported_columns(table)).order_by(*primary_key))
    return [{key: encode_value(value) for key, value in row.items()} for row in result.mappings()]


async def build_payload(
    engine: AsyncEngine, *, schema_version: str, exported_at: datetime
) -> dict[str, Any]:
    """Собирает словарь ``data.json`` из текущего состояния БД."""
    tables: dict[str, list[dict[str, Any]]] = {}
    async with engine.connect() as conn:
        await conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        for table in tables_in_order():
            tables[table.name] = await _read_table(conn, table)
    return {
        "format": FORMAT,
        "schema_version": schema_version,
        "exported_at": iso_utc(exported_at),
        "tables": tables,
    }


async def export_archive(
    settings: Settings,
    out: Path,
    *,
    schema_version: str,
    exported_at: datetime,
) -> dict[str, int]:
    """Экспортирует БД в ``out`` и возвращает число строк по таблицам."""
    engine = create_engine(settings)
    try:
        payload = await build_payload(
            engine, schema_version=schema_version, exported_at=exported_at
        )
    finally:
        await engine.dispose()
    write_archive(payload_bytes(payload), out, files=_attachment_files(settings, payload))
    return {name: len(rows) for name, rows in payload["tables"].items()}


class ExportError(RuntimeError):
    """Экспорт невозможен: данные БД и файлы вложений не согласованы."""


def _attachment_files(settings: Settings, payload: dict[str, Any]) -> dict[str, Path]:
    """Файлы живых вложений (spec 011 FR-11); отсутствующий файл — ошибка, а не тихий пропуск."""
    files: dict[str, Path] = {}
    for key, (sha, size) in expected_files(payload["tables"]).items():
        path = final_path(settings.attachments_dir, key)
        if not path.is_file():
            raise ExportError(f"нет файла вложения {key}")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        if path.stat().st_size != size or digest.hexdigest() != sha:
            raise ExportError(f"файл вложения {key} повреждён: размер или sha256 не совпадает")
        files[key] = path
    return files
