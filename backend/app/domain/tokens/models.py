"""Модель ``api_token`` — персональные токены доступа AI-агентов (ADR-0018, PN-1).

Сам токен в БД не хранится: только SHA-256 (32 байта, ``token_hash``). Токен действует
на MCP-эндпоинте и не принимается REST API (PN-2). Строка не удаляется при отзыве:
``revoked_at`` проставляется, история сохраняется.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base


class ApiToken(Base):
    __tablename__ = "api_token"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 64", name="name_length"),
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
        Index(
            "ix_api_token_user_id_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
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
    name: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
