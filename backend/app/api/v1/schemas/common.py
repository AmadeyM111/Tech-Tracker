"""Общие схемы ответов API (plan §10.3): ссылки на пользователя и проект, элемент справочника."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.pagination import PageParams
from app.domain.access.roles import Role


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    login: str


class ProjectRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class DirectoryUser(BaseModel):
    """Элемент ``GET /users``: ровно ``{id, login, role}`` (роль БА или П)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    login: str
    role: Role


class DirectoryQuery(PageParams):
    """``?q&page&page_size``: одна модель параметров запроса."""

    # Fail Fast: длина <= 64 и без NUL (PostgreSQL не принимает \x00 в тексте) -> 422.
    q: str | None = Field(None, max_length=64, pattern=r"^[^\x00]*$")
