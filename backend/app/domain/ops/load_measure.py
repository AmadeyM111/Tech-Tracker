"""Харнесс замера нормативов (spec 016 FR-2, FR-3; plan §2, §4).

``measure`` выполняет прогрев одним клиентом, затем ``clients`` параллельных httpx-клиентов,
у каждого своя сессия входа. Каждый клиент делает ``samples`` замеров каждой операции (итого
``clients * samples`` на операцию). Перцентили — nearest-rank. Ответ не-200 прерывает замер
(``MeasureError``). Пороги на код выхода не влияют; вердикт печатается справочно, решение по
нормативам — в отчёте.

Список операций — кортеж ``OPERATIONS``: строку счётчика уведомлений и вложения добавят сюда,
когда появятся эндпоинты (012/T-05, 011). Пока строки не замеряются (в отчёте: «отложено» /
«не реализовано»).
"""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Final, Literal
from uuid import UUID

import httpx

API: Final = "/api/v1"
PAGE_SIZE: Final = 50  # ТЗ v1.0 §5: 50 элементов на странице
POOL_PAGES: Final = 8  # страниц «Сводки», из которых берётся пул задач для карточек
WARMUP_ROUNDS: Final = 10
_LIST_VARIANTS: Final[tuple[tuple[tuple[str, str], ...], ...]] = (
    (("due", "overdue"),),
    (("due", "week"),),
    (("priority", "high"),),
    (("status", "todo"), ("priority", "high")),
    (("due", "none"),),
    (("needs_review", "true"),),
)

OperationKind = Literal["tiles", "list", "task", "comments"]


class MeasureError(Exception):
    """Замер прерван: ответ не 200, вход отклонён или нет задач для карточек (код 1 в CLI)."""


@dataclass(frozen=True)
class Operation:
    name: str  # подпись строки отчёта
    kind: OperationKind  # как строится запрос (см. _request)
    path: str  # путь относительно /api/v1; ``{task_id}`` подставляется из пула
    budget_p95_ms: int  # норматив p95, мс (spec 016 FR-2, ТЗ v1.0 §5)


OPERATIONS: Final[tuple[Operation, ...]] = (
    Operation("summary_tiles", "tiles", f"{API}/me/overview", 500),
    Operation("summary_list", "list", f"{API}/me/overview/tasks", 500),
    Operation("card_task", "task", f"{API}/tasks/{{task_id}}", 200),
    Operation("card_comments", "comments", f"{API}/tasks/{{task_id}}/comments", 200),
)


@dataclass(frozen=True)
class OperationStats:
    name: str
    n: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    budget_p95_ms: int

    @property
    def verdict(self) -> str:
        return "ok" if self.p95_ms <= self.budget_p95_ms else "exceeds"

    def line(self) -> str:
        return (
            f"operation={self.name} n={self.n} p50_ms={self.p50_ms:.1f} "
            f"p95_ms={self.p95_ms:.1f} max_ms={self.max_ms:.1f} "
            f"budget_p95_ms={self.budget_p95_ms} verdict={self.verdict}"
        )


@dataclass(frozen=True)
class _Pool:
    task_ids: list[UUID]
    project_ids: list[UUID]


def percentile(values: Sequence[float], q: float) -> float:
    """Перцентиль по методу nearest-rank: ``q`` в (0, 1]."""
    if not values:
        raise ValueError("нет замеров")
    if not 0 < q <= 1:
        raise ValueError("q должно быть в (0, 1]")
    ordered = sorted(values)
    rank = math.ceil(q * len(ordered))
    return ordered[max(rank, 1) - 1]


def summarize(op: Operation, samples: Sequence[float]) -> OperationStats:
    return OperationStats(
        name=op.name,
        n=len(samples),
        p50_ms=percentile(samples, 0.5),
        p95_ms=percentile(samples, 0.95),
        max_ms=max(samples),
        budget_p95_ms=op.budget_p95_ms,
    )


def _list_params(round_no: int, pool: _Pool) -> list[tuple[str, str]]:
    """Фильтры списка «Сводки» по кругу: пресеты срока, приоритет, статус, проект, «проверить»."""
    variants = len(_LIST_VARIANTS) + 1  # последний вариант — проект
    position = round_no % variants
    if position == len(_LIST_VARIANTS):
        project = pool.project_ids[round_no % len(pool.project_ids)]
        params = [("project_id", str(project))]
    else:
        params = list(_LIST_VARIANTS[position])
    return [*params, ("page_size", str(PAGE_SIZE))]


def _request(
    op: Operation, round_no: int, pool: _Pool, rng: random.Random
) -> tuple[str, list[tuple[str, str]]]:
    if op.kind == "tiles":
        return op.path, []
    if op.kind == "list":
        return op.path, _list_params(round_no, pool)
    task_id = str(rng.choice(pool.task_ids))
    path = op.path.format(task_id=task_id)
    if op.kind == "comments":
        return path, [("page", "1"), ("page_size", str(PAGE_SIZE))]
    return path, []


