"""Подкоманда ``gostracker hash-bench [--iterations N]`` (plan §4.13; AC-38, FR-52).

Замеряет время ``PasswordHasher.hash`` с параметрами Argon2id из ``Settings`` на одном и том же
случайном пароле. БД, секретный ключ и файлы не затрагиваются; пароль и хеши не печатаются.
В stdout — один JSON-объект: ``p50_ms``, ``p95_ms``, ``iterations`` и параметры хеширования.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from typing import Final

from app.core.config import get_settings
from app.core.security.passwords import PasswordHasher, generate_password

DEFAULT_ITERATIONS: Final = 20


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"ожидается целое число, получено {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError("число итераций должно быть не меньше 1")
    return number


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "hash-bench",
        help="замерить время хеширования пароля (p50/p95) с текущими параметрами Argon2",
        description=(
            "Хеширует случайный пароль N раз с параметрами ARGON2_* и печатает p50/p95 "
            "времени в миллисекундах. База данных не нужна; пароль не печатается."
        ),
    )
    parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=DEFAULT_ITERATIONS,
        metavar="N",
        help=f"число замеров, не меньше 1 (по умолчанию {DEFAULT_ITERATIONS})",
    )
    parser.set_defaults(handler=run)


def percentile(sorted_values: list[float], fraction: float) -> float:
    """Перцентиль по методу ближайшего ранга; ``sorted_values`` не пуст и отсортирован."""
    rank = max(math.ceil(fraction * len(sorted_values)), 1)
    return sorted_values[rank - 1]


def run(args: argparse.Namespace) -> int:
    iterations: int = args.iterations
    try:
        settings = get_settings()
        hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost_kib=settings.argon2_memory_cost_kib,
            parallelism=settings.argon2_parallelism,
        )
        password = generate_password()
        samples_ms: list[float] = []
        for _ in range(iterations):
            started = time.perf_counter()
            hasher.hash(password)
            samples_ms.append((time.perf_counter() - started) * 1000.0)
    except Exception as exc:
        # тексты ошибок argon2 пароль и хеш не содержат
        print(f"Ошибка: {type(exc).__name__}", file=sys.stderr)
        return 1

    samples_ms.sort()
    report = {
        "p50_ms": round(percentile(samples_ms, 0.50), 3),
        "p95_ms": round(percentile(samples_ms, 0.95), 3),
        "iterations": iterations,
        "time_cost": settings.argon2_time_cost,
        "memory_cost_kib": settings.argon2_memory_cost_kib,
        "parallelism": settings.argon2_parallelism,
    }
    print(json.dumps(report, indent=2), flush=True)
    return 0
