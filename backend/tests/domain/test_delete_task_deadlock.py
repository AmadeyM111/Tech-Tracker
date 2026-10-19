"""T80 (регрессия ревью T79): ``delete_task`` не даёт взаимоблокировку с параллельным удалением.

Параллельные ``delete_task(parent)`` и ``delete_task(subtask)`` при комментариях у подзадачи:
порядок обновлений comment/task обязан быть единым (сначала task/семья, потом comment).
Допустимо: оба успешны или один получает 404; недопустимо: 40P01 / DBAPIError.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from tests.factories import make_comment
from tests.projects_support import actor_of, make_world
from tests.tasks_support import mk_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ROUNDS = 40


@pytest.mark.committed
async def test_t79_review_parallel_delete_parent_and_subtask_no_deadlock(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    import app.domain.tasks.service as svc
    from app.core.errors import AppError

    async with committed() as setup:
        w = await make_world(setup)
        pairs = []
        for _ in range(ROUNDS):
            parent = await mk_task(setup, w)
            sub = await mk_task(setup, w, parent_id=parent)
            for task_id in (sub, sub, parent):
                await make_comment(
                    setup, task_id=task_id, workspace_id=w.ws.id, created_by=w.usr.id
                )
            pairs.append((parent, sub))
        await setup.commit()

    outcomes: list[Any] = []

    async def run(task_id: Any, gate: asyncio.Event) -> None:
        async with committed() as s:
            await gate.wait()
            try:
                await svc.delete_task(s, actor_of(w.ba), task_id)
                await s.commit()
                outcomes.append("ok")
            except AppError as exc:
                await s.rollback()
                outcomes.append(str(exc.code))
            except BaseException as exc:  # DBAPIError/40P01 и прочее — провал
                await s.rollback()
                outcomes.append(f"ERR {type(exc).__name__}: {str(exc)[:80]}")

    # все раунды сразу: сессий 2*ROUNDS — ограничим пачками, чтобы не упереться в пул
    for start in range(0, ROUNDS, 10):
        gate = asyncio.Event()
        jobs = []
        for parent, sub in pairs[start : start + 10]:
            jobs += [run(parent, gate), run(sub, gate)]
        futures = [asyncio.ensure_future(j) for j in jobs]
        await asyncio.sleep(0.05)
        gate.set()
        await asyncio.wait_for(asyncio.gather(*futures), timeout=60)

    bad = [o for o in outcomes if o not in {"ok", "not_found"}]
    assert not bad, bad[:5]
    assert len(outcomes) == 2 * ROUNDS
