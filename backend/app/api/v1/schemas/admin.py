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
from app.api.v1.schemas.common import UserRef
from app.domain.access.roles import Role
from app.domain.api_keys.service import (
    DEFAULT_TTL_DAYS,
    MAX_NAME_LENGTH,
    MAX_TTL_DAYS,
    ApiKeyState,
)


class AdminUser(BaseModel):
    """Учётная запись в разделе администрирования (``GET``, ``POST``, ``PUT …/role``)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    login: str
    role: Role | None
    is_blocked: bool
    must_change_password: bool
    created_at: datetime
    is_agent: bool


class CreateUserRequest(BaseModel):
    """``POST /admin/users``: роль не передаётся, назначается отдельным действием (FR-4)."""

    model_config = ConfigDict(extra="forbid")

    login: Annotated[str, Field(max_length=MAX_CREDENTIAL_LENGTH)]
    one_time_password: Password


class CreateAgentRequest(BaseModel):
    """``POST /admin/agents``: пароля нет; ``role`` обязателен, ``null`` = «без роли» (007 FR-1)."""

    model_config = ConfigDict(extra="forbid")

    login: Annotated[str, Field(max_length=MAX_CREDENTIAL_LENGTH)]
    role: Role | None


class ResetPasswordRequest(BaseModel):
    """``POST /admin/users/{user_id}/reset-password`` (FR-65)."""

    model_config = ConfigDict(extra="forbid")

    one_time_password: Password


class SetRoleRequest(BaseModel):
    """``PUT /admin/users/{user_id}/role``: ``null`` снимает роль (FR-12, FR-66)."""

    model_config = ConfigDict(extra="forbid")

    role: Role | None


class ApiKeyInfo(BaseModel):
    """Ключ агента в перечне и в ответе выпуска: ровно восемь полей, секрета и дайджеста нет
    (007 FR-7, plan §4.6)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime
    created_by: UserRef | None
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    state: ApiKeyState


class IssueApiKeyRequest(BaseModel):
    """``POST /admin/agents/{user_id}/api-keys``: срок в сутках 1…365, по умолчанию 90 (FR-5, FR-9).

    Срок — строго целое число: строка ``"30"`` и дробное значение отклоняются с 422.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LENGTH, pattern=r"^[^\x00]*$")]
    expires_in_days: Annotated[int, Field(ge=1, le=MAX_TTL_DAYS, strict=True)] = DEFAULT_TTL_DAYS


class IssuedApiKeyResponse(BaseModel):
    """Ответ выпуска — единственное место, где есть секрет ключа (FR-6)."""

    key: ApiKeyInfo
    secret: Annotated[str, Field(description="Показывается один раз", repr=False)]
