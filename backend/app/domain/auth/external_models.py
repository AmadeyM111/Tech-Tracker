"""Модели внешнего входа (spec 029, ADR-0026): ``external_identity`` и ``oauth_login_state``.

Провайдерские токены не хранятся (FR-21): только факт привязки. ``oauth_login_state`` — одноразовое
состояние входа или привязки (``state`` хранится как SHA-256, PKCE-``verifier`` и ``nonce`` живут
10 минут и удаляются при первом же обращении к ``callback``).
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
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base


class ExternalIdentity(Base):
    __tablename__ = "external_identity"
    __table_args__ = (
        CheckConstraint("provider IN ('yandex', 'vk', 'google')", name="provider_valid"),
        CheckConstraint("char_length(provider_subject) >= 1", name="subject_not_empty"),
        # ключ идентичности — стабильный идентификатор провайдера (FR-14); отвязанные не мешают
        Index(
            "uq_external_identity_subject_active",
            "provider",
            "provider_subject",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL"),
        ),
        Index(
            "uq_external_identity_user_provider_active",
            "user_id",
            "provider",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email_at_link: Mapped[str | None] = mapped_column(String(254), nullable=True)
    email_verified_by_provider: Mapped[bool] = mapped_column(Boolean, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OauthLoginState(Base):
    __tablename__ = "oauth_login_state"
    __table_args__ = (
        CheckConstraint("provider IN ('yandex', 'vk', 'google')", name="provider_valid"),
        CheckConstraint("purpose IN ('login', 'link')", name="purpose_valid"),
        CheckConstraint("octet_length(state_hash) = 32", name="state_hash_length"),
        CheckConstraint("(purpose = 'link') = (user_id IS NOT NULL)", name="link_has_user"),
    )

    state_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    verifier: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=True
    )
    remember: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
