"""Вход через внешних провайдеров, привязка и отвязка (spec 029 FR-12…FR-21, FR-23; ADR-0026).

Состояние (``oauth_login_state``): ``state`` — 256 бит случайности, в БД SHA-256; PKCE-``verifier``
и срок 10 минут; запись одноразовая (удаляется первым же обращением к ``callback``, FR-13).

Любой отказ входа через провайдера наружу одинаков (``login_failed``): заблокированный
пользователь, закрытая регистрация, учётка с таким email без права автопривязки, лишняя
идентичность. Так экран не подтверждает существование учётки (FR-2, FR-17). Отличаются только
``cancelled`` (пользователь отказал у провайдера), ``provider_unavailable`` и ``state_invalid``.

Email провайдера, не подтверждающего адрес (Яндекс, VK ID), в ``app_user.email`` не пишется:
иначе злоумышленник мог бы занять чужой адрес в нашей системе (``external_identity.email_at_link``
хранит его только как справочное значение). Google с ``email_verified`` — пишется и допускает
автопривязку (FR-16). Токены провайдеров не хранятся (FR-21).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import islice
from typing import TYPE_CHECKING, Final, Literal
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.errors import ErrorCode, NotFound, Unprocessable
from app.core.security.passwords import (
    PasswordHasher,
    PasswordPolicyError,
    hash_in_thread,
    validate_new_password,
)
from app.domain.access.roles import Role
from app.domain.auth.external_models import ExternalIdentity, OauthLoginState
from app.domain.auth.external_providers import (
    ExternalProfile,
    ProviderConfig,
    ProviderError,
    ProviderName,
    authorize_url,
    callback_url,
    fetch_identity,
)
from app.domain.auth.login_generation import login_candidates, name_slug
from app.domain.auth.sessions import SessionStore
from app.domain.events.catalog import EventAction
from app.domain.events.writer import UserEventDetails, record_event
from app.domain.legal import consent as consent_domain
from app.domain.oauth.service import pkce_s256
from app.domain.users.models import AppUser
from app.domain.workspaces.models import Workspace, WorkspaceMember

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

STATE_TTL: Final = timedelta(minutes=10)
LOGIN_ATTEMPTS: Final = 100
ErrorKind = Literal[
    "login_failed", "provider_unavailable", "state_invalid", "cancelled", "already_linked"
]


@dataclass(frozen=True)
class CallbackRequest:
    """Параметры обратного вызова провайдера и сведения о текущей сессии браузера."""

    provider: str
    state: str | None = field(repr=False)
    code: str | None = field(repr=False)
    device_id: str | None
    provider_error: str | None
    session_user_id: UUID | None  # пользователь текущей сессии (для привязки)


@dataclass(frozen=True)
class CallbackOutcome:
    purpose: Literal["login", "link"]
    token: str | None = None
    remember: bool = False
    error: ErrorKind | None = None


def hash_state(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8", errors="surrogatepass")).digest()


async def start(
    db: AsyncSession,
    cfg: ProviderConfig,
    *,
    base_url: str,
    purpose: Literal["login", "link"],
    user_id: UUID | None,
    remember: bool,
    now: datetime,
    consent_version: str | None = None,
) -> str:
    """Создаёт состояние и возвращает адрес авторизации у провайдера (FR-13)."""
    await db.execute(delete(OauthLoginState).where(OauthLoginState.expires_at <= now))
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    db.add(
        OauthLoginState(
            state_hash=hash_state(state),
            provider=cfg.name,
            purpose=purpose,
            verifier=verifier,
            user_id=user_id if purpose == "link" else None,
            remember=remember and purpose == "login",
            pdn_consent_version=consent_version if purpose == "login" else None,
            created_at=now,
            expires_at=now + STATE_TTL,
        )
    )
    await db.flush()
    return authorize_url(
        cfg,
        redirect_uri=callback_url(base_url, cfg.name),
        state=state,
        challenge=pkce_s256(verifier),
    )


async def complete(
    db: AsyncSession,
    client: httpx.AsyncClient,
    providers: dict[ProviderName, ProviderConfig],
    sessions: SessionStore,
    req: CallbackRequest,
    *,
    base_url: str,
    registration_open: bool,
    now: datetime,
) -> CallbackOutcome:
    """Обратный вызов провайдера. Не бросает исключений: транзакция фиксирует сгоревший state."""
    row = None
    if req.state:
        row = (
            await db.execute(
                delete(OauthLoginState)
                .where(OauthLoginState.state_hash == hash_state(req.state))
                .returning(
                    OauthLoginState.provider,
                    OauthLoginState.purpose,
                    OauthLoginState.verifier,
                    OauthLoginState.user_id,
                    OauthLoginState.remember,
                    OauthLoginState.pdn_consent_version,
                    OauthLoginState.expires_at,
                )
            )
        ).one_or_none()
    if row is None or row.provider != req.provider or row.expires_at <= now:
        return CallbackOutcome(purpose="login", error="state_invalid")
    purpose: Literal["login", "link"] = "link" if row.purpose == "link" else "login"
    if req.provider_error or not req.code:
        return CallbackOutcome(purpose=purpose, error="cancelled")
    cfg = next((c for name, c in providers.items() if name == req.provider), None)
    if cfg is None:
        return CallbackOutcome(purpose=purpose, error="provider_unavailable")
    try:
        profile = await fetch_identity(
            client,
            cfg,
            code=req.code,
            verifier=row.verifier,
            redirect_uri=callback_url(base_url, req.provider),
            device_id=req.device_id,
            state=req.state,
        )
    except ProviderError:
        return CallbackOutcome(purpose=purpose, error="provider_unavailable")

    if purpose == "link":
        # привязка только из той же сессии, которая её начала (FR-18)
        if row.user_id is None or req.session_user_id != row.user_id:
            return CallbackOutcome(purpose="link", error="state_invalid")
        error = await _link(db, row.user_id, cfg, profile, now)
        return CallbackOutcome(purpose="link", error=error)

    token = await _login(
        db,
        sessions,
        cfg,
        profile,
        remember=row.remember,
        registration_open=registration_open,
        consent_version=row.pdn_consent_version,
        now=now,
    )
    if token is None:
        return CallbackOutcome(purpose="login", error="login_failed")
    return CallbackOutcome(purpose="login", token=token, remember=row.remember)


async def _active_identity(
    db: AsyncSession, provider: str, subject: str
) -> ExternalIdentity | None:
    return (
        await db.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == provider,
                ExternalIdentity.provider_subject == subject,
                ExternalIdentity.unlinked_at.is_(None),
            )
        )
    ).one_or_none()


async def _insert_identity(
    db: AsyncSession, user_id: UUID, cfg: ProviderConfig, profile: ExternalProfile, now: datetime
) -> bool:
    """Вставка в savepoint; ``False`` — гонка или лишняя идентичность того же провайдера."""
    try:
        async with db.begin_nested():
            db.add(
                ExternalIdentity(
                    id=uuid4(),
                    user_id=user_id,
                    provider=cfg.name,
                    provider_subject=profile.subject,
                    email_at_link=profile.email,
                    email_verified_by_provider=profile.email_verified,
                    linked_at=now,
                    last_used_at=now,
                )
            )
            await db.flush()
    except IntegrityError:
        return False
    return True


async def _link(
    db: AsyncSession, user_id: UUID, cfg: ProviderConfig, profile: ExternalProfile, now: datetime
) -> ErrorKind | None:
    existing = await _active_identity(db, cfg.name, profile.subject)
    if existing is not None:
        return None if existing.user_id == user_id else "already_linked"
    if not await _insert_identity(db, user_id, cfg, profile, now):
        return "already_linked"
    workspace_id = await _member_workspace(db, user_id)
    if workspace_id is not None:
        await record_event(
            db,
            workspace_id=workspace_id,
            actor_id=user_id,
            action=EventAction.USER_EXTERNAL_LINKED,
            entity_id=user_id,
            details=UserEventDetails(client=cfg.name),
        )
    return None


async def _member_workspace(db: AsyncSession, user_id: UUID) -> UUID | None:
    return (
        await db.execute(
            select(WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(WorkspaceMember.created_at, WorkspaceMember.workspace_id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def _accept_consent(
    db: AsyncSession, user_id: UUID, consent_version: str | None, now: datetime
) -> None:
    """021: существующий пользователь отметил согласие на /login до перехода к провайдеру.

    Пишется, только если версия в учётной записи другая (повторный вход событий не плодит).
    """
    if consent_version is None:
        return
    current = (
        await db.execute(select(AppUser.pdn_consent_version).where(AppUser.id == user_id))
    ).scalar_one()
    workspace_id = await _member_workspace(db, user_id)
    if current != consent_version and workspace_id is not None:
        await consent_domain.accept(
            db, user_id=user_id, workspace_id=workspace_id, version=consent_version, now=now
        )


async def _open_session(
    db: AsyncSession,
    sessions: SessionStore,
    user_id: UUID,
    cfg: ProviderConfig,
    *,
    remember: bool,
    now: datetime,
) -> str | None:
    """Сессия для действующей учётки (не заблокирована, есть членство); иначе ``None`` (FR-20)."""
    blocked = (
        await db.execute(select(AppUser.is_blocked).where(AppUser.id == user_id))
    ).scalar_one_or_none()
    workspace_id = await _member_workspace(db, user_id)
    if blocked is not False or workspace_id is None:
        return None
    return await sessions.create(
        db,
        user_id=user_id,
        workspace_id=workspace_id,
        now=now,
        remember=remember,
        auth_method=cfg.name,
    )


async def _login(
    db: AsyncSession,
    sessions: SessionStore,
    cfg: ProviderConfig,
    profile: ExternalProfile,
    *,
    remember: bool,
    registration_open: bool,
    consent_version: str | None,
    now: datetime,
) -> str | None:
    identity = await _active_identity(db, cfg.name, profile.subject)
    if identity is not None:
        token = await _open_session(db, sessions, identity.user_id, cfg, remember=remember, now=now)
        if token is not None:
            identity.last_used_at = now
            await _accept_consent(db, identity.user_id, consent_version, now)
        return token

    existing_id = None
    if profile.email is not None:
        existing_id = (
            await db.execute(select(AppUser.id).where(AppUser.email == profile.email))
        ).scalar_one_or_none()
    if existing_id is not None:
        # FR-16: автопривязка только при подтверждённом провайдером email (Google); иначе FR-17
        if not (cfg.auto_link_by_verified_email and profile.email_verified):
            return None
        if not await _insert_identity(db, existing_id, cfg, profile, now):
            return None
        token = await _open_session(db, sessions, existing_id, cfg, remember=remember, now=now)
        if token is not None:
            await _accept_consent(db, existing_id, consent_version, now)
        return token

    if not registration_open:  # Q-3: учётки создаются только при открытой регистрации 019
        return None
    user_id = await _create_account(db, cfg, profile, consent_version, now)
    if user_id is None:
        return None
    return await _open_session(db, sessions, user_id, cfg, remember=remember, now=now)


def _login_base(email: str | None) -> str:
    """База логина из локальной части email по правилам 019 (имени провайдер не отдаёт, NFR-2)."""
    slug = name_slug(email.partition("@")[0]) if email else None
    if not slug:
        return "user"
    return slug if len(slug) >= 3 else f"{slug}.user"


async def _create_account(
    db: AsyncSession,
    cfg: ProviderConfig,
    profile: ExternalProfile,
    consent_version: str | None,
    now: datetime,
) -> UUID | None:
    ids = (await db.scalars(select(Workspace.id).limit(2))).all()
    if len(ids) != 1:
        return None
    workspace_id = ids[0]
    stored_email = profile.email if profile.email_verified else None
    user_id = uuid4()
    for login in islice(login_candidates(_login_base(profile.email)), LOGIN_ATTEMPTS):
        taken = (await db.execute(select(AppUser.id).where(AppUser.login == login))).first()
        if taken is not None:
            continue
        stmt = (
            pg_insert(AppUser)
            .values(
                id=user_id,
                login=login,
                login_display=login,
                email=stored_email,
                self_registered=True,
                # 021: согласие, отмеченное до перехода к провайдеру
                pdn_consent_version=consent_version,
                pdn_consented_at=None if consent_version is None else now,
                password_hash=None,
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
        except IntegrityError:
            return None  # адрес занят параллельно
        if inserted is not None:
            break
    else:
        return None
    await db.execute(
        pg_insert(WorkspaceMember).values(
            workspace_id=workspace_id,
            user_id=user_id,
            role=Role.USER.value,
            created_at=now,
            updated_at=now,
            created_by=None,
        )
    )
    if not await _insert_identity(db, user_id, cfg, profile, now):
        return None
    await record_event(
        db,
        workspace_id=workspace_id,
        actor_id=user_id,
        action=EventAction.USER_SELF_REGISTERED,
        entity_id=user_id,
        details=UserEventDetails(client=cfg.name),
    )
    await record_event(
        db,
        workspace_id=workspace_id,
        actor_id=None,
        action=EventAction.USER_ROLE_ASSIGNED,
        entity_id=user_id,
        details=UserEventDetails(role_from=None, role_to=Role.USER.value),
    )
    if consent_version is not None:
        await record_event(
            db,
            workspace_id=workspace_id,
            actor_id=user_id,
            action=EventAction.USER_PDN_CONSENT_GIVEN,
            entity_id=user_id,
            details=UserEventDetails(version=consent_version),
        )
    return user_id


# --- профиль: список, отвязка, пароль -------------------------------------------------------


@dataclass(frozen=True)
class IdentityItem:
    id: UUID
    provider: str
    linked_at: datetime
    last_used_at: datetime | None
    can_unlink: bool


async def list_identities(db: AsyncSession, user_id: UUID) -> tuple[bool, list[IdentityItem]]:
    """``(есть ли пароль, активные привязки)``; ``can_unlink`` — FR-19."""
    has_password = (
        await db.execute(select(AppUser.password_hash.is_not(None)).where(AppUser.id == user_id))
    ).scalar_one()
    rows = (
        await db.scalars(
            select(ExternalIdentity)
            .where(ExternalIdentity.user_id == user_id, ExternalIdentity.unlinked_at.is_(None))
            .order_by(ExternalIdentity.linked_at)
        )
    ).all()
    can = has_password or len(rows) > 1
    return has_password, [
        IdentityItem(r.id, r.provider, r.linked_at, r.last_used_at, can) for r in rows
    ]


async def unlink(db: AsyncSession, user_id: UUID, identity_id: UUID, now: datetime) -> None:
    """Отвязка (FR-19): запрещена для последнего способа входа; чужая или отвязанная — 404."""
    # блокировка строки пользователя: две параллельные отвязки не уберут оба последних способа
    has_password = (
        await db.execute(
            select(AppUser.password_hash.is_not(None))
            .where(AppUser.id == user_id)
            .with_for_update()
        )
    ).scalar_one()
    ident = (
        await db.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.id == identity_id,
                ExternalIdentity.user_id == user_id,
                ExternalIdentity.unlinked_at.is_(None),
            )
        )
    ).one_or_none()
    if ident is None:
        raise NotFound()
    others = (
        await db.execute(
            select(
                exists().where(
                    ExternalIdentity.user_id == user_id,
                    ExternalIdentity.unlinked_at.is_(None),
                    ExternalIdentity.id != identity_id,
                )
            )
        )
    ).scalar_one()
    if not (has_password or others):
        raise Unprocessable(
            "Нельзя отвязать последний способ входа: сначала задайте пароль или привяжите "
            "другой аккаунт",
            code=ErrorCode.last_login_method,
        )
    ident.unlinked_at = now
    workspace_id = await _member_workspace(db, user_id)
    if workspace_id is not None:
        await record_event(
            db,
            workspace_id=workspace_id,
            actor_id=user_id,
            action=EventAction.USER_EXTERNAL_UNLINKED,
            entity_id=user_id,
            details=UserEventDetails(client=ident.provider),
        )


async def set_initial_password(
    db: AsyncSession,
    hasher: PasswordHasher,
    sessions: SessionStore,
    user_id: UUID,
    keep_session_id: bytes,
    password: SecretStr,
    now: datetime,
) -> None:
    """Q-6: пароль можно задать из профиля, только если его ещё нет; прочие сессии завершаются."""
    value = password.get_secret_value()
    try:
        value.encode("utf-8")
        validate_new_password(value)
    except UnicodeEncodeError:
        raise Unprocessable(code=ErrorCode.validation_error) from None
    except PasswordPolicyError as exc:
        raise Unprocessable(str(exc), code=exc.code) from None
    new_hash = await hash_in_thread(hasher, value)
    changed = await db.execute(
        update(AppUser)
        .where(AppUser.id == user_id, AppUser.password_hash.is_(None))
        .values(password_hash=new_hash, password_changed_at=now, must_change_password=False)
        .returning(AppUser.id)
        .execution_options(synchronize_session=False)
    )
    if changed.scalar_one_or_none() is None:
        raise Unprocessable("Пароль уже задан", code=ErrorCode.password_already_set)
    await sessions.delete_all_for_user(db, user_id, keep_id=keep_session_id)
