"""Самостоятельная регистрация по email (spec 019: FR-3..FR-11; plan §4.3, RG-1, RG-5..RG-9, RG-19).

Заявка (``request_registration``), порядок — RG-7: пространство (RG-9) → лимит заявок с IP,
попытка фиксируется до разбора формы (RG-5, RG-6) → email → имя → фамилия (очистка до латиницы) →
логин генерируется сервером и выбирается первый свободный кандидат (v0.5) → пароль → Argon2 (во всех
ветках после валидации) → занятость адреса в ``app_user`` (любой статус) → если адрес свободен:
удаление истёкших заявок, upsert по email (RG-1), письмо.
Ответ при занятом и свободном адресе одинаков (FR-4): функция возвращает ``None`` вместо письма.

Подтверждение (``confirm_registration``), порядок — RG-8: пространство (RG-9, первым, как в RG-7) →
лимиты по IP и по ссылке (429) → заявка по хешу токена с ``expires_at > now`` и ``FOR UPDATE``
(иначе 400) → адрес занят: заявка удаляется, 400 → кандидаты логина (логин из заявки, затем
``база.N``): первый свободный вставляется в savepoint; при гонке (``ON CONFLICT (login)``) берётся
следующий; после ``CONFIRM_LOGIN_ATTEMPTS`` попыток — 409 → членство с ролью «Пользователь»
(решение владельца 2026-11-11) → удаление заявки → события ``user.self_registered`` и
``user.role_assigned`` (автор второго — «система»). Сессия не создаётся (AC-16). Возвращает
логин учётной записи.

Модуль не пишет логов и не включает ПДн, пароль и токен в тексты исключений (NFR-1). Транзакцию
запроса фиксирует ``get_db``. Внутри модуля ``commit_durably`` вызывается в местах RG-6: после
записи попытки лимита и перед ``raise`` в ветках отказа подтверждения, где заявка уже поглощена.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import chain, islice
from typing import TYPE_CHECKING, Final, Literal, NoReturn
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.db import commit_durably
from app.core.errors import (
    ErrorCode,
    FeatureDisabled,
    LoginTakenConflict,
    RateLimited,
    RegistrationTokenInvalid,
    Unprocessable,
)
from app.core.mail import MailMessage
from app.core.security.passwords import (
    PasswordHasher,
    PasswordPolicyError,
    hash_in_thread,
    validate_new_password,
)
from app.domain.access.roles import Role
from app.domain.auth import password_reset
from app.domain.auth.login_generation import login_base, login_candidates, name_slug
from app.domain.auth.models import RegistrationRequest
from app.domain.auth.registration_limits import Scope, register_attempt
from app.domain.auth.registration_mail import build_registration_mail
from app.domain.events.catalog import EventAction
from app.domain.events.writer import UserEventDetails, record_event
from app.domain.users.email import normalize_email
from app.domain.users.models import AppUser
from app.domain.users.names import normalize_person_name
from app.domain.workspaces.models import Workspace, WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

TOKEN_TTL: Final = timedelta(minutes=30)
ACCEPTED_DETAIL: Final = (
    "Если адрес можно использовать для регистрации, мы отправили на него письмо с "
    "подтверждением. Ссылка действует 30 минут."
)
# Попыток вставки учётной записи при подтверждении (логин из заявки и суффиксы), затем 409.
CONFIRM_LOGIN_ATTEMPTS: Final = 100


@dataclass(frozen=True)
class RegistrationPolicy:
    base_url: str
    limit_key: bytes = field(repr=False)


@dataclass(frozen=True)
class RegistrationForm:
    """Форма заявки (v0.5: логина нет, его выбирает сервер)."""

    email: str = field(repr=False)
    first_name: str = field(repr=False)
    last_name: str = field(repr=False)
    password: SecretStr


@dataclass(frozen=True)
class _Checked:
    """Значения формы после нормализации (FR-3, FR-3a) и выбранный логин (v0.5)."""

    email: str = field(repr=False)
    first_name: str = field(repr=False)
    last_name: str = field(repr=False)
    login: str = field(repr=False)


def confirm_link(base_url: str, token: str) -> str:
    return f"{base_url}/register/confirm#token={token}"


def _ip_value(client_ip: str | None) -> str:
    """Значение лимита по IP. Без IP такие запросы делят корзину ``"no-ip"`` (ревью R8-T09)."""
    return "no-ip" if client_ip is None else client_ip


def _token_value(raw: str) -> str:
    """Значение лимита по ссылке: hex SHA-256 токена (RG-4). Не-ASCII строки тоже учитываются."""
    return hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()


async def _single_workspace_id(db: AsyncSession) -> UUID:
    """RG-9: пространство пилота — ровно одно; иначе 404 ``feature_disabled``."""
    ids = (await db.scalars(select(Workspace.id).limit(2))).all()
    if len(ids) != 1:
        raise FeatureDisabled()
    return ids[0]


async def _admit(
    db: AsyncSession, policy: RegistrationPolicy, checks: list[tuple[Scope, str]], now: datetime
) -> None:
    """Лимиты (RG-4, RG-5, RG-8). Отказ — 429 без записи; допуск фиксируется сразу (RG-6)."""
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


async def _request_login(db: AsyncSession, base: str, email: str, now: datetime) -> str:
    """Первый свободный кандидат ``base``, ``base.2`` … (v0.5).

    Занят логин учётной записью (``app_user``) или активной заявкой с ДРУГИМ адресом. Своя заявка
    этого адреса не блокирует себя. Если заняты все кандидаты — ``login_taken`` (422).
    """
    candidates = list(login_candidates(base))
    taken = set(await db.scalars(select(AppUser.login).where(AppUser.login.in_(candidates))))
    taken |= set(
        await db.scalars(
            select(RegistrationRequest.login).where(
                RegistrationRequest.login.in_(candidates),
                RegistrationRequest.email != email,
                RegistrationRequest.expires_at > now,
            )
        )
    )
    for candidate in candidates:
        if candidate not in taken:
            return candidate
    raise Unprocessable("Логин уже занят", code=ErrorCode.login_taken)


async def _validate_form(db: AsyncSession, form: RegistrationForm, now: datetime) -> _Checked:
    """RG-7: email → имя → фамилия (латиница) → логин (выбор) → пароль. Не зависит от адреса."""
    email = normalize_email(form.email)
    if email is None:
        raise Unprocessable("Недопустимый email", code=ErrorCode.email_invalid)
    first = normalize_person_name(form.first_name)
    first_slug = name_slug(first) if first is not None else None
    if first is None or first_slug is None:
        raise Unprocessable("Недопустимое имя", code=ErrorCode.first_name_invalid)
    last = normalize_person_name(form.last_name)
    last_slug = name_slug(last) if last is not None else None
    if last is None or last_slug is None:
        raise Unprocessable("Недопустимая фамилия", code=ErrorCode.last_name_invalid)
    login = await _request_login(db, login_base(last_slug, first_slug), email, now)
    _check_password(form.password.get_secret_value())
    return _Checked(email=email, first_name=first, last_name=last, login=login)


async def _purge_expired(db: AsyncSession, now: datetime) -> None:
    """NFR-9: истёкшие заявки удаляются при каждой принятой заявке."""
    await db.execute(delete(RegistrationRequest).where(RegistrationRequest.expires_at <= now))


async def _upsert_request(
    db: AsyncSession,
    *,
    checked: _Checked,
    password_hash: str,
    token_digest: bytes,
    now: datetime,
) -> None:
    """RG-1: заявка на тот же адрес заменяет токен, логин, имя, фамилию, хеш пароля и сроки.

    Логин сгенерирован сервером и нижнего регистра, поэтому ``login_display`` равен ``login``.
    """
    stmt = pg_insert(RegistrationRequest).values(
        email=checked.email,
        login=checked.login,
        login_display=checked.login,
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
    await _single_workspace_id(db)
    await _admit(db, policy, [("request_ip", _ip_value(client_ip))], now)
    checked = await _validate_form(db, form, now)
    password_hash = await hash_in_thread(hasher, form.password.get_secret_value())
    if await _email_taken(db, checked.email):
        return None
    await _purge_expired(db, now)
    token, digest = password_reset.new_token()
    await _upsert_request(
        db,
        checked=checked,
        password_hash=password_hash,
        token_digest=digest,
        now=now,
    )
    return build_registration_mail(
        to=checked.email, link=confirm_link(policy.base_url, token), ttl=TOKEN_TTL
    )


async def _load_request(
    db: AsyncSession, digest: bytes | None, now: datetime
) -> RegistrationRequest:
    """Заявка по хешу токена с действующим сроком; строка блокируется до конца транзакции (RG-8)."""
    if digest is None:
        raise RegistrationTokenInvalid()
    found = (
        await db.scalars(
            select(RegistrationRequest)
            .where(RegistrationRequest.token_hash == digest, RegistrationRequest.expires_at > now)
            .with_for_update()
        )
    ).one_or_none()
    if found is None:
        raise RegistrationTokenInvalid()
    return found


async def _consume_and_fail(
    db: AsyncSession, request_id: UUID, error: RegistrationTokenInvalid | LoginTakenConflict
) -> NoReturn:
    """RG-6: отказ из-за занятости поглощает заявку; удаление фиксируется до ``raise``."""
    await db.execute(delete(RegistrationRequest).where(RegistrationRequest.id == request_id))
    await commit_durably(db)
    raise error


def _base_of(req: RegistrationRequest) -> str:
    """База логина из имени и фамилии заявки. Имена прошли проверку очистки при заявке (RG-7)."""
    last = name_slug(req.last_name)
    first = name_slug(req.first_name)
    if last is None or first is None:
        # Fail Fast: заявка с именем без латиницы не может появиться через ``request_registration``.
        raise RuntimeError("registration_request: имя без латинской части")
    return login_base(last, first)


async def _insert_row(
    db: AsyncSession, req: RegistrationRequest, login: str, now: datetime
) -> UUID | Literal["email", "login"]:
    """Одна попытка вставки учётной записи с логином ``login`` (AC-13). В savepoint, как в
    ``users/service.create_user``.

    Возвращает id новой записи; ``"login"`` — логин занят параллельной транзакцией
    (``ON CONFLICT (login) DO NOTHING`` не вставил строку); ``"email"`` — адрес занят параллельно
    (нарушение ``uq_app_user_email``). Текст ошибки БД не выводится.
    """
    user_id = uuid4()
    stmt = (
        pg_insert(AppUser)
        .values(
            id=user_id,
            login=login,
            login_display=login,
            email=req.email,
            first_name=req.first_name,
            last_name=req.last_name,
            self_registered=True,
            password_hash=req.password_hash,
            must_change_password=False,
            is_blocked=False,
            failed_login_count=0,
            password_changed_at=now,
            created_at=now,
            updated_at=now,
            created_by=None,
        )
        .on_conflict_do_nothing(index_elements=[AppUser.login])
        .returning(AppUser.id)
    )
    try:
        async with db.begin_nested():
            inserted = (await db.execute(stmt)).one_or_none()
    except IntegrityError as exc:
        if "uq_app_user_email" not in str(exc.orig):
            raise
        return "email"
    return user_id if inserted is not None else "login"


async def _create_account(
    db: AsyncSession, req: RegistrationRequest, now: datetime
) -> tuple[UUID, str] | Literal["email", "login"]:
    """Учётная запись с первым свободным логином (v0.5, RG-8).

    Кандидаты: логин из заявки, затем ``база.N`` (база пересчитана из имени и фамилии заявки).
    Логин, занятый в ``app_user``, пропускается; проигранная гонка (``ON CONFLICT``) тоже переводит
    к следующему кандидату. Не более ``CONFIRM_LOGIN_ATTEMPTS`` попыток. Возвращает ``(id, логин)``,
    ``"email"`` — адрес занят параллельно, ``"login"`` — все попытки заняты.
    """
    base = _base_of(req)
    candidates = islice(
        dict.fromkeys(chain([req.login], login_candidates(base))), CONFIRM_LOGIN_ATTEMPTS
    )
    for login in candidates:
        if await _login_taken(db, login):
            continue
        outcome = await _insert_row(db, req, login, now)
        if isinstance(outcome, UUID):
            return outcome, login
        if outcome == "email":
            return "email"
    return "login"


async def confirm_registration(
    db: AsyncSession,
    policy: RegistrationPolicy | None,
    *,
    token: SecretStr,
    client_ip: str | None,
    now: datetime,
) -> str:
    """Подтверждение регистрации по ссылке (FR-8, FR-9, FR-10, FR-11; RG-8).

    Порядок: политика → пространство (RG-9, первым, как в RG-7; неверный токен при нуле или двух
    пространствах даёт 404, а не 400) → лимиты по IP и по ссылке → заявка по токену → адрес →
    логин (первый свободный кандидат) → вставка → членство → удаление заявки → событие.

    Создаёт учётную запись ``self_registered=True`` с ролью «Пользователь» в единственном
    пространстве и пишет ``user.self_registered`` (актор и объект — новый пользователь) и
    ``user.role_assigned`` (актор — «система», ``role_from=None``, ``role_to=user``). Возвращает
    логин учётной записи (v0.5: он может отличаться от логина заявки, если тот занят). Ошибки:
    ``FeatureDisabled``,
    ``RateLimited`` (429), ``RegistrationTokenInvalid`` (400: токен не найден или истёк,
    адрес занят), ``LoginTakenConflict`` (409, только если все попытки заняты). Сессия не создаётся
    (AC-16).
    """
    if policy is None:
        raise FeatureDisabled()
    workspace_id = await _single_workspace_id(db)
    raw = token.get_secret_value()
    await _admit(
        db,
        policy,
        [("confirm_ip", _ip_value(client_ip)), ("confirm_token", _token_value(raw))],
        now,
    )
    req = await _load_request(db, password_reset.token_hash(raw), now)
    if await _email_taken(db, req.email):
        await _consume_and_fail(db, req.id, RegistrationTokenInvalid())
    outcome = await _create_account(db, req, now)
    if isinstance(outcome, str):
        race_error = RegistrationTokenInvalid() if outcome == "email" else LoginTakenConflict()
        await _consume_and_fail(db, req.id, race_error)
    user_id, login = outcome
    await db.execute(
        pg_insert(WorkspaceMember).values(
            workspace_id=workspace_id,
            user_id=user_id,
            role=Role.USER.value,  # владелец, 2026-11-11: сразу «Пользователь»
            created_at=now,
            updated_at=now,
            created_by=None,
        )
    )
    await db.execute(delete(RegistrationRequest).where(RegistrationRequest.id == req.id))
    await record_event(
        db,
        workspace_id=workspace_id,
        actor_id=user_id,
        action=EventAction.USER_SELF_REGISTERED,
        entity_id=user_id,
    )
    # Роль назначена в той же транзакции; событие как при назначении роли, автор — «система».
    await record_event(
        db,
        workspace_id=workspace_id,
        actor_id=None,
        action=EventAction.USER_ROLE_ASSIGNED,
        entity_id=user_id,
        details=UserEventDetails(role_from=None, role_to=Role.USER.value),
    )
    return login
