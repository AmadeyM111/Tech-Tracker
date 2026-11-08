"""Подкоманда ``gtrack backup`` (spec 009 FR-1…FR-5; plan PB-1…PB-4).

Ждёт БД (до 60 с), снимает и проверяет копию в ``--out`` (по умолчанию ``BACKUP_DIR``), ротирует
до ``BACKUP_KEEP`` копий и пишет строку ``backup_run``. В stdout — строки ``ключ=значение``;
ошибки — в stderr без DSN и паролей. Коды: 0 — копия готова; 1 — сбой (строка ``failed``).
Для таймера хоста: ``docker compose -p <проект> exec -T api gtrack backup``.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import threading
from importlib import metadata
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli.commands.bootstrap import BootstrapError, _safe_description, wait_for_database
from app.cli.commands.maintenance import _quiet_asyncio_logger
from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.core.db import create_engine, transaction
from app.domain.ops.backup import (
    BackupError,
    BackupResult,
    BackupRunRecord,
    create_backup,
    record_run,
)


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "backup",
        help="резервная копия БД и каталога данных (tar 0600, проверка, ротация)",
        description=(
            "Ждёт БД (до 60 с), снимает копию БД (pg_dump -Fc) и каталога данных в один tar "
            "(0600), проверяет её, оставляет BACKUP_KEEP последних копий и пишет журнал запуска. "
            "Безопасна при работающем API."
        ),
    )
    parser.add_argument("--out", metavar="DIR", help="каталог копий (по умолчанию BACKUP_DIR)")
    parser.set_defaults(handler=run)


def app_version() -> str:
    try:
        return metadata.version("tracker-backend")
    except metadata.PackageNotFoundError:
        return "unknown"


async def _current_revision(settings: Settings) -> str:
    engine = create_engine(settings)
    try:
        async with engine.connect() as conn:
            value = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    finally:
        await engine.dispose()
    if value is None:
        raise BootstrapError("схема БД не создана: выполните gtrack bootstrap")
    return str(value)


async def _record(settings: Settings, run: BackupRunRecord) -> None:
    engine = create_engine(settings)
    try:
        async with transaction(async_sessionmaker(engine, expire_on_commit=False)) as session:
            await record_run(session, run)
    finally:
        await engine.dispose()


def _report(result: BackupResult) -> None:
    print(f"path={result.path}")
    print(f"size_bytes={result.size_bytes}")
    print(f"schema_revision={result.schema_revision}")
    print(f"same_device={int(result.same_device)}")
    print(f"removed={len(result.removed)}")
    print(f"rotate_error={int(result.rotate_error)}")
    sys.stdout.flush()


def _save_run(settings: Settings, run: BackupRunRecord) -> bool:
    try:
        asyncio.run(_record(settings, run))
    except Exception as exc:
        print(
            f"Ошибка (журнал запуска): {_safe_description(exc, settings)}",
            file=sys.stderr,
            flush=True,
        )
        return False
    return True


def _warn_result(result: BackupResult) -> None:
    if result.rotate_error:
        print("ВНИМАНИЕ: копия снята, старые копии удалить не удалось", file=sys.stderr, flush=True)
    if result.same_device:
        print(
            "ВНИМАНИЕ: каталог копий на том же устройстве, что и данные",
            file=sys.stderr,
            flush=True,
        )


def _install_sigterm() -> None:
    if threading.current_thread() is threading.main_thread():  # signal — только главный поток
        signal.signal(signal.SIGTERM, _terminate)


def _terminate(signum: int, _frame: object) -> None:
    """SIGTERM (``docker stop``, пересоздание api) → исключение: ``finally`` уберёт временные."""
    raise SystemExit(128 + signum)


def run(args: argparse.Namespace) -> int:
    """Выполняет ``gtrack backup``; возвращает код выхода."""
    _install_sigterm()
    step = "настройки"
    settings: Settings | None = None
    started = utcnow()
    try:
        settings = get_settings()
        out = Path(args.out) if args.out else settings.backup_dir
        step = "ожидание БД"
        with _quiet_asyncio_logger():
            asyncio.run(wait_for_database(settings.database_url))
            step = "версия схемы"
            revision = asyncio.run(_current_revision(settings))
        step = "копия"
        result = create_backup(
            settings,
            out,
            schema_revision=revision,
            app_version=app_version(),
            now=started,
            keep=settings.backup_keep,
        )
    except BackupError as exc:
        print(f"Ошибка ({step}): {exc}", file=sys.stderr, flush=True)
        print(f"error_code={exc.code}", flush=True)
        if settings is not None:
            with _quiet_asyncio_logger():
                _save_run(settings, BackupRunRecord(started, utcnow(), error_code=exc.code))
        return 1
    except BootstrapError as exc:
        print(f"Ошибка ({step}): {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(f"Ошибка ({step}): {_safe_description(exc, settings)}", file=sys.stderr, flush=True)
        if settings is not None and step == "копия":
            with _quiet_asyncio_logger():
                _save_run(settings, BackupRunRecord(started, utcnow(), error_code="unexpected"))
        return 1
    _warn_result(result)
    record = BackupRunRecord(
        started,
        utcnow(),
        size_bytes=result.size_bytes,
        schema_revision=result.schema_revision,
        file_name=result.path.name,
    )
    with _quiet_asyncio_logger():
        saved = _save_run(settings, record)
    _report(result)
    return 0 if saved else 1
