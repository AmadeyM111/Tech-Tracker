"""Схемы самостоятельной регистрации (spec 019: FR-3, FR-4, FR-8; plan §4.4, RG-7, RG-20).

Схема ограничивает только тип и размер. Формат адреса, имени, фамилии и логина проверяет домен
(RG-7): ошибка получает код поля (``email_invalid``, ``first_name_invalid`` и т. д.), а не
``validation_error``. Пароль проходит ту же проверку кодируемости, что и вход (ревью T08).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.api.v1.schemas.auth import Password, _require_encodable
from app.domain.auth.registration import ACCEPTED_DETAIL

# Верхняя граница строк совпадает с ``MAX_CREDENTIAL_LENGTH``: длиннее — ``validation_error``.
_TEXT_MAX_LENGTH = 1024


class RegistrationRequest(BaseModel):
    """``POST /auth/registration/request``: заявка на регистрацию (FR-3)."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(max_length=_TEXT_MAX_LENGTH)]
    first_name: Annotated[str, Field(max_length=_TEXT_MAX_LENGTH)]
    last_name: Annotated[str, Field(max_length=_TEXT_MAX_LENGTH)]
    login: Annotated[str, Field(max_length=_TEXT_MAX_LENGTH)]
    password: Password

    _password_encodable = field_validator("password")(_require_encodable)


class RegistrationAccepted(BaseModel):
    """Единый ответ на заявку (FR-4, RG-20): одинаков для свободного и занятого адреса."""

    detail: str = ACCEPTED_DETAIL


class RegistrationConfirm(BaseModel):
    """``POST /auth/registration/confirm``: токен из ссылки (FR-8)."""

    model_config = ConfigDict(extra="forbid")

    token: Annotated[SecretStr, Field(max_length=128)]
