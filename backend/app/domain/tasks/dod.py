"""Критерии готовности и блокер (спека 033, CD-01, CD-03)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from app.core.clock import utcnow
from app.core.errors import ErrorCode, Forbidden, HumanCloseOnly, NotFound, Unprocessable
from app.domain.access.policy import (
    ProjectFacts,
    TaskFacts,
    can_check_dod,
    can_edit_task_fully,
    can_read_project_content,
)
from app.domain.access.roles import Actor
from app.domain.events.catalog import EventAction
from app.domain.events.client_context import current_client_name
from app.domain.events.writer import record_event
from app.domain.tasks.context import load_task_context
from app.domain.tasks.models import DodKind, Task, TaskDodCriterion, TaskMode, TaskStatus
from app.domain.users.directory import UserRef, user_refs

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

BODY_MAX = 500
REASON_MAX = 500


@dataclass(frozen=True)
class DodItem:
    id: UUID
    body: str
    required: bool
    checked: bool
    checked_by: UserRef | None
    checked_at: datetime | None
    position: int
    kind: str
    evidence_ref: str | None
    evidence_note: str | None


@dataclass(frozen=True)
class DodView:
    closed: int
    total: int
    human_close_only: bool
    items: list[DodItem]
    missing_artifacts: list[str]


def _facts(task: Task) -> TaskFacts:
    return TaskFacts(
        created_by=task.created_by, assignee_id=task.assignee_id, parent_id=task.parent_id
    )


def _body(text: str) -> str:
    value = text.strip()
    if not value or len(value) > BODY_MAX:
        raise Unprocessable(
            f"Текст критерия: 1–{BODY_MAX} символов", code=ErrorCode.validation_error
        )
    if "\x00" in value:
        raise Unprocessable("Текст критерия недопустим", code=ErrorCode.validation_error)
    return value


def _reason(text: str) -> str:
    value = text.strip()
    if not value or len(value) > REASON_MAX:
        raise Unprocessable(
            f"Причина блокера: 1–{REASON_MAX} символов", code=ErrorCode.validation_error
        )
    if "\x00" in value:
        raise Unprocessable("Причина блокера недопустима", code=ErrorCode.validation_error)
    return value


def criterion_is_open(row: TaskDodCriterion) -> bool:
    if row.kind == DodKind.EVIDENCE.value:
        ref = (row.evidence_ref or "").strip()
        return not row.checked or not ref
    return not row.checked


async def open_required_bodies(db: AsyncSession, task_id: UUID) -> list[str]:
    rows = (
        (
            await db.execute(
                select(TaskDodCriterion)
                .where(
                    TaskDodCriterion.task_id == task_id,
                    TaskDodCriterion.required.is_(True),
                )
                .order_by(TaskDodCriterion.position, TaskDodCriterion.id)
            )
        )
        .scalars()
        .all()
    )
    return [row.body for row in rows if criterion_is_open(row)]


async def assert_can_close(db: AsyncSession, task: Task) -> None:
    """Перед ``done``: блокер, MCP при флаге, открытый обязательный DoD."""
    if task.blocked:
        raise Unprocessable(
            "Снимите блокер, прежде чем закрыть задачу", code=ErrorCode.task_blocked
        )
    agent = current_client_name() is not None
    if agent and (task.human_close_only or task.mode == TaskMode.RESEARCH.value):
        raise HumanCloseOnly()
    open_bodies = await open_required_bodies(db, task.id)
    if open_bodies:
        listed = "; ".join(open_bodies)
        raise Unprocessable(
            f"Отметьте обязательные критерии готовности: {listed}",
            code=ErrorCode.dod_open,
        )


async def load_dod(db: AsyncSession, workspace_id: UUID, task: Task) -> DodView:
    rows = (
        (
            await db.execute(
                select(TaskDodCriterion)
                .where(TaskDodCriterion.task_id == task.id)
                .order_by(TaskDodCriterion.position, TaskDodCriterion.id)
            )
        )
        .scalars()
        .all()
    )
    ids = {r.checked_by for r in rows if r.checked_by is not None}
    refs = await user_refs(db, workspace_id, list(ids))
    items = [
        DodItem(
            id=r.id,
            body=r.body,
            required=r.required,
            checked=r.checked,
            checked_by=None if r.checked_by is None else refs[r.checked_by],
            checked_at=r.checked_at,
            position=r.position,
            kind=r.kind,
            evidence_ref=r.evidence_ref,
            evidence_note=r.evidence_note,
        )
        for r in rows
    ]
    closed = sum(1 for i, r in zip(items, rows, strict=True) if not criterion_is_open(r))
    missing = [
        r.body
        for r in rows
        if r.required and r.kind == DodKind.EVIDENCE.value and criterion_is_open(r)
    ]
    return DodView(
        closed=closed,
        total=len(items),
        human_close_only=task.human_close_only,
        items=items,
        missing_artifacts=missing,
    )


async def insert_created_criteria(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    task_id: UUID,
    created_by: UUID,
    items: list[tuple[str, bool, str]],
) -> None:
    """Критерии при создании задачи; без повторной проверки прав."""
    for i, (body, required, kind) in enumerate(items, start=1):
        if kind not in {DodKind.CHECKLIST.value, DodKind.EVIDENCE.value}:
            raise Unprocessable(
                "Тип критерия: checklist или evidence", code=ErrorCode.validation_error
            )
        db.add(
            TaskDodCriterion(
                workspace_id=workspace_id,
                task_id=task_id,
                body=_body(body),
                required=required,
                checked=False,
                checked_by=None,
                checked_at=None,
                position=i,
                created_by=created_by,
                kind=kind,
                evidence_ref=None,
                evidence_note=None,
            )
        )
    if items:
        await db.flush()


async def add_criterion(
    db: AsyncSession,
    actor: Actor,
    task_id: UUID,
    *,
    body: str,
    required: bool,
    kind: str = DodKind.CHECKLIST.value,
) -> UUID:
    ctx = await load_task_context(db, actor, task_id, lock_project="share")
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    task = (
        await db.execute(select(Task).where(Task.id == task_id, Task.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if task is None:
        raise NotFound("Задача не найдена")
    if not can_edit_task_fully(actor, ctx.project, _facts(task)):
        raise Forbidden()
    text = _body(body)
    if kind not in {DodKind.CHECKLIST.value, DodKind.EVIDENCE.value}:
        raise Unprocessable("Тип критерия: checklist или evidence", code=ErrorCode.validation_error)
    nxt = (
        await db.execute(
            select(func.coalesce(func.max(TaskDodCriterion.position), 0)).where(
                TaskDodCriterion.task_id == task_id
            )
        )
    ).scalar_one()
    row = TaskDodCriterion(
        workspace_id=actor.workspace_id,
        task_id=task_id,
        body=text,
        required=required,
        checked=False,
        checked_by=None,
        checked_at=None,
        position=int(nxt) + 1,
        created_by=actor.user_id,
        kind=kind,
        evidence_ref=None,
        evidence_note=None,
    )
    db.add(row)
    await db.flush()
    return row.id


def _apply_evidence(
    row: TaskDodCriterion, *, evidence_ref: str | None, evidence_note: str | None
) -> None:
    ref = (evidence_ref if evidence_ref is not None else row.evidence_ref) or ""
    ref = ref.strip()
    if not ref or len(ref) > BODY_MAX:
        raise Unprocessable("Нужен URL или id артефакта (1–500)", code=ErrorCode.validation_error)
    row.evidence_ref = ref
    if evidence_note is None:
        return
    note = evidence_note.strip()
    if len(note) > BODY_MAX:
        raise Unprocessable(
            "Комментарий evidence: до 500 символов", code=ErrorCode.validation_error
        )
    row.evidence_note = note or None


async def check_criterion(
    db: AsyncSession,
    actor: Actor,
    task_id: UUID,
    criterion_id: UUID,
    *,
    checked: bool,
    evidence_ref: str | None = None,
    evidence_note: str | None = None,
) -> None:
    ctx = await load_task_context(db, actor, task_id, lock_project="share")
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    task = (
        await db.execute(select(Task).where(Task.id == task_id, Task.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if task is None:
        raise NotFound("Задача не найдена")
    if not can_check_dod(actor, ctx.project, _facts(task)):
        raise Forbidden()
    row = (
        await db.execute(
            select(TaskDodCriterion).where(
                TaskDodCriterion.id == criterion_id,
                TaskDodCriterion.task_id == task_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Критерий не найден")
    if row.kind == DodKind.EVIDENCE.value and checked:
        _apply_evidence(row, evidence_ref=evidence_ref, evidence_note=evidence_note)
    if row.checked == checked and not (checked and row.kind == DodKind.EVIDENCE.value):
        return
    now = utcnow()
    if checked:
        row.checked = True
        row.checked_by = actor.user_id
        row.checked_at = now
    else:
        row.checked = False
        row.checked_by = None
        row.checked_at = None
        if row.kind == DodKind.EVIDENCE.value:
            row.evidence_ref = None
            row.evidence_note = None
    await db.flush()
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.TASK_DOD_CHECKED,
        entity_id=task_id,
        project_id=task.project_id,
    )


async def delete_criterion(
    db: AsyncSession, actor: Actor, task_id: UUID, criterion_id: UUID
) -> None:
    ctx = await load_task_context(db, actor, task_id, lock_project="share")
    if not can_read_project_content(actor, ctx.project):
        raise Forbidden()
    task = (
        await db.execute(select(Task).where(Task.id == task_id, Task.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if task is None:
        raise NotFound("Задача не найдена")
    if not can_edit_task_fully(actor, ctx.project, _facts(task)):
        raise Forbidden()
    row = (
        await db.execute(
            select(TaskDodCriterion).where(
                TaskDodCriterion.id == criterion_id,
                TaskDodCriterion.task_id == task_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Критерий не найден")
    await db.delete(row)
    await db.flush()


def apply_blocked(
    task: Task, actor: Actor, *, blocked: bool, reason: str | None
) -> EventAction | None:
    """Меняет поля блокера на уже загруженной строке. ``None`` — без изменения."""
    if blocked:
        if task.status == TaskStatus.DONE.value:
            raise Unprocessable(
                "Нельзя поставить блокер на закрытую задачу", code=ErrorCode.task_already_done
            )
        if reason is None:
            raise Unprocessable("Укажите причину блокера", code=ErrorCode.validation_error)
        text = _reason(reason)
        if task.blocked and task.blocked_reason == text:
            return None
        task.blocked = True
        task.blocked_reason = text
        task.blocked_by = actor.user_id
        task.blocked_at = utcnow()
        return EventAction.TASK_BLOCKED
    if not task.blocked:
        return None
    task.blocked = False
    task.blocked_reason = None
    task.blocked_by = None
    task.blocked_at = None
    return EventAction.TASK_UNBLOCKED


async def record_block_event(
    db: AsyncSession, actor: Actor, task: Task, action: EventAction
) -> None:
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=action,
        entity_id=task.id,
        project_id=task.project_id,
    )


def authorize_block_or_flag(actor: Actor, project: ProjectFacts, task: Task) -> None:
    if not can_check_dod(actor, project, _facts(task)):
        raise Forbidden()
