"""Формат архива экспорта/импорта (plan §4.10, FR-40, ADR-0010, З-10).

Архив — tar без сжатия с одним членом ``data.json``::

    {"format": "gtrack-export", "schema_version": "<alembic head>",
     "exported_at": "<UTC>", "tables": {"<table>": [rows...]}}

Строки отсортированы по первичному ключу; ключи JSON отсортированы; ``uuid`` — строки,
``timestamptz`` — ISO 8601 UTC с микросекундами и ``Z``, ``date`` — ``YYYY-MM-DD``.
Сессии (``user_session``), таблицы сброса пароля (``password_reset_token``,
``password_reset_attempt``) и колонка ``app_user.email`` не выгружаются.
Членов ``files/`` в этой версии нет: вложений в схеме пока нет.
Всё, что не совпадает с ожидаемым форматом, отвергается как ``ImportRefused``.
"""

from __future__ import annotations

import io
import json
import os
import tarfile
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa

# Регистрация всех таблиц в Base.metadata до обхода (без импорта таблицы не попадут в архив).
import app.domain.auth.models  # noqa: F401
import app.domain.comments.models  # noqa: F401
import app.domain.events.models  # noqa: F401
import app.domain.projects.models  # noqa: F401
import app.domain.tasks.models  # noqa: F401
import app.domain.users.models  # noqa: F401
import app.domain.workspaces.models  # noqa: F401
from app.core.models import Base

FORMAT: Final = "gtrack-export"
# Архивы, созданные до переименования (GOSTracker): импорт принимает и этот формат.
LEGACY_FORMAT: Final = "gostracker-export"
ACCEPTED_FORMATS: Final = frozenset({FORMAT, LEGACY_FORMAT})
DATA_MEMBER: Final = "data.json"
# Сессии входа не переносятся: их идентификаторы — секреты текущей установки.
EXCLUDED_TABLES: Final = frozenset(
    {"user_session", "password_reset_token", "password_reset_attempt"}
)
# Колонки, не попадающие в архив (персональные данные); после импорта они NULL.
EXCLUDED_COLUMNS: Final[Mapping[str, frozenset[str]]] = {"app_user": frozenset({"email"})}
MAX_DATA_BYTES: Final = 1024 * 1024 * 1024  # 1 GiB: защита от архива-бомбы


class ImportRefused(Exception):
    """Отказ по условиям (код выхода 2): непустая система, другая версия схемы, плохой архив."""


def tables_in_order() -> list[sa.Table]:
    """Таблицы для выгрузки в порядке зависимостей FK: родители раньше потомков."""
    return [t for t in Base.metadata.sorted_tables if t.name not in EXCLUDED_TABLES]


def exported_columns(table: sa.Table) -> list[sa.Column[Any]]:
    """Колонки таблицы, входящие в архив (без ``EXCLUDED_COLUMNS``)."""
    skipped = EXCLUDED_COLUMNS.get(table.name, frozenset())
    return [column for column in table.columns if column.name not in skipped]


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise ValueError("метка времени без часового пояса")
    return value.astimezone(UTC)


def encode_value(value: Any) -> Any:
    """Значение строки → JSON-совместимое значение."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):  # datetime — подкласс date, проверяем раньше
        return iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def decode_value(column: sa.Column[Any], value: Any) -> Any:
    """JSON-значение → значение для вставки, по типу колонки."""
    if value is None:
        return None
    if isinstance(column.type, sa.Uuid):
        return UUID(value)
    if isinstance(column.type, sa.DateTime):
        return _parse_utc(value)
    if isinstance(column.type, sa.Date):
        return date.fromisoformat(value)
    return value


def payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def write_archive(data: bytes, out: Path) -> None:
    """Пишет tar с ``data.json`` атомарно; файл создаётся с режимом 0600."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".partial")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w") as tar:
            info = tarfile.TarInfo(DATA_MEMBER)
            info.size = len(data)
            info.mode = 0o600
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
        os.chmod(tmp, 0o600)
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_data_member(path: Path) -> bytes:
    """Читает ``data.json`` из архива; любые другие члены — отказ (безопасное чтение)."""
    try:
        with tarfile.open(path, mode="r:") as tar:
            return _single_member_bytes(tar)
    except tarfile.ReadError as exc:
        raise ImportRefused("файл не является архивом экспорта") from exc


def _single_member_bytes(tar: tarfile.TarFile) -> bytes:
    members = tar.getmembers()
    if len(members) != 1 or members[0].name != DATA_MEMBER or not members[0].isreg():
        raise ImportRefused(f"архив должен содержать только {DATA_MEMBER}")
    member = members[0]
    if member.size > MAX_DATA_BYTES:
        raise ImportRefused("data.json больше допустимого размера")
    handle = tar.extractfile(member)
    if handle is None:
        raise ImportRefused(f"не удалось прочитать {DATA_MEMBER}")
    return handle.read()
