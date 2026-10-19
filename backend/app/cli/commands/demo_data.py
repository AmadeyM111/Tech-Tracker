"""Подкоманда ``gostracker demo-data`` (plan §11.8, D-63; ожидание БД как у ``maintenance``).

Загружает демо-данные (12 пользователей, 2 проекта, задачи, комментарии) и записывает пароли
в ``secrets/demo-passwords.txt``. В stdout — строки ``ключ=значение``: путь к файлу и счётчики;
паролей нет нигде. Коды: 0 — успех, 2 — отказ (в базе уже есть данные), 1 — ошибка БД или
конфигурации, нет пространства или не применены миграции (без DSN, SQL и паролей).
При ``ENV=production`` в stderr печатается предупреждение (код возврата не меняется).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.cli.commands.bootstrap import BootstrapError, _safe_description, wait_for_database
from app.cli.commands.maintenance import _quiet_asyncio_logger
from app.core.clock import FixedClock, utcnow
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.domain.ops.demo import DemoDataRefused, DemoReport, WorkspaceMissing, load_demo_data


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "demo-data",
        help="загрузить демо-данные (пользователи, проекты, задачи) в чистую установку",
        description=(
            "Ждёт БД (до 60 с) и загружает демо-данные одной транзакцией; пароли "
            "демо-пользователей пишутся в secrets/demo-passwords.txt (0600). "
            "Отказ (код 2), если в базе уже есть "
            "проекты, задачи или пользователи сверх первого техадминистратора. "
            "В stdout печатаются строки ключ=значение."
        ),
    )
    parser.add_argument(
        "--seed", type=int, default=1, help="seed генератора данных (по умолчанию 1)"
    )
    parser.set_defaults(handler=run)


async def _load(settings: Settings, *, seed: int) -> DemoReport:
    engine = create_engine(settings)
    try:
        return await load_demo_data(
            async_sessionmaker(engine, expire_on_commit=False),
            settings,
            clock=FixedClock(utcnow()),
            seed=seed,
        )
    finally:
        await engine.dispose()


_BOOTSTRAP_HINT = "Выполните `gostracker bootstrap` и повторите команду."


def run(args: argparse.Namespace) -> int:
    """Выполняет ``gostracker demo-data``; возвращает код выхода."""
    step = "настройки"
    try:
        settings = get_settings()
        if settings.env == "production":
            print(
                "Предупреждение: ENV=production - демо-данные (общеизвестные учётные записи "
                "demo.*) загружаются в рабочей системе; удалите их до реального использования.",
                file=sys.stderr,
                flush=True,
            )
        step = "ожидание БД"
        with _quiet_asyncio_logger():
            asyncio.run(wait_for_database(settings.database_url))
            step = "загрузка демо-данных"
            report = asyncio.run(_load(settings, seed=int(args.seed)))
    except WorkspaceMissing:
        print(f"Рабочее пространство не создано. {_BOOTSTRAP_HINT}", file=sys.stderr, flush=True)
        return 1
    except DemoDataRefused as exc:
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
    print(f"passwords_file={report.passwords_file}")
    for key in ("users", "projects", "tasks", "subtasks", "comments"):
        print(f"{key}={getattr(report, key)}")
    sys.stdout.flush()
    return 0
