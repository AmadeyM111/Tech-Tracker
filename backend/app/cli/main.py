"""Точка входа CLI ``gtrack`` (plan §4.13, D-29): ``argparse``, тонкие подкоманды."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from app.cli.commands import (
    backup,
    bootstrap,
    demo_data,
    export,
    hash_bench,
    import_,
    maintenance,
    mcp,
    notify_due,
    openapi,
    restore,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gtrack",
        description="Команды оператора GTrack.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="КОМАНДА", required=True)
    bootstrap.add_parser(subparsers)
    openapi.add_parser(subparsers)
    hash_bench.add_parser(subparsers)
    maintenance.add_parser(subparsers)
    demo_data.add_parser(subparsers)
    export.add_parser(subparsers)
    import_.add_parser(subparsers)
    mcp.add_parser(subparsers)
    backup.add_parser(subparsers)
    restore.add_parser(subparsers)
    notify_due.add_parser(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Разбирает аргументы, выполняет подкоманду, возвращает код выхода.

    Ошибки разбора аргументов (в том числе неизвестная подкоманда) — код 2; ``--help`` — 0.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 2
    handler: Callable[[argparse.Namespace], int] = args.handler
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
