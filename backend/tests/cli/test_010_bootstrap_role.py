"""D10-T02: ``gtrack bootstrap`` создаёт рабочую роль и пароль (spec 010 FR-1, FR-4; AC-6)."""

from __future__ import annotations

import asyncio
import secrets
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from tests.db_support import ALEMBIC_INI

pytestmark = pytest.mark.committed


@pytest.fixture
def role_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_database_url: str
) -> Iterator[tuple[Path, str]]:
    role = f"gt_app_t{secrets.token_hex(4)}"
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_APP_ROLE", role)
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_MEMORY_COST_KIB", "1024")
    monkeypatch.setenv("ARGON2_PARALLELISM", "1")
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ALEMBIC_INI))
    get_settings.cache_clear()
    yield tmp_path / "data", role
    get_settings.cache_clear()


def _run(argv: list[str]) -> int:
    from app.cli.main import main

    return int(main(argv))


async def test_010_ac6_bootstrap_creates_role_and_keeps_password(
    committed: Any,
    db_engine: AsyncEngine,
    role_env: tuple[Path, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    data, role = role_env
    try:
        assert await asyncio.to_thread(_run, ["bootstrap"]) == 0
        path = data / "secrets" / "db_app_password"
        password = path.read_text()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert await asyncio.to_thread(_run, ["bootstrap"]) == 0
        assert path.read_text() == password
        out, err = capsys.readouterr()
        assert password.strip() not in out + err
        async with db_engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT rolsuper, rolpassword FROM pg_authid WHERE rolname = :r"),
                    {"r": role},
                )
            ).one()
        assert row.rolsuper is False
        assert row.rolpassword.startswith("SCRAM-SHA-256$")
    finally:
        async with db_engine.begin() as conn:
            exists = (
                await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
            ).scalar()
            if exists:
                await conn.execute(text(f"DROP OWNED BY {role}"))
                await conn.execute(text(f"DROP ROLE {role}"))
