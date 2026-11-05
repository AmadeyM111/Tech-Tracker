"""Схемы сброса пароля по email (spec 007: FR-3, FR-6; plan §4.4)."""

from __future__ import annotations

from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.api.v1.schemas.auth import Password, _require_encodable

ACCEPTED_DETAIL: Final = (
    "Если для этого адреса есть учётная запись, мы отправили письмо со ссылкой."
)


class PasswordResetStatus(BaseModel):
    """``GET /auth/password-reset/status``: настроена ли отправка писем."""

    enabled: bool


class PasswordResetRequest(BaseModel):
    """``POST /auth/password-reset/request``: формат адреса проверяет домен, не схема (PR-21)."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(min_length=1, max_length=254)]


class PasswordResetAccepted(BaseModel):
    """Единый ответ на запрос сброса (FR-6)."""

    detail: str = ACCEPTED_DETAIL


class PasswordResetConfirm(BaseModel):
    """``POST /auth/password-reset/confirm``: токен из ссылки и новый пароль (FR-11)."""

    model_config = ConfigDict(extra="forbid")

    token: Annotated[SecretStr, Field(max_length=128)]
    new_password: Password

    _encodable = field_validator("token", "new_password")(_require_encodable)
