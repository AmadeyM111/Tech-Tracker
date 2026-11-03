"""Лента проекта (plan §4.4, §10.3; FR-38 в объёме проекта, ADR-0015).

Читает ``domain_event`` по ``project_id``, новые первыми. Тело события не содержит
текста комментариев и названий/описаний: ``changes`` пишутся только для полей из каталога
``value_fields``. Удалённый объект (нет строки или ``deleted_at``) отдаётся без названия и
значений (FR-25b).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from app.core.errors import Forbidden
from app.core.pagination import PageParams, paginate
from app.domain.access.policy import can_read_project_content
from app.domain.access.roles import Actor
from app.domain.comments.models import Comment
from app.domain.events.models import DomainEvent
from app.domain.projects.models import Project
from app.domain.projects.queries import load_project_facts
from app.domain.tasks.models import Task
from app.domain.users.directory import UserRef, user_refs

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class FeedEntity:
    type: str
    id: UUID
    deleted: bool
    title: str | None


@dataclass(frozen=True)
class FeedRow:
    id: int
    occurred_at: datetime
    actor: UserRef | None
    action: str
    entity: FeedEntity
    changed_fields: list[str]
    changes: list[dict[str, Any]] | None


EntityState = tuple[bool, str | None]  # (удалён, название)


async def _entity_states(
    db: AsyncSession, workspace_id: UUID, events: Sequence[DomainEvent]
) -> dict[tuple[str, UUID], EntityState]:
    """Одна выборка на тип сущности для всей страницы; отсутствующая строка — удалена."""
    ids: dict[str, set[UUID]] = {}
    for event in events:
        ids.setdefault(event.entity_type, set()).add(event.entity_id)
    states: dict[tuple[str, UUID], EntityState] = {}
    if project_ids := ids.get("project"):
        rows = await db.execute(
            select(Project.id, Project.name, Project.deleted_at).where(
                Project.workspace_id == workspace_id, Project.id.in_(project_ids)
            )
        )
        for row in rows:
            states[("project", row.id)] = (row.deleted_at is not None, row.name)
    if task_ids := ids.get("task"):
        rows = await db.execute(
            select(Task.id, Task.title, Task.deleted_at).where(
                Task.workspace_id == workspace_id, Task.id.in_(task_ids)
            )
        )
        for row in rows:
            states[("task", row.id)] = (row.deleted_at is not None, row.title)
    if comment_ids := ids.get("comment"):
        rows = await db.execute(
            select(Comment.id, Comment.deleted_at).where(
                Comment.workspace_id == workspace_id, Comment.id.in_(comment_ids)
            )
        )
        for row in rows:
            states[("comment", row.id)] = (row.deleted_at is not None, None)
    if user_ids := ids.get("user"):
        for user_id, ref in (await user_refs(db, workspace_id, user_ids)).items():
            states[("user", user_id)] = (False, ref.login)
    return states


async def project_feed(
    db: AsyncSession, actor: Actor, project_id: UUID, params: PageParams
) -> tuple[list[FeedRow], bool]:
    """Страница ленты: проект (404) → участник содержимого (403) → события ``ORDER BY id DESC``."""
    facts = await load_project_facts(db, actor, project_id)
    if not can_read_project_content(actor, facts):
        raise Forbidden()
    stmt = (
        select(DomainEvent)
        .where(DomainEvent.workspace_id == actor.workspace_id, DomainEvent.project_id == project_id)
        .order_by(DomainEvent.id.desc())
    )
    events, has_next = await paginate(db, stmt, params)
    if not events:
        return [], has_next
    states = await _entity_states(db, actor.workspace_id, events)
    actors = await user_refs(
        db, actor.workspace_id, [e.actor_id for e in events if e.actor_id is not None]
    )
    rows: list[FeedRow] = []
    for event in events:
        deleted, title = states.get((event.entity_type, event.entity_id), (True, None))
        title = None if deleted else title  # удалённый объект — без названия (FR-25b)
        rows.append(
            FeedRow(
                id=event.id,
                occurred_at=event.occurred_at,
                actor=None if event.actor_id is None else actors.get(event.actor_id),
                action=event.action,
                entity=FeedEntity(
                    type=event.entity_type,
                    id=event.entity_id,
                    deleted=deleted,
                    title=title,
                ),
                changed_fields=list(event.changed_fields),
                changes=None if deleted or event.changes is None else list(event.changes),
            )
        )
    return rows, has_next
