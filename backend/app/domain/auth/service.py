"""Вход, выход, смена своего пароля (plan §4.6, D-10, FR-1, FR-5, FR-56, FR-60, FR-61).

Сервис не вызывает ``commit()``: транзакцию запроса фиксирует ``get_db``. Единственное
исключение — ``commit_durably``: (1) сразу после резервирования попытки провайдером, до
медленной проверки пароля (параллельные запросы видят занятый слот, FR-61); (2) на ветках
отказа входа перед ``InvalidCredentials`` (счётчик неудач и блокировка должны пережить откат
запроса).

Смена пароля (tasks.md T14): неверный текущий пароль занимает тот же слот попытки, что вход
(``reserve_attempt``, FR-61), поэтому перебор ``current_password`` ограничен тем же порогом.
Файл пароля первого ТА удаляется хуком ``after_commit``: до COMMIT он остаётся на месте.

Событий в ``domain_event`` вход, выход и смена пароля не пишут (FR-41). Пароли, хеши и
токены не попадают в исключения и логи (FR-57).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import event, select, update

from app.core.db import commit_durably
from app.core.errors import ErrorCode, InvalidCredentials, NotAuthenticated, Unprocessable
from app.core.security.passwords import (
    PasswordHasher,
    PasswordPolicyError,
    hash_in_thread,
    validate_new_password,
    verify_in_thread,
)
from app.domain.auth.provider import (
    AttemptReservation,
    AuthProvider,
    PasswordCredentials,
    normalize_login,
    reserve_attempt,
    series_not_locked_by_others,
)
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

    Логин нормализуется для поиска учётной записи; в результате — отображаемый логин (FR-73a);
    логин вне шаблона отклоняется без обращения
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
                AppUser.login_display,
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
        login=row.login_display,
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
    """Смена своего пароля (FR-56, FR-52, FR-53, FR-61).

    Порядок проверок: текущий пароль (``invalid_current_password``) -> новый совпадает с
    текущим (``password_reused``) -> недопустимые символы (``validation_error``) -> политика
    (``password_too_short`` / ``password_too_common``). При успехе: новый хеш,
    ``must_change_password = false``, ``password_changed_at = now``, счётчик неудач сброшен, все
    остальные сессии пользователя удалены (заблокированный параллельно пользователь пароль не
    меняет: 401, T17/ревью T16a); файл пароля первого ТА (если он выдан этому логину)
    удаляется после COMMIT транзакции запроса, а не здесь.

    Неверный текущий пароль занимает слот попытки как неудачный вход (общий счётчик, порог и
    срок блокировки): пятая подряд ставит ``login_locked_until`` и завершает текущую сессию
    (фиксируется до ответа). Наружу во всех этих случаях уходит один и тот же
    ``invalid_current_password``. Блокировка входа, поставленная ранее, ответ не меняет: попытка
    не засчитывается, пароль не проверяется.
    """
    current_value = current.get_secret_value()
    new_value = new.get_secret_value()

    reservation = await reserve_attempt(
        db,
        where=AppUser.id == actor.user_id,
        now=now,
        max_failures=settings.login_max_failures,
        lock_duration=settings.login_lock_duration,
    )
    if reservation is None:
        exists = (
            await db.execute(select(AppUser.id).where(AppUser.id == actor.user_id))
        ).scalar_one_or_none()
        if exists is None:
            raise NotAuthenticated()
        # вход заблокирован: время ответа как у настоящей проверки, пароль не сверяется
        await asyncio.to_thread(hasher.dummy_verify, "")
        raise Unprocessable(code=ErrorCode.invalid_current_password)

    # слот попытки виден параллельным запросам до медленной проверки пароля (FR-61)
    await commit_durably(db)

    if not await _current_password_matches(hasher, reservation.password_hash, current_value):
        if reservation.own_lock is not None:
            # порог достигнут: блокировка уже зафиксирована, текущая сессия завершается
            await sessions.delete_by_id(db, actor.session_id)
            await commit_durably(db)
        raise Unprocessable(code=ErrorCode.invalid_current_password)

    try:
        _check_new_password(current_value, new_value)
    except Unprocessable:
        # текущий пароль верен: серия неудач прерывается, даже если новый пароль не принят
        await _reset_series(db, reservation, now)
        await commit_durably(db)
        raise

    new_hash = await hash_in_thread(hasher, new_value)
    changed = await db.execute(
        update(AppUser)
        .where(
            AppUser.id == actor.user_id,
            # заблокированный параллельно (между get_actor и этим UPDATE) пароль не меняет
            AppUser.is_blocked.is_(False),
            # параллельная смена или блокировка входа, поставленная пока проверялся пароль
            AppUser.password_hash == reservation.password_hash,
            series_not_locked_by_others(reservation, now),
        )
        .values(
            password_hash=new_hash,
            must_change_password=False,
            password_changed_at=now,
            failed_login_count=0,
            login_locked_until=None,
        )
        .returning(AppUser.id)
        .execution_options(synchronize_session=False)
    )
    if changed.scalar_one_or_none() is None:
        blocked = (
            await db.execute(select(AppUser.is_blocked).where(AppUser.id == actor.user_id))
        ).scalar_one_or_none()
        if blocked is not False:  # заблокирован (или удалён) параллельно: как у get_actor
            raise NotAuthenticated()
        raise Unprocessable(code=ErrorCode.invalid_current_password)
    await sessions.delete_all_for_user(db, actor.user_id, keep_id=actor.session_id)

    # ПОСЛЕДНИМ действием: после этой точки фиксаций до COMMIT запроса быть не должно
    _remove_initial_admin_file_after_commit(db, settings, actor.login)


def _check_new_password(current: str, new: str) -> None:
    """``password_reused`` -> недопустимые символы -> политика FR-52/FR-53 (422)."""
    if new == current:
        raise Unprocessable(code=ErrorCode.password_reused)
    try:
        new.encode("utf-8")
    except UnicodeEncodeError:
        # исключение не пробрасываем: его args содержат пароль (ревью T08)
        raise Unprocessable(code=ErrorCode.validation_error) from None
    try:
        validate_new_password(new)
    except PasswordPolicyError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


async def _reset_series(db: AsyncSession, reservation: AttemptReservation, now: datetime) -> None:
    await db.execute(
        update(AppUser)
        .where(AppUser.id == reservation.user_id, series_not_locked_by_others(reservation, now))
        .values(failed_login_count=0, login_locked_until=None)
        .execution_options(synchronize_session=False)
    )


def _remove_initial_admin_file_after_commit(
    db: AsyncSession, settings: Settings, login: str
) -> None:
    """Удаляет файл пароля первого ТА (FR-6) после успешного COMMIT текущей транзакции.

    Откат или сбой COMMIT оставляют файл на месте: пароль не сменён, файл ещё действителен.
    Сбой удаления смену не отменяет и наружу не выходит (в лог — только тип ошибки): пароль
    уже сменён, файл содержит недействительный пароль.
    """

    def remove(_session: object) -> None:
        try:
            remove_initial_admin_file_if_for(settings, login)
        except Exception as exc:
            logger.warning(
                "Не удалось удалить файл пароля первого администратора: %s", type(exc).__name__
            )

    event.listen(db.sync_session, "after_commit", remove, once=True)


async def _current_password_matches(
    hasher: PasswordHasher, stored_hash: str, password: str
) -> bool:
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return await verify_in_thread(hasher, stored_hash, password)
