"""Базовый класс ORM и миксины (plan §4.2, D-2, D-3, D-4, D-26)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.core.clock import utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPkMixin:
    """Первичный ключ — UUID v4, генерируется приложением (D-2)."""

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class TimestampMixin:
    """Метки времени timestamptz, значения — из ``utcnow()`` (D-4, FR-46); без DEFAULT now()."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class WorkspaceMixin:
    """Принадлежность пространству (FR-13): NOT NULL, FK на ``workspace.id``, индекс."""

    @declared_attr
    def workspace_id(cls) -> Mapped[UUID]:
        return mapped_column(
            Uuid,
            ForeignKey("workspace.id", deferrable=True, initially="IMMEDIATE"),
            nullable=False,
            index=True,
        )


class AuthoredMixin:
    """Автор записи; NULL — «система». FK на ``app_user.id`` с RESTRICT (D-26)."""

    @declared_attr
    def created_by(cls) -> Mapped[UUID | None]:
        return mapped_column(
            Uuid,
            ForeignKey(
                "app_user.id",
                ondelete="RESTRICT",
                deferrable=True,
                initially="IMMEDIATE",
            ),
            nullable=True,
        )


class SoftDeleteMixin:
    """Мягкое удаление: момент и пакет удаления (корзина, FR-25)."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_batch_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
