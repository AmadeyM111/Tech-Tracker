"""Модель ``domain_event`` — append-only журнал событий (plan §4.3, D-7, D-8, D-26).

Нет ``created_at``/``updated_at``: строка не изменяется, время события — ``occurred_at``.
FK только на ``workspace`` и ``app_user``; на доменные сущности FK нет (``entity_id``,
``project_id``, ``deal_id`` переживают окончательное удаление объекта, FR-25b).
Неизменяемость обеспечивают триггеры БД (миграция 0002).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base
from app.domain.events.catalog import EntityType

_ENTITY_TYPES_SQL = ",".join(f"'{e.value}'" for e in EntityType)


class DomainEvent(Base):
    __tablename__ = "domain_event"
    __table_args__ = (
        # D-41, D-58: тип объекта — одно из значений EntityType (в БД их 7, как в каталоге).
        CheckConstraint(f"entity_type IN ({_ENTITY_TYPES_SQL})", name="entity_type_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workspace.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        nullable=True,
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    changed_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    project_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    deal_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    in_audit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changes: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)


# Лента проекта (FR-38), история и лента сделки (FR-35), аудит (FR-41), события объекта.
Index(
    "ix_domain_event_workspace_id_project_id_id",
    DomainEvent.workspace_id,
    DomainEvent.project_id,
    DomainEvent.id.desc(),
    postgresql_where=DomainEvent.project_id.is_not(None),
)
Index(
    "ix_domain_event_workspace_id_deal_id_id",
    DomainEvent.workspace_id,
    DomainEvent.deal_id,
    DomainEvent.id.desc(),
    postgresql_where=DomainEvent.deal_id.is_not(None),
)
Index(
    "ix_domain_event_workspace_id_id_audit",
    DomainEvent.workspace_id,
    DomainEvent.id.desc(),
    postgresql_where=DomainEvent.in_audit,
)
Index("ix_domain_event_entity_type_entity_id", DomainEvent.entity_type, DomainEvent.entity_id)
