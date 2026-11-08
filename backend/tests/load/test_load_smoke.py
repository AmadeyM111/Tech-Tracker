"""spec 016 FR-4, AC-4: короткий прогон замера в CI без проверки порогов.

500 задач, 5 клиентов по 10 замеров. Тест проходит, если набор загружен, операции отвечают 200 и
``measure`` вернул статистику по всем операциям. Пороги p95 здесь не проверяются (это AC-3, стенд).

Пропуск (с причиной в выводе pytest): до слияния «Сводки» (008) в ветке нет модуля
``app.api.v1.overview``, и операции «Сводки» вернули бы 404. Пропуск снимается слиянием.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import httpx
import pytest

from app.core.clock import FixedClock
from app.core.config import Settings
from app.domain.ops.load import LOAD_TEST_LOGIN, derive_password, load_synthetic_data
from app.domain.ops.load_measure import OPERATIONS, measure
from app.domain.system.bootstrap import run_bootstrap
from tests.conftest import FIXED_NOW

pytestmark = [
    pytest.mark.committed,
    pytest.mark.skipif(
        importlib.util.find_spec("app.api.v1.overview") is None,
        reason="маршруты «Сводки» (008) не слиты в эту ветку: смоук пропущен",
    ),
]

SEED = 16
TASKS = 500
CLIENTS = 5
SAMPLES = 10
FIRST_ADMIN_PASSWORD = "Zq7Lm2Vx9FirstAdminPw"


async def test_load_measure_smoke_exits_zero(committed: Any, settings: Settings) -> None:
    from app.main import create_app

    await run_bootstrap(
        committed,
        settings,
        clock=FixedClock(FIXED_NOW),
        generate=lambda: FIRST_ADMIN_PASSWORD,
    )
    await load_synthetic_data(committed, settings, seed=SEED, tasks=TASKS)

    app = create_app(settings, clock=FixedClock(FIXED_NOW))
    async with app.router.lifespan_context(app):
        app.state.sessionmaker = committed
        transport = httpx.ASGITransport(app=app)
        stats = await measure(
            base_url="http://testserver",
            login=LOAD_TEST_LOGIN,
            password=derive_password(SEED, LOAD_TEST_LOGIN),
            clients=CLIENTS,
            samples=SAMPLES,
            seed=SEED,
            transport=transport,
        )

    assert [s.name for s in stats] == [op.name for op in OPERATIONS]
    assert all(s.n == CLIENTS * SAMPLES for s in stats)
