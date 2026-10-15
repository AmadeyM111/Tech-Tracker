"""Модели ``workspace`` и ``workspace_member`` (plan §4.3, D-5, FR-13, FR-66)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import AuthoredMixin, Base, TimestampMixin, UUIDPkMixin


class Workspace(UUIDPkMixin, TimestampMixin, Base):
    """Пространство: граница данных (FR-13). В R1 одно, структура готова к нескольким (D-5)."""

    __tablename__ = "workspace"


class WorkspaceMember(TimestampMixin, AuthoredMixin, Base):
    """Членство пользователя в пространстве и его роль.

    PK(workspace_id, user_id): не больше одной роли в пространстве (FR-66). ``role IS NULL`` —
    «без роли». Отдельного индекса по ``workspace_id`` нет: он — префикс PK и индекса
    (workspace_id, role).
    """

    __tablename__ = "workspace_member"
    __table_args__ = (
        CheckConstraint(
            "role IN ('tech_admin','business_admin','mixed','user')",
            name="role_valid",
        ),
        Index("ix_workspace_member_workspace_id_role", "workspace_id", "role"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workspace.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        primary_key=True,
    )
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
