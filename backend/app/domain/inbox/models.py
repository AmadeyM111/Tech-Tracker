"""Модель ``external_message`` (спека 034, ADR-0030): идемпотентный ключ внешнего сообщения.

Без ALTER ``task``. Источник и ссылка живут здесь; карточка и комментарий читают их JOIN-ом.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampMixin, UUIDPkMixin, WorkspaceMixin


class ExternalMessage(UUIDPkMixin, TimestampMixin, WorkspaceMixin, Base):
    __tablename__ = "external_message"
    __table_args__ = (
        CheckConstraint("source IN ('telegram')", name="source_valid"),
        CheckConstraint("char_length(external_id) BETWEEN 1 AND 256", name="external_id_length"),
        CheckConstraint("url IS NULL OR char_length(url) BETWEEN 1 AND 2048", name="url_length"),
        UniqueConstraint(
            "workspace_id",
            "source",
            "external_id",
            name="uq_external_message_source_external_id",
        ),
        Index("ix_external_message_task_id", "task_id"),
        Index("ix_external_message_comment_id", "comment_id"),
    )

    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )
    comment_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("comment.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=True,
    )
