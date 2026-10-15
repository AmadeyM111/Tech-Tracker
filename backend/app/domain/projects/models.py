"""Модели ``project`` и ``project_member`` (plan §11.6, D-2, D-25, D-26, D-52, D-57).

Статуса проекта нет (архив отложен, D-57). Пустое название отсекает сервис (D-52); БД
проверяет длину ``name`` 1..255 и ``description`` <= 10000 символов (FR-14).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import (
    AuthoredMixin,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPkMixin,
    WorkspaceMixin,
)


class Project(UUIDPkMixin, TimestampMixin, WorkspaceMixin, AuthoredMixin, SoftDeleteMixin, Base):
    __tablename__ = "project"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 255", name="name_length"),
        CheckConstraint("char_length(description) <= 10000", name="description_length"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )


class ProjectMember(TimestampMixin, WorkspaceMixin, AuthoredMixin, Base):
    """Участник проекта; PK (project_id, user_id), отдельного ``id`` нет."""

    __tablename__ = "project_member"

    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("project.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        primary_key=True,
        index=True,
    )
