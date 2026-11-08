"""Подкоманда ``gtrack load-measure`` (spec 016 FR-2, FR-3; plan §4).

Прогрев, затем замеры ``--samples`` раундов на каждого из ``--clients`` параллельных клиентов
по операциям ``OPERATIONS`` (``domain/ops/load_measure.py``). В stdout — строки ``ключ=значение``:
стенд, параметры и по строке на операцию (p50, p95, max, норматив, вердикт). Вердикт справочный:
код выхода зависит только от успешности запросов (spec 016 FR-4).
Коды: 0 — все запросы 200; 1 — ошибка (вход, пустой набор, HTTP, сеть, параметры).
Логин и пароль: ``--login``/``--password`` или ``GT_LOAD_LOGIN``/``GT_LOAD_PASSWORD``.
Пароль не печатается.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

from app.domain.ops.load import LOAD_TEST_LOGIN
from app.domain.ops.load_measure import WARMUP_ROUNDS, MeasureError, measure


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "load-measure",
        help="замер p50/p95/max по операциям «Сводки» и карточки задачи",
        description=(
            "После прогрева выполняет --samples замеров каждой операции на каждом из --clients "
            "параллельных клиентов и печатает p50, p95 и max в миллисекундах. Пароль берётся из "
            "GT_LOAD_PASSWORD или --password."
        ),
    )
    parser.add_argument(
        "--base-url",
        required=True,
        metavar="URL",
        help="адрес API, например http://127.0.0.1:18600",
    )
    parser.add_argument(
        "--clients", type=int, default=5, help="параллельные клиенты (по умолчанию 5)"
    )
    parser.add_argument(
        "--samples", type=int, default=100, help="замеров на клиента и операцию (по умолчанию 100)"
    )
    parser.add_argument(
        "--login", default=None, help="логин (по умолчанию GT_LOAD_LOGIN или load.user1)"
    )
    parser.add_argument("--password", default=None, help="пароль (по умолчанию GT_LOAD_PASSWORD)")
    parser.add_argument("--warmup-rounds", type=int, default=WARMUP_ROUNDS, help="раундов прогрева")
    parser.add_argument("--seed", type=int, default=0, help="seed выбора задач для карточек")
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    """Выполняет ``gtrack load-measure``; возвращает код выхода."""
    login = args.login or os.environ.get("GT_LOAD_LOGIN") or LOAD_TEST_LOGIN
    password = args.password or os.environ.get("GT_LOAD_PASSWORD")
    if not password:
        print(
            "Ошибка: пароль не задан: GT_LOAD_PASSWORD или --password", file=sys.stderr, flush=True
        )
        return 1
    try:
        stats = asyncio.run(
            measure(
                base_url=args.base_url,
                login=login,
                password=password,
                clients=int(args.clients),
                samples=int(args.samples),
                warmup_rounds=int(args.warmup_rounds),
                seed=int(args.seed),
            )
        )
    except ValueError as exc:
        print(f"Ошибка параметров: {exc}", file=sys.stderr, flush=True)
        return 1
    except MeasureError as exc:
        print(f"Ошибка замера: {exc}", file=sys.stderr, flush=True)
        return 1
    except httpx.HTTPError as exc:
        print(f"Ошибка замера: сеть ({type(exc).__name__})", file=sys.stderr, flush=True)
        return 1
    print(f"base_url={args.base_url}")
    print(f"clients={args.clients}")
    print(f"samples_per_client={args.samples}")
    print(f"warmup_rounds={args.warmup_rounds}")
    for item in stats:
        print(item.line())
    sys.stdout.flush()
    return 0
