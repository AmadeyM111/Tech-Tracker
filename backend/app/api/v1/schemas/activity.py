"""Схемы ленты проекта: ``GET /projects/{id}/activity`` (plan §10.3, FR-38, ADR-0015).

Текст комментариев, названия и описания в ленту не попадают: ``changes`` — только поля из
каталога ``value_fields``; у удалённого объекта ``title`` и ``changes`` — ``null`` (FR-25b).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, JsonValue

from app.domain.events.catalog import EntityType


class ActivityActor(BaseModel):
    """Автор действия; ``kind = system`` при отсутствии автора (id и login — ``null``)."""

    kind: Literal["user", "system"]
    id: UUID | None
    login: str | None


class ActivityEntity(BaseModel):
    type: EntityType
    id: UUID
    deleted: bool
    title: str | None


class ActivityChange(BaseModel):
    field: str
    old: JsonValue
    new: JsonValue


class ActivityItem(BaseModel):
    id: int
    occurred_at: datetime
    actor: ActivityActor
    action: str
    entity: ActivityEntity
    changed_fields: list[str]
    changes: list[ActivityChange] | None
