"""Позиции карточек и перемещение по соседям (plan §4.8, D-22, §10.2 п.4; FR-28a, FR-21).

Позиция есть только у задач верхнего уровня; порядок колонки — ``(position, created_at, id)``.
Все функции работают в транзакции вызывающего и не фиксируют её. Колонку (проект + статус)
сериализует ``pg_advisory_xact_lock``; в одном вызове ``lock_columns`` блокировки берутся
в отсортированном порядке. Повторная попытка в ``move_task`` добирает блокировки вне этого
порядка (уже удерживая строку и прежние колонки), поэтому возможна взаимоблокировка БД
(``40P01``) — она отдаётся как ``503 service_busy`` (D-40).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import func, select, text, tuple_, update

from app.core.errors import ErrorCode, NotFound, ServiceBusy, Unprocessable
from app.domain.tasks.models import Task, TaskStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

STEP: Final = 1024
# Единственное определение порядка колонки ``(position, created_at, id)``; им же пользуются доска
# и все функции модуля (соседи, границы, перенумерация).
COLUMN_ORDER: Final = (Task.position, Task.created_at, Task.id)
_LOCK_ATTEMPTS: Final = 3
SUBTASK_NOT_ON_BOARD: Final = "Подзадачи не размещаются на доске"


async def lock_columns(db: AsyncSession, project_id: UUID, *statuses: TaskStatus) -> None:
    """Блокировка колонок до конца транзакции; повторы отбрасываются, порядок — по статусу."""
    for status in sorted({str(s) for s in statuses}):
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))").bindparams(
                key=f"{project_id}:{status}"
            )
        )


def _column(project_id: UUID, status: str) -> tuple[object, ...]:
    """Условия колонки: неудалённые задачи верхнего уровня проекта в статусе."""
    return (
        Task.project_id == project_id,
        Task.status == str(status),
        Task.deleted_at.is_(None),
        Task.parent_id.is_(None),
    )


async def append_position(db: AsyncSession, project_id: UUID, status: TaskStatus) -> int:
    """Позиция в конец колонки: ``max(position) + STEP`` или ``STEP`` для пустой."""
    top = (
        await db.execute(select(func.max(Task.position)).where(*_column(project_id, status)))  # type: ignore[arg-type]
    ).scalar_one()
    return STEP if top is None else int(top) + STEP


async def renumber_column(db: AsyncSession, project_id: UUID, status: TaskStatus) -> None:
    """Позиции колонки заново: ``STEP, 2*STEP, …`` в порядке ``COLUMN_ORDER``.

    Внешнее условие повторяет условия колонки: строка, ушедшая из неё (статус, удаление,
    подзадача) до фиксации чужой транзакции, не перезаписывается. ``updated_at`` не меняется.
    """
    ranked = (
        select(Task.id, func.row_number().over(order_by=COLUMN_ORDER).label("n"))
        .where(*_column(project_id, status))  # type: ignore[arg-type]
        .subquery("r")
    )
    await db.execute(
        update(Task)
        .where(Task.id == ranked.c.id, *_column(project_id, status))  # type: ignore[arg-type]
        # Явно: иначе ``onupdate`` подставит ``utcnow`` — перенумерация не правка карточек.
        .values(position=ranked.c.n * STEP, updated_at=Task.updated_at)
        .execution_options(synchronize_session=False)
    )


async def _neighbor(
    db: AsyncSession, task: Task, status: TaskStatus, neighbor_id: UUID
) -> tuple[int, datetime, UUID]:
    """Ключ порядка соседа; не годится — ``invalid_neighbors``."""
    row = (
        await db.execute(
            select(*COLUMN_ORDER).where(
                Task.id == neighbor_id,
                Task.id != task.id,
                Task.workspace_id == task.workspace_id,
                *_column(task.project_id, status),  # type: ignore[arg-type]
            )
        )
    ).one_or_none()
    if row is None or row[0] is None:
        raise Unprocessable(
            "Соседняя задача недоступна для перемещения", code=ErrorCode.invalid_neighbors
        )
    return int(row[0]), row[1], row[2]


async def _bounds(
    db: AsyncSession,
    task: Task,
    status: TaskStatus,
    after: tuple[int, datetime, UUID] | None,
    before: tuple[int, datetime, UUID] | None,
) -> tuple[int, int | None]:
    """Границы ``(low, high)`` по текущему состоянию колонки; ``high is None`` — конец."""
    key = tuple_(*COLUMN_ORDER)
    others = (*_column(task.project_id, status), Task.id != task.id)
    if after is not None:
        high = (
            await db.execute(
                select(Task.position)
                .where(*others, key > tuple_(*after))  # type: ignore[arg-type]
                .order_by(*COLUMN_ORDER)
                .limit(1)
            )
        ).scalar_one_or_none()
        return after[0], None if high is None else int(high)
    assert before is not None
    low = (
        await db.execute(
            select(Task.position)
            .where(*others, key < tuple_(*before))  # type: ignore[arg-type]
            .order_by(*(c.desc() for c in COLUMN_ORDER))
            .limit(1)
        )
    ).scalar_one_or_none()
    return (before[0] - 2 * STEP if low is None else int(low)), before[0]


async def _read_state(db: AsyncSession, task_id: UUID, *, lock: bool) -> str:
    """Актуальный статус строки; удалена — ``404``, подзадача — ``422``."""
    stmt = select(Task.status, Task.parent_id, Task.deleted_at).where(Task.id == task_id)
    row = (await db.execute(stmt.with_for_update(key_share=True) if lock else stmt)).one_or_none()
    if row is None or row.deleted_at is not None:
        raise NotFound("Задача не найдена")
    if row.parent_id is not None:
        raise Unprocessable(SUBTASK_NOT_ON_BOARD, code=ErrorCode.validation_error)
    return str(row.status)


async def lock_task_columns(db: AsyncSession, task: Task, status: TaskStatus) -> None:
    """Колонки текущего статуса задачи и ``status``, затем её строка (§10.2 п.4 -> п.5).

    Статус сверяется по актуальной строке: сменился — блокировка повторяется по актуальному
    (до ``_LOCK_ATTEMPTS`` раз, затем ``503 service_busy``, D-40); строка берётся
    ``FOR NO KEY UPDATE``, и статус под ней сверяется с заблокированным ещё раз. Удалена —
    ``404``, подзадача — ``422``. ``task.status``/``task.position`` обновляются из строки.
    """
    locked = str(task.status)
    for _ in range(_LOCK_ATTEMPTS):
        await lock_columns(db, task.project_id, TaskStatus(locked), status)
        # Без блокировки строки: её нельзя держать, пока ждём advisory-блокировку другой колонки
        # (дедлок с перенумерацией). Статус меняют только под блокировкой его колонки.
        actual = await _read_state(db, task.id, lock=False)
        if actual == locked:
            actual = await _read_state(db, task.id, lock=True)
            if actual == locked:
                break
        locked = actual
    else:
        raise ServiceBusy("Задача перемещается одновременно, повторите запрос")
    await db.refresh(task, ["status", "position", "parent_id", "deleted_at"])


async def move_task(
    db: AsyncSession,
    task: Task,
    *,
    status: TaskStatus,
    before_task_id: UUID | None,
    after_task_id: UUID | None,
) -> None:
    """Перенос карточки в колонку ``status`` между соседями (FR-28a); без ``commit``.

    ``after_task_id`` — сосед сверху, ``before_task_id`` — снизу (приоритет у ``after``);
    без соседей — в конец целевой колонки.

    Контракт для вызывающего (T77): доступ и существование задачи проверяются до вызова;
    ``move_task`` права не проверяет. Блокировки и перечитывание строки — ``lock_task_columns``
    (повторный вызов в той же транзакции под уже взятыми блокировками ничего не ждёт).
    ``task.status``/``task.position`` обновляются по актуальной строке, а не по снимку объекта.
    """
    if task.parent_id is not None:
        raise Unprocessable(SUBTASK_NOT_ON_BOARD, code=ErrorCode.validation_error)
    if before_task_id is not None and before_task_id == after_task_id:
        raise Unprocessable(
            "Соседи сверху и снизу должны различаться", code=ErrorCode.invalid_neighbors
        )

    await lock_task_columns(db, task, status)

    after = await _neighbor(db, task, status, after_task_id) if after_task_id else None
    before = await _neighbor(db, task, status, before_task_id) if before_task_id else None

    if after is None and before is None:
        position = await append_position(db, task.project_id, status)
    else:
        low, high = await _bounds(db, task, status, after, before)
        if high is not None and high - low < 2:
            await renumber_column(db, task.project_id, status)
            # Ключи соседей устарели: перечитываем и считаем границы заново.
            after = await _neighbor(db, task, status, after_task_id) if after_task_id else None
            before = await _neighbor(db, task, status, before_task_id) if before_task_id else None
            low, high = await _bounds(db, task, status, after, before)
        position = low + STEP if high is None else (low + high) // 2

    task.status = str(status)
    task.position = position
