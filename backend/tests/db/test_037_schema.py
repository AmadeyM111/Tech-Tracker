"""Спека 037: таблица knowledge_record, миграция 0021, down_revision 0018."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.knowledge.models import KnowledgeRecord
from tests.db_support import run_alembic
from tests.factories import make_project, make_user, make_workspace


@pytest.mark.committed
async def test_037_migration_0021_upgrade_downgrade_upgrade_and_check(
    committed: Any, test_database_url: str
) -> None:
    async def alembic(*args: str) -> None:
        result = await asyncio.to_thread(run_alembic, test_database_url, *args)
        assert result.returncode == 0, (
            f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
        )

    await alembic("upgrade", "head")
    await alembic("downgrade", "0018")
    await alembic("upgrade", "head")
    await alembic("check")


async def test_037_space_forbids_project_id(db: Any) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role="business_admin")
    project = await make_project(db, workspace_id=ws.id, owner_id=user.id)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                KnowledgeRecord(
                    workspace_id=ws.id,
                    scope="space",
                    project_id=project.id,
                    kind="decision",
                    title="Решили",
                    body="Потому что",
                    confirmed_by=user.id,
                    created_by=user.id,
                )
            )
            await db.flush()


async def test_037_agreement_requires_confirmed_with(db: Any) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role="business_admin")
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                KnowledgeRecord(
                    workspace_id=ws.id,
                    scope="space",
                    project_id=None,
                    kind="agreement",
                    title="Договорились",
                    body="Потому что",
                    confirmed_with=None,
                    confirmed_by=user.id,
                    created_by=user.id,
                )
            )
            await db.flush()
    db.add(
        KnowledgeRecord(
            workspace_id=ws.id,
            scope="space",
            kind="agreement",
            title="Договорились",
            body="Потому что",
            confirmed_with="Илья",
            confirmed_by=user.id,
            created_by=user.id,
        )
    )
    await db.flush()
