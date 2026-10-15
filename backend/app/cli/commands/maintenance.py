"""Подкоманда ``gostracker maintenance`` (plan §4.13; ревью T11, T16a).

Ждёт БД (до 60 с, как ``bootstrap``) и выполняет обслуживание (plan §10.4, D-42): удаляет
истёкшие сессии пользователей. ``--dry-run`` только считает. Секретный ключ не нужен, события
в журнал не пишутся. В stdout — ровно строки ``ключ=значение`` в порядке полей
``MaintenanceReport``; сообщения об ошибках — в stderr без DSN и паролей.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli.commands.bootstrap import BootstrapError, _safe_description, wait_for_database
from app.core.clock import FixedClock, utcnow
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.domain.ops.maintenance import MaintenanceReport, run_maintenance


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "maintenance",
        help="регулярное обслуживание: удалить истёкшие сессии пользователей",
        description=(
            "Ждёт БД (до 60 с) и выполняет обслуживание: удаляет истёкшие сессии "
            "(простой или абсолютный срок). В stdout печатаются строки ключ=значение. "
            "Безопасна при работающем API."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="только посчитать, что было бы удалено; ничего не менять",
    )
    parser.set_defaults(handler=run)


async def _maintain(settings: Settings, *, dry_run: bool) -> MaintenanceReport:
    engine = create_engine(settings)
    try:
        return await run_maintenance(
            async_sessionmaker(engine, expire_on_commit=False),
            settings,
            clock=FixedClock(utcnow()),  # один момент «сейчас» на запуск
            dry_run=dry_run,
        )
    finally:
        await engine.dispose()


@contextmanager
def _quiet_asyncio_logger() -> Iterator[None]:
    """Отладочные записи цикла событий не должны попасть в stdout (там только отчёт)."""
    asyncio_logger = logging.getLogger("asyncio")
    previous = asyncio_logger.level
    asyncio_logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        asyncio_logger.setLevel(previous)


def run(args: argparse.Namespace) -> int:
    """Выполняет ``gostracker maintenance``; возвращает код выхода (0 — успех)."""
    step = "настройки"
    try:
        settings = get_settings()
        step = "ожидание БД"
        with _quiet_asyncio_logger():
            asyncio.run(wait_for_database(settings.database_url))
            step = "удаление истёкших сессий"
            report = asyncio.run(_maintain(settings, dry_run=bool(args.dry_run)))
    except BootstrapError as exc:
        print(f"Ошибка ({step}): {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(f"Ошибка ({step}): {_safe_description(exc)}", file=sys.stderr, flush=True)
        return 1
    for field in dataclasses.fields(report):
        print(f"{field.name}={int(getattr(report, field.name))}")
    sys.stdout.flush()
    return 0
