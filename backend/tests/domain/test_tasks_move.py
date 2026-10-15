"""T75: перемещение карточки по доске (plan §11.4, §11.5, §10.2 п.4; FR-19b, FR-28a, D-40, D-55).

AC-47 (исполнитель переносит статус), AC-48 (БА не владелец), AC-61, AC-81, AC-103, FR-21.

Ожидаемый интерфейс ``app.domain.tasks.service``::

    move(db, actor, task_id, *, status: TaskStatus | str,
         before_task_id: UUID | None, after_task_id: UUID | None) -> None

Порядок: контекст (404, FOR SHARE проекта) -> подзадача: 422 ``validation_error`` ->
``can_change_task_status`` (403) -> неверный статус 422 ``validation_error`` ->
``positions.move_task`` (сама перечитывает и блокирует строку; 422 ``invalid_neighbors``;
503 ``service_busy`` при исчерпании попыток). ``after_task_id`` — сосед сверху,
``before_task_id`` — сосед снизу. События не пишутся (D-55). ``commit()`` не вызывается.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from tests.factories import make_project, make_task, make_user, make_workspace
from tests.projects_support import (
    actor_of,
    add_member_row,
    capture_sql,
    events,
    fails,
    forbidden,
    make_world,
    not_found,
    task_row,
)
from tests.tasks_support import column, mk_task, positions

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

STEP = 1024


@pytest.fixture
def svc() -> Any:
    import app.domain.tasks.service as module

    return module


async def _mv(
    svc: Any,
    db: AsyncSession,
    who: Any,
    task_id: uuid.UUID,
    status: str,
    *,
    before: uuid.UUID | None = None,
    after: uuid.UUID | None = None,
) -> Any:
    return await svc.move(
        db, actor_of(who), task_id, status=status, before_task_id=before, after_task_id=after
    )


# --- позиция ----------------------------------------------------------------------------------


async def test_ac61_move_between_neighbors_in_same_column(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    a = await mk_task(db, w, position=1024)
    b = await mk_task(db, w, position=2048)
    c = await mk_task(db, w, position=3072)
    result = await _mv(svc, db, w.ba, c, "todo", after=a, before=b)
    assert result is None
    assert await column(db, w.project_id, "todo") == [a, c, b]
    assert (await task_row(db, c)).position == 1536
    assert (await task_row(db, a)).position == 1024  # соседи не тронуты
    assert (await task_row(db, b)).position == 2048


async def test_ac61_move_to_other_column_between_neighbors(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    r1 = await mk_task(db, w, status="review", position=1024)
    r2 = await mk_task(db, w, status="review", position=2048)
    t = await mk_task(db, w, position=1024)
    await _mv(svc, db, w.ba, t, "review", after=r1, before=r2)
    assert await column(db, w.project_id, "review") == [r1, t, r2]
    r = await task_row(db, t)
    assert (r.status, r.position) == ("review", 1536)
    assert await column(db, w.project_id, "todo") == []


async def test_ac81_move_without_neighbors_goes_to_end_of_column(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    ids = [await mk_task(db, w, status="in_progress", position=STEP * i) for i in (1, 2, 3)]
    t = await mk_task(db, w, position=1024)
    await _mv(svc, db, w.ba, t, "in_progress")
    assert await column(db, w.project_id, "in_progress") == [*ids, t]
    assert (await task_row(db, t)).position == 3 * STEP + STEP


async def test_ac61_move_into_empty_column(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w, position=5000)
    await _mv(svc, db, w.ba, t, "done")
    r = await task_row(db, t)
    assert (r.status, r.position) == ("done", STEP)


async def test_ac61_move_to_first_and_last_place(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    a = await mk_task(db, w, position=1024)
    b = await mk_task(db, w, position=2048)
    c = await mk_task(db, w, position=3072)
    await _mv(svc, db, w.ba, c, "todo", before=a)  # перед первой
    assert await column(db, w.project_id, "todo") == [c, a, b]
    await _mv(svc, db, w.ba, c, "todo", after=b)  # после последней
    assert await column(db, w.project_id, "todo") == [a, b, c]


async def test_ac61_exhausted_gap_renumbers_and_keeps_order(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    a = await mk_task(db, w, position=1000)
    b = await mk_task(db, w, position=1001)
    t = await mk_task(db, w, position=9000)
    await _mv(svc, db, w.ba, t, "todo", after=a, before=b)
    assert await column(db, w.project_id, "todo") == [a, t, b]
    ps = await positions(db, [a, t, b])
    assert len(set(ps.values())) == 3
    # после перенумерации соседи кратны STEP, новая карточка — середина между ними
    assert (ps[a], ps[b]) == (STEP, 2 * STEP)
    assert ps[t] is not None and STEP < ps[t] < 2 * STEP


async def test_ac61_repeated_move_is_idempotent(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    a = await mk_task(db, w, position=1024)
    b = await mk_task(db, w, position=2048)
    t = await mk_task(db, w, status="done", position=1024)
    await _mv(svc, db, w.ba, t, "todo", after=a, before=b)
    first = await positions(db, [a, b, t])
    await _mv(svc, db, w.ba, t, "todo", after=a, before=b)
    assert await positions(db, [a, b, t]) == first
    assert await column(db, w.project_id, "todo") == [a, t, b]
    # без соседей в той же колонке — остаётся последней
    await _mv(svc, db, w.ba, t, "todo")
    await _mv(svc, db, w.ba, t, "todo")
    assert await column(db, w.project_id, "todo") == [a, b, t]


async def test_ac61_move_updates_only_moved_task_updated_at(
    db: AsyncSession, svc: Any, fixed_clock: Any
) -> None:
    w = await make_world(db)
    a = await mk_task(db, w, position=1024)
    t = await mk_task(db, w, status="done", position=1024)
    a_updated = (await task_row(db, a)).updated_at
    fixed_clock.advance(timedelta(minutes=5))
    await _mv(svc, db, w.ba, t, "todo", after=a)
    assert (await task_row(db, t)).updated_at == fixed_clock.now()
    assert (await task_row(db, a)).updated_at == a_updated


async def test_fr21_moving_parent_leaves_subtask_position_null(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w, position=1024)
    sub = await mk_task(db, w, parent_id=parent)
    await _mv(svc, db, w.ba, parent, "review")
    assert (await task_row(db, sub)).position is None
    assert (await task_row(db, sub)).status == "todo"


# --- права ------------------------------------------------------------------------------------


async def test_ac47_assignee_moves_assigned_task(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w, assignee_id=w.usr.id)  # автор ba
    await _mv(svc, db, w.usr, t, "in_progress")
    assert (await task_row(db, t)).status == "in_progress"


async def test_ac47_user_cannot_move_foreign_task(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w, assignee_id=w.ba2.id)
    unassigned = await mk_task(db, w)
    for tid in (t, unassigned):
        await forbidden(db, _mv(svc, db, w.usr, tid, "done"))
        r = await task_row(db, tid)
        assert (r.status, r.position) == ("todo", 1024)


async def test_ac48_ba_not_owner_moves_only_own_task(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    foreign = await mk_task(db, w, assignee_id=w.usr.id)
    for_other = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.usr.id)
    own = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.ba2.id)
    for tid in (foreign, for_other):
        await forbidden(db, _mv(svc, db, w.ba2, tid, "done"))
        assert (await task_row(db, tid)).status == "todo"
    await _mv(svc, db, w.ba2, own, "done")
    assert (await task_row(db, own)).status == "done"
    # исполнитель-БА (не владелец) чужой задачи переносит её (FR-19b)
    assigned = await mk_task(db, w, assignee_id=w.ba2.id)
    await _mv(svc, db, w.ba2, assigned, "review")
    assert (await task_row(db, assigned)).status == "review"


async def test_ac48_owner_ba_moves_any_task(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.usr.id)
    await _mv(svc, db, w.ba, t, "review")
    assert (await task_row(db, t)).status == "review"


async def test_ac103_sm_member_moves_non_member_403(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w, assignee_id=w.usr.id)
    await forbidden(db, _mv(svc, db, w.sm, t, "done"))
    await add_member_row(db, w, w.project_id, w.sm)
    await db.commit()
    await _mv(svc, db, w.sm, t, "done")
    assert (await task_row(db, t)).status == "done"


@pytest.mark.parametrize("who", ["ta", "norole", "usr2", "ba3"])
async def test_fr19_move_no_rights_actors_get_403(db: AsyncSession, svc: Any, who: str) -> None:
    w = await make_world(db)
    t = await mk_task(db, w, assignee_id=w.usr.id)
    await forbidden(db, _mv(svc, db, getattr(w, who), t, "done"))
    r = await task_row(db, t)
    assert (r.status, r.position) == ("todo", 1024)


async def test_fr19_403_comes_before_neighbor_validation(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w, assignee_id=w.ba2.id)
    await forbidden(db, _mv(svc, db, w.usr, t, "done", after=uuid.uuid4()))


# --- 404 / подзадача / валидация --------------------------------------------------------------


async def test_fr13_move_404_unknown_deleted_foreign_deleted_project(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    other_ws = await make_workspace(db)
    other_owner = await make_user(db, workspace=other_ws, role="business_admin", login="o.ba")
    other_project = await make_project(db, workspace_id=other_ws.id, owner_id=other_owner.id)
    foreign = await make_task(
        db, project_id=other_project.id, workspace_id=other_ws.id, created_by=other_owner.id
    )
    deleted = await mk_task(db, w, deleted_at=datetime(2026, 1, 1))
    dead_project = await make_project(
        db, workspace_id=w.ws.id, owner_id=w.ba.id, deleted_at=datetime(2026, 1, 1)
    )
    in_dead = await mk_task(db, w, project_id=dead_project.id)
    await db.commit()
    for tid in (uuid.uuid4(), foreign.id, deleted, in_dead):
        for who in (w.ba, w.ta):
            await not_found(db, _mv(svc, db, who, tid, "done"))


async def test_fr21_moving_subtask_is_422_validation_error_before_403(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w)
    sub = await mk_task(db, w, parent_id=parent, assignee_id=w.usr.id)
    for who in (w.ba, w.usr, w.usr2, w.ta):  # подзадача раньше проверки прав
        await fails(db, _mv(svc, db, who, sub, "done"), "validation_error")
    r = await task_row(db, sub)
    assert (r.status, r.position) == ("todo", None)


async def test_ac61_invalid_status_is_422(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w)
    await fails(db, _mv(svc, db, w.ba, t, "archived"), "validation_error")
    assert (await task_row(db, t)).status == "todo"


async def test_ac61_invalid_neighbors_are_422(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w, position=1024)
    todo_other = await mk_task(db, w, position=2048)  # соседняя не из целевой колонки
    in_review = await mk_task(db, w, status="review", position=1024)
    deleted = await mk_task(db, w, status="review", position=2048, deleted_at=datetime(2026, 1, 1))
    parent = await mk_task(db, w, status="review", position=3072)
    sub = await mk_task(db, w, parent_id=parent, status="review")
    other_project = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Другой")
    foreign_project_task = await mk_task(
        db, w, project_id=other_project.id, status="review", position=4096
    )
    bad = [uuid.uuid4(), todo_other, deleted, sub, foreign_project_task, t]
    for neighbor in bad:
        for kw in ({"after": neighbor}, {"before": neighbor}):
            await fails(db, _mv(svc, db, w.ba, t, "review", **kw), "invalid_neighbors")
    await fails(
        db, _mv(svc, db, w.ba, t, "review", after=in_review, before=in_review), "invalid_neighbors"
    )
    r = await task_row(db, t)
    assert (r.status, r.position) == ("todo", 1024)


async def test_p10_2_move_locks_project_share(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w)
    with capture_sql(db) as seen:
        await _mv(svc, db, w.ba, t, "review")
    assert any("for share" in s.lower() and "from project" in s.lower() for s in seen), seen
    assert any("pg_advisory_xact_lock" in s.lower() for s in seen), seen


async def test_d55_move_writes_no_events(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w)
    await _mv(svc, db, w.ba, t, "done")
    assert await events(db, w.ws.id) == []


async def test_t73_review_exhausted_lock_attempts_is_503(
    db: AsyncSession, svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ServiceBusy из positions.move_task проходит через move как 503 service_busy."""
    import app.domain.tasks.positions as pos

    w = await make_world(db)
    t = await mk_task(db, w)
    answers = iter(["review", "done", "review", "done", "review", "done"])

    async def flapping(_db: Any, _task_id: Any, *, lock: bool) -> str:
        return next(answers)

    monkeypatch.setattr(pos, "_read_state", flapping)
    await fails(db, _mv(svc, db, w.ba, t, "done"), "service_busy", status=503)


