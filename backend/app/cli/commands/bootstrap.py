"""Подкоманда ``gostracker bootstrap`` (plan §4.7, §4.13, D-21, D-29, FR-6).

Последовательность: ожидание БД (до 60 с) → ``ensure_secret_key`` → под одной
advisory-блокировкой ``alembic upgrade head`` (``ALEMBIC_CONFIG``) → ``run_bootstrap``.
В stdout — только путь к файлу пароля первого ТА (и только когда он создан); сообщения — в stderr.
Пароли, ключ и DSN в вывод не попадают: ошибки печатаются как имя типа исключения и очищенный текст.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app as app_package
from app.core.clock import SystemClock
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.core.logging import redact_text
from app.core.secrets import ensure_secret_key
from app.domain.system.bootstrap import (
    INITIAL_ADMIN_FILE,
    BootstrapResult,
    bootstrap_lock,
    run_bootstrap,
)

DB_WAIT_TIMEOUT_SECONDS: Final = 60.0
DB_WAIT_INTERVAL_SECONDS: Final = 1.0
DB_CONNECT_TIMEOUT_SECONDS: Final = 5.0

_MASK: Final = "***"


class BootstrapError(Exception):
    """Ошибка шага запуска; текст безопасен для вывода (без DSN, паролей и ключей)."""


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "bootstrap",
        help="миграции и первый запуск: секретный ключ, пространство, первый техадминистратор",
        description=(
            "Ждёт БД (до 60 с), создаёт секретный ключ, применяет миграции и на чистой "
            "установке создаёт пространство и первого техадминистратора. Пароль записывается "
            "в файл (0600); в stdout печатается только путь к файлу."
        ),
    )
    parser.set_defaults(handler=run)


async def wait_for_database(
    database_url: str,
    *,
    timeout: float = DB_WAIT_TIMEOUT_SECONDS,
    interval: float = DB_WAIT_INTERVAL_SECONDS,
) -> None:
    """Опрашивает БД ``SELECT 1`` до успеха или до исчерпания ``timeout`` секунд."""
    try:
        url = make_url(database_url)
        engine = create_async_engine(
            url,
            poolclass=NullPool,
            hide_parameters=True,
            connect_args={"timeout": DB_CONNECT_TIMEOUT_SECONDS},
        )
    except Exception as exc:
        # текст исходного исключения содержит DSN целиком
        raise BootstrapError(f"Не удалось разобрать DATABASE_URL ({type(exc).__name__})") from None

    target = f"{url.host}:{url.port}" if url.host else "локальный сокет"
    last_error = "нет ответа"
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                return
            except (OSError, SQLAlchemyError) as exc:
                last_error = type(exc).__name__
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(interval, remaining))
    finally:
        await engine.dispose()
    raise BootstrapError(
        f"База данных {target} недоступна в течение {timeout:.0f} с "
        f"(последняя ошибка: {last_error})"
    )


def _alembic_config_path() -> Path:
    configured = os.environ.get("ALEMBIC_CONFIG")
    if configured:
        return Path(configured)
    # backend/app/__init__.py -> backend/alembic.ini (в образе: /app/app -> /app/alembic.ini)
    return Path(app_package.__file__).resolve().parents[1] / "alembic.ini"


def _alembic_upgrade_head() -> None:
    path = _alembic_config_path()
    if not path.is_file():
        raise BootstrapError(f"Не найден файл конфигурации Alembic: {path}")
    command.upgrade(Config(str(path)), "head")


async def _migrate_and_first_start(settings: Settings, stage: list[str]) -> BootstrapResult:
    """Миграции и первый запуск под одной advisory-блокировкой (ревью T10 (1), AC-23).

    Параллельные запуски на чистой БД выстраиваются в очередь: второй видит уже применённые
    миграции и созданного ТА. Alembic работает в потоке (``env.py`` вызывает ``asyncio.run``).
    ``stage`` — изменяемая ссылка на название текущего шага для сообщения об ошибке.
    """
    engine = create_engine(settings)
    try:
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        stage[0] = "блокировка первого запуска"
        async with bootstrap_lock(sessionmaker) as lock:
            stage[0] = "миграции"
            await asyncio.to_thread(_alembic_upgrade_head)
            stage[0] = "первый запуск"
            return await run_bootstrap(sessionmaker, settings, clock=SystemClock(), locked=lock)
    finally:
        await engine.dispose()


def _known_secrets(settings: Settings | None = None) -> list[str]:
    """Значения, которые нельзя печатать: ключ приложения и пароль из DSN.

    Берутся из ``settings`` (настройки могли прийти не из окружения процесса), плюс из окружения
    (на случай, когда ``get_settings`` сам упал на проверке).
    """
    values: list[str] = []
    dsns: list[str] = []
    if settings is not None:
        if settings.secret_key is not None:
            values.append(settings.secret_key.get_secret_value())
        dsns.append(settings.database_url)
    values.append(os.environ.get("SECRET_KEY", ""))
    dsns.append(os.environ.get("DATABASE_URL", ""))
    for dsn in dsns:
        if not dsn:
            continue
        try:
            password = make_url(dsn).password
        except Exception:
            password = None
        if password:
            values.append(password)
    return [v for v in dict.fromkeys(values) if v]


def _safe_description(exc: BaseException, settings: Settings | None = None) -> str:
    message = redact_text(str(exc))
    for secret in _known_secrets(settings):
        message = message.replace(secret, _MASK)
    name = type(exc).__name__
    return f"{name}: {message}" if message else name


def _warn(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def run(args: argparse.Namespace) -> int:
    """Выполняет ``gostracker bootstrap``; возвращает код выхода (0 — успех)."""
    step = "настройки"
    loaded: Settings | None = None  # для маскирования секретов, если сбой случится позже
    try:
        settings = get_settings()
        loaded = settings
        step = "ожидание БД"
        asyncio.run(wait_for_database(settings.database_url))
        step = "секретный ключ"
        ensure_secret_key(settings)  # значение не используется и не печатается
        stage = ["блокировка первого запуска"]
        try:
            result = asyncio.run(_migrate_and_first_start(settings, stage))
        finally:
            step = stage[0]
    except BootstrapError as exc:
        _warn(f"Ошибка ({step}): {exc}")
        return 1
    except Exception as exc:
        _warn(f"Ошибка ({step}): {_safe_description(exc, loaded)}")
        return 1

    if result.admin_created:
        path = settings.secrets_dir / INITIAL_ADMIN_FILE
        _warn("Создан первый техадминистратор; путь к файлу с паролем выведен в stdout")
        print(path, flush=True)
    else:
        _warn("Первый запуск уже выполнен: изменений нет")
    return 0
