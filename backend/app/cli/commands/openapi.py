"""Подкоманда ``gostracker openapi [--out PATH]`` (plan §4.13, §4.14, FR-44, D-32, D-33).

Схема строится из объекта приложения без БД, сети и секретов: lifespan не запускается,
секретный ключ не читается и не создаётся. Вывод детерминирован: ``sort_keys``, ``indent=2``,
``ensure_ascii=False`` и завершающий перевод строки. С ``--out`` файл пишется атомарно
(временный файл в том же каталоге и ``os.replace``); каталог назначения должен существовать.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from app.core.config import get_settings


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "openapi",
        help="выгрузить схему OpenAPI (без подключения к БД)",
        description=(
            "Печатает схему OpenAPI в stdout или, с --out, записывает её в файл (атомарно). "
            "База данных и секретный ключ не требуются."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help="записать в файл вместо stdout; каталог должен существовать",
    )
    parser.set_defaults(handler=run)


def render_openapi() -> str:
    """Каноничный JSON схемы приложения."""
    from app.main import create_app  # лениво: импорт модуля создаёт приложение

    schema: dict[str, Any] = create_app(get_settings()).openapi()
    return json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_atomically(target: Path, content: str) -> None:
    """Пишет ``content`` во временный файл рядом с ``target`` и заменяет ``target``.

    При любой ошибке временный файл удаляется, прежний ``target`` остаётся нетронутым.
    """
    tmp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "xb") as handle:  # права по umask, как у обычного файла
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def run(args: argparse.Namespace) -> int:
    out: Path | None = args.out
    if out is not None and not out.parent.is_dir():
        print(f"Ошибка: каталог не существует: {out.parent}", file=sys.stderr)
        return 1
    try:
        content = render_openapi()
        if out is None:
            sys.stdout.write(content)
            sys.stdout.flush()
        else:
            write_atomically(out, content)
    except Exception as exc:
        print(f"Ошибка: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0
