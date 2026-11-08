"""Формат архива экспорта/импорта (plan §4.10, FR-40, ADR-0010, З-10).

Архив — tar без сжатия с одним членом ``data.json``::

    {"format": "gtrack-export", "schema_version": "<alembic head>",
     "exported_at": "<UTC>", "tables": {"<table>": [rows...]}}

Строки отсортированы по первичному ключу; ключи JSON отсортированы; ``uuid`` — строки,
``timestamptz`` — ISO 8601 UTC с микросекундами и ``Z``, ``date`` — ``YYYY-MM-DD``.
Сессии (``user_session``), таблицы сброса пароля (``password_reset_token``,
``password_reset_attempt``), заявки и попытки самостоятельной регистрации
(``registration_request``, ``registration_attempt``) и колонка ``app_user.email``
не выгружаются. Неподтверждённые заявки и токены в архив не попадают; имя, фамилия
и ``self_registered`` учётных записей выгружаются (ADR-0019).
Файлы живых вложений (spec 011 FR-11) — члены ``files/<storage_key>``; при импорте их набор и sha256
сверяются со строками ``attachment`` из ``data.json``.
Всё, что не совпадает с ожидаемым форматом, отвергается как ``ImportRefused``.
"""

from __future__ import annotations

import io
import json
import os
import re
import tarfile
from collections.abc import Iterator, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import IO, Any, Final
from uuid import UUID

import sqlalchemy as sa

# Регистрация всех таблиц в Base.metadata до обхода (без импорта таблицы не попадут в архив).
import app.domain.attachments.models  # noqa: F401
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
# Сессии входа не переносятся: их идентификаторы — секреты текущей установки. Заявки регистрации
# содержат email и токены до подтверждения (NFR-7, ADR-0019). Попытки хранят только хеши ключей
# лимитов: IP и токены в них не записываются, но таблица служебная и в архив не входит.
# ``backup_run`` (spec 009) — журнал эксплуатации установки, не данные пространства.
EXCLUDED_TABLES: Final = frozenset(
    {
        "user_session",
        "password_reset_token",
        "password_reset_attempt",
        "registration_request",
        "registration_attempt",
        "backup_run",
    }
)
# Колонки, не попадающие в архив (персональные данные); после импорта они NULL.
EXCLUDED_COLUMNS: Final[Mapping[str, frozenset[str]]] = {"app_user": frozenset({"email"})}
MAX_DATA_BYTES: Final = 1024 * 1024 * 1024  # 1 GiB: защита от архива-бомбы
FILES_PREFIX: Final = "files/"
_FILE_MEMBER: Final = re.compile(r"files/([0-9a-f]{32})")
MAX_FILE_BYTES: Final = 64 * 1024 * 1024  # больше лимита вложения с запасом


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


def write_archive(data: bytes, out: Path, files: Mapping[str, Path] | None = None) -> None:
    """Пишет tar с ``data.json`` и ``files/<ключ>`` атомарно; файл создаётся с режимом 0600."""
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
            for key, path in sorted((files or {}).items()):
                member = tarfile.TarInfo(f"{FILES_PREFIX}{key}")
                member.size = path.stat().st_size
                member.mode = 0o600
                member.mtime = 0
                with path.open("rb") as handle:
                    tar.addfile(member, handle)
        os.chmod(tmp, 0o600)
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_archive(path: Path) -> tuple[bytes, dict[str, int]]:
    """``data.json`` и ``{ключ: размер}`` файлов вложений; прочие члены — отказ."""
    try:
        with tarfile.open(path, mode="r:") as tar:
            return _scan(tar)
    except tarfile.ReadError as exc:
        raise ImportRefused("файл не является архивом экспорта") from exc


def read_data_member(path: Path) -> bytes:
    """Читает ``data.json`` из архива (безопасное чтение, см. ``read_archive``)."""
    return read_archive(path)[0]


def iter_files(path: Path) -> Iterator[tuple[str, IO[bytes]]]:
    """Члены ``files/<ключ>`` по одному (потоково); вызывать после ``read_archive``."""
    with tarfile.open(path, mode="r:") as tar:
        for member in tar:
            match = _FILE_MEMBER.fullmatch(member.name)
            if match is None:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                raise ImportRefused(f"не удалось прочитать {member.name}")
            yield match.group(1), handle


def _scan(tar: tarfile.TarFile) -> tuple[bytes, dict[str, int]]:
    data: bytes | None = None
    files: dict[str, int] = {}
    for member in tar.getmembers():
        if not member.isreg():
            raise ImportRefused(f"недопустимый член архива: {member.name}")
        if member.name == DATA_MEMBER:
            if data is not None:
                raise ImportRefused(f"{DATA_MEMBER} встречается дважды")
            data = _member_bytes(tar, member)
            continue
        match = _FILE_MEMBER.fullmatch(member.name)
        if match is None or match.group(1) in files or member.size > MAX_FILE_BYTES:
            raise ImportRefused(
                f"архив должен содержать только {DATA_MEMBER} и {FILES_PREFIX}<ключ>"
            )
        files[match.group(1)] = member.size
    if data is None:
        raise ImportRefused(f"в архиве нет {DATA_MEMBER}")
    return data, files


def _member_bytes(tar: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    if member.size > MAX_DATA_BYTES:
        raise ImportRefused("data.json больше допустимого размера")
    handle = tar.extractfile(member)
    if handle is None:
        raise ImportRefused(f"не удалось прочитать {DATA_MEMBER}")
    return handle.read()


def expected_files(rows: Mapping[str, list[dict[str, Any]]]) -> dict[str, tuple[str, int]]:
    """Файлы, которые должны быть в архиве: живые вложения ``{ключ: (sha256, размер)}``."""
    return {
        str(r["storage_key"]): (str(r["sha256"]), int(r["size_bytes"]))
        for r in rows.get("attachment", [])
        if r.get("deleted_at") is None
    }


def match_files(expected: Mapping[str, tuple[str, int]], present: Mapping[str, int]) -> None:
    """Набор и размеры файлов архива совпадают с живыми вложениями ``data.json``."""
    if set(expected) != set(present):
        raise ImportRefused("файлы вложений в архиве не совпадают с data.json")
    for key, (_sha, size) in expected.items():
        if present[key] != size:
            raise ImportRefused(f"размер файла вложения {key} не совпадает с data.json")
