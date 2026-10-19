"""T73: позиции карточек и перемещение по соседям (plan §4.8, D-22, §10.2 п.4; FR-28a).

AC-61 (домен), AC-81 (домен), FR-21 (подзадачи без позиции), FR-28a.

Ожидаемый интерфейс ``app.domain.tasks.positions``::

    STEP: Final = 1024
    async lock_columns(db, project_id: UUID, *statuses: TaskStatus) -> None
        # pg_advisory_xact_lock(hashtext(f"{project_id}:{status}")), уникальные статусы по порядку
    async append_position(db, project_id: UUID, status: TaskStatus) -> int
        # max(position) по неудалённым задачам верхнего уровня колонки + STEP, иначе STEP
    async renumber_column(db, project_id: UUID, status: TaskStatus) -> None
        # STEP, 2*STEP, ... по (position, created_at, id); неудалённые верхнего уровня
    async move_task(db, task: Task, *, status: TaskStatus,
                    before_task_id: UUID | None, after_task_id: UUID | None) -> None
        # меняет task.status и task.position; плохие соседи -> Unprocessable(code=invalid_neighbors)

``after_task_id`` — сосед сверху, ``before_task_id`` — сосед снизу. ``commit`` функции не вызывают.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from app.domain.tasks.models import Task, TaskStatus
from tests.factories import make_project, make_task, make_workspace
from tests.projects_support import fails, make_world

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.projects_support import World

STEP = 1024
TODO, PROG, REVIEW, DONE = (
    TaskStatus.TODO,
    TaskStatus.IN_PROGRESS,
    TaskStatus.REVIEW,
    TaskStatus.DONE,
)


@pytest.fixture
def pos() -> Any:
    import app.domain.tasks.positions as positions

    return positions


async def _task(db: AsyncSession, w: World, **kw: Any) -> uuid.UUID:
    row = await make_task(
        db, project_id=kw.pop("project_id", w.project_id), workspace_id=w.ws.id,
        created_by=w.ba.id, **kw,
    )  # fmt: skip
    return kw.get("id", row.id)  # type: ignore[no-any-return]


async def _column(db: AsyncSession, project_id: uuid.UUID, status: str) -> list[uuid.UUID]:
    rows = await db.execute(
        text(
            "SELECT id FROM task WHERE project_id = :p AND status = :s AND deleted_at IS NULL "
            "AND parent_id IS NULL ORDER BY position, created_at, id"
        ).bindparams(p=project_id, s=str(status))
    )
    return [r[0] for r in rows]


async def _positions(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int | None]:
    rows = await db.execute(
        text("SELECT id, position FROM task WHERE id = ANY(:ids)").bindparams(ids=ids)
    )
    return {r[0]: r[1] for r in rows}


async def _pos(db: AsyncSession, task_id: uuid.UUID) -> int:
    value = (await _positions(db, [task_id]))[task_id]
    assert value is not None
    return value


async def _status(db: AsyncSession, task_id: uuid.UUID) -> str:
    return str((await db.execute(
        text("SELECT status FROM task WHERE id = :i").bindparams(i=task_id)
    )).scalar_one())  # fmt: skip


async def _move(
    db: AsyncSession,
    pos: Any,
    task_id: uuid.UUID,
    *,
    status: TaskStatus,
    before: uuid.UUID | None = None,
    after: uuid.UUID | None = None,
) -> None:
    task = await db.get(Task, task_id, populate_existing=True)
    assert task is not None
    await pos.move_task(db, task, status=status, before_task_id=before, after_task_id=after)
    await db.flush()


def test_step_is_1024(pos: Any) -> None:
    assert pos.STEP == 1024


# --- append_position ---------------------------------------------------------------------


async def test_ac61_append_position_empty_column_is_step(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    assert await pos.append_position(db, w.project_id, TODO) == STEP


async def test_ac61_append_position_is_max_plus_step(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    await _task(db, w, position=500)
    await _task(db, w, position=7000)
    await _task(db, w, position=3)
    assert await pos.append_position(db, w.project_id, TODO) == 7000 + STEP


async def test_ac61_append_position_ignores_other_column_project_deleted_subtasks(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    other = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Другой")
    parent = await _task(db, w, position=2048)
    await _task(db, w, status="in_progress", position=90000)
    await _task(db, w, project_id=other.id, position=80000)
    await _task(db, w, position=70000, deleted_at=datetime.now(UTC))
    await _task(db, w, parent_id=parent, position=None)
    assert await pos.append_position(db, w.project_id, TODO) == 2048 + STEP
    assert await pos.append_position(db, w.project_id, REVIEW) == STEP


# --- move_task: сосед сверху / снизу / между --------------------------------------------


async def test_ac61_move_between_two_neighbors_takes_midpoint(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=1024)
    b = await _task(db, w, position=2048)
    c = await _task(db, w, position=3072)
    await db.commit()
    await _move(db, pos, c, status=TODO, after=a, before=b)
    assert await _pos(db, c) == 1536
    assert await _column(db, w.project_id, "todo") == [a, c, b]


async def test_ac61_move_after_only_uses_next_neighbor_as_upper_bound(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=1024)
    b = await _task(db, w, position=2048)
    c = await _task(db, w, position=3072)
    await db.commit()
    await _move(db, pos, c, status=TODO, after=a)
    assert await _column(db, w.project_id, "todo") == [a, c, b]
    assert await _pos(db, c) == 1536


async def test_ac61_move_after_last_goes_to_end(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=1024)
    b = await _task(db, w, position=2048)
    c = await _task(db, w, position=3072)
    await db.commit()
    await _move(db, pos, a, status=TODO, after=c)
    assert await _column(db, w.project_id, "todo") == [b, c, a]
    assert await _pos(db, a) == 3072 + STEP


async def test_ac61_move_before_first_goes_to_start(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=1024)
    b = await _task(db, w, position=2048)
    c = await _task(db, w, position=3072)
    await db.commit()
    await _move(db, pos, c, status=TODO, before=a)
    assert await _column(db, w.project_id, "todo") == [c, a, b]
    # plan D-22: нижняя граница = high - 2*STEP, позиция = (low + high) // 2 = high - STEP
    assert await _pos(db, c) == 1024 - STEP


async def test_ac61_move_before_only_uses_previous_neighbor_as_lower_bound(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=1024)
    b = await _task(db, w, position=2048)
    c = await _task(db, w, position=3072)
    await db.commit()
    await _move(db, pos, a, status=TODO, before=c)
    assert await _column(db, w.project_id, "todo") == [b, a, c]
    assert await _pos(db, a) == (2048 + 3072) // 2


async def test_ac61_move_to_other_column_changes_status_and_inserts_between(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    x = await _task(db, w, status="in_progress", position=1024)
    y = await _task(db, w, status="in_progress", position=2048)
    t = await _task(db, w, position=1024)
    await db.commit()
    await _move(db, pos, t, status=PROG, after=x, before=y)
    assert await _status(db, t) == "in_progress"
    assert await _column(db, w.project_id, "in_progress") == [x, t, y]
    assert await _column(db, w.project_id, "todo") == []


async def test_ac61_move_without_neighbors_into_empty_column(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    t = await _task(db, w, position=5000)
    await db.commit()
    await _move(db, pos, t, status=DONE)
    assert await _status(db, t) == "done"
    assert await _pos(db, t) == STEP


async def test_ac81_status_change_without_neighbors_goes_to_end_of_target_column(
    db: AsyncSession, pos: Any
) -> None:
    """AC-81: 3 задачи «В работе», четвёртая переведена без соседей — последняя."""
    w = await make_world(db)
    cols = [await _task(db, w, status="in_progress", position=p) for p in (1024, 2048, 3072)]
    fourth = await _task(db, w, position=1024)
    await db.commit()
    await _move(db, pos, fourth, status=PROG)
    assert await _status(db, fourth) == "in_progress"
    assert await _column(db, w.project_id, "in_progress") == [*cols, fourth]
    assert await _pos(db, fourth) == 3072 + STEP


async def test_ac81_same_status_without_neighbors_goes_to_end_of_own_column(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=1024)
    b = await _task(db, w, position=2048)
    await db.commit()
    await _move(db, pos, a, status=TODO)
    assert await _column(db, w.project_id, "todo") == [b, a]


async def test_ac61_moving_does_not_touch_other_tasks(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=1024)
    b = await _task(db, w, position=2048)
    c = await _task(db, w, position=3072)
    await db.commit()
    before = await _positions(db, [a, b])
    await _move(db, pos, c, status=TODO, after=a, before=b)
    assert await _positions(db, [a, b]) == before


# --- перенумерация -----------------------------------------------------------------------


async def test_ac61_exhausted_gap_renumbers_column_and_places_between(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=10)
    b = await _task(db, w, position=11)
    c = await _task(db, w, position=500)
    d = await _task(db, w, status="review", position=77)
    await db.commit()
    await _move(db, pos, c, status=TODO, after=a, before=b)
    assert await _column(db, w.project_id, "todo") == [a, c, b]
    ps = await _positions(db, [a, b, c])
    values = [ps[a], ps[c], ps[b]]
    assert len(set(values)) == 3
    assert values == sorted(values)
    assert ps[a] == STEP and ps[b] == 2 * STEP  # перенумерация шагом, затем середина
    assert STEP < ps[c] < 2 * STEP
    assert await _pos(db, d) == 77  # другая колонка не тронута


async def test_ac61_renumber_column_assigns_step_multiples_in_order(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=5)
    b = await _task(db, w, position=3)
    c = await _task(db, w, position=900)
    sub = await _task(db, w, parent_id=a, position=None)
    gone = await _task(db, w, position=1, deleted_at=datetime.now(UTC))
    other = await _task(db, w, status="done", position=42)
    await db.commit()
    await pos.renumber_column(db, w.project_id, TODO)
    ps = await _positions(db, [a, b, c, sub, gone, other])
    assert [ps[b], ps[a], ps[c]] == [STEP, 2 * STEP, 3 * STEP]
    assert ps[sub] is None
    assert ps[gone] == 1
    assert ps[other] == 42


async def test_ac61_renumber_tie_break_is_created_at_then_id(db: AsyncSession, pos: Any) -> None:
    """Равные позиции: порядок (position, created_at, id) стабилен."""
    w = await make_world(db)
    same = datetime(2026, 1, 1, tzinfo=UTC)
    ids = [await _task(db, w, position=1000, created_at=same) for _ in range(4)]
    older = await _task(db, w, position=1000, created_at=datetime(2025, 1, 1, tzinfo=UTC))
    await db.commit()
    await pos.renumber_column(db, w.project_id, TODO)
    ps = await _positions(db, [older, *ids])
    expected = [older, *sorted(ids)]
    assert sorted(ps, key=lambda i: ps[i]) == expected
    assert [ps[i] for i in expected] == [STEP * k for k in range(1, 6)]


async def test_ac61_equal_positions_move_is_deterministic(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    same = datetime(2026, 1, 1, tzinfo=UTC)
    a = await _task(db, w, position=1000, created_at=same)
    b = await _task(db, w, position=1000, created_at=same)
    c = await _task(db, w, position=5000)
    await db.commit()
    first, second = sorted([a, b])
    await _move(db, pos, c, status=TODO, after=first, before=second)
    assert await _column(db, w.project_id, "todo") == [first, c, second]
    ps = await _positions(db, [a, b, c])
    assert len(set(ps.values())) == 3


# --- идемпотентность / подзадачи ---------------------------------------------------------


async def test_ac61_repeated_move_keeps_order(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=1024)
    b = await _task(db, w, position=2048)
    c = await _task(db, w, position=3072)
    await db.commit()
    await _move(db, pos, c, status=TODO, after=a, before=b)
    first = await _column(db, w.project_id, "todo")
    await _move(db, pos, c, status=TODO, after=a, before=b)
    assert await _column(db, w.project_id, "todo") == first == [a, c, b]


async def test_fr21_subtask_positions_stay_null_when_parent_moves(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    parent = await _task(db, w, position=1024)
    sub = await _task(db, w, parent_id=parent, position=None, status="done")
    await db.commit()
    await _move(db, pos, parent, status=PROG)
    assert (await _positions(db, [sub]))[sub] is None
    assert await _status(db, sub) == "done"  # статус подзадачи не наследуется
    assert await _pos(db, parent) == STEP


async def test_fr21_moving_a_subtask_is_rejected_422(db: AsyncSession, pos: Any) -> None:
    from app.core.errors import AppError

    w = await make_world(db)
    parent = await _task(db, w, position=1024)
    sub = await _task(db, w, parent_id=parent, position=None)
    await db.commit()
    task = await db.get(Task, sub)
    assert task is not None
    with pytest.raises(AppError) as info:
        await pos.move_task(db, task, status=PROG, before_task_id=None, after_task_id=None)
    assert info.value.status_code == 422
    await db.rollback()
    assert (await _positions(db, [sub]))[sub] is None


# --- неверные соседи ---------------------------------------------------------------------


async def _bad_neighbor_setup(db: AsyncSession) -> tuple[Any, dict[str, uuid.UUID]]:
    w = await make_world(db)
    other = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Другой")
    ws2 = await make_workspace(db)
    # Другое пространство: проект и задача (создатель — тот же пользователь допустим для фабрики).
    p2 = await make_project(db, workspace_id=ws2.id, owner_id=w.ba.id, name="Чужой")
    t2 = await make_task(db, project_id=p2.id, workspace_id=ws2.id, created_by=w.ba.id)
    ids = {
        "moving": await _task(db, w, position=1024),
        "good": await _task(db, w, position=2048),
        "other_column": await _task(db, w, status="review", position=1024),
        "other_project": await _task(db, w, project_id=other.id, position=1024),
        "deleted": await _task(db, w, position=3072, deleted_at=datetime.now(UTC)),
        "other_ws": t2.id,
        "missing": uuid.uuid4(),
    }
    ids["subtask"] = await _task(db, w, parent_id=ids["good"], position=None)
    await db.commit()
    return w, ids


@pytest.mark.parametrize(
    "key",
    ["other_column", "other_project", "deleted", "subtask", "other_ws", "missing", "moving"],
)
@pytest.mark.parametrize("side", ["after", "before"])
async def test_ac61_invalid_neighbor_is_422_invalid_neighbors(
    db: AsyncSession, pos: Any, key: str, side: str
) -> None:
    w, ids = await _bad_neighbor_setup(db)
    task = await db.get(Task, ids["moving"])
    assert task is not None
    kwargs: dict[str, Any] = {"before_task_id": None, "after_task_id": None}
    kwargs[f"{side}_task_id"] = ids[key]
    await fails(db, pos.move_task(db, task, status=TODO, **kwargs), "invalid_neighbors")
    assert await _pos(db, ids["moving"]) == 1024
    assert await _status(db, ids["moving"]) == "todo"


async def test_ac61_one_valid_one_invalid_neighbor_is_rejected(db: AsyncSession, pos: Any) -> None:
    w, ids = await _bad_neighbor_setup(db)
    task = await db.get(Task, ids["moving"])
    assert task is not None
    await fails(
        db,
        pos.move_task(
            db, task, status=TODO, after_task_id=ids["good"], before_task_id=ids["deleted"]
        ),
        "invalid_neighbors",
    )


async def test_ac61_neighbor_must_be_in_target_column_not_current_one(
    db: AsyncSession, pos: Any
) -> None:
    """Сосед из текущей колонки при переносе в другую — invalid_neighbors."""
    w, ids = await _bad_neighbor_setup(db)
    task = await db.get(Task, ids["moving"])
    assert task is not None
    await fails(
        db,
        pos.move_task(db, task, status=REVIEW, after_task_id=ids["good"], before_task_id=None),
        "invalid_neighbors",
    )


# --- AC-61: 1000 последовательных перемещений -------------------------------------------


async def test_ac61_thousand_sequential_moves_keep_expected_order_and_unique_positions(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    ids = [await _task(db, w, position=STEP * (i + 1)) for i in range(6)]
    await db.commit()
    expected = list(ids)
    for i in range(1000):
        # Всегда вставляем последнюю карточку сразу после первой: зазор быстро исчерпывается.
        mover = expected[-1] if i % 2 == 0 else expected[len(expected) // 2]
        rest = [t for t in expected if t != mover]
        anchor = rest[0] if i % 3 else rest[1]
        idx = rest.index(anchor)
        nxt = rest[idx + 1] if idx + 1 < len(rest) else None
        await _move(db, pos, mover, status=TODO, after=anchor, before=nxt)
        rest.insert(idx + 1, mover)
        expected = rest
    assert await _column(db, w.project_id, "todo") == expected
    ps = await _positions(db, ids)
    assert len(set(ps.values())) == len(ids)


# --- блокировки (§10.2 п.4) --------------------------------------------------------------


@pytest.mark.committed
async def test_p10_2_move_task_locks_old_and_new_column(
    committed: async_sessionmaker[AsyncSession], pos: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
        t = await _task(setup, w, position=1024)
        await setup.commit()

    async def try_lock(status: str) -> bool:
        async with committed() as s:
            key = f"{w.project_id}:{status}"
            got = (await s.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:k))").bindparams(k=key)
            )).scalar_one()  # fmt: skip
            await s.rollback()
            return bool(got)

    async with committed() as holder:
        task = await holder.get(Task, t)
        assert task is not None
        await pos.move_task(holder, task, status=REVIEW, before_task_id=None, after_task_id=None)
        assert await try_lock("todo") is False
        assert await try_lock("review") is False
        assert await try_lock("done") is True
        await holder.rollback()
    assert await try_lock("todo") is True


@pytest.mark.committed
async def test_p10_2_lock_columns_dedupes_and_blocks_same_key_only(
    committed: async_sessionmaker[AsyncSession], pos: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
        await setup.commit()
    async with committed() as holder, committed() as other:
        await pos.lock_columns(holder, w.project_id, DONE, TODO, TODO)  # повтор не блокирует себя
        key = lambda s: f"{w.project_id}:{s}"  # noqa: E731

        async def free(k: str) -> bool:
            return bool((await other.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:k))").bindparams(k=k)
            )).scalar_one())  # fmt: skip

        assert await free(key("todo")) is False
        assert await free(key("done")) is False
        assert await free(key("review")) is True


@pytest.mark.committed
async def test_p10_2_opposite_lock_order_does_not_deadlock(
    committed: async_sessionmaker[AsyncSession], pos: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
        await setup.commit()

    async def worker(order: tuple[TaskStatus, ...]) -> None:
        for _ in range(10):
            async with committed() as s:
                await pos.lock_columns(s, w.project_id, *order)
                await asyncio.sleep(0.01)
                await s.rollback()

    await asyncio.wait_for(
        asyncio.gather(worker((TODO, DONE)), worker((DONE, TODO)), worker((PROG, TODO, DONE))),
        timeout=20,
    )


@pytest.mark.committed
async def test_ac61_concurrent_moves_into_same_column_no_deadlock_unique_positions(
    committed: async_sessionmaker[AsyncSession], pos: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
        anchors = [
            await _task(setup, w, status="review", position=STEP * (i + 1)) for i in range(2)
        ]
        movers_a = [await _task(setup, w, position=STEP * (i + 1)) for i in range(8)]
        movers_b = [
            await _task(setup, w, status="in_progress", position=STEP * (i + 1)) for i in range(8)
        ]
        await setup.commit()

    async def run(ids: list[uuid.UUID]) -> None:
        for tid in ids:
            async with committed() as s:
                task = await s.get(Task, tid)
                assert task is not None
                # Все вставляют между одними и теми же двумя соседями: зазор исчерпывается.
                await pos.move_task(
                    s, task, status=REVIEW, after_task_id=anchors[0], before_task_id=anchors[1]
                )
                await s.commit()

    await asyncio.wait_for(asyncio.gather(run(movers_a), run(movers_b)), timeout=60)

    async with committed() as s:
        col = await _column(s, w.project_id, "review")
        assert len(col) == 2 + 16
        assert col[0] == anchors[0] and col[-1] == anchors[1]
        ps = await _positions(s, col)
        assert len(set(ps.values())) == len(col)
        assert [ps[i] for i in col] == sorted(ps.values())


# --- попытка 2: ревью T73 -----------------------------------------------------------------


def test_ac61_column_order_is_single_constant(pos: Any) -> None:
    """Решение (3): порядок колонки (position, created_at, id) — одна константа COLUMN_ORDER."""
    assert hasattr(pos, "COLUMN_ORDER")
    assert pos.COLUMN_ORDER


async def test_ac61_tie_break_created_at_contradicts_id_order(db: AsyncSession, pos: Any) -> None:
    """Равные позиции: created_at важнее id; id порядок обратный created_at."""
    w = await make_world(db)
    low_id, high_id = uuid.UUID(int=1), uuid.UUID(int=2)
    newer = datetime(2026, 1, 2, tzinfo=UTC)
    older = datetime(2026, 1, 1, tzinfo=UTC)
    # id меньше, но создана позже -> в колонке она вторая
    await _task(db, w, id=low_id, position=1000, created_at=newer)
    await _task(db, w, id=high_id, position=1000, created_at=older)
    await db.commit()
    assert await _column(db, w.project_id, "todo") == [high_id, low_id]
    await pos.renumber_column(db, w.project_id, TODO)
    ps = await _positions(db, [low_id, high_id])
    assert ps[high_id] == STEP
    assert ps[low_id] == 2 * STEP


async def test_ac61_tie_break_id_when_created_at_equal(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    same = datetime(2026, 1, 1, tzinfo=UTC)
    first, second = uuid.UUID(int=10), uuid.UUID(int=20)
    await _task(db, w, id=second, position=1000, created_at=same)
    await _task(db, w, id=first, position=1000, created_at=same)
    await db.commit()
    await pos.renumber_column(db, w.project_id, TODO)
    ps = await _positions(db, [first, second])
    assert (ps[first], ps[second]) == (STEP, 2 * STEP)


async def test_ac61_same_before_and_after_is_invalid_neighbors(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    a = await _task(db, w, position=1024)
    b = await _task(db, w, position=2048)
    t = await _task(db, w, position=3072)
    await db.commit()
    task = await db.get(Task, t)
    assert task is not None
    await fails(
        db,
        pos.move_task(db, task, status=TODO, after_task_id=b, before_task_id=b),
        "invalid_neighbors",
    )
    assert await _column(db, w.project_id, "todo") == [a, b, t]


async def test_ac61_stale_task_object_moves_by_actual_status(db: AsyncSession, pos: Any) -> None:
    """Решение (1): объект задачи устарел (в БД другой статус) — действуем по актуальному."""
    w = await make_world(db)
    t = await _task(db, w, position=1024)
    d1 = await _task(db, w, status="done", position=1024)
    d2 = await _task(db, w, status="done", position=2048)
    r1 = await _task(db, w, status="review", position=9000)
    await db.commit()
    stale = await db.get(Task, t)
    assert stale is not None and stale.status == "todo"
    await db.execute(
        text("UPDATE task SET status = 'review', position = 9000 + 1024 WHERE id = :i").bindparams(
            i=t
        )
    )
    await pos.move_task(db, stale, status=DONE, before_task_id=None, after_task_id=None)
    await db.flush()
    assert await _status(db, t) == "done"
    assert await _column(db, w.project_id, "done") == [d1, d2, t]
    assert await _pos(db, t) == 2048 + STEP
    assert await _pos(db, r1) == 9000
    # блокировка актуальной колонки проверяется в test_p10_2_stale_object_locks_actual_column


async def test_ac61_task_deleted_meanwhile_is_error_not_moved(db: AsyncSession, pos: Any) -> None:
    from app.core.errors import AppError

    w = await make_world(db)
    t = await _task(db, w, position=1024)
    await db.commit()
    stale = await db.get(Task, t)
    assert stale is not None
    await db.execute(text("UPDATE task SET deleted_at = now() WHERE id = :i").bindparams(i=t))
    with pytest.raises(AppError) as info:
        await pos.move_task(db, stale, status=DONE, before_task_id=None, after_task_id=None)
    assert info.value.status_code in (404, 422)
    await db.rollback()


@pytest.mark.committed
async def test_p10_2_race_stale_move_vs_other_move_and_renumber(
    committed: async_sessionmaker[AsyncSession], pos: Any
) -> None:
    """Регрессия ревью: T2 todo->review (commit), T1 (устаревший объект) -> done, T3 renumber."""
    async with committed() as setup:
        w = await make_world(setup)
        t = await _task(setup, w, position=1024)
        reviews = [await _task(setup, w, status="review", position=7 + i) for i in range(3)]
        dones = [await _task(setup, w, status="done", position=STEP * (i + 1)) for i in range(3)]
        await setup.commit()

    async with committed() as s1:
        stale = await s1.get(Task, t)  # статус todo загружен до коммита T2
        assert stale is not None and stale.status == "todo"

        async with committed() as s2:
            task2 = await s2.get(Task, t)
            assert task2 is not None
            await pos.move_task(s2, task2, status=REVIEW, before_task_id=None, after_task_id=None)
            await s2.commit()

        async def t1() -> None:
            await pos.move_task(s1, stale, status=DONE, before_task_id=None, after_task_id=None)
            await s1.commit()

        async def t3() -> None:
            async with committed() as s3:
                await pos.lock_columns(s3, w.project_id, REVIEW)
                await pos.renumber_column(s3, w.project_id, REVIEW)
                await s3.commit()

        await asyncio.wait_for(asyncio.gather(t1(), t3()), timeout=30)

    async with committed() as s:
        assert await _status(s, t) == "done"
        assert await _column(s, w.project_id, "done") == [*dones, t]
        assert await _pos(s, t) == 3 * STEP + STEP
        review = await _column(s, w.project_id, "review")
        assert review == reviews
        ps = await _positions(s, review)
        assert [ps[i] for i in review] == [STEP, 2 * STEP, 3 * STEP]
        done_ps = await _positions(s, [*dones, t])
        assert len(set(done_ps.values())) == 4


@pytest.mark.committed
async def test_p10_2_renumber_skips_row_moved_out_concurrently(
    committed: async_sessionmaker[AsyncSession], pos: Any
) -> None:
    """Решение (2): строка, ушедшая из колонки до фиксации, не перенумеровывается."""
    async with committed() as setup:
        w = await make_world(setup)
        a = await _task(setup, w, status="review", position=10)
        t = await _task(setup, w, status="review", position=20)
        c = await _task(setup, w, status="review", position=30)
        await setup.commit()

    async with committed() as mover, committed() as renum:
        await mover.execute(
            text("UPDATE task SET status = 'done', position = 424242 WHERE id = :i").bindparams(i=t)
        )
        job = asyncio.ensure_future(pos.renumber_column(renum, w.project_id, REVIEW))
        await asyncio.wait({job}, timeout=0.5)
        await mover.commit()
        await asyncio.wait_for(job, timeout=10)
        await renum.commit()

    async with committed() as s:
        assert await _status(s, t) == "done"
        assert await _pos(s, t) == 424242
        ps = await _positions(s, [a, c])
        assert ps[a] == STEP
        assert ps[c] in (STEP * 2, STEP * 3)


# --- попытка 3 ---------------------------------------------------------------------------

OLD = datetime(2020, 1, 1, tzinfo=UTC)


async def _updated_at(db: AsyncSession, task_id: uuid.UUID) -> datetime:
    return (  # type: ignore[no-any-return]
        await db.execute(text("SELECT updated_at FROM task WHERE id = :i").bindparams(i=task_id))
    ).scalar_one()


async def test_ac61_renumber_keeps_updated_at_move_updates_it(db: AsyncSession, pos: Any) -> None:
    w = await make_world(db)
    ids = [await _task(db, w, position=5 + i, updated_at=OLD) for i in range(3)]
    mover = await _task(db, w, position=9000, updated_at=OLD)
    await db.commit()
    await pos.renumber_column(db, w.project_id, TODO)
    await db.flush()
    for i in ids:
        assert await _updated_at(db, i) == OLD
    assert [await _pos(db, i) for i in ids] == [STEP, 2 * STEP, 3 * STEP]
    await _move(db, pos, mover, status=PROG)
    assert await _updated_at(db, mover) > OLD


@pytest.mark.committed
async def test_p10_2_stale_object_locks_actual_column(
    committed: async_sessionmaker[AsyncSession], pos: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
        t = await _task(setup, w, position=1024)
        await setup.commit()

    async def try_lock(status: str) -> bool:
        async with committed() as s:
            got = (
                await s.execute(
                    text("SELECT pg_try_advisory_xact_lock(hashtext(:k))").bindparams(
                        k=f"{w.project_id}:{status}"
                    )
                )
            ).scalar_one()
            await s.rollback()
            return bool(got)

    async with committed() as holder:
        stale = await holder.get(Task, t)
        assert stale is not None and stale.status == "todo"
        async with committed() as other:
            await other.execute(
                text("UPDATE task SET status = 'review' WHERE id = :i").bindparams(i=t)
            )
            await other.commit()
        await pos.move_task(holder, stale, status=DONE, before_task_id=None, after_task_id=None)
        assert await try_lock("review") is False  # актуальная колонка
        assert await try_lock("done") is False
        await holder.rollback()


async def test_ac61_stale_todo_object_db_review_move_to_todo_ends_todo_column(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    t = await _task(db, w, position=1024)
    a = await _task(db, w, position=1024)
    b = await _task(db, w, position=2048)
    await db.commit()
    stale = await db.get(Task, t)
    assert stale is not None and stale.status == "todo"
    await db.execute(
        text("UPDATE task SET status = 'review', position = 5000 WHERE id = :i").bindparams(i=t)
    )
    await pos.move_task(db, stale, status=TODO, before_task_id=None, after_task_id=None)
    await db.flush()
    assert stale.status == "todo"
    assert await _status(db, t) == "todo"
    assert await _column(db, w.project_id, "todo") == [a, b, t]
    assert await _pos(db, t) == 2048 + STEP
    assert await _column(db, w.project_id, "review") == []


async def test_ac61_before_only_with_many_predecessors_lands_right_before_neighbor(
    db: AsyncSession, pos: Any
) -> None:
    w = await make_world(db)
    col = [await _task(db, w, position=STEP * (i + 1)) for i in range(4)]
    x = await _task(db, w, position=9000)
    await db.commit()
    await _move(db, pos, x, status=TODO, before=col[3])
    assert await _column(db, w.project_id, "todo") == [*col[:3], x, col[3]]
    assert await _pos(db, x) == (3072 + 4096) // 2


async def test_p10_2_lock_attempts_exhausted_is_503_service_busy(
    db: AsyncSession, pos: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Статус «меняется» при каждом перечитывании: после 3 попыток — 503 service_busy."""
    w = await make_world(db)
    t = await _task(db, w, position=1024)
    await db.commit()
    task = await db.get(Task, t)
    assert task is not None
    answers = iter(["review", "done", "review", "done", "review", "done"])

    async def flapping(_db: Any, _task_id: Any, *, lock: bool) -> str:
        return next(answers)

    monkeypatch.setattr(pos, "_read_state", flapping)
    await fails(
        db,
        pos.move_task(db, task, status=DONE, before_task_id=None, after_task_id=None),
        "service_busy",
        status=503,
    )
