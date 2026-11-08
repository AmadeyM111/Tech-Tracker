"""D10-T02: API работает под рабочей ролью БД (spec 010 FR-3; AC-4).

Движок берётся из lifespan приложения (без подмены ``sessionmaker``), роль создаёт
``ensure_app_role`` под владельцем; роль кластера удаляется после теста.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.db_roles import ensure_app_password, ensure_app_role, scram_verifier
from app.main import create_app
from tests.factories import make_user

pytestmark = pytest.mark.committed


@pytest_asyncio.fixture
async def role_settings(
    committed: Any, db_engine: AsyncEngine, settings: Settings
) -> AsyncIterator[Settings]:
    role = f"gt_app_t{secrets.token_hex(4)}"
    cfg = settings.model_copy(update={"db_app_role": role})
    async with db_engine.begin() as conn:
        await ensure_app_role(conn, role, scram_verifier(ensure_app_password(cfg)))
    try:
        yield cfg
    finally:
        async with db_engine.begin() as conn:
            await conn.execute(text(f"DROP OWNED BY {role}"))
            await conn.execute(text(f"DROP ROLE {role}"))


async def test_010_ac4_login_and_project_create_under_app_role(
    role_settings: Settings, committed: Any, fixed_clock: FixedClock
) -> None:
    async with committed() as s:
        ba = await make_user(s, role="business_admin")
        await s.commit()
    app = create_app(role_settings, clock=fixed_clock)
    async with app.router.lifespan_context(app):
        engine: AsyncEngine = app.state.engine
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT current_user"))).scalar_one() == (
                role_settings.db_app_role
            )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            login = await c.post(
                "/api/v1/auth/login", json={"login": ba.login, "password": ba.password}
            )
            assert login.status_code == 200, login.text
            cookie = login.headers["set-cookie"].split(";", 1)[0]
            created = await c.post(
                "/api/v1/projects", json={"name": "Проект под ролью"}, headers={"Cookie": cookie}
            )
            assert created.status_code == 201, created.text
            listed = await c.get("/api/v1/projects", headers={"Cookie": cookie})
            assert listed.status_code == 200
