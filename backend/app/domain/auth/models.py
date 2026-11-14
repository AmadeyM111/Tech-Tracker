"""Модели ``user_session`` (серверная сессия, plan §4.3, FR-58) и сброса пароля (007, plan §4.1).

``id`` — HMAC токена (bytea, 32 байта, CHECK ``octet_length(id) = 32``, миграция 0003); сам
токен в БД не хранится. ``password_reset_token`` и ``password_reset_attempt`` хранят только
хеши (32 байта): SHA-256 токена и HMAC-SHA256 ключа лимита.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.expression import false

from app.core.clock import utcnow
from app.core.models import Base


class UserSession(Base):
    __tablename__ = "user_session"
    __table_args__ = (
        CheckConstraint("octet_length(id) = 32", name="id_length"),
        # spec 029 (миграция 0015): способы входа; 'password' — до появления других
        CheckConstraint(
            "auth_method IN ('password', 'magic_link', 'yandex', 'vk', 'google')",
            name="auth_method_valid",
        ),
    )

    id: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workspace.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # «Запомнить меня» (spec 029 FR-5): длинный простой и абсолютный срок
    # Серверные значения по умолчанию, как в миграции 0015 (старая схема тоже принимает вставку)
    remember: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    auth_method: Mapped[str] = mapped_column(Text, nullable=False, server_default="password")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_token"
    __table_args__ = (CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordResetAttempt(Base):
    __tablename__ = "password_reset_attempt"
    __table_args__ = (
        CheckConstraint("scope IN ('email','ip')", name="scope_valid"),
        CheckConstraint("octet_length(key_hash) = 32", name="key_hash_length"),
        Index(
            "ix_password_reset_attempt_scope_key_hash_created_at", "scope", "key_hash", "created_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class RegistrationRequest(Base):
    """Заявка на самостоятельную регистрацию (019, plan §4.1). Только хеши; без FK."""

    __tablename__ = "registration_request"
    __table_args__ = (
        CheckConstraint('lower(email COLLATE "C") = email', name="email_lower"),
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    login: Mapped[str] = mapped_column(String(64), nullable=False)
    login_display: Mapped[str] = mapped_column(String(64), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class RegistrationAttempt(Base):
    __tablename__ = "registration_attempt"
    __table_args__ = (
        CheckConstraint("scope IN ('request_ip','confirm_ip','confirm_token')", name="scope_valid"),
        CheckConstraint("octet_length(key_hash) = 32", name="key_hash_length"),
        Index(
            "ix_registration_attempt_scope_key_hash_created_at", "scope", "key_hash", "created_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
