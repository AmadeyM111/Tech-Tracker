"""Модели ``comment_mention`` и ``notification`` (spec 012 FR-1…FR-6; plan PN-2…PN-4).

Уведомление не хранит текста комментария (FR-6): только вид, задачу, проект, автора действия и
ссылку на комментарий. Повторы исключает ``UNIQUE (recipient_id, kind, task_id, dedup_key)``:
у действий — свой ключ на событие, у комментариев — id комментария, у сроков — дата срока.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, UUIDPkMixin, WorkspaceMixin


class NotificationKind(StrEnum):
    ASSIGNED = "assigned"
    REVIEW_REQUESTED = "review_requested"
    REVIEW_RETURNED = "review_returned"
    MENTIONED = "mentioned"
    COMMENTED = "commented"
    DUE_TOMORROW = "due_tomorrow"
    OVERDUE = "overdue"


class CommentMention(WorkspaceMixin, Base):
    """Кого упомянули в комментарии; PK (comment_id, user_id)."""

    __tablename__ = "comment_mention"

    comment_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("comment.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Notification(UUIDPkMixin, WorkspaceMixin, Base):
    __tablename__ = "notification"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('assigned','review_requested','review_returned','mentioned','commented',"
            "'due_tomorrow','overdue')",
            name="kind_valid",
        ),
        CheckConstraint("char_length(dedup_key) BETWEEN 1 AND 64", name="dedup_key_length"),
        UniqueConstraint(
            "recipient_id", "kind", "task_id", "dedup_key", name="uq_notification_dedup"
        ),
    )

    recipient_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("project.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="SET NULL", deferrable=True, initially="IMMEDIATE"),
        nullable=True,
    )
    comment_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("comment.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=True,
    )
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Список и счётчик получателя (PN-4): новые сверху, непрочитанные.
Index(
    "ix_notification_recipient_id_read_at_created_at",
    Notification.recipient_id,
    Notification.read_at,
    Notification.created_at.desc(),
)
# Очистка старше 90 дней (FR-9).
Index("ix_notification_created_at", Notification.created_at)
