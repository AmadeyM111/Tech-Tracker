"""Пакетная атрибуция агента по ``domain_event.client_name`` (спека 022, ADR-0031)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Select, and_, any_, func, literal, or_, select

from app.domain.events.catalog import EntityType, EventAction
from app.domain.events.models import DomainEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class TaskAttribution:
    last_client_name: str | None
    assignee_client_name: str | None


def _norm(name: str | None) -> str | None:
    if name is None:
        return None
    stripped = name.strip()
    return stripped or None


_EMPTY = TaskAttribution(None, None)


async def load_task_attribution(
    db: AsyncSession, workspace_id: UUID, task_ids: Sequence[UUID]
) -> dict[UUID, TaskAttribution]:
    """Последнее событие и последнее назначение исполнителя; один набор id, не N+1."""
    ids = list(task_ids)
    if not ids:
        return {}

    def _latest(extra: Any = True) -> Select[Any]:
        numbered = (
            select(
                DomainEvent.entity_id,
                DomainEvent.client_name,
                func.row_number()
                .over(partition_by=DomainEvent.entity_id, order_by=DomainEvent.id.desc())
                .label("rn"),
            ).where(
                DomainEvent.workspace_id == workspace_id,
                DomainEvent.entity_type == EntityType.TASK.value,
                DomainEvent.entity_id.in_(ids),
                extra,
            )
        ).subquery()
        return select(numbered.c.entity_id, numbered.c.client_name).where(numbered.c.rn == 1)

    last_rows = (await db.execute(_latest())).all()
    assignee_filter = or_(
        DomainEvent.action == EventAction.TASK_CREATED.value,
        and_(
            DomainEvent.action == EventAction.TASK_UPDATED.value,
            literal("assignee_id") == any_(DomainEvent.changed_fields),
        ),
    )
    assignee_rows = (await db.execute(_latest(assignee_filter))).all()
    last_map = {row.entity_id: _norm(row.client_name) for row in last_rows}
    assignee_map = {row.entity_id: _norm(row.client_name) for row in assignee_rows}
    return {
        task_id: TaskAttribution(
            last_client_name=last_map.get(task_id),
            assignee_client_name=assignee_map.get(task_id),
        )
        for task_id in ids
    }


def attr_of(mapping: dict[UUID, TaskAttribution], task_id: UUID) -> TaskAttribution:
    return mapping.get(task_id, _EMPTY)
