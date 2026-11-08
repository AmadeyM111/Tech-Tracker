"""Резервная копия и восстановление (spec 009 FR-1…FR-5, FR-8; plan PB-1…PB-4, PB-8).

Архив ``gtrack-backup-<UTC>.tar`` (0600) из трёх членов: ``manifest.json``, ``db.dump``
(``pg_dump -Fc``) и ``appdata.tar`` (``DATA_DIR`` без ``exports/``). Архив собирается во временном
каталоге внутри ``out_dir``, проверяется (sha256, ``pg_restore --list``, чтение tar) и только
потом получает итоговое имя; ротация удаляет лишь файлы с итоговым шаблоном имени.

Пароль БД передаётся инструментам только через ``PGPASSWORD`` (NFR-2): в argv, лог и тексты
исключений он не попадает. Ошибки — ``BackupError`` с машинным кодом для ``backup_run``.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Final

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.domain.ops.archive import iso_utc
from app.domain.ops.models import BackupRun, BackupRunStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

FORMAT: Final = "gtrack-backup"
FORMAT_VERSION: Final = 1
MANIFEST: Final = "manifest.json"
DB_MEMBER: Final = "db.dump"
APPDATA_MEMBER: Final = "appdata.tar"
MEMBERS: Final = (MANIFEST, DB_MEMBER, APPDATA_MEMBER)
NAME_RE: Final = re.compile(r"gtrack-backup-(\d{8}T\d{6}Z)\.tar")
EXCLUDED_DATA: Final = frozenset({"exports", "lost+found"})
_CHUNK: Final = 1024 * 1024
MAX_MANIFEST_BYTES: Final = 64 * 1024

# argv, env (только PG*), stdin, stdout. Ненулевой код — ``BackupError``.
Runner = Callable[[Sequence[str], Mapping[str, str], IO[bytes] | None, IO[bytes] | None], None]


class BackupError(Exception):
    """Сбой копии или восстановления; ``code`` пишется в ``backup_run.error_code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RestoreRefused(Exception):
    """Отказ восстановления по условиям (код выхода 2): цель не пуста."""


@dataclass(frozen=True)
class BackupResult:
    path: Path
    size_bytes: int
    schema_revision: str
    same_device: bool
    removed: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    created_at: str
    schema_revision: str
    app_version: str
    members: Mapping[str, Mapping[str, Any]]


def backup_name(now: datetime) -> str:
    return f"gtrack-backup-{now.strftime('%Y%m%dT%H%M%SZ')}.tar"


def libpq_env(database_url: str) -> dict[str, str]:
    """Параметры подключения для ``pg_dump``/``pg_restore``; пароль — только в ``PGPASSWORD``."""
    url = make_url(database_url)
    env = {
        "PGHOST": url.host or "localhost",
        "PGPORT": str(url.port or 5432),
        "PGDATABASE": url.database or "",
        "PGCONNECT_TIMEOUT": "10",
    }
    if url.username:
        env["PGUSER"] = url.username
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    return env


def tool(settings: Settings, name: str) -> str:
    """Путь к инструменту PostgreSQL: ``pg_bin_dir`` или ``PATH``; нет — ``BackupError``."""
    if settings.pg_bin_dir is not None:
        candidate = settings.pg_bin_dir / name
        if candidate.is_file():
            return str(candidate)
    else:
        found = shutil.which(name)
        if found:
            return found
    raise BackupError("tool_missing", f"не найден {name} (клиент PostgreSQL 16)")


def run_tool(
    argv: Sequence[str],
    env: Mapping[str, str],
    stdin: IO[bytes] | None,
    stdout: IO[bytes] | None,
) -> None:
    """Запуск инструмента; stderr не выводится (может содержать имена объектов БД)."""
    base = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    proc = subprocess.run(  # noqa: S603  # argv собран кодом, без shell
        list(argv),
        env={**base, **env},
        stdin=stdin if stdin is not None else subprocess.DEVNULL,
        stdout=stdout if stdout is not None else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        name = Path(argv[0]).name
        raise BackupError(f"{name.replace('-', '_')}_failed", f"{name}: код {proc.returncode}")


def _private_file(path: Path) -> IO[bytes]:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, "wb")


def _digest(stream: IO[bytes]) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    while chunk := stream.read(_CHUNK):
        h.update(chunk)
        size += len(chunk)
    return size, h.hexdigest()


