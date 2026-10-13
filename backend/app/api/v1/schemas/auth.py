"""Схемы входа и профиля (plan §4.6, FR-57).

Пароль — ``SecretStr``: значение не попадает в ``repr``, ``model_dump`` и сообщения об
ошибках валидации (обработчик 422 не возвращает ``input``).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr

from app.domain.access.roles import Capability, Role


class LoginRequest(BaseModel):
    """``POST /auth/login``: логин нормализуется и проверяется сервисом (FR-73)."""

    model_config = ConfigDict(extra="forbid")

    login: str
    password: SecretStr


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
