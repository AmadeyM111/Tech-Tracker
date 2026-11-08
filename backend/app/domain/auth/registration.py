"""Заявка на самостоятельную регистрацию (spec 019: FR-3, FR-3a, FR-4..FR-7, FR-10; plan §4.3, RG-1,
RG-5..RG-7, RG-9, RG-19).

Порядок проверок заявки — RG-7: пространство (RG-9) → лимит заявок с IP, попытка фиксируется до
разбора формы (RG-5, RG-6) → email → имя → фамилия → логин (формат, занятость) → пароль → Argon2
(во всех ветках после валидации) → занятость адреса в ``app_user`` (любой статус) → если адрес
свободен: удаление истёкших заявок, upsert по email (RG-1), письмо. Ответ при занятом и свободном
адресе одинаков (FR-4): функция возвращает ``None`` вместо письма. Модуль не пишет логов и не
включает ПДн, пароль и токен в тексты исключений (NFR-1).

Транзакцию запроса фиксирует ``get_db``; внутри модуля единственный COMMIT — ``commit_durably``
после записи попытки лимита, чтобы отказ 422 не отменял учёт попытки.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import commit_durably
from app.core.errors import ErrorCode, FeatureDisabled, RateLimited, Unprocessable
from app.core.mail import MailMessage
from app.core.security.passwords import (
    PasswordHasher,
    PasswordPolicyError,
    hash_in_thread,
    validate_new_password,
)
from app.domain.auth import password_reset
from app.domain.auth.models import RegistrationRequest
from app.domain.auth.provider import normalize_login
from app.domain.auth.registration_limits import Scope, register_attempt
from app.domain.auth.registration_mail import build_registration_mail
from app.domain.users.email import normalize_email
from app.domain.users.models import AppUser
from app.domain.users.names import normalize_person_name
from app.domain.workspaces.models import Workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

TOKEN_TTL: Final = timedelta(minutes=30)
ACCEPTED_DETAIL: Final = (
    "Если адрес можно использовать для регистрации, мы отправили на него письмо с "
    "подтверждением. Ссылка действует 30 минут."
)


@dataclass(frozen=True)
class RegistrationPolicy:
    base_url: str
    limit_key: bytes = field(repr=False)


@dataclass(frozen=True)
class RegistrationForm:
    email: str = field(repr=False)
    first_name: str = field(repr=False)
    last_name: str = field(repr=False)
    login: str = field(repr=False)
    password: SecretStr


@dataclass(frozen=True)
class _Checked:
    """Значения формы после нормализации (FR-3, FR-3a)."""

    email: str = field(repr=False)
    first_name: str = field(repr=False)
    last_name: str = field(repr=False)
    login: str = field(repr=False)  # ключ: normalize_login


def confirm_link(base_url: str, token: str) -> str:
    return f"{base_url}/register/confirm#token={token}"


async def _require_single_workspace(db: AsyncSession) -> None:
    """RG-9: пространство пилота — ровно одно; иначе 404 ``feature_disabled``."""
    ids = (await db.scalars(select(Workspace.id).limit(2))).all()
    if len(ids) != 1:
        raise FeatureDisabled()


async def _admit(
    db: AsyncSession, policy: RegistrationPolicy, client_ip: str | None, now: datetime
) -> None:
    """Лимит заявок с IP (RG-4, RG-5). Отказ — 429 без записи; допуск фиксируется сразу (RG-6).

    Без IP (``client_ip is None``) все такие заявки делят общую корзину ``"no-ip"``: лимит
    действует и для них, реальные адреса не затрагиваются (ревью R8-T09; требует подтверждения
    владельца, plan RG-5).
    """
    value = "no-ip" if client_ip is None else client_ip
    checks: list[tuple[Scope, str]] = [("request_ip", value)]
    if not await register_attempt(db, policy.limit_key, checks, now=now):
        raise RateLimited()
    await commit_durably(db)


def _check_password(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise Unprocessable(code=ErrorCode.validation_error) from None
    try:
        validate_new_password(value)
    except PasswordPolicyError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None


async def _login_taken(db: AsyncSession, login: str) -> bool:
    return (await db.execute(select(AppUser.id).where(AppUser.login == login))).first() is not None


async def _email_taken(db: AsyncSession, email: str) -> bool:
    """Адрес занят учётной записью любого статуса (FR-7)."""
    return (await db.execute(select(AppUser.id).where(AppUser.email == email))).first() is not None


async def _validate_form(db: AsyncSession, form: RegistrationForm) -> _Checked:
    """RG-7: email → имя → фамилия → логин (формат, занятость) → пароль. Не зависит от адреса."""
    email = normalize_email(form.email)
    if email is None:
        raise Unprocessable("Недопустимый email", code=ErrorCode.email_invalid)
    first = normalize_person_name(form.first_name)
    if first is None:
        raise Unprocessable("Недопустимое имя", code=ErrorCode.first_name_invalid)
    last = normalize_person_name(form.last_name)
    if last is None:
        raise Unprocessable("Недопустимая фамилия", code=ErrorCode.last_name_invalid)
    login = normalize_login(form.login)
    if login is None:
        raise Unprocessable("Недопустимый логин", code=ErrorCode.login_invalid)
    if await _login_taken(db, login):
        raise Unprocessable("Логин уже занят", code=ErrorCode.login_taken)
    _check_password(form.password.get_secret_value())
    return _Checked(email=email, first_name=first, last_name=last, login=login)


async def _purge_expired(db: AsyncSession, now: datetime) -> None:
    """NFR-9: истёкшие заявки удаляются при каждой принятой заявке."""
    await db.execute(delete(RegistrationRequest).where(RegistrationRequest.expires_at <= now))


async def _upsert_request(
    db: AsyncSession,
    *,
    checked: _Checked,
    login_display: str,
    password_hash: str,
    token_digest: bytes,
    now: datetime,
) -> None:
    """RG-1: заявка на тот же адрес заменяет токен, логин, имя, фамилию, хеш пароля и сроки."""
    stmt = pg_insert(RegistrationRequest).values(
        email=checked.email,
        login=checked.login,
        login_display=login_display,
        first_name=checked.first_name,
        last_name=checked.last_name,
        password_hash=password_hash,
        token_hash=token_digest,
        created_at=now,
        expires_at=now + TOKEN_TTL,
    )
    fresh = stmt.excluded
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["email"],
            set_={
                "login": fresh.login,
                "login_display": fresh.login_display,
                "first_name": fresh.first_name,
                "last_name": fresh.last_name,
                "password_hash": fresh.password_hash,
                "token_hash": fresh.token_hash,
                "created_at": fresh.created_at,
                "expires_at": fresh.expires_at,
            },
        )
    )


async def request_registration(
    db: AsyncSession,
    policy: RegistrationPolicy | None,
    hasher: PasswordHasher,
    *,
    form: RegistrationForm,
    client_ip: str | None,
    now: datetime,
) -> MailMessage | None:
    """Принимает заявку (FR-3..FR-7).

    Возвращает письмо для свободного адреса или ``None``, если адрес занят (вызывающий отвечает
    одинаково, FR-4). Ошибки: ``FeatureDisabled`` (политики нет или пространств не ровно одно),
    ``RateLimited``, ``Unprocessable`` с кодом поля или пароля.
    """
    if policy is None:
        raise FeatureDisabled()
    await _require_single_workspace(db)
    await _admit(db, policy, client_ip, now)
    checked = await _validate_form(db, form)
    password_hash = await hash_in_thread(hasher, form.password.get_secret_value())
    if await _email_taken(db, checked.email):
        return None
    await _purge_expired(db, now)
    token, digest = password_reset.new_token()
    await _upsert_request(
        db,
        checked=checked,
        login_display=form.login,
        password_hash=password_hash,
        token_digest=digest,
        now=now,
    )
    return build_registration_mail(
        to=checked.email, link=confirm_link(policy.base_url, token), ttl=TOKEN_TTL
    )