def _file_digest(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        size, sha = _digest(f)
    return {"size": size, "sha256": sha}


def _appdata_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(info.name).parts
    top = parts[1] if len(parts) > 1 and parts[0] == "." else (parts[0] if parts else "")
    if top in EXCLUDED_DATA:
        return None
    if not (info.isfile() or info.isdir()):
        return None  # ссылки и устройства не копируются
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def _write_appdata(data_dir: Path, dest: Path) -> None:
    if not data_dir.is_dir():
        raise BackupError("appdata_failed", "каталог данных не найден")
    try:
        with _private_file(dest) as raw, tarfile.open(fileobj=raw, mode="w") as tar:
            tar.add(str(data_dir), arcname=".", filter=_appdata_filter)
    except OSError as exc:
        raise BackupError("appdata_failed", f"архив данных: {type(exc).__name__}") from exc


def _write_outer(work: Path, manifest: bytes, dest: Path) -> None:
    with _private_file(dest) as raw, tarfile.open(fileobj=raw, mode="w") as tar:
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(manifest)
        info.mode = 0o600
        tar.addfile(info, io.BytesIO(manifest))
        for name in (DB_MEMBER, APPDATA_MEMBER):
            member = tar.gettarinfo(str(work / name), arcname=name)
            member.mode = 0o600
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            with (work / name).open("rb") as f:
                tar.addfile(member, f)


def _read_manifest(tar: tarfile.TarFile) -> Manifest:
    names = tar.getnames()
    if sorted(names) != sorted(MEMBERS) or len(names) != len(MEMBERS):
        raise BackupError("verify_failed", "состав архива не совпадает с форматом")
    info = tar.getmember(MANIFEST)
    if not info.isfile() or info.size > MAX_MANIFEST_BYTES:
        raise BackupError("verify_failed", "манифест повреждён")
    stream = tar.extractfile(info)
    if stream is None:
        raise BackupError("verify_failed", "манифест не читается")
    try:
        raw = json.loads(stream.read())
        if raw["format"] != FORMAT or raw["format_version"] != FORMAT_VERSION:
            raise BackupError("verify_failed", "неизвестный формат архива")
        return Manifest(
            created_at=str(raw["created_at"]),
            schema_revision=str(raw["schema_revision"]),
            app_version=str(raw["app_version"]),
            members={k: dict(raw["members"][k]) for k in (DB_MEMBER, APPDATA_MEMBER)},
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupError("verify_failed", "манифест повреждён") from exc


def _check_appdata_member(member: tarfile.TarInfo) -> None:
    """Член ``appdata.tar``: только файлы и каталоги внутри корня (защита от обхода путей)."""
    path = Path(member.name)
    if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
        raise BackupError("verify_failed", "архив данных содержит недопустимый член")


def verify_backup(
    settings: Settings, path: Path, *, extract_to: Path, runner: Runner = run_tool
) -> Manifest:
    """sha256 и размеры членов, ``pg_restore --list`` по дампу, чтение ``appdata.tar``.

    Члены извлекаются в ``extract_to`` (существующий приватный каталог); при успехе там лежат
    проверенные ``db.dump`` и ``appdata.tar``.
    """
    try:
        with tarfile.open(path, mode="r:") as tar:
            manifest = _read_manifest(tar)
            for name in (DB_MEMBER, APPDATA_MEMBER):
                info = tar.getmember(name)
                stream = tar.extractfile(info) if info.isfile() else None
                if stream is None:
                    raise BackupError("verify_failed", f"{name} не является файлом")
                with _private_file(extract_to / name) as out:
                    shutil.copyfileobj(stream, out, _CHUNK)
                if _file_digest(extract_to / name) != dict(manifest.members[name]):
                    raise BackupError("verify_failed", f"контрольная сумма {name} не совпадает")
    except tarfile.TarError as exc:
        raise BackupError("verify_failed", "файл не является архивом копии") from exc
    with (extract_to / DB_MEMBER).open("rb") as dump:
        try:
            runner([tool(settings, "pg_restore"), "--list"], {}, dump, None)
        except BackupError as exc:
            raise BackupError("verify_failed", "дамп не читается pg_restore") from exc
    try:
        with tarfile.open(extract_to / APPDATA_MEMBER, mode="r:") as inner:
            for member in inner:
                _check_appdata_member(member)
    except tarfile.TarError as exc:
        raise BackupError("verify_failed", "архив данных не читается") from exc
    return manifest


def rotate(out_dir: Path, keep: int) -> tuple[str, ...]:
    """Оставляет ``keep`` самых новых копий; другие файлы каталога не трогает."""
    if keep < 1:
        raise ValueError("keep должен быть >= 1")
    copies = sorted(p.name for p in out_dir.iterdir() if p.is_file() and NAME_RE.fullmatch(p.name))
    stale = copies[: max(0, len(copies) - keep)]
    for name in stale:
        (out_dir / name).unlink()
    return tuple(stale)


def same_device(a: Path, b: Path) -> bool:
    return os.stat(a).st_dev == os.stat(b).st_dev


def create_backup(
    settings: Settings,
    out_dir: Path,
    *,
    schema_revision: str,
    app_version: str,
    now: datetime,
    keep: int,
    runner: Runner = run_tool,
) -> BackupResult:
    """Снимает, проверяет и публикует копию, затем ротирует (FR-1…FR-3, FR-5)."""
    try:
        out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        probe = Path(tempfile.mkdtemp(prefix=".gtrack-probe-", dir=out_dir))
        probe.rmdir()
    except OSError as exc:
        raise BackupError(
            "backup_dir_unavailable", f"каталог копий недоступен для записи: {type(exc).__name__}"
        ) from exc
    final = out_dir / backup_name(now)
    if final.exists():
        raise BackupError("exists", f"файл уже существует: {final.name}")
    work = Path(tempfile.mkdtemp(prefix=".gtrack-backup-", dir=out_dir))
    try:
        with _private_file(work / DB_MEMBER) as dump:
            runner(
                [tool(settings, "pg_dump"), "-Fc", "--no-password"],
                libpq_env(settings.database_url),
                None,
                dump,
            )
        if (work / DB_MEMBER).stat().st_size == 0:
            raise BackupError("pg_dump_failed", "дамп пуст")
        _write_appdata(settings.data_dir, work / APPDATA_MEMBER)
        manifest = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "created_at": iso_utc(now),
            "schema_revision": schema_revision,
            "app_version": app_version,
            "members": {n: _file_digest(work / n) for n in (DB_MEMBER, APPDATA_MEMBER)},
        }
        partial = work / "archive.partial"
        _write_outer(work, json.dumps(manifest, sort_keys=True, indent=2).encode(), partial)
        check = work / "verify"
        check.mkdir(mode=0o700)
        verify_backup(settings, partial, extract_to=check, runner=runner)
        os.replace(partial, final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    removed = rotate(out_dir, keep)
    return BackupResult(
        path=final,
        size_bytes=final.stat().st_size,
        schema_revision=schema_revision,
        same_device=same_device(out_dir, settings.data_dir),
        removed=removed,
    )


def _data_dir_entries(data_dir: Path) -> list[str]:
    if not data_dir.exists():
        return []
    return [p.name for p in data_dir.iterdir() if p.name != "lost+found"]


async def public_tables(conn: Any) -> list[str]:
    """Таблицы схемы ``public`` целевой БД (пустая БД — пустой список)."""
    rows = await conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
    )
    return [str(r[0]) for r in rows]


def restore_backup(
    settings: Settings, archive: Path, *, db_tables: Sequence[str], runner: Runner = run_tool
) -> Manifest:
    """Разворачивает копию в пустую БД и пустой ``DATA_DIR`` (FR-8, PB-8).

    ``db_tables`` — результат ``public_tables`` целевой БД (проверка делается вызывающим до
    вызова, в его цикле событий). Сначала проверяется архив, затем пустота целей.
    """
    if not archive.is_file():
        raise BackupError("not_found", "файл копии не найден")
    work = Path(tempfile.mkdtemp(prefix=".gtrack-restore-"))
    try:
        manifest = verify_backup(settings, archive, extract_to=work, runner=runner)
        if db_tables:
            raise RestoreRefused(f"БД не пуста: таблиц в public — {len(db_tables)}")
        if _data_dir_entries(settings.data_dir):
            raise RestoreRefused("каталог данных не пуст")
        env = libpq_env(settings.database_url)
        with (work / DB_MEMBER).open("rb") as dump:
            runner(
                [
                    tool(settings, "pg_restore"),
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "--no-password",
                    "--dbname",
                    env["PGDATABASE"],
                ],
                env,
                dump,
                None,
            )
        settings.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tarfile.open(work / APPDATA_MEMBER, mode="r:") as inner:
            inner.extractall(settings.data_dir, filter="data")
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)


@dataclass(frozen=True)
class BackupRunRecord:
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None
    size_bytes: int | None = None
    schema_revision: str | None = None
    file_name: str | None = None


async def record_run(session: AsyncSession, run: BackupRunRecord) -> None:
    """Строка ``backup_run`` (FR-4): ``ok`` без ``error_code``, иначе ``failed``."""
    session.add(
        BackupRun(
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=BackupRunStatus.OK if run.error_code is None else BackupRunStatus.FAILED,
            size_bytes=run.size_bytes,
            schema_revision=run.schema_revision,
            file_name=run.file_name,
            error_code=run.error_code,
        )
    )
    await session.flush()
