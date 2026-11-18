"""Классификатор routine/research (спека 036, CD-10). Без LLM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.errors import ErrorCode, Forbidden, NotFound, Unprocessable
from app.domain.access.policy import TaskFacts, can_edit_task_fully, can_read_project_content
from app.domain.access.roles import Actor
from app.domain.events.catalog import EventAction
from app.domain.events.writer import record_event
from app.domain.tasks.context import load_task_context
from app.domain.tasks.models import Task, TaskDodCriterion, TaskMode

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

RESEARCH_HINTS = ("сравни", "конкурент", "исслед", "развед", "неизвес")
GAPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("source", ("источник", "source", "http://", "https://")),
    ("completeness", ("полнот", "complete", "охват")),
    ("verification", ("проверк", "verify", "тест", "критер")),
    ("evidence", ("evidence", "артефакт", "отчёт", "отчет", "github.com", "/pull/")),
)
RESEARCH_TEMPLATE = ("источник", "полнота", "проверка")


@dataclass(frozen=True)
class ClassifyResult:
    mode: str
    missing: list[str]
    can_run_without_human: bool
    task_id: UUID | None
    committed: bool


def _blob(*parts: str | None) -> str:
    return " ".join(p for p in parts if p).lower()


def missing_from_text(*parts: str | None) -> list[str]:
    blob = _blob(*parts)
    return [name for name, hints in GAPS if not any(h in blob for h in hints)]


def research_template_gaps(*parts: str | None) -> list[str]:
    blob = _blob(*parts)
    keys = {
        "источник": ("источник", "source"),
        "полнота": ("полнот", "complete"),
        "проверка": ("проверк", "verify", "тест"),
    }
    return [name for name, hints in keys.items() if not any(h in blob for h in hints)]


def looks_research(text: str) -> bool:
    blob = text.lower()
    return any(h in blob for h in RESEARCH_HINTS)


def require_research_dod(bodies: list[str]) -> None:
    if research_template_gaps(*bodies):
        listed = ", ".join(RESEARCH_TEMPLATE)
        raise Unprocessable(
            f"Для research нужны критерии: {listed}",
            code=ErrorCode.dod_required,
        )


def _decide(text: str, missing: list[str]) -> tuple[str, bool]:
    research_fields = [item for item in missing if item != "evidence"]
    mode = (
        TaskMode.RESEARCH.value
        if looks_research(text) or research_fields
        else TaskMode.ROUTINE.value
    )
    # Слой знаний (CD-08) в этом PR нет: can_run_without_human всегда ложен (038 FR-8).
    return mode, False


async def classify(
    db: AsyncSession,
    actor: Actor,
    *,
    text: str | None,
    task_id: UUID | None,
    commit: bool,
) -> ClassifyResult:
    if not text and task_id is None:
        raise Unprocessable("Нужен text или task_id", code=ErrorCode.validation_error)
    task: Task | None = None
    extra_parts: list[str] = []
    if task_id is not None:
        ctx = await load_task_context(db, actor, task_id, lock_project="share")
        if not can_read_project_content(actor, ctx.project):
            raise Forbidden()
        task = (
            await db.execute(select(Task).where(Task.id == task_id, Task.deleted_at.is_(None)))
        ).scalar_one_or_none()
        if task is None:
            raise NotFound("Задача не найдена")
        rows = (
            (
                await db.execute(
                    select(TaskDodCriterion)
                    .where(TaskDodCriterion.task_id == task_id)
                    .order_by(TaskDodCriterion.position, TaskDodCriterion.id)
                )
            )
            .scalars()
            .all()
        )
        extra_parts = [
            task.title,
            task.description,
            *[r.body for r in rows],
            *[r.evidence_ref or "" for r in rows],
        ]
    blob_text = " ".join(filter(None, [text, *extra_parts]))
    missing = missing_from_text(blob_text)
    mode, can_run = _decide(blob_text, missing)
    committed = False
    if commit:
        if task is None:
            raise Unprocessable("commit требует task_id", code=ErrorCode.validation_error)
        ctx = await load_task_context(db, actor, task.id, lock_project="share")
        facts = TaskFacts(
            created_by=task.created_by, assignee_id=task.assignee_id, parent_id=task.parent_id
        )
        if not can_edit_task_fully(actor, ctx.project, facts):
            raise Forbidden()
        if task.mode != mode:
            task.mode = mode
            await db.flush()
            await record_event(
                db,
                workspace_id=actor.workspace_id,
                actor_id=actor.user_id,
                action=EventAction.TASK_UPDATED,
                entity_id=task.id,
                project_id=task.project_id,
                changed_fields=["mode"],
            )
        committed = True
    return ClassifyResult(
        mode=mode,
        missing=missing,
        can_run_without_human=can_run,
        task_id=task.id if task is not None else None,
        committed=committed,
    )
