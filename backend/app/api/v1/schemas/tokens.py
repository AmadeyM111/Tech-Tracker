"""Схемы управления токенами агентов: ``/api/v1/me/tokens`` (ADR-0018, PN-1, PN-2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.tokens.service import NAME_MAX_LENGTH


class TokenCreate(BaseModel):
    name: str = Field(max_length=NAME_MAX_LENGTH)


class TokenItem(BaseModel):
    """Токен без значения и хеша; ``active`` вычислен на сервере."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    active: bool


class TokenCreated(TokenItem):
    """Ответ на выдачу: значение ``token`` показывается один раз и больше не отдаётся."""

    token: str
