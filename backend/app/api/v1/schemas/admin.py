"""Схемы раздела «Учётные записи» (plan §4.6, D-15, FR-57).

Одноразовый пароль приходит только в запросе (``SecretStr``: в ``repr``, ``model_dump`` и
сообщения 422 значение не попадает; в OpenAPI поле — ``format: password``, ``writeOnly``).
В ответах паролей, хешей и счётчиков входа нет: ``AdminUser`` — ровно шесть полей.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.auth import MAX_CREDENTIAL_LENGTH, Password
from app.domain.access.roles import Role


class AdminUser(BaseModel):
    """Учётная запись в разделе администрирования (``GET``, ``POST``, ``PUT …/role``)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    login: str
    role: Role | None
    is_blocked: bool
    must_change_password: bool
    created_at: datetime


class CreateUserRequest(BaseModel):
    """``POST /admin/users``: роль не передаётся, назначается отдельным действием (FR-4)."""

    model_config = ConfigDict(extra="forbid")

    login: Annotated[str, Field(max_length=MAX_CREDENTIAL_LENGTH)]
    one_time_password: Password


class ResetPasswordRequest(BaseModel):
    """``POST /admin/users/{user_id}/reset-password`` (FR-65)."""

    model_config = ConfigDict(extra="forbid")

    one_time_password: Password


class SetRoleRequest(BaseModel):
    """``PUT /admin/users/{user_id}/role``: ``null`` снимает роль (FR-12, FR-66)."""

    model_config = ConfigDict(extra="forbid")

    role: Role | None
