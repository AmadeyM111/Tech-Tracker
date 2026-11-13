"""Подкоманда ``gtrack pilot-report`` (spec 031): метрики пилота в Markdown, только чтение.

``docker exec <проект>-api-1 gtrack pilot-report --from 2026-11-09 --to 2026-11-23``.
Без аргументов - последние 14 суток. Границы — даты по Москве; ``--to`` не включается.
Запросы идут в транзакции ``READ ONLY``: ничего не пишется.
В stdout — отчёт; ошибки — в stderr без DSN и паролей.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli.commands.bootstrap import BootstrapError, _safe_description, wait_for_database
from app.cli.commands.maintenance import _quiet_asyncio_logger
from app.core.clock import MOSCOW_TZ, utcnow
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.domain.ops.pilot_metrics import ACTIVE_DAYS, collect, render_markdown

DEFAULT_DAYS = 14


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "pilot-report",
        help="метрики пилота в Markdown (только чтение)",
        description=(
            "Печатает метрики пилота за период (по Москве): пользователи, задачи, время до первой "
            "реакции, MCP и токены, вложения, упоминания. Ничего не пишет в БД."
        ),
    )
    parser.add_argument("--from", dest="since", type=date.fromisoformat, metavar="ГГГГ-ММ-ДД")
    parser.add_argument("--to", dest="until", type=date.fromisoformat, metavar="ГГГГ-ММ-ДД")
    parser.add_argument("--active-days", type=int, default=ACTIVE_DAYS, metavar="N")
    parser.set_defaults(handler=run)


def _bounds(args: argparse.Namespace, now: datetime) -> tuple[datetime, datetime]:
    today = now.astimezone(MOSCOW_TZ).date()
    until_day = args.until if args.until is not None else today + timedelta(days=1)
    since_day = args.since if args.since is not None else until_day - timedelta(days=DEFAULT_DAYS)
    if since_day >= until_day:
        raise ValueError("--from должна быть раньше --to")
    start = datetime.combine(since_day, time.min, tzinfo=MOSCOW_TZ)
    end = datetime.combine(until_day, time.min, tzinfo=MOSCOW_TZ)
    return start, end


async def _report(settings: Settings, since: datetime, until: datetime, active_days: int) -> str:
    engine = create_engine(settings)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            metrics = await collect(session, since=since, until=until, active_days=active_days)
            await session.rollback()  # читали только; транзакция ничего не фиксирует
        return render_markdown(metrics, generated_at=utcnow(), active_days=active_days)
    finally:
        await engine.dispose()


def run(args: argparse.Namespace) -> int:
    """Выполняет ``gtrack pilot-report``; возвращает код выхода (0 — успех)."""
    step = "аргументы"
    settings: Settings | None = None
    try:
        since, until = _bounds(args, utcnow())
        if args.active_days < 1:
            raise ValueError("--active-days должно быть не меньше 1")
        settings = get_settings()
        step = "ожидание БД"
        with _quiet_asyncio_logger():
            asyncio.run(wait_for_database(settings.database_url))
            step = "метрики"
            report = asyncio.run(_report(settings, since, until, args.active_days))
    except (BootstrapError, ValueError) as exc:
        print(f"Ошибка ({step}): {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(f"Ошибка ({step}): {_safe_description(exc, settings)}", file=sys.stderr, flush=True)
        return 1
    print(report)
    sys.stdout.flush()
    return 0
