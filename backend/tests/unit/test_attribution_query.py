from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.domain.tasks.attribution import load_task_attribution


@pytest.mark.asyncio
async def test_attribution_empty_ids_ok(db: Any) -> None:
    assert await load_task_attribution(db, uuid4(), []) == {}


@pytest.mark.asyncio
async def test_attribution_unknown_ids_ok(db: Any) -> None:
    ws = uuid4()
    tid = uuid4()
    mapping = await load_task_attribution(db, ws, [tid])
    assert mapping[tid].last_client_name is None
