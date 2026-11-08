"""Подкоманда ``gtrack notify-due`` (spec 012 FR-4; Q-1).

Создаёт напоминания «срок завтра» и «срок прошёл» на сегодня по Москве; повторный запуск ничего не
дублирует. Таймер хоста: раз в сутки в 09:00 МСК — ``docker exec <проект>-api-1 gtrack notify-due``.
В stdout — ``due_tomorrow=N`` и ``overdue=N``; ошибки — в stderr без DSN и паролей.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli.commands.bootstrap import BootstrapError, _safe_description, wait_for_database
from app.cli.commands.maintenance import _quiet_asyncio_logger
from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.domain.notifications.due import DueReport, notify_due


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "notify-due",
        help="напоминания о сроках задач: «срок завтра» и «срок прошёл»",
        description=(
            "Создаёт уведомления исполнителям о сроке завтра и о прошедшем сроке (по Москве). "
            "Повторный запуск в тот же день ничего не дублирует. Безопасна при работающем API."
        ),
    )
    parser.set_defaults(handler=run)


async def _run(settings: Settings) -> DueReport:
    engine = create_engine(settings)
    try:
        return await notify_due(async_sessionmaker(engine, expire_on_commit=False), now=utcnow())
    finally:
        await engine.dispose()


def run(args: argparse.Namespace) -> int:  # noqa: ARG001  # сигнатура задана фреймворком
    """Выполняет ``gtrack notify-due``; возвращает код выхода (0 — успех)."""
    step = "настройки"
    settings: Settings | None = None
    try:
        settings = get_settings()
        step = "ожидание БД"
        with _quiet_asyncio_logger():
            asyncio.run(wait_for_database(settings.database_url))
            step = "напоминания"
            report = asyncio.run(_run(settings))
    except BootstrapError as exc:
        print(f"Ошибка ({step}): {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(f"Ошибка ({step}): {_safe_description(exc, settings)}", file=sys.stderr, flush=True)
        return 1
    print(f"due_tomorrow={report.due_tomorrow}")
    print(f"overdue={report.overdue}")
    sys.stdout.flush()
    return 0
