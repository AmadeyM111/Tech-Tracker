"""Вход, выход, смена своего пароля (plan §4.6, D-10, FR-1, FR-5, FR-56, FR-60, FR-61).

Сервис не вызывает ``commit()``: транзакцию запроса фиксирует ``get_db``. Единственное
исключение — ``commit_durably``: (1) сразу после резервирования попытки провайдером, до
медленной проверки пароля (параллельные запросы видят занятый слот, FR-61); (2) на ветках
отказа входа перед ``InvalidCredentials`` (счётчик неудач и блокировка должны пережить откат
запроса).

Событий в ``domain_event`` вход, выход и смена пароля не пишут (FR-41). Пароли, хеши и
токены не попадают в исключения и логи (FR-57).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select, update

from app.core.db import commit_durably
from app.core.errors import ErrorCode, InvalidCredentials, NotAuthenticated, Unprocessable
from app.core.security.passwords import (
    PasswordHasher,
    PasswordPolicyError,
    hash_in_thread,
    validate_new_password,
    verify_in_thread,
)
from app.domain.auth.provider import AuthProvider, PasswordCredentials, normalize_login
from app.domain.auth.sessions import SessionStore
from app.domain.system.bootstrap import remove_initial_admin_file_if_for
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

logger = logging.getLogger("app.auth")


class SessionActor(Protocol):
    """Часть ``Actor`` (plan §4.5, T12), нужная этому сервису."""

    @property
    def user_id(self) -> UUID: ...

    @property
    def login(self) -> str: ...

    @property
    def session_id(self) -> bytes: ...


@dataclass(frozen=True)
class LoginResult:
    token: str
    user_id: UUID
    login: str
    # значение роли (``Role``, T12); None — «без роли» (FR-66)
    role: str | None
    must_change_password: bool


async def login(
    db: AsyncSession,
    provider: AuthProvider,
    sessions: SessionStore,
    *,
    login: str,
    password: SecretStr,
    now: datetime,
) -> LoginResult:
    """Вход по логину и паролю; любая причина отказа — один и тот же ``InvalidCredentials``.

    Логин приводится к нижнему регистру (FR-73); логин вне шаблона отклоняется без обращения
    к БД. Заблокированный пользователь и пользователь без членства в пространстве получают тот
    же отказ (FR-5, FR-61). Роль ``NULL`` вход не запрещает (FR-66).
    """
    normalized = normalize_login(login)
    if normalized is None:
        raise InvalidCredentials()

    async def reserved() -> None:
        # занятый слот попытки виден параллельным запросам до медленной проверки пароля
        await commit_durably(db)

    user_id = await provider.authenticate(
        db, PasswordCredentials(login=normalized, password=password), now=now, checkpoint=reserved
    )
    if user_id is None:
        await commit_durably(db)
        raise InvalidCredentials()

    row = (
        await db.execute(
            select(
                AppUser.login,
                AppUser.is_blocked,
                AppUser.must_change_password,
                WorkspaceMember.workspace_id,
                WorkspaceMember.role,
            )
            .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
            .where(AppUser.id == user_id)
            .order_by(WorkspaceMember.created_at, WorkspaceMember.workspace_id)
            .limit(1)
        )
    ).one_or_none()
    if row is None or row.is_blocked:
        await commit_durably(db)
        raise InvalidCredentials()

    token = await sessions.create(db, user_id=user_id, workspace_id=row.workspace_id, now=now)
    return LoginResult(
        token=token,
        user_id=user_id,
        login=row.login,
        role=row.role,
        must_change_password=row.must_change_password,
    )


async def logout(db: AsyncSession, sessions: SessionStore, token: str) -> None:
    """Удаляет сессию на сервере (FR-60); неизвестный токен — не ошибка."""
    await sessions.delete(db, token)


async def change_own_password(
    db: AsyncSession,
    actor: SessionActor,
    hasher: PasswordHasher,
    sessions: SessionStore,
    settings: Settings,
    *,
    current: SecretStr,
    new: SecretStr,
    now: datetime,
) -> None:
    """Смена своего пароля (FR-56, FR-52, FR-53).

    Порядок проверок: текущий пароль (``invalid_current_password``) -> новый совпадает с
    текущим (``password_reused``) -> недопустимые символы (``validation_error``) -> политика
    (``password_too_short`` / ``password_too_common``). При успехе: новый хеш,
    ``must_change_password = false``, ``password_changed_at = now``, все остальные сессии
    пользователя удалены, файл пароля первого ТА (если он выдан этому логину) удалён.
    """
    current_value = current.get_secret_value()
    new_value = new.get_secret_value()

    stored_hash = (
        await db.execute(
            select(AppUser.password_hash).where(AppUser.id == actor.user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if stored_hash is None:
        raise NotAuthenticated()

    if not await _current_password_matches(hasher, stored_hash, current_value):
        raise Unprocessable(code=ErrorCode.invalid_current_password)
    if new_value == current_value:
        raise Unprocessable(code=ErrorCode.password_reused)
    try:
        new_value.encode("utf-8")
    except UnicodeEncodeError:
        # исключение не пробрасываем: его args содержат пароль (ревью T08)
        raise Unprocessable(code=ErrorCode.validation_error) from None
    try:
        validate_new_password(new_value)
    except PasswordPolicyError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None

    new_hash = await hash_in_thread(hasher, new_value)
    await db.execute(
        update(AppUser)
        .where(AppUser.id == actor.user_id)
        .values(password_hash=new_hash, must_change_password=False, password_changed_at=now)
    )
    await sessions.delete_all_for_user(db, actor.user_id, keep_id=actor.session_id)

    try:
        remove_initial_admin_file_if_for(settings, actor.login)
    except Exception as exc:
        # Пароль уже сменён, файл содержит недействительный пароль: сбой удаления не
        # откатывает смену. В лог — только тип ошибки (без текста и трассировки).
        logger.warning(
            "Не удалось удалить файл пароля первого администратора: %s", type(exc).__name__
        )


async def _current_password_matches(
    hasher: PasswordHasher, stored_hash: str, password: str
) -> bool:
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return await verify_in_thread(hasher, stored_hash, password)
