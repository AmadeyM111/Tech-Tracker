"""Запрос сброса пароля по email (spec 007: FR-3, FR-4, FR-6..FR-9, FR-15; plan §4.3).

Токен — 32 случайных байта (base64url); в БД только sha256. Ответ не зависит от того, найден ли
пользователь (FR-6): любая ветка «письма нет» возвращает ``None``. Токен, email и ссылка не
попадают в события и логи. Транзакцию ведёт вызывающий слой; письмо отправляется им после COMMIT.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import delete, select, update

from app.core.errors import ErrorCode, FeatureDisabled, ResetTokenInvalid, Unprocessable
from app.core.mail import MailMessage
from app.core.security.passwords import (
    PasswordHasher,
    PasswordPolicyError,
    hash_in_thread,
    validate_new_password,
)
from app.domain.auth.models import PasswordResetToken
from app.domain.auth.reset_limits import register_request
from app.domain.auth.reset_mail import build_reset_mail
from app.domain.auth.service import remove_initial_admin_file_after_commit
from app.domain.auth.sessions import SessionStore
from app.domain.events.catalog import EventAction
from app.domain.events.writer import record_event
from app.domain.users.email import normalize_email
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.config import Settings

TOKEN_TTL: Final = timedelta(minutes=30)
TOKEN_BYTES: Final = 32


@dataclass(frozen=True)
class ResetPolicy:
    base_url: str
    limit_key: bytes = field(repr=False)


def new_token() -> tuple[str, bytes]:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hashlib.sha256(token.encode("ascii")).digest()


def token_hash(token: str) -> bytes | None:
    """sha256 токена; ``None`` для не-ASCII."""
    if not token.isascii():
        return None
    return hashlib.sha256(token.encode("ascii")).digest()


def reset_link(base_url: str, token: str) -> str:
    return f"{base_url}/password-reset/confirm#token={token}"


async def _find_active_user(db: AsyncSession, email: str) -> tuple[UUID, UUID] | None:
    """(user_id, workspace_id) активного пользователя; пространство — первое членство (PR-5)."""
    row = (
        await db.execute(
            select(AppUser.id, WorkspaceMember.workspace_id)
            .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
            .where(AppUser.email == email, AppUser.is_blocked.is_(False))
            .order_by(WorkspaceMember.created_at, WorkspaceMember.workspace_id)
            .limit(1)
        )
    ).one_or_none()
    return None if row is None else (row.id, row.workspace_id)


async def _issue_token(db: AsyncSession, user_id: UUID, now: datetime) -> str:
    await db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None)
        )
    )
    token, digest = new_token()
    db.add(
        PasswordResetToken(
            user_id=user_id, token_hash=digest, created_at=now, expires_at=now + TOKEN_TTL
        )
    )
    await db.flush()
    return token


async def request_reset(
    db: AsyncSession,
    policy: ResetPolicy | None,
    *,
    email: str,
    client_ip: str | None,
    now: datetime,
) -> MailMessage | None:
    """Письмо со ссылкой сброса либо ``None`` (лимит, неизвестный/невалидный адрес, блокировка)."""
    if policy is None:
        raise FeatureDisabled()
    normalized = normalize_email(email)
    allowed = await register_request(db, policy.limit_key, email=normalized, ip=client_ip, now=now)
    if not allowed or normalized is None:
        return None
    found = await _find_active_user(db, normalized)
    if found is None:
        return None
    user_id, workspace_id = found
    token = await _issue_token(db, user_id, now)
    await record_event(
        db,
        workspace_id=workspace_id,
        actor_id=None,
        action=EventAction.USER_PASSWORD_RESET_REQUESTED,
        entity_id=user_id,
    )
    return build_reset_mail(to=normalized, link=reset_link(policy.base_url, token), ttl=TOKEN_TTL)


async def _find_token_owner(
    db: AsyncSession, digest: bytes, now: datetime
) -> tuple[UUID, str, UUID] | None:
    """(user_id, login, workspace_id) владельца действующего токена; иначе ``None``."""
    row = (
        await db.execute(
            select(AppUser.id, AppUser.login, WorkspaceMember.workspace_id)
            .join(PasswordResetToken, PasswordResetToken.user_id == AppUser.id)
            .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
            .where(
                PasswordResetToken.token_hash == digest,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
                AppUser.is_blocked.is_(False),
            )
            .order_by(WorkspaceMember.created_at, WorkspaceMember.workspace_id)
            .limit(1)
        )
    ).one_or_none()
    return None if row is None else (row.id, row.login, row.workspace_id)


def _check_password(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise Unprocessable(code=ErrorCode.validation_error) from None
    try:
        validate_new_password(value)
    except PasswordPolicyError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


async def confirm_reset(
    db: AsyncSession,
    policy: ResetPolicy | None,
    hasher: PasswordHasher,
    sessions: SessionStore,
    settings: Settings,
    *,
    token: SecretStr,
    new_password: SecretStr,
    now: datetime,
) -> None:
    """Смена пароля по токену (FR-11..FR-14). Сначала токен, затем пароль (PR-20)."""
    if policy is None:
        raise FeatureDisabled()
    digest = token_hash(token.get_secret_value())
    owner = None if digest is None else await _find_token_owner(db, digest, now)
    if digest is None or owner is None:
        raise ResetTokenInvalid()
    user_id, login, workspace_id = owner
    password = new_password.get_secret_value()
    _check_password(password)  # до поглощения токена: ошибка пароля его не расходует
    new_hash = await hash_in_thread(hasher, password)

    used = await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == digest,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(PasswordResetToken.id)
        .execution_options(synchronize_session=False)
    )
    if used.scalar_one_or_none() is None:
        raise ResetTokenInvalid()
    changed = await db.execute(
        update(AppUser)
        .where(AppUser.id == user_id, AppUser.is_blocked.is_(False))
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
        raise ResetTokenInvalid()
    await db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None)
        )
    )
    await sessions.delete_all_for_user(db, user_id)
    await record_event(
        db,
        workspace_id=workspace_id,
        actor_id=user_id,
        action=EventAction.USER_PASSWORD_RESET_COMPLETED,
        entity_id=user_id,
    )
    # ПОСЛЕДНИМ действием: файл первого ТА удаляется после COMMIT
    remove_initial_admin_file_after_commit(db, settings, login)
