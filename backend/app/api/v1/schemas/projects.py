"""Схемы API проектов и участников (plan §11.4, D-52).

Входные схемы проверяют только форму (длины, отсутствие NUL — PostgreSQL не принимает
``\\x00`` в тексте); «название из одних пробелов» (D-52) проверяет сервис. Ответов со ``status``
нет (архива в MVP нет, D-57).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    model_config = ConfigDict(extra="forbid")

    user_id: UUID


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
