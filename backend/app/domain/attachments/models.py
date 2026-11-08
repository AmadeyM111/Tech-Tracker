"""Модель ``attachment`` (spec 011 FR-5, FR-7; plan PA-3, PA-4).

Файл лежит в ``DATA_DIR/attachments/<ключ[:2]>/<ключ>``; ключ — случайный ``uuid4().hex``.
Исходное имя — только метаданные (в путь не попадает). Тип (``kind``) и ``content_type``
определяет сервер по сигнатуре, а не клиент. Удаление мягкое (корзина, ADR-0010).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    AuthoredMixin,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPkMixin,
    WorkspaceMixin,
)


class Attachment(UUIDPkMixin, TimestampMixin, WorkspaceMixin, AuthoredMixin, SoftDeleteMixin, Base):
    __tablename__ = "attachment"
    __table_args__ = (
        CheckConstraint("char_length(original_name) BETWEEN 1 AND 255", name="name_length"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint("storage_key ~ '^[0-9a-f]{32}$'", name="storage_key_hex"),
        CheckConstraint(
            "kind IN ('pdf','docx','xlsx','pptx','txt','csv','png','jpeg','gif','webp')",
            name="kind_valid",
        ),
    )

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
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


# Список вложений задачи и лимит на задачу — только живые.
Index(
    "ix_attachment_task_id_created_at",
    Attachment.task_id,
    Attachment.created_at,
    postgresql_where=text("deleted_at IS NULL"),
)
# Очистка корзины: удалённые по времени удаления.
Index(
    "ix_attachment_deleted_at",
    Attachment.deleted_at,
    postgresql_where=text("deleted_at IS NOT NULL"),
)
