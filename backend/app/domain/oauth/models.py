"""Модели OAuth: клиенты (DCR), гранты, коды авторизации, токены, счётчики лимитов (spec 028 §9).

Секреты (код, access- и refresh-токены) в БД не хранятся: только SHA-256 (32 байта), как у
``api_token`` (ADR-0018 PN-1). ``oauth_grant`` — согласие пользователя клиенту: отзыв гранта
отзывает все его токены (FR-11).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base


class OauthClient(Base):
    __tablename__ = "oauth_client"
    __table_args__ = (
        CheckConstraint("char_length(client_id) BETWEEN 16 AND 64", name="client_id_length"),
        CheckConstraint(
            "client_name IS NULL OR char_length(client_name) BETWEEN 1 AND 64",
            name="client_name_length",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    client_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    client_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class OauthGrant(Base):
    __tablename__ = "oauth_grant"
    __table_args__ = (
        Index(
            "ix_oauth_grant_user_id_active", "user_id", postgresql_where=text("revoked_at IS NULL")
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workspace.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("app_user.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )
    client_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("oauth_client.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
        index=True,
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OauthCode(Base):
    __tablename__ = "oauth_code"
    __table_args__ = (CheckConstraint("octet_length(code_hash) = 32", name="code_hash_length"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    grant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("oauth_grant.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
        index=True,
    )
    code_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OauthToken(Base):
    """Access- или refresh-токен гранта. Refresh при использовании помечается ``used_at``."""

    __tablename__ = "oauth_token"
    __table_args__ = (
        CheckConstraint("kind IN ('access','refresh')", name="kind_valid"),
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    grant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("oauth_grant.id", ondelete="CASCADE", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OauthAttempt(Base):
    """Счётчик лимитов по IP (регистрация, token endpoint); ключ — HMAC, IP не хранится."""

    __tablename__ = "oauth_attempt"
    __table_args__ = (
        CheckConstraint("scope IN ('register_ip','token_ip')", name="scope_valid"),
        CheckConstraint("octet_length(key_hash) = 32", name="key_hash_length"),
        Index("ix_oauth_attempt_scope_key_hash_created_at", "scope", "key_hash", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
