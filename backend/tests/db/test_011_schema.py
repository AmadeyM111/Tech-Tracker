"""A11-T01: схема ``attachment`` и миграция 0012 (spec 011 FR-5)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.attachments.models import Attachment
from tests.db_support import run_alembic
from tests.factories import make_project, make_task, make_user


@pytest.mark.committed
async def test_011_migration_0012_upgrade_downgrade_upgrade_and_check(
    committed: Any, test_database_url: str
) -> None:
    async def alembic(*args: str) -> None:
        result = await asyncio.to_thread(run_alembic, test_database_url, *args)
        assert result.returncode == 0, f"{args}: {result.stdout}\n{result.stderr}"

    await alembic("upgrade", "head")
    await alembic("downgrade", "0011")
    await alembic("upgrade", "head")
    await alembic("check")


async def _row(db: Any, **over: Any) -> Attachment:
    user = await make_user(db, role="business_admin")
    project = await make_project(db, workspace_id=user.workspace_id, owner_id=user.id)
    task = await make_task(
        db, project_id=project.id, workspace_id=user.workspace_id, created_by=user.id
    )
    values: dict[str, Any] = {
        "workspace_id": user.workspace_id,
        "task_id": task.id,
        "project_id": project.id,
        "created_by": user.id,
        "original_name": "отчёт.pdf",
        "kind": "pdf",
        "content_type": "application/pdf",
        "size_bytes": 10,
        "sha256": "a" * 64,
        "storage_key": uuid.uuid4().hex,
    }
    values.update(over)
    row = Attachment(**values)
    db.add(row)
    await db.flush()
    return row


async def test_011_attachment_row_roundtrip(db: Any) -> None:
    row = await _row(db)
    assert row.deleted_at is None


@pytest.mark.parametrize(
    "over",
    [
        {"original_name": ""},
        {"size_bytes": 0},
        {"sha256": "XYZ"},
        {"storage_key": "../escape"},
        {"kind": "svg"},
    ],
    ids=["empty-name", "zero-size", "bad-sha", "bad-key", "svg"],
)
async def test_011_attachment_constraints(db: Any, over: dict[str, Any]) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await _row(db, **over)
