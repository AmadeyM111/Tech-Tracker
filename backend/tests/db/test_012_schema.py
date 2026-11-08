"""N12-T01: схема ``comment_mention`` и ``notification``, миграция 0013 (spec 012)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.db_support import run_alembic


@pytest.mark.committed
async def test_012_migration_0013_upgrade_downgrade_upgrade_and_check(
    committed: Any, test_database_url: str
) -> None:
    async def alembic(*args: str) -> None:
        result = await asyncio.to_thread(run_alembic, test_database_url, *args)
        assert result.returncode == 0, f"{args}: {result.stdout}\n{result.stderr}"

    await alembic("upgrade", "head")
    await alembic("downgrade", "0012")
    await alembic("upgrade", "head")
    await alembic("check")
