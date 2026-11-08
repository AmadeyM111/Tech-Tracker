"""spec 016 FR-2: харнесс ``load-measure`` (перцентили, конфиг операций, отказ при не-200).

Сервер заменён ``httpx.MockTransport``: тесты не ходят в сеть и не зависят от БД.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from app.domain.ops.load_measure import (
    OPERATIONS,
    MeasureError,
    Operation,
    measure,
    percentile,
)

TASK_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
BASE = "http://test"


def _page(items: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"items": items, "page": 1, "page_size": 50, "has_next": False, "total": total}


def _handler(*, fail_path: str | None = None, status: int = 500) -> Any:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/auth/login"):
            return httpx.Response(200, json={"user": {"login": "load.user1"}})
        if fail_path is not None and path == fail_path:
            return httpx.Response(status, json={"detail": "boom", "code": "internal"})
        if path == "/api/v1/me/overview/tasks":
            item = {
                "id": str(TASK_ID),
                "title": "t",
                "project": {"id": str(PROJECT_ID), "name": "p"},
                "parent_id": None,
            }
            return httpx.Response(200, json=_page([item], total=1))
        if path.endswith("/comments"):
            return httpx.Response(200, json=_page([], total=0))
        if path == f"/api/v1/tasks/{TASK_ID}":
            return httpx.Response(200, json={"id": str(TASK_ID)})
        if path == "/api/v1/me/overview":
            return httpx.Response(200, json={"total": 1})
        return httpx.Response(404, json={"detail": "нет", "code": "not_found"})

    return handle


def test_percentile_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 0.5) == 50.0
    assert percentile(values, 0.95) == 95.0
    assert percentile(values, 1.0) == 100.0
    assert percentile([7.0], 0.95) == 7.0
    assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0


def test_percentile_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        percentile([], 0.5)
    with pytest.raises(ValueError):
        percentile([1.0], 0.0)


def test_operations_config_matches_spec() -> None:
    """FR-2: плитки и список «Сводки» — 500 мс, карточка — 200 мс; пути в /api/v1."""
    by_name = {op.name: op for op in OPERATIONS}
    assert len({op.name for op in OPERATIONS}) == len(OPERATIONS)
    assert by_name["summary_tiles"].budget_p95_ms == 500
    assert by_name["summary_list"].budget_p95_ms == 500
    assert by_name["card_task"].budget_p95_ms == 200
    assert by_name["card_comments"].budget_p95_ms == 200
    assert all(op.path.startswith("/api/v1/") for op in OPERATIONS)
    # уведомления и вложения не замеряются, пока их эндпоинтов нет (spec 016, FR-2 и §8 plan)
    assert not any("notifications" in op.path or "attachments" in op.path for op in OPERATIONS)


async def test_measure_counts_and_verdict() -> None:
    transport = httpx.MockTransport(_handler())
    stats = await measure(
        base_url=BASE,
        login="load.user1",
        password="x" * 20,
        clients=2,
        samples=3,
        warmup_rounds=1,
        transport=transport,
    )
    assert [s.name for s in stats] == [op.name for op in OPERATIONS]
    assert all(s.n == 2 * 3 for s in stats)
    assert all(s.verdict == "ok" for s in stats)  # мок отвечает мгновенно
    assert all(s.p50_ms <= s.p95_ms <= s.max_ms for s in stats)
    assert "operation=summary_tiles n=6" in stats[0].line()


async def test_measure_stops_on_non_200() -> None:
    transport = httpx.MockTransport(_handler(fail_path="/api/v1/me/overview", status=500))
    with pytest.raises(MeasureError, match="summary_tiles: HTTP 500"):
        await measure(
            base_url=BASE,
            login="load.user1",
            password="x" * 20,
            clients=1,
            samples=1,
            warmup_rounds=0,
            transport=transport,
        )


async def test_measure_refuses_empty_set() -> None:
    def empty(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={})
        return httpx.Response(200, content=json.dumps(_page([], total=0)).encode())

    with pytest.raises(MeasureError, match="нет задач"):
        await measure(
            base_url=BASE,
            login="load.user1",
            password="x" * 20,
            clients=1,
            samples=1,
            warmup_rounds=0,
            transport=httpx.MockTransport(empty),
        )


async def test_measure_refuses_bad_login() -> None:
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "x", "code": "invalid_credentials"})

    with pytest.raises(MeasureError, match="вход отклонён: HTTP 401"):
        await measure(
            base_url=BASE,
            login="load.user1",
            password="wrong-password-1",
            clients=1,
            samples=1,
            warmup_rounds=0,
            transport=httpx.MockTransport(denied),
        )


async def test_measure_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError):
        await measure(base_url=BASE, login="a", password="b", clients=0, samples=1)


async def test_custom_operation_list_is_config() -> None:
    """Строку (например, счётчика уведомлений) добавляют списком, без правки кода замера."""
    extra = Operation("summary_extra", "tiles", "/api/v1/me/overview", 200)
    stats = await measure(
        base_url=BASE,
        login="load.user1",
        password="x" * 20,
        clients=1,
        samples=2,
        warmup_rounds=0,
        operations=(extra,),
        transport=httpx.MockTransport(_handler()),
    )
    assert [s.name for s in stats] == ["summary_extra"]
    assert stats[0].budget_p95_ms == 200
