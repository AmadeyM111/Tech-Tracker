"""Подкоманда ``gtrack load-data`` (spec 016 FR-1, AC-1, AC-2; plan §2, §4).

Загружает нагрузочный набор: 12 пользователей, 8 проектов, ``--tasks`` задач (около одной десятой —
подзадачи) и комментарии. Одинаковый ``--seed`` даёт одинаковый набор: ``gtrack export`` совпадает.
Коды: 0 — успех; 2 — отказ (в базе уже есть проекты, задачи или пользователи сверх первого ТА);
1 — ошибка БД или конфигурации, нет пространства или миграций, ``ENV=production``.
В stdout — строки ``ключ=значение``: логин и синтетический пароль для ``load-measure`` и счётчики.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli.commands.bootstrap import BootstrapError, _safe_description, wait_for_database
from app.cli.commands.maintenance import _quiet_asyncio_logger
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.domain.ops.load import (
    LOAD_TEST_LOGIN,
    MIN_TASKS,
    LoadDataRefused,
    LoadReport,
    LoadWorkspaceMissing,
    derive_password,
    load_synthetic_data,
)

_BOOTSTRAP_HINT = "Выполните `gtrack bootstrap` и повторите команду."


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "load-data",
        help="нагрузочный набор для замера нормативов (50 000 задач при --tasks 50000)",
        description=(
            "Ждёт БД (до 60 с) и загружает синтетический набор одной транзакцией. Одинаковый "
            "--seed даёт одинаковый набор. Отказ (код 2), если в базе уже есть проекты, задачи "
            "или пользователи сверх первого ТА. Не запускается при ENV=production."
        ),
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=50000,
        help="число задач, включая подзадачи (по умолчанию 50000)",
    )
    parser.add_argument(
        "--seed", type=int, required=True, help="seed генератора (обязателен: набор воспроизводим)"
    )
    parser.set_defaults(handler=run)


async def _load(settings: Settings, *, seed: int, tasks: int) -> LoadReport:
    engine = create_engine(settings)
    try:
        return await load_synthetic_data(
            async_sessionmaker(engine, expire_on_commit=False), settings, seed=seed, tasks=tasks
        )
    finally:
        await engine.dispose()


def run(args: argparse.Namespace) -> int:
    """Выполняет ``gtrack load-data``; возвращает код выхода."""
    step = "настройки"
    seed = int(args.seed)
    tasks = int(args.tasks)
    try:
        settings = get_settings()
        if settings.env == "production":
            print(
                "Отказ: load-data не запускается при ENV=production: учётные записи набора "
                "выводятся из seed и известны всем, кто его знает.",
                file=sys.stderr,
                flush=True,
            )
            return 1
        if tasks < MIN_TASKS:
            print(f"Ошибка: --tasks должно быть не меньше {MIN_TASKS}", file=sys.stderr, flush=True)
            return 1
        step = "ожидание БД"
        with _quiet_asyncio_logger():
            asyncio.run(wait_for_database(settings.database_url))
            step = "загрузка набора"
            report = asyncio.run(_load(settings, seed=seed, tasks=tasks))
    except LoadWorkspaceMissing:
        print(f"Рабочее пространство не создано. {_BOOTSTRAP_HINT}", file=sys.stderr, flush=True)
        return 1
    except LoadDataRefused as exc:
        print(f"Отказ: {exc}", file=sys.stderr, flush=True)
        return 2
    except ProgrammingError:
        print(
            f"Схема БД не готова: миграции не применены. {_BOOTSTRAP_HINT}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    except BootstrapError as exc:
        print(f"Ошибка ({step}): {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(f"Ошибка ({step}): {_safe_description(exc)}", file=sys.stderr, flush=True)
        return 1
    print(f"load_login={LOAD_TEST_LOGIN}")
    print(f"load_password={derive_password(seed, LOAD_TEST_LOGIN)}")
    for key in ("users", "projects", "tasks", "subtasks", "comments"):
        print(f"{key}={getattr(report, key)}")
    sys.stdout.flush()
    return 0
