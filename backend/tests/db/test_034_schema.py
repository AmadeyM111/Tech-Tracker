"""Спека 034: таблица external_message, уникальный ключ, миграция 0020."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.inbox.models import ExternalMessage
from tests.db_support import run_alembic
from tests.factories import make_comment, make_project, make_task, make_user, make_workspace


@pytest.mark.committed
async def test_034_migration_0020_upgrade_downgrade_upgrade_and_check(
    committed: Any, test_database_url: str
) -> None:
    async def alembic(*args: str) -> None:
        result = await asyncio.to_thread(run_alembic, test_database_url, *args)
        assert result.returncode == 0, (
            f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
        )

    await alembic("upgrade", "head")
    await alembic("downgrade", "0019")
    await alembic("upgrade", "head")
    await alembic("check")


async def test_034_external_message_unique_per_workspace_source_id(db: Any) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role="business_admin")
    project = await make_project(db, workspace_id=ws.id, owner_id=user.id)
    task = await make_task(db, project_id=project.id, workspace_id=ws.id, created_by=user.id)
    db.add(
        ExternalMessage(
            workspace_id=ws.id,
            source="telegram",
            external_id="chat:1",
            task_id=task.id,
        )
    )
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                ExternalMessage(
                    workspace_id=ws.id,
                    source="telegram",
                    external_id="chat:1",
                    task_id=task.id,
                )
            )
            await db.flush()
    comment = await make_comment(db, task_id=task.id, workspace_id=ws.id, created_by=user.id)
    db.add(
        ExternalMessage(
            workspace_id=ws.id,
            source="telegram",
            external_id="chat:2",
            task_id=task.id,
            comment_id=comment.id,
            url="https://t.me/c/1/2",
        )
    )
    await db.flush()