# --- перечитывание и гонки (committed) --------------------------------------------------------


@pytest.mark.committed
async def test_t74_review_move_rereads_assignee_after_project_lock(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Исполнитель переназначен другой сессией (под FOR NO KEY UPDATE проекта) — перенос
    бывшего исполнителя после ожидания FOR SHARE получает 403, а не успех по старому снимку."""
    from app.core.errors import Forbidden

    async with committed() as setup:
        w = await make_world(setup)
        t = await mk_task(setup, w, assignee_id=w.usr.id)
    holder = committed()
    try:
        await holder.execute(
            text("SELECT 1 FROM project WHERE id = :p FOR NO KEY UPDATE").bindparams(p=w.project_id)
        )
        await holder.execute(
            text("UPDATE task SET assignee_id = :a WHERE id = :t").bindparams(a=w.ba2.id, t=t)
        )

        async def job() -> None:
            async with committed() as s:
                try:
                    await svc.move(
                        s, actor_of(w.usr), t, status="done", before_task_id=None,
                        after_task_id=None,
                    )  # fmt: skip
                    await s.commit()
                finally:
                    await s.rollback()

        task = asyncio.ensure_future(job())
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert not done
        await holder.commit()
    finally:
        await holder.close()
    with pytest.raises(Forbidden):
        await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        assert (await task_row(s, t)).status == "todo"


@pytest.mark.committed
async def test_ac61_concurrent_moves_no_deadlock_unique_positions(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Параллельные перемещения (move, update статуса) между теми же соседями и колонками:
    без взаимоблокировок, без 5xx, позиции уникальны, порядок колонки согласован."""
    async with committed() as setup:
        w = await make_world(setup)
        anchors = [
            await mk_task(setup, w, status="review", position=STEP * (i + 1)) for i in range(2)
        ]
        movers_a = [await mk_task(setup, w, position=STEP * (i + 1)) for i in range(6)]
        movers_b = [
            await mk_task(setup, w, status="in_progress", position=STEP * (i + 1)) for i in range(6)
        ]

    async def run_move(ids: list[uuid.UUID]) -> None:
        for tid in ids:
            async with committed() as s:
                await svc.move(
                    s, actor_of(w.ba), tid, status="review",
                    after_task_id=anchors[0], before_task_id=anchors[1],
                )  # fmt: skip
                await s.commit()

    async def run_update(ids: list[uuid.UUID]) -> None:
        for tid in ids:
            async with committed() as s:
                await svc.update_task(s, actor_of(w.ba), tid, svc.TaskPatch(status="todo"))
                await s.commit()
            async with committed() as s:
                await svc.move(
                    s, actor_of(w.ba), tid, status="done", after_task_id=None,
                    before_task_id=None,
                )  # fmt: skip
                await s.commit()

    extra = []
    async with committed() as setup:
        for _ in range(4):
            extra.append(await mk_task(setup, w, status="review", position=9000))

    outcomes = await asyncio.wait_for(
        asyncio.gather(
            run_move(movers_a), run_move(movers_b), run_update(extra), return_exceptions=True
        ),
        timeout=60,
    )
    assert outcomes == [None, None, None], outcomes
    async with committed() as s:
        col = await column(s, w.project_id, "review")
        assert len(col) == 2 + 12
        assert col[0] == anchors[0] and col[-1] == anchors[1]
        ps = await positions(s, col)
        assert len(set(ps.values())) == len(col)
        assert [ps[i] for i in col] == sorted(p for p in ps.values() if p is not None)
        done_col = await column(s, w.project_id, "done")
        assert sorted(done_col) == sorted(extra)
        dps = await positions(s, done_col)
        assert len(set(dps.values())) == len(done_col)


@pytest.mark.committed
async def test_d56_delete_task_concurrent_with_move_has_no_deadlock(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    from app.core.errors import AppError

    async with committed() as setup:
        w = await make_world(setup)
        ids = [await mk_task(setup, w, position=STEP * (i + 1)) for i in range(8)]
    go = asyncio.Event()

    async def run(factory: Any) -> str:
        async with committed() as s:
            await go.wait()
            try:
                await factory(s)
                await s.commit()
            except AppError as exc:
                await s.rollback()
                return str(exc.code)
            return "ok"

    jobs = []
    for i, tid in enumerate(ids):
        jobs.append(
            run(
                lambda s, tid=tid: svc.move(
                    s,
                    actor_of(w.ba),
                    tid,
                    status="review",
                    before_task_id=None,
                    after_task_id=None,
                )  # fmt: skip
            )
        )
        if i % 2 == 0:
            jobs.append(run(lambda s, tid=tid: svc.delete_task(s, actor_of(w.ba), tid)))
    futures = [asyncio.ensure_future(j) for j in jobs]
    await asyncio.sleep(0)
    go.set()
    results = await asyncio.wait_for(asyncio.gather(*futures, return_exceptions=True), timeout=30)
    assert set(results) <= {"ok", "not_found"}, results
    async with committed() as s:
        live = await column(s, w.project_id, "review") + await column(s, w.project_id, "todo")
        ps = await positions(s, live)
        in_review = await column(s, w.project_id, "review")
        assert len({ps[i] for i in in_review}) == len(in_review)


async def test_t75_review_subtask_422_message_is_same_in_move_and_move_task(
    db: AsyncSession, svc: Any
) -> None:
    from app.core.errors import AppError
    from app.domain.tasks import positions as pos
    from app.domain.tasks.models import Task, TaskStatus

    w = await make_world(db)
    parent = await mk_task(db, w)
    sub = await mk_task(db, w, parent_id=parent)
    with pytest.raises(AppError) as via_service:
        await _mv(svc, db, w.ba, sub, "done")
    await db.rollback()
    task = await db.get(Task, sub)
    assert task is not None
    with pytest.raises(AppError) as via_positions:
        await pos.move_task(
            db, task, status=TaskStatus.DONE, before_task_id=None, after_task_id=None
        )
    assert via_service.value.detail == via_positions.value.detail
    assert str(via_service.value.code) == str(via_positions.value.code) == "validation_error"
