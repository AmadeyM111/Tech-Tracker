"""Модель ``comment`` (plan §11.6, D-2, D-25, D-26, FR-23).

Тело — простой текст 1..10000 символов (CHECK по ``char_length``); ``edited_at`` — момент
последнего редактирования, ``NULL`` у неотредактированного.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    AuthoredMixin,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPkMixin,
    WorkspaceMixin,
)


class Comment(UUIDPkMixin, TimestampMixin, WorkspaceMixin, AuthoredMixin, SoftDeleteMixin, Base):
    __tablename__ = "comment"
    __table_args__ = (
        CheckConstraint("char_length(body) BETWEEN 1 AND 10000", name="body_length"),
        Index("ix_comment_task_id_created_at", "task_id", "created_at"),
    )

    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
