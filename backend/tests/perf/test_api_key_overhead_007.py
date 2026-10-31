"""R7-T23: замер накладных расходов аутентификации по ключу (007/NFR-2, AC-48 *вне CI*; plan PD-19).

Методика NFR-2: мир spec §5 (``make_world007``), один клиент, запросы по очереди (ключ и сессия
чередуются, порядок внутри пары меняется на каждом шаге), ``time.perf_counter``.

- Без ``GT_PERF`` (CI): 20 запросов карточки T1 по ``K_u`` и 20 по cookie-сессии пользователя с
  ролью П; проверяются только ответы 200 (порог не проверяется).
- ``GT_PERF=1``: 20 прогревочных пар, затем 200 + 200 запросов карточки T1;
  p95(ключ) − p95(сессия) ≤ 20 мс (AC-48). Дополнительно (заметка ревью R7-T14: +1 INSERT в
  ``domain_event`` на каждую запись задачи/комментария) — тот же порог для записи: PATCH статуса и
  создание комментария по ключу против того же по cookie (событие пишется и для людей, различие —
  только аутентификация). Перенос по доске (``move``, +блокировки и чтения R7-T14) по cookie —
  только информационный вывод p50/p95/max, без порога (базовой линии до R7-T14 нет).

Замеры ``GT_PERF`` идут с реальными фиксациями (``committed_api_env``): иначе ``commit_durably``
был бы лишь освобождением SAVEPOINT внешней транзакции теста и стоимость фиксации не попала бы в
замер. Пользователь с ролью П и cookie — ``u1`` (участник P; у ``agent.u`` сессии нет). Карточка
T1 читается обоими. Для PATCH статуса ``u1`` по правилам FR-19b меняет только свою задачу T2 (тот
же проект, та же колонка «todo»), агент — свою T1.

Лимит FR-33 (120 в минуту на ключ) обходится сдвигом ``fixed_clock`` на 61 с после каждых 100
запросов по ключу (вне замера времени). Cookie-сессии мира созданы на ``CLOCK`` (не на
``FIXED_NOW``) и живут 8 ч простоя; каждый запрос по cookie обновляет ``last_activity_at``, так
что сдвиги на 61 с сессию не гасят (проверяется: все ответы по cookie — 200).

Секрет ключа не печатается: в вывод попадают только числа (мс); заголовки с ключом не входят в
выражения ``assert``.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from tests.agents007_support import (
    World007,
    bearer,
    comments_url,
    make_world007,
    task_url,
)

if TYPE_CHECKING:
    import httpx

    from tests.conftest import ApiEnv

PERF = os.environ.get("GT_PERF") == "1"
needs_perf = pytest.mark.skipif(not PERF, reason="замер NFR-2 вне CI: нужен GT_PERF=1")

THRESHOLD_MS = 20.0  # NFR-2: p95(ключ) - p95(сессия)
CI_REQUESTS = 20
WARMUP = 20
MEASURED = 200
KEY_REQUESTS_PER_WINDOW = 100  # < 120 (FR-33), затем сдвиг часов
CLOCK_STEP = timedelta(seconds=61)  # > окна лимита 60 с

Send = Callable[[int], Awaitable["httpx.Response"]]


# --- помощники ---------------------------------------------------------------------------------


def percentile(samples: list[float], q: float) -> float:
    """Перцентиль методом ближайшего ранга (p95 из 200 = 190-е значение по возрастанию)."""
    ordered = sorted(samples)
    rank = max(1, math.ceil(q / 100.0 * len(ordered)))
    return ordered[rank - 1]


def summary(label: str, samples: list[float]) -> dict[str, float]:
    stats = {
        "p50": percentile(samples, 50),
        "p95": percentile(samples, 95),
        "max": max(samples),
    }
    print(
        f"[NFR-2] {label}: n={len(samples)} p50={stats['p50']:.2f} мс "
        f"p95={stats['p95']:.2f} мс max={stats['max']:.2f} мс"
    )
    return stats


class KeyBudget:
    """Считает запросы по ключу; после каждых 100 сдвигает часы на 61 с (лимит FR-33)."""

    def __init__(self, env: ApiEnv) -> None:
        self.env = env
        self.sent = 0

    def before_request(self) -> None:
        if self.sent and self.sent % KEY_REQUESTS_PER_WINDOW == 0:
            self.env.clock.advance(CLOCK_STEP)
        self.sent += 1


async def timed(send: Send, i: int) -> tuple[float, httpx.Response]:
    started = time.perf_counter()
    response = await send(i)
    return (time.perf_counter() - started) * 1000.0, response


def check(response: httpx.Response, expected: int, what: str) -> None:
    assert response.status_code == expected, (what, response.status_code, response.text)


async def paired_run(
    env: ApiEnv,
    *,
    by_key: Send,
    by_cookie: Send,
    expected: int,
    warmup: int,
    measured: int,
) -> tuple[list[float], list[float]]:
    """Прогрев и замер парами «ключ/сессия» по очереди одним клиентом; порядок в паре чередуется.

    Возвращает (времена по ключу, времена по сессии) в мс — только замеренная часть."""
    budget = KeyBudget(env)
    key_ms: list[float] = []
    cookie_ms: list[float] = []
    for step in range(warmup + measured):
        order = ("key", "cookie") if step % 2 == 0 else ("cookie", "key")
        for who in order:
            if who == "key":
                budget.before_request()
                elapsed, response = await timed(by_key, step)
                check(response, expected, "по ключу")
                if step >= warmup:
                    key_ms.append(elapsed)
            else:
                elapsed, response = await timed(by_cookie, step)
                check(response, expected, "по cookie")
                if step >= warmup:
                    cookie_ms.append(elapsed)
    return key_ms, cookie_ms


def key_headers(w: World007) -> dict[str, str]:
    return bearer(w.K_u.secret)


def cookie_headers(env: ApiEnv, w: World007) -> dict[str, str]:
    return env.auth(w.cookie("u1"))


def card_senders(env: ApiEnv, w: World007) -> tuple[Send, Send]:
    k_headers = key_headers(w)
    c_headers = cookie_headers(env, w)
    url = task_url(w.T1)

    async def by_key(_: int) -> httpx.Response:
        return await env.client.get(url, headers=k_headers)

    async def by_cookie(_: int) -> httpx.Response:
        return await env.client.get(url, headers=c_headers)

    return by_key, by_cookie


def report_overhead(label: str, key_ms: list[float], cookie_ms: list[float]) -> float:
    key = summary(f"{label} по ключу K_u", key_ms)
    cookie = summary(f"{label} по cookie u1", cookie_ms)
    delta = key["p95"] - cookie["p95"]
    verdict = "OK" if delta <= THRESHOLD_MS else "ПРЕВЫШЕН"
    print(
        f"[NFR-2] {label}: p95(ключ) - p95(сессия) = {delta:.2f} мс "
        f"(порог {THRESHOLD_MS:.0f} мс) -> {verdict}"
    )
    return delta


# --- CI: короткий прогон без порога ------------------------------------------------------------


async def test_007_ac48_card_by_key_and_cookie_ci_smoke(api_env: ApiEnv) -> None:
    """AC-48 (CI-часть NFR-2): 20 запросов карточки T1 по ``K_u`` и 20 по cookie-сессии
    пользователя с ролью П — все 200 и это карточка T1; время не проверяется."""
    w = await make_world007(api_env)
    by_key, by_cookie = card_senders(api_env, w)
    for i in range(CI_REQUESTS):
        r_key = await by_key(i)
        check(r_key, 200, "карточка по ключу")
        assert r_key.json()["id"] == str(w.T1)
        r_cookie = await by_cookie(i)
        check(r_cookie, 200, "карточка по cookie")
        assert r_cookie.json()["id"] == str(w.T1)


# --- GT_PERF=1: замер с порогом ----------------------------------------------------------------


@needs_perf
@pytest.mark.committed
async def test_007_ac48_card_key_overhead_p95_within_20ms(committed_api_env: ApiEnv) -> None:
    """AC-48 / NFR-2 (*вне CI*): 20 прогревочных, затем 200 + 200 запросов карточки T1 по ``K_u``
    и по cookie-сессии ``u1`` (П); p95(ключ) − p95(сессия) ≤ 20 мс."""
    env = committed_api_env
    w = await make_world007(env)
    by_key, by_cookie = card_senders(env, w)
    key_ms, cookie_ms = await paired_run(
        env, by_key=by_key, by_cookie=by_cookie, expected=200, warmup=WARMUP, measured=MEASURED
    )
    assert len(key_ms) == MEASURED and len(cookie_ms) == MEASURED
    delta = report_overhead("карточка T1 (GET)", key_ms, cookie_ms)
    assert delta <= THRESHOLD_MS, f"NFR-2: разница p95 {delta:.2f} мс > {THRESHOLD_MS} мс"


@needs_perf
@pytest.mark.committed
async def test_007_nfr2_status_patch_key_overhead_p95_within_20ms(
    committed_api_env: ApiEnv,
) -> None:
    """NFR-2 + заметка ревью R7-T14 (*вне CI*): PATCH статуса (событие ``task.updated`` пишется
    и для человека) — агент по ``K_u`` свою T1, ``u1`` по cookie свою T2, статус чередуется
    todo/in_progress (каждый запрос — реальное изменение). p95(ключ) − p95(сессия) ≤ 20 мс."""
    env = committed_api_env
    w = await make_world007(env)
    k_headers = key_headers(w)
    c_headers = cookie_headers(env, w)

    def status(i: int) -> dict[str, Any]:
        return {"status": "in_progress" if i % 2 == 0 else "todo"}

    async def by_key(i: int) -> httpx.Response:
        return await env.client.patch(task_url(w.T1), json=status(i), headers=k_headers)

    async def by_cookie(i: int) -> httpx.Response:
        return await env.client.patch(task_url(w.T2), json=status(i), headers=c_headers)

    key_ms, cookie_ms = await paired_run(
        env, by_key=by_key, by_cookie=by_cookie, expected=200, warmup=WARMUP, measured=MEASURED
    )
    delta = report_overhead("PATCH статуса", key_ms, cookie_ms)
    assert delta <= THRESHOLD_MS, f"NFR-2: разница p95 {delta:.2f} мс > {THRESHOLD_MS} мс"


@needs_perf
@pytest.mark.committed
async def test_007_nfr2_comment_create_key_overhead_p95_within_20ms(
    committed_api_env: ApiEnv,
) -> None:
    """NFR-2 + заметка ревью R7-T14 (*вне CI*): создание комментария к T1 (событие
    ``comment.created`` пишется и для человека) по ``K_u`` и по cookie ``u1``;
    p95(ключ) − p95(сессия) ≤ 20 мс."""
    env = committed_api_env
    w = await make_world007(env)
    k_headers = key_headers(w)
    c_headers = cookie_headers(env, w)
    url = comments_url(w.T1)

    async def by_key(i: int) -> httpx.Response:
        return await env.client.post(url, json={"body": f"perf key {i}"}, headers=k_headers)

    async def by_cookie(i: int) -> httpx.Response:
        return await env.client.post(url, json={"body": f"perf cookie {i}"}, headers=c_headers)

    key_ms, cookie_ms = await paired_run(
        env, by_key=by_key, by_cookie=by_cookie, expected=201, warmup=WARMUP, measured=MEASURED
    )
    delta = report_overhead("создание комментария", key_ms, cookie_ms)
    assert delta <= THRESHOLD_MS, f"NFR-2: разница p95 {delta:.2f} мс > {THRESHOLD_MS} мс"


@needs_perf
@pytest.mark.committed
async def test_007_nfr2_board_move_by_cookie_informational(committed_api_env: ApiEnv) -> None:
    """Заметка ревью R7-T14 (*вне CI*, без порога): перенос T2 по доске (``POST /tasks/{id}/move``,
    +блокировки колонок, чтение статуса, событие) по cookie ``u1`` между todo и in_progress —
    20 прогревочных, 200 замеренных; печатаются p50/p95/max. Для сравнения тем же клиентом
    печатается PATCH статуса T2 по cookie (тот же перенос через ``update_task``)."""
    env = committed_api_env
    w = await make_world007(env)
    c_headers = cookie_headers(env, w)

    def target(i: int) -> str:
        return "in_progress" if i % 2 == 0 else "todo"

    async def move(i: int) -> httpx.Response:
        return await env.client.post(
            f"{task_url(w.T2)}/move", json={"status": target(i)}, headers=c_headers
        )

    async def patch(i: int) -> httpx.Response:
        return await env.client.patch(task_url(w.T2), json={"status": target(i)}, headers=c_headers)

    move_ms: list[float] = []
    patch_ms: list[float] = []
    for i in range(WARMUP + MEASURED):
        elapsed, response = await timed(move, i)
        check(response, 204, "move по cookie")
        if i >= WARMUP:
            move_ms.append(elapsed)
    for i in range(WARMUP + MEASURED):
        elapsed, response = await timed(patch, i)
        check(response, 200, "PATCH статуса по cookie")
        if i >= WARMUP:
            patch_ms.append(elapsed)
    move_stats = summary("move T2 по cookie u1 (информационно, без порога)", move_ms)
    summary("PATCH статуса T2 по cookie u1 (информационно, без порога)", patch_ms)
    assert len(move_ms) == MEASURED
    assert math.isfinite(move_stats["p95"]) and move_stats["p95"] > 0
