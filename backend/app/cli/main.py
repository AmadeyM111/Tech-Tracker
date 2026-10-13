"""Точка входа CLI ``gostracker`` (plan §4.13, D-29): ``argparse``, тонкие подкоманды."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from app.cli.commands import bootstrap


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gostracker",
        description="Команды оператора GOSTracker.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="КОМАНДА", required=True)
    bootstrap.add_parser(subparsers)
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
