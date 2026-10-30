"""Модель ``api_key`` — ключи API агентов (spec 007 FR-6, FR-30; plan 007 §4.1, PD-1, PD-9).

В БД хранится только ``sha256(секрет)`` (32 байта); секрет, его префикс и любая часть секрета —
нет. Ключи не удаляются (FK ``RESTRICT``): отзыв — ``revoked_at`` + ``revoked_by``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, UUIDPkMixin


def _user_fk() -> ForeignKey:
    return ForeignKey("app_user.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE")


class ApiKey(UUIDPkMixin, Base):
    __tablename__ = "api_key"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 100", name="name_length"),
        CheckConstraint("octet_length(secret_digest) = 32", name="digest_length"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint("rate_count >= 0", name="rate_count_nonnegative"),
        CheckConstraint("(revoked_at IS NULL) = (revoked_by IS NULL)", name="revoked_pair"),
        Index("ix_api_key_workspace_id_user_id", "workspace_id", "user_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("workspace.id", ondelete="RESTRICT", deferrable=True, initially="IMMEDIATE"),
        nullable=False,
    )
    # Агент, которому принадлежит ключ.
    user_id: Mapped[UUID] = mapped_column(Uuid, _user_fk(), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    secret_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    # Технический администратор, выпустивший ключ.
    created_by: Mapped[UUID] = mapped_column(Uuid, _user_fk(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[UUID | None] = mapped_column(Uuid, _user_fk(), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_window_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
