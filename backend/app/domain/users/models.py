"""Модель ``app_user`` (plan §4.3, D-5, D-39, FR-73).

Пользователь — глобальная идентичность: ``workspace_id`` и роли здесь нет, принадлежность
пространству и роль хранит ``workspace_member``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import AuthoredMixin, Base, TimestampMixin, UUIDPkMixin


class AppUser(UUIDPkMixin, TimestampMixin, AuthoredMixin, Base):
    __tablename__ = "app_user"
    __table_args__ = (
        # Шаблон логина (FR-73); заодно гарантирует нижний регистр, поэтому UNIQUE(login)
        # регистронезависим (D-39).
        CheckConstraint("login ~ '^[a-z0-9][a-z0-9._-]{2,63}$'", name="login_format"),
    )

    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    login_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
