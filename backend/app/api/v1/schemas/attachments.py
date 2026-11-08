"""Схемы вложений (spec 011 FR-9)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.api.v1.schemas.common import UserRef
from app.domain.attachments.types import FileKind


class AttachmentOut(BaseModel):
    """Вложение задачи: метаданные и права; путь хранения не отдаётся."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    name: str
    kind: FileKind
    content_type: str
    size_bytes: int
    created_at: datetime
    author: UserRef | None
    inline: bool
    can_delete: bool
