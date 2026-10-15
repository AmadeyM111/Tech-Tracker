"""Схемы API комментариев (plan §11.4, D-65).

Входная схема проверяет форму: ``body`` — строка 1-10 000 символов до очистки, без NUL
(PostgreSQL не принимает ``\\x00``), без ``null``, лишние поля запрещены. «Пусто после очистки»
проверяет сервис (422 домена). Все поля ответа обязательны; ``null`` — у ``body`` удалённого
комментария и у ``edited_at`` неправленого.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.common import UserRef
from app.domain.comments.service import BODY_MAX

CommentBody = Annotated[str, Field(min_length=1, max_length=BODY_MAX, pattern=r"^[^\x00]*$")]


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: CommentBody


class CommentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: CommentBody


class CommentPermissions(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    edit: bool
    delete: bool


class Comment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    author: UserRef
    body: str | None
    is_deleted: bool
    created_at: datetime
    edited_at: datetime | None
    permissions: CommentPermissions
