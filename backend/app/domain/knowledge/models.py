"""Модель ``knowledge_record`` (спека 037, ADR-0033, миграция 0021)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import AuthoredMixin, Base, TimestampMixin, UUIDPkMixin, WorkspaceMixin


class KnowledgeRecord(UUIDPkMixin, TimestampMixin, WorkspaceMixin, AuthoredMixin, Base):
    __tablename__ = "knowledge_record"
    __table_args__ = (
        CheckConstraint("scope IN ('space','project')", name="scope_valid"),
        CheckConstraint("kind IN ('decision','reason','agreement')", name="kind_valid"),
        CheckConstraint(
            "(scope = 'space' AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL)",
            name="scope_project",
        ),
        CheckConstraint("char_length(title) BETWEEN 1 AND 255", name="title_length"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 10000", name="body_length"),
        CheckConstraint(
            "(kind = 'agreement' AND confirmed_with IS NOT NULL "
            "AND char_length(confirmed_with) BETWEEN 1 AND 255) OR "
            "(kind <> 'agreement' AND confirmed_with IS NULL)",
            name="confirmed_with",
        ),
        CheckConstraint(
            "client_name IS NULL OR char_length(client_name) BETWEEN 1 AND 64",
            name="client_name_length",
        ),
        Index(
            "ix_knowledge_record_workspace_id_scope_created_at",
            "workspace_id",
            "scope",
            "created_at",
        ),
    )

    scope: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("project.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_with: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "app_user.id",
            ondelete="RESTRICT",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        nullable=False,
    )
    client_name: Mapped[str | None] = mapped_column(Text, nullable=True)
