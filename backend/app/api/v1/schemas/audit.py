"""Схемы раздела «Журнал аудита» (plan §4.4, §4.6, D-7, FR-41, FR-57, BR-2).

``AuditEntry`` — ровно девять полей. Поля ``changes`` нет: значения и названия бизнес-сущностей
не могут попасть в ответ. ``details`` заполняется только для ``entity_type = user``, ключ
присутствует всегда (иначе ``null``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.pagination import PageParams
from app.domain.events.catalog import EntityType


class AuditActor(BaseModel):
    """Автор действия; ``kind = system`` при ``actor_id IS NULL`` (id и login — ``null``)."""

    kind: Literal["user", "system"]
    id: UUID | None
    login: str | None


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    actor: AuditActor
    action: str
    entity_type: EntityType
    entity_id: UUID
    entity_deleted: bool
    changed_fields: list[str]
    details: dict[str, str | None] | None


class AuditListQuery(PageParams):
    """``?page&page_size&entity_type&actor_id``: одна модель параметров запроса."""

    entity_type: EntityType | None = None
    actor_id: UUID | None = None
