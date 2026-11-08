"""Схемы уведомлений (spec 012 FR-5): без текста комментариев (FR-6)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.v1.schemas.common import ProjectRef, UserRef
from app.domain.notifications.models import NotificationKind


class NotificationTask(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: NotificationKind
    task: NotificationTask
    project: ProjectRef
    actor: UserRef | None
    created_at: datetime
    read: bool


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    page: int
    page_size: int
    has_next: bool
    unread: int


class UnreadCount(BaseModel):
    unread: int


class MarkRead(BaseModel):
    """Выбранные (``ids``) или все (``all=true``); ровно одно из двух."""

    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] | None = Field(default=None, max_length=100)
    all: bool = False

    @model_validator(mode="after")
    def _one_of(self) -> MarkRead:
        if (self.ids is None) == (not self.all):
            raise ValueError("укажите ids или all=true")
        return self
