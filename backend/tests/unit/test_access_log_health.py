"""T26 (перенос T20): ``/api/v1/health`` не пишется в access-лог на уровне INFO.

HEALTHCHECK образа api бьёт в этот путь каждые 10 с (~8,6 тыс. записей в сутки на пустом месте,
а ротация логов - 10 МБ x 5). Остальные запросы по-прежнему пишутся в INFO.

ВНИМАНИЕ: существующие тесты T09 ``tests/unit/test_logging.py::test_access_log_has_method_path_
status_duration`` (ожидает ровно одну запись health на уровне INFO) и
``test_access_log_strips_query_string`` (ищет запись health) противоречат этому контракту и
должны быть изменены владельцем тестов (пути /api/v1/health заменить на другой путь);
этот файл их не правит.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

from app.core.config import Settings


@pytest.fixture
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
async def client(restore_logging: None) -> AsyncIterator[httpx.AsyncClient]:
    from app.main import create_app

    app = create_app(Settings(env="test", cookie_secure=False, expose_api_docs=False))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_t20_health_requests_are_not_logged_at_info(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    for _ in range(3):
        assert (await client.get("/api/v1/health")).status_code == 200
    # контроль: access-лог не отключён целиком
    assert (await client.get("/api/v1/definitely-unknown")).status_code == 404

    records = [r for r in caplog.records if r.name == "app.access"]
    info = [(r.getMessage(), getattr(r, "path", None)) for r in records if r.levelno >= 20]
    paths_info = [p for _, p in info]
    assert "/api/v1/definitely-unknown" in paths_info, "обычные запросы должны логироваться"
    assert "/api/v1/health" not in paths_info, "health попал в INFO"
