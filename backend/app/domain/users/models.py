"""Модель ``app_user`` (plan §4.3, D-5, D-39, D-66, FR-73, FR-73a).

Пользователь — глобальная идентичность: ``workspace_id`` и роли здесь нет, принадлежность
пространству и роль хранит ``workspace_member``.

Логин хранится дважды (D-66): ``login`` — КЛЮЧ (нормализованный вид, строчные): вход,
уникальность, поиск, сортировка; наружу не отдаётся. ``login_display`` — ПОКАЗ: написание при
создании; все ответы API берут логин отсюда.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.engine.default import DefaultExecutionContext
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import AuthoredMixin, Base, TimestampMixin, UUIDPkMixin


def _login_display_default(context: DefaultExecutionContext) -> str:
    """Не передан — равен ключу (демо-логины, фабрики тестов): как до v0.17 (FR-73a)."""
    # в SQLAlchemy метод без аннотаций (strict mypy: no-untyped-call)
    return str(context.get_current_parameters()["login"])  # type: ignore[no-untyped-call]


class AppUser(UUIDPkMixin, TimestampMixin, AuthoredMixin, Base):
    __tablename__ = "app_user"
    __table_args__ = (
        # Шаблон логина (FR-73); заодно гарантирует нижний регистр, поэтому UNIQUE(login)
        # регистронезависим (D-39).
        CheckConstraint("login ~ '^[a-z0-9][a-z0-9._-]{2,63}$'", name="login_format"),
        # D-66: показ совпадает с ключом с точностью до регистра латинских букв; COLLATE "C"
        # делает lower() ASCII-only и независимым от локали БД (знак Кельвина не приводится).
        CheckConstraint('lower(login_display COLLATE "C") = login', name="login_display_lower"),
    )

    # КЛЮЧ: нормализованный вид (вход, уникальность, поиск, сортировка). НЕ показывать.
    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # ПОКАЗ: написание при создании (FR-73a). Все ответы API берут логин отсюда.
    login_display: Mapped[str] = mapped_column(
        String(64), nullable=False, default=_login_display_default
    )
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
