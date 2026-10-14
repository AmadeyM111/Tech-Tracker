"""Подкоманда ``gostracker maintenance`` (plan §4.13; ревью T11, T16a).

Ждёт БД (до 60 с, как ``bootstrap``) и удаляет истёкшие сессии пользователей. Секретный ключ
не нужен, события в журнал не пишутся. В stdout — только число удалённых сессий; сообщения об
ошибках — в stderr без DSN и паролей.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli.commands.bootstrap import BootstrapError, _safe_description, wait_for_database
from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.domain.system.maintenance import purge_expired_sessions


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "maintenance",
        help="служебная очистка: удалить истёкшие сессии пользователей",
        description=(
            "Ждёт БД (до 60 с) и удаляет истёкшие сессии (простой или абсолютный срок). "
            "В stdout печатается число удалённых сессий. Безопасна при работающем API."
        ),
    )
    parser.set_defaults(handler=run)


async def _purge(settings: Settings) -> int:
    engine = create_engine(settings)
    try:
        return await purge_expired_sessions(
            async_sessionmaker(engine, expire_on_commit=False),
            now=utcnow(),
            idle_timeout=settings.session_idle_timeout,
        )
    finally:
        await engine.dispose()


@contextmanager
def _quiet_asyncio_logger() -> Iterator[None]:
    """Отладочные записи цикла событий не должны попасть в stdout (там только число)."""
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
            deleted = asyncio.run(_purge(settings))
    except BootstrapError as exc:
        print(f"Ошибка ({step}): {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(f"Ошибка ({step}): {_safe_description(exc)}", file=sys.stderr, flush=True)
        return 1
    print(deleted, flush=True)
    return 0