async def _login(client: httpx.AsyncClient, login: str, password: str) -> None:
    response = await client.post(f"{API}/auth/login", json={"login": login, "password": password})
    if response.status_code != 200:
        raise MeasureError(f"вход отклонён: HTTP {response.status_code}")


@asynccontextmanager
async def _session(
    base_url: str, transport: httpx.AsyncBaseTransport | None, login: str, password: str
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=base_url, transport=transport, timeout=30.0) as client:
        await _login(client, login, password)
        yield client


async def _get_json(client: httpx.AsyncClient, path: str, params: Sequence[tuple[str, str]]) -> Any:
    response = await client.get(path, params=tuple(params))
    if response.status_code != 200:
        raise MeasureError(f"подготовка пула: HTTP {response.status_code}")
    return response.json()


async def _build_pool(client: httpx.AsyncClient, rng: random.Random) -> _Pool:
    """Задачи верхнего уровня из случайных страниц «Сводки» (видны тестовому пользователю)."""
    list_path = f"{API}/me/overview/tasks"
    first = await _get_json(client, list_path, [("page", "1"), ("page_size", str(PAGE_SIZE))])
    pages = max(1, math.ceil(int(first["total"]) / PAGE_SIZE))
    chosen = {1, *rng.sample(range(1, pages + 1), min(POOL_PAGES, pages))}
    task_ids: dict[UUID, None] = {}
    project_ids: dict[UUID, None] = {}
    for page in sorted(chosen):
        body = (
            first
            if page == 1
            else await _get_json(
                client, list_path, [("page", str(page)), ("page_size", str(PAGE_SIZE))]
            )
        )
        for item in body["items"]:
            project_ids[UUID(item["project"]["id"])] = None
            if item["parent_id"] is None:
                task_ids[UUID(item["id"])] = None
    if not task_ids:
        raise MeasureError("нет задач для замера: набор не загружен или не виден пользователю")
    return _Pool(task_ids=list(task_ids), project_ids=list(project_ids))


async def _timed_get(
    client: httpx.AsyncClient,
    op: Operation,
    path: str,
    params: list[tuple[str, str]],
) -> float:
    started = perf_counter()
    response = await client.get(path, params=tuple(params))
    elapsed_ms = (perf_counter() - started) * 1000
    if response.status_code != 200:
        raise MeasureError(f"{op.name}: HTTP {response.status_code}")
    return elapsed_ms


async def _client_run(
    index: int,
    *,
    base_url: str,
    transport: httpx.AsyncBaseTransport | None,
    login: str,
    password: str,
    operations: Sequence[Operation],
    pool: _Pool,
    samples: int,
    seed: int,
) -> dict[str, list[float]]:
    rng = random.Random(seed * 1000 + index)
    recorded: dict[str, list[float]] = {op.name: [] for op in operations}
    async with _session(base_url, transport, login, password) as client:
        for round_no in range(samples):
            for op in operations:
                path, params = _request(op, round_no, pool, rng)
                recorded[op.name].append(await _timed_get(client, op, path, params))
    return recorded


async def _warm_up(
    base_url: str,
    transport: httpx.AsyncBaseTransport | None,
    login: str,
    password: str,
    operations: Sequence[Operation],
    rounds: int,
    seed: int,
) -> _Pool:
    rng = random.Random(seed)
    async with _session(base_url, transport, login, password) as client:
        pool = await _build_pool(client, rng)
        for round_no in range(rounds):
            for op in operations:
                path, params = _request(op, round_no, pool, rng)
                await _timed_get(client, op, path, params)
    return pool


async def measure(
    *,
    base_url: str,
    login: str,
    password: str,
    clients: int = 5,
    samples: int = 100,
    operations: Sequence[Operation] = OPERATIONS,
    warmup_rounds: int = WARMUP_ROUNDS,
    seed: int = 0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[OperationStats]:
    """Прогрев, затем ``clients`` параллельных клиентов по ``samples`` раундов; статистика."""
    if clients < 1 or samples < 1 or warmup_rounds < 0:
        raise ValueError("clients и samples должны быть не меньше 1, warmup_rounds — не меньше 0")
    pool = await _warm_up(base_url, transport, login, password, operations, warmup_rounds, seed)
    runs = await asyncio.gather(
        *(
            _client_run(
                index,
                base_url=base_url,
                transport=transport,
                login=login,
                password=password,
                operations=operations,
                pool=pool,
                samples=samples,
                seed=seed,
            )
            for index in range(clients)
        )
    )
    stats: list[OperationStats] = []
    for op in operations:
        merged = [value for run in runs for value in run[op.name]]
        stats.append(summarize(op, merged))
    return stats
