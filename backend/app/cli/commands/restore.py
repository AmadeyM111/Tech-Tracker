"""Подкоманда ``gtrack restore`` (spec 009 FR-8; plan PB-8).

Разворачивает копию ``gtrack backup`` на ЧИСТОМ стенде: БД без таблиц в ``public`` и пустой
``DATA_DIR``. Восстановление поверх работающей системы — ``scripts/restore.sh``. Порядок: проверка
архива (sha256, формат) → проверка пустоты целей → распаковка данных во временный каталог →
``pg_restore`` → перенос данных. Сбой на любом шаге до переноса оставляет БД и ``DATA_DIR`` пустыми.
Коды: 0 — восстановлено; 2 — отказ (нет ``--yes``, цель не пуста); 1 — ошибка или плохой архив.
После восстановления запустите api: миграции применит ``gtrack bootstrap`` при старте.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.cli.commands.bootstrap import BootstrapError, _safe_description, wait_for_database
from app.cli.commands.maintenance import _quiet_asyncio_logger
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.domain.ops.backup import BackupError, RestoreRefused, public_tables, restore_backup


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "restore",
        help="восстановить копию gtrack backup на чистом стенде (пустая БД и DATA_DIR)",
        description=(
            "Проверяет архив копии и разворачивает БД и каталог данных. Работает только с пустой "
            "БД (нет таблиц в public) и пустым DATA_DIR; иначе отказ с кодом 2."
        ),
    )
    parser.add_argument("archive", metavar="ARCHIVE", help="файл gtrack-backup-*.tar")
    parser.add_argument("--yes", action="store_true", help="подтверждение восстановления")
    parser.set_defaults(handler=run)


async def _tables(settings: Settings) -> list[str]:
    engine = create_engine(settings)
    try:
        async with engine.connect() as conn:
            return await public_tables(conn)
    finally:
        await engine.dispose()


def run(args: argparse.Namespace) -> int:
    """Выполняет ``gtrack restore``; возвращает код выхода."""
    if not args.yes:
        print("Отказ: восстановление требует --yes", file=sys.stderr, flush=True)
        return 2
    step = "настройки"
    settings: Settings | None = None
    try:
        settings = get_settings()
        step = "ожидание БД"
        with _quiet_asyncio_logger():
            asyncio.run(wait_for_database(settings.database_url))
            step = "проверка БД"
            tables = asyncio.run(_tables(settings))
        step = "восстановление"
        manifest = restore_backup(settings, Path(args.archive), db_tables=tables)
    except RestoreRefused as exc:
        print(f"Отказ: {exc}", file=sys.stderr, flush=True)
        return 2
    except (BackupError, BootstrapError) as exc:
        print(f"Ошибка ({step}): {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(f"Ошибка ({step}): {_safe_description(exc, settings)}", file=sys.stderr, flush=True)
        return 1
    print(f"created_at={manifest.created_at}")
    print(f"schema_revision={manifest.schema_revision}")
    sys.stdout.flush()
    print("Восстановлено. Запустите api: миграции применятся при старте.", file=sys.stderr)
    return 0
