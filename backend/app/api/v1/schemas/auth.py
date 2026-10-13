"""Схемы входа и профиля (plan §4.6, FR-57).

Пароль — ``SecretStr``: значение не попадает в ``repr``, ``model_dump`` и сообщения об
ошибках валидации (обработчик 422 не возвращает ``input``). Длина логина и паролей ограничена
``MAX_CREDENTIAL_LENGTH``: пароль на мегабайты не доходит до Argon2 (ревью T13); одиночный
суррогат (``\\ud800``) в строке отклоняется как ``validation_error``, а не 500 при хешировании
(ревью T08).
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.domain.access.roles import Capability, Role

MAX_CREDENTIAL_LENGTH: Final = 1024


Password = Annotated[SecretStr, Field(max_length=MAX_CREDENTIAL_LENGTH)]


def _require_encodable(value: SecretStr) -> SecretStr:
    try:
        value.get_secret_value().encode("utf-8")
    except UnicodeEncodeError:
        # сообщение без значения: ``args`` исключения кодирования содержат пароль
        raise ValueError("Недопустимые символы в пароле") from None
    return value


class LoginRequest(BaseModel):
    """``POST /auth/login``: логин нормализуется и проверяется сервисом (FR-73)."""

    model_config = ConfigDict(extra="forbid")

    login: Annotated[str, Field(max_length=MAX_CREDENTIAL_LENGTH)]
    password: Password

    _password_encodable = field_validator("password")(_require_encodable)


class ChangePasswordRequest(BaseModel):
    """``POST /auth/password`` (FR-56): ответ 204 без тела."""

    model_config = ConfigDict(extra="forbid")

    current_password: Password
    new_password: Password

    _passwords_encodable = field_validator("current_password", "new_password")(_require_encodable)


class SessionUser(BaseModel):
    """Профиль в ответе на вход: ровно эти четыре поля."""

    id: UUID
    login: str
    role: Role | None
    must_change_password: bool


class LoginResponse(BaseModel):
    user: SessionUser


class MeResponse(BaseModel):
    """``GET /me``: активный пользователь (роль назначена, пароль не одноразовый)."""

    id: UUID
    login: str
    role: Role
    must_change_password: bool
    capabilities: list[Capability]
