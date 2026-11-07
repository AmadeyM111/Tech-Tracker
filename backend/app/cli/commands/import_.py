"""Подкоманда ``gtrack import PATH`` (plan §4.10, FR-40, AC-93).

Заменяет автоданные установки (первого ТА, воронку по умолчанию) данными архива в
одной транзакции; идентификаторы сохраняются. Импорт в непустую систему и архив другой
версии схемы отклоняются. После фиксации удаляется файл с паролем первого ТА.
Коды: 0 — успех; 2 — отказ по условиям (непустая система, другая версия схемы, плохой архив);
1 — ошибка выполнения (нет файла, БД, конфигурации или миграций).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy.exc import ProgrammingError

from app.cli.commands.bootstrap import BootstrapError, _safe_description, wait_for_database
from app.cli.commands.export import schema_head
from app.cli.commands.maintenance import _quiet_asyncio_logger
from app.core.config import Settings, get_settings
from app.domain.ops.archive import ImportRefused
from app.domain.ops.importer import import_archive

_BOOTSTRAP_HINT = "Выполните `gtrack bootstrap` и повторите команду."


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "import",
        help="импорт архива экспорта в пустую систему",
        description=(
            "Заменяет автоданные первого ТА данными архива в одной транзакции. Отказ (код 2), "
            "если в системе есть данные, кроме автоданных, или версия схемы архива другая. "
            "После импорта удаляется файл с паролем первого ТА."
        ),
    )
    parser.add_argument("path", metavar="PATH", help="архив, созданный gtrack export")
    parser.set_defaults(handler=run)


async def _import(settings: Settings, archive: Path, *, schema_version: str) -> dict[str, int]:
    return await import_archive(settings, archive, schema_version=schema_version)


def run(args: argparse.Namespace) -> int:
    """Выполняет ``gtrack import``; возвращает код выхода."""
    step = "настройки"
    archive = Path(args.path)
    try:
        settings = get_settings()
        if not archive.is_file():
            print(f"Ошибка: файл не найден: {archive}", file=sys.stderr, flush=True)
            return 1
        step = "ожидание БД"
        with _quiet_asyncio_logger():
            asyncio.run(wait_for_database(settings.database_url))
            step = "схема"
            version = schema_head()
            step = "импорт"
            counts = asyncio.run(_import(settings, archive, schema_version=version))
    except ImportRefused as exc:
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
    print(f"schema_version={version}")
    print(f"tables={len(counts)}")
    print(f"rows={sum(counts.values())}")
    sys.stdout.flush()
    return 0
