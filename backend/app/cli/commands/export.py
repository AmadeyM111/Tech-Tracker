"""Подкоманда ``gtrack export`` (plan §4.10, FR-40, AC-17).

Пишет tar-архив с ``data.json`` (режим 0600). Без ``--out`` архив кладётся в
``data_dir/exports/gtrack-export-<UTC>.tar``. Существующий файл не перезаписывается.
Коды: 0 — успех; 2 — отказ (файл уже существует); 1 — ошибка БД, конфигурации или миграций.
В stdout — строки ``ключ=значение``: путь к архиву и счётчики.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import ProgrammingError

from app.cli.commands.bootstrap import (
    BootstrapError,
    _alembic_config_path,
    _safe_description,
    wait_for_database,
)
from app.cli.commands.maintenance import _quiet_asyncio_logger
from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.core.secrets import ensure_private_dir
from app.domain.ops.export import export_archive

_BOOTSTRAP_HINT = "Выполните `gtrack bootstrap` и повторите команду."


def schema_head() -> str:
    """Текущая версия схемы (alembic head) — записывается в архив и сверяется при импорте."""
    config = Config(str(_alembic_config_path()))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise BootstrapError("в миграциях Alembic не найдена версия схемы")
    return head


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "export",
        help="экспорт рабочего пространства в архив (tar с data.json)",
        description=(
            "Ждёт БД (до 60 с) и выгружает все таблицы, кроме сессий входа, в tar-архив "
            "с data.json (режим 0600). Без --out архив пишется в data_dir/exports/."
        ),
    )
    parser.add_argument("--out", metavar="PATH", help="путь к архиву (не должен существовать)")
    parser.set_defaults(handler=run)


def _default_out(settings: Settings) -> Path:
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    return settings.exports_dir / f"gtrack-export-{stamp}.tar"


async def _export(settings: Settings, out: Path, *, schema_version: str) -> dict[str, int]:
    return await export_archive(settings, out, schema_version=schema_version, exported_at=utcnow())


def run(args: argparse.Namespace) -> int:
    """Выполняет ``gtrack export``; возвращает код выхода."""
    step = "настройки"
    try:
        settings = get_settings()
        if args.out:
            out = Path(args.out)
        else:
            ensure_private_dir(settings.exports_dir)
            out = _default_out(settings)
        if out.exists():
            print(f"Отказ: файл уже существует: {out}", file=sys.stderr, flush=True)
            return 2
        step = "ожидание БД"
        with _quiet_asyncio_logger():
            asyncio.run(wait_for_database(settings.database_url))
            step = "схема"
            version = schema_head()
            step = "экспорт"
            counts = asyncio.run(_export(settings, out, schema_version=version))
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
    print(f"archive={out}")
    print(f"schema_version={version}")
    print(f"tables={len(counts)}")
    print(f"rows={sum(counts.values())}")
    sys.stdout.flush()
    return 0
