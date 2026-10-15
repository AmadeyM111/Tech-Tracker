"""Контекст задачи для сервисов: факты задачи и проекта (plan §10.4, §10.2 п.2; FR-13).

Только чтение. Несуществующая, мягко удалённая, чужого пространства и задача удалённого
проекта неразличимы — ``NotFound``. Права и порядок проверок — на вызывающем.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from sqlalchemy import select

from app.core.errors import NotFound
from app.domain.access.policy import ProjectFacts, TaskFacts
from app.domain.projects.queries import load_project_facts
from app.domain.tasks.models import Task, TaskStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.access.roles import Actor


@dataclass(frozen=True)
class TaskContext:
    project: ProjectFacts
    task: TaskFacts
    task_id: UUID
    status: TaskStatus
    position: int | None


async def _read_task(db: AsyncSession, actor: Actor, task_id: UUID) -> Any:
    return (
        await db.execute(
            select(
                Task.project_id,
                Task.created_by,
                Task.assignee_id,
                Task.parent_id,
                Task.status,
                Task.position,
            ).where(
                Task.id == task_id,
                Task.workspace_id == actor.workspace_id,
                Task.deleted_at.is_(None),
            )
        )
    ).one_or_none()


async def load_task_context(
    db: AsyncSession,
    actor: Actor,
    task_id: UUID,
    *,
    lock_project: Literal["share"] | None = None,
) -> TaskContext:
    """Факты задачи и проекта; ``lock_project="share"`` — ``FOR SHARE`` на проекте (§10.2 п.2).

    С блокировкой факты задачи перечитываются после неё: ожидание блокировки не должно
    оставлять устаревший снимок (исключение участника снимает исполнителя, FR-15a).
    """
    row = await _read_task(db, actor, task_id)
    if row is None:
        raise NotFound("Задача не найдена")
    project = await load_project_facts(db, actor, row.project_id, lock=lock_project)
    if lock_project is not None:
        row = await _read_task(db, actor, task_id)
        if row is None or row.project_id != project.project_id:
            raise NotFound("Задача не найдена")
    return TaskContext(
        project=project,
        task=TaskFacts(
            created_by=row.created_by, assignee_id=row.assignee_id, parent_id=row.parent_id
        ),
        task_id=task_id,
        status=TaskStatus(row.status),
        position=row.position,
    )
