"""Схемы API проектов и участников (plan §11.4, D-52).

Входные схемы проверяют только форму (длины, отсутствие NUL — PostgreSQL не принимает
``\\x00`` в тексте); «название из одних пробелов» (D-52) проверяет сервис. Ответов со ``status``
нет (архива в MVP нет, D-57).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.v1.schemas.common import UserRef
from app.domain.access.roles import Role
from app.domain.projects.service import DESCRIPTION_MAX, NAME_MAX

_NO_NUL = r"^[^\x00]*$"

ProjectName = Annotated[str, Field(min_length=1, max_length=NAME_MAX, pattern=_NO_NUL)]
ProjectDescription = Annotated[str, Field(max_length=DESCRIPTION_MAX, pattern=_NO_NUL)]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName
    description: ProjectDescription = ""


class ProjectPatch(BaseModel):
    """Оба поля необязательны и не nullable; не переданное поле не меняется.

    «Не передано» — отсутствие поля в теле (``model_fields_set``), явный ``null`` — 422.
    ``default_factory`` нужен лишь затем, чтобы поле не было обязательным и в OpenAPI не
    появился ``null``/``default``; само значение по умолчанию нигде не читается.
    """

    model_config = ConfigDict(extra="forbid")

    name: ProjectName = Field(default_factory=str)
    description: ProjectDescription = Field(default_factory=str)


class OwnerChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID


class MemberAdd(BaseModel):
    """Ровно одно из: ``user_id`` (БА) или точные ``login``/``email`` (spec 027 FR-4)."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = None
    login: str | None = Field(default=None, min_length=1, max_length=64)
    email: str | None = Field(default=None, min_length=1, max_length=254)

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        given = [v for v in (self.user_id, self.login, self.email) if v is not None]
        if len(given) != 1:
            raise ValueError("укажите ровно одно из user_id, login, email")
        return self


class ProjectPermissions(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    manage: bool
    manage_members: bool
    create_task: bool
    remove_self: bool


class ProjectDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    owner: UserRef
    task_count: int
    is_member: bool
    created_at: datetime
    updated_at: datetime
    permissions: ProjectPermissions


class ProjectListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    owner: UserRef
    task_count: int


class ProjectMember(BaseModel):
    """Участник проекта; ``role`` — ``null``, если роль снята (участие сохраняется, AC-74)."""

    model_config = ConfigDict(from_attributes=True)

    user: UserRef
    role: Role | None
    is_blocked: bool
    is_owner: bool
