"""Общие помощники доменных тестов задач (T75). Не тест-модуль."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tests.factories import make_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.projects_support import World


async def mk_task(
    db: AsyncSession,
    w: World,
    *,
    created_by: uuid.UUID | None = None,
    commit: bool = True,
    **kw: Any,
) -> uuid.UUID:
    """Задача в проекте мира (по умолчанию автор — владелец ``ba``); фиксируется."""
    kw.setdefault("project_id", w.project_id)
    row = await make_task(db, workspace_id=w.ws.id, created_by=created_by or w.ba.id, **kw)
    if commit:
        await db.commit()
    return row.id


async def column(db: AsyncSession, project_id: uuid.UUID, status: str) -> list[uuid.UUID]:
    """Порядок колонки: неудалённые верхнего уровня по (position, created_at, id)."""
    await db.flush()
    rows = await db.execute(
        text(
            "SELECT id FROM task WHERE project_id = :p AND status = :s AND deleted_at IS NULL "
            "AND parent_id IS NULL ORDER BY position, created_at, id"
        ).bindparams(p=project_id, s=status)
    )
    return [r[0] for r in rows]


async def positions(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int | None]:
    await db.flush()
    rows = await db.execute(
        text("SELECT id, position FROM task WHERE id = ANY(:ids)").bindparams(ids=ids)
    )
    return {r[0]: r[1] for r in rows}
