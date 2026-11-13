"""OAuth 2.1 authorization server (spec 028): регистрация, согласие, коды, токены, отзыв.

Только authorization code + PKCE S256, публичные клиенты (``token_endpoint_auth_method=none``).
Секреты (код, access ``gtat_``, refresh ``gtrt_``) — 256 бит случайности, в БД SHA-256.
Refresh ротируется при каждом использовании; повторное предъявление использованного refresh и
повторное использование кода отзывают весь грант. Все адреса (issuer, resource) строятся только
из ``PUBLIC_BASE_URL`` (за nginx и Caddy схема запроса — ``http``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import delete, func, select, update

from app.core.clock import utcnow
from app.core.errors import ErrorCode, NotFound, Unprocessable
from app.domain.access.roles import Actor, Role
from app.domain.events.catalog import EventAction
from app.domain.events.writer import UserEventDetails, record_event
from app.domain.oauth.models import (
    OauthAttempt,
    OauthClient,
    OauthCode,
    OauthGrant,
    OauthToken,
)
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ACCESS_PREFIX: Final = "gtat_"
REFRESH_PREFIX: Final = "gtrt_"
SCOPE: Final = "mcp"
SCOPES_SUPPORTED: Final = ("mcp", "offline_access")
ACCESS_TTL: Final = timedelta(hours=1)
REFRESH_TTL: Final = timedelta(days=90)  # владелец 2026-11-12: 90 суток, ротация
CODE_TTL: Final = timedelta(seconds=60)
CONTEXT_TTL: Final = timedelta(minutes=10)
MAX_ACTIVE_GRANTS: Final = 20
MAX_CLIENTS: Final = 500
MAX_REDIRECT_URIS: Final = 5
UNUSED_CLIENT_AGE: Final = timedelta(days=7)
REGISTER_PER_HOUR: Final = 20
TOKEN_PER_MINUTE: Final = 60
LAST_USED_GRANULARITY: Final = timedelta(minutes=1)
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")
_VERIFIER: Final = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
_CHALLENGE: Final = re.compile(r"[A-Za-z0-9\-_]{43}")
_IP_LITERAL: Final = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$|^\[.*\]$")


class OauthError(Exception):
    """Ошибка протокола: ``error`` (RFC 6749 §5.2) и описание; ``status`` — HTTP-код ответа."""

    def __init__(self, error: str, description: str, status: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status = status


class AuthorizeError(OauthError):
    """Ошибка запроса авторизации; ``redirect`` — можно ли вернуть её клиенту редиректом."""

    def __init__(self, error: str, description: str, *, redirect: bool) -> None:
        super().__init__(error, description)
        self.redirect = redirect


# --- токены и подписи ---------------------------------------------------------------------


def hash_secret(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8")).digest()


def new_secret(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def canonical_resource(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/mcp"


def issuer(base_url: str) -> str:
    return base_url.rstrip("/")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def pkce_s256(verifier: str) -> str:
    return _b64(hashlib.sha256(verifier.encode("ascii")).digest())


def ip_key_hash(key: bytes, scope: str, ip: str) -> bytes:
    return hmac.new(key, f"oauth:{scope}:{ip}".encode(), hashlib.sha256).digest()


# --- лимиты ---------------------------------------------------------------------------------


async def hit_limit(
    db: AsyncSession, key: bytes, scope: str, ip: str, *, limit: int, window: timedelta
) -> int | None:
    """Учитывает попытку; ``None`` — можно, иначе секунд до освобождения окна (``Retry-After``)."""
    now = utcnow()
    key_hash = ip_key_hash(key, scope, ip or "unknown")
    await db.execute(select(func.pg_advisory_xact_lock(0x6F617574, key_hash[0] << 8 | key_hash[1])))
    row = (
        await db.execute(
            select(func.count(), func.min(OauthAttempt.created_at)).where(
                OauthAttempt.scope == scope,
                OauthAttempt.key_hash == key_hash,
                OauthAttempt.created_at >= now - window,
            )
        )
    ).one()
    if row[0] >= limit and row[1] is not None:
        return max(1, int((row[1] + window - now).total_seconds()) + 1)
    db.add(OauthAttempt(scope=scope, key_hash=key_hash, created_at=now))
    await db.flush()
    return None


# --- регистрация клиентов (RFC 7591) -------------------------------------------------------


def parse_redirect_hosts(raw: str) -> frozenset[str]:
    """Хосты из ``OAUTH_REDIRECT_HOSTS``; пустой набор — «любой https-хост» (``*``)."""
    hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    return frozenset() if "*" in hosts else frozenset(hosts)


def validate_redirect_uri(uri: str, allowed_hosts: frozenset[str] = frozenset()) -> str:
    """Только ``https``, без userinfo и фрагмента, не IP и не ``localhost``; хост — из allowlist.

    ``allowed_hosts`` пуст — любой https-хост (настройка ``*``). Неизвестный хост — отказ
    ``invalid_redirect_uri`` (спека 030).
    """
    if not isinstance(uri, str) or len(uri) > 512 or _CONTROL.search(uri):
        raise OauthError("invalid_redirect_uri", "Недопустимый redirect_uri")
    parts = urlsplit(uri)
    host = (parts.hostname or "").lower()
    bad = (
        parts.scheme != "https"
        or not host
        or "@" in parts.netloc
        or parts.fragment
        or host == "localhost"
        or host.endswith(".localhost")
        or _IP_LITERAL.match(host) is not None
        or (allowed_hosts and host not in allowed_hosts)
    )
    if bad:
        raise OauthError("invalid_redirect_uri", "redirect_uri должен быть https-адресом клиента")
    return uri


def client_label(client_name: str | None, redirect_uri: str) -> str:
    """Название для экрана и ленты: ``client_name`` или домен (решение владельца 2026-11-12)."""
    name = (client_name or "").strip()
    return name if name else (urlsplit(redirect_uri).hostname or "client")


async def register_client(
    db: AsyncSession, body: dict[str, Any], allowed_hosts: frozenset[str]
) -> OauthClient:
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= MAX_REDIRECT_URIS:
        raise OauthError("invalid_redirect_uri", "redirect_uris: от 1 до 5 адресов")
    checked = [validate_redirect_uri(u, allowed_hosts) for u in uris]
    method = body.get("token_endpoint_auth_method", "none")
    if method != "none":
        raise OauthError(
            "invalid_client_metadata", "Поддерживается только token_endpoint_auth_method=none"
        )
    for field, allowed in (
        ("grant_types", {"authorization_code", "refresh_token"}),
        ("response_types", {"code"}),
    ):
        value = body.get(field)
        if value is not None and (
            not isinstance(value, list) or not value or not set(value) <= allowed
        ):
            raise OauthError("invalid_client_metadata", f"{field}: недопустимое значение")
    name = body.get("client_name")
    if name is not None:
        if not isinstance(name, str):
            raise OauthError("invalid_client_metadata", "client_name: строка")
        name = _CONTROL.sub("", name).strip()[:64] or None
    total = await db.scalar(select(func.count()).select_from(OauthClient))
    if (total or 0) >= MAX_CLIENTS:
        raise OauthError("temporarily_unavailable", "Регистрация временно недоступна", 503)
    client = OauthClient(
        client_id=secrets.token_urlsafe(24),
        client_name=name,
        redirect_uris=list(dict.fromkeys(checked)),
    )
    db.add(client)
    await db.flush()
    return client


# --- запрос авторизации и согласие ----------------------------------------------------------


@dataclass(frozen=True)
class AuthRequest:
    client: OauthClient
    redirect_uri: str
    code_challenge: str
    state: str | None
    scope: str
    resource: str

    @property
    def label(self) -> str:
        return client_label(self.client.client_name, self.redirect_uri)

    @property
    def redirect_host(self) -> str:
        return urlsplit(self.redirect_uri).hostname or ""


def redirect_with(redirect_uri: str, base_url: str, params: dict[str, str | None]) -> str:
    """``redirect_uri`` + параметры (+ ``iss`` — RFC 9207, во всех ответах авторизации)."""
    parts = urlsplit(redirect_uri)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query += [(k, v) for k, v in params.items() if v is not None]
    query.append(("iss", issuer(base_url)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


async def check_authorize_request(
    db: AsyncSession, base_url: str, params: dict[str, str]
) -> AuthRequest:
    """Проверка запроса: ошибки клиента/адреса — без редиректа, остальные — ``redirect=True``."""
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    client = (
        (await db.execute(select(OauthClient).where(OauthClient.client_id == client_id)))
        .scalars()
        .one_or_none()
        if client_id
        else None
    )
    if client is None:
        raise AuthorizeError("invalid_client", "Клиент не найден", redirect=False)
    if redirect_uri not in client.redirect_uris:
        raise AuthorizeError("invalid_request", "redirect_uri не зарегистрирован", redirect=False)
    if params.get("response_type") != "code":
        raise AuthorizeError("unsupported_response_type", "Нужен response_type=code", redirect=True)
    challenge = params.get("code_challenge", "")
    if params.get("code_challenge_method") != "S256" or not _CHALLENGE.fullmatch(challenge):
        raise AuthorizeError("invalid_request", "Нужен PKCE S256 (code_challenge)", redirect=True)
    resource = params.get("resource") or canonical_resource(base_url)
    if resource.rstrip("/") != canonical_resource(base_url):
        raise AuthorizeError(
            "invalid_target", "resource не принадлежит этому серверу", redirect=True
        )
    scope = params.get("scope") or SCOPE
    if not set(scope.split()) <= set(SCOPES_SUPPORTED):
        raise AuthorizeError("invalid_scope", "Недопустимый scope", redirect=True)
    state = params.get("state")
    return AuthRequest(
        client=client,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        state=state,
        scope=SCOPE,
        resource=canonical_resource(base_url),
    )


async def public_client_label(db: AsyncSession, client_id: str, redirect_uri: str) -> str | None:
    """Название клиента для публичного экрана входа; ``None``, если адрес возврата не его."""
    client = (
        (await db.execute(select(OauthClient).where(OauthClient.client_id == client_id)))
        .scalars()
        .one_or_none()
    )
    if client is None or redirect_uri not in client.redirect_uris:
        return None
    return client_label(client.client_name, redirect_uri)


def sign_context(key: bytes, req: AuthRequest, user_id: UUID, now: datetime) -> str:
    """Подписанный контекст запроса: решение нельзя применить к подменённым параметрам."""
    payload = {
        "c": req.client.client_id,
        "r": req.redirect_uri,
        "ch": req.code_challenge,
        "s": req.state,
        "u": str(user_id),
        "e": int((now + CONTEXT_TTL).timestamp()),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(key, b"oauth-ctx:" + body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def verify_context(key: bytes, token: str, user_id: UUID, now: datetime) -> dict[str, Any]:
    body, _, sig = token.partition(".")
    expected = hmac.new(key, b"oauth-ctx:" + body.encode(), hashlib.sha256).digest()
    try:
        ok = hmac.compare_digest(_unb64(sig), expected)
        payload = json.loads(_unb64(body)) if ok else None
    except (ValueError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict) or payload.get("u") != str(user_id):
        raise OauthError("invalid_request", "Запрос на доступ недействителен")
    if payload.get("e", 0) < int(now.timestamp()):
        raise OauthError("invalid_request", "Запрос на доступ устарел, начните подключение заново")
    return payload


async def grant_consent(db: AsyncSession, actor: Actor, base_url: str, ctx: dict[str, Any]) -> str:
    """«Разрешить»: грант + одноразовый код + аудит; возвращает адрес редиректа клиенту."""
    req = await check_authorize_request(
        db,
        base_url,
        {
            "client_id": ctx["c"],
            "redirect_uri": ctx["r"],
            "response_type": "code",
            "code_challenge": ctx["ch"],
            "code_challenge_method": "S256",
            **({"state": ctx["s"]} if ctx.get("s") else {}),
        },
    )
    await db.execute(select(AppUser.id).where(AppUser.id == actor.user_id).with_for_update())
    active = await db.scalar(
        select(func.count())
        .select_from(OauthGrant)
        .where(OauthGrant.user_id == actor.user_id, OauthGrant.revoked_at.is_(None))
    )
    if (active or 0) >= MAX_ACTIVE_GRANTS:
        raise Unprocessable(
            "Слишком много подключённых клиентов: отключите ненужные в «Доступе для агентов»",
            code=ErrorCode.limit_reached,
        )
    now = utcnow()
    grant = OauthGrant(
        workspace_id=actor.workspace_id,
        user_id=actor.user_id,
        client_id=req.client.id,
        scope=req.scope,
        resource=req.resource,
        created_at=now,
    )
    db.add(grant)
    await db.flush()
    code = new_secret()
    db.add(
        OauthCode(
            grant_id=grant.id,
            code_hash=hash_secret(code),
            redirect_uri=req.redirect_uri,
            code_challenge=req.code_challenge,
            created_at=now,
            expires_at=now + CODE_TTL,
        )
    )
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_OAUTH_GRANTED,
        entity_id=actor.user_id,
        details=UserEventDetails(client=req.label[:64]),
    )
    return redirect_with(req.redirect_uri, base_url, {"code": code, "state": req.state})


# --- token endpoint -------------------------------------------------------------------------


def refresh_ceiling(grant: OauthGrant, max_age: timedelta) -> datetime:
    """Момент, после которого refresh-токены гранта не действуют: выдача гранта + потолок."""
    return grant.created_at + max_age


async def _issue(
    db: AsyncSession, grant: OauthGrant, now: datetime, max_age: timedelta
) -> dict[str, Any]:
    access, refresh = new_secret(ACCESS_PREFIX), new_secret(REFRESH_PREFIX)
    db.add(
        OauthToken(
            grant_id=grant.id,
            kind="access",
            token_hash=hash_secret(access),
            created_at=now,
            expires_at=now + ACCESS_TTL,
        )
    )
    db.add(
        OauthToken(
            grant_id=grant.id,
            kind="refresh",
            token_hash=hash_secret(refresh),
            created_at=now,
            expires_at=min(now + REFRESH_TTL, refresh_ceiling(grant, max_age)),
        )
    )
    await db.flush()
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
        "refresh_token": refresh,
        "scope": grant.scope,
    }


async def _revoke_grant_rows(db: AsyncSession, grant_id: UUID, now: datetime) -> None:
    await db.execute(
        update(OauthGrant)
        .where(OauthGrant.id == grant_id, OauthGrant.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.execute(
        update(OauthToken)
        .where(OauthToken.grant_id == grant_id, OauthToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def exchange_code(
    db: AsyncSession, form: dict[str, str], base_url: str, max_age: timedelta = REFRESH_TTL
) -> dict[str, Any]:
    code = form.get("code", "")
    verifier = form.get("code_verifier", "")
    row = (
        await db.execute(
            select(OauthCode, OauthGrant, OauthClient)
            .join(OauthGrant, OauthGrant.id == OauthCode.grant_id)
            .join(OauthClient, OauthClient.id == OauthGrant.client_id)
            .where(OauthCode.code_hash == hash_secret(code))
            .with_for_update(of=OauthCode)
        )
    ).one_or_none()
    invalid = OauthError("invalid_grant", "Код недействителен")
    if row is None:
        raise invalid
    code_row, grant, client = row
    now = utcnow()
    if code_row.used_at is not None:  # повторное использование кода: отзыв всего выданного
        await _revoke_grant_rows(db, grant.id, now)
        raise invalid
    code_row.used_at = now  # одна попытка: при любой ошибке ниже код сгорает
    if grant.revoked_at is not None or code_row.expires_at <= now:
        raise invalid
    if form.get("client_id") not in (None, "", client.client_id):
        raise invalid
    if form.get("redirect_uri") != code_row.redirect_uri:
        raise invalid
    if not _VERIFIER.fullmatch(verifier) or not hmac.compare_digest(
        pkce_s256(verifier), code_row.code_challenge
    ):
        raise invalid
    resource = form.get("resource")
    if resource and resource.rstrip("/") != canonical_resource(base_url):
        raise OauthError("invalid_target", "resource не принадлежит этому серверу")
    return await _issue(db, grant, now, max_age)


async def exchange_refresh(
    db: AsyncSession, form: dict[str, str], max_age: timedelta = REFRESH_TTL
) -> dict[str, Any]:
    raw = form.get("refresh_token", "")
    invalid = OauthError("invalid_grant", "Refresh-токен недействителен")
    row = (
        await db.execute(
            select(OauthToken, OauthGrant, OauthClient)
            .join(OauthGrant, OauthGrant.id == OauthToken.grant_id)
            .join(OauthClient, OauthClient.id == OauthGrant.client_id)
            .where(OauthToken.token_hash == hash_secret(raw), OauthToken.kind == "refresh")
            .with_for_update(of=OauthToken)
        )
    ).one_or_none()
    if row is None:
        raise invalid
    token, grant, client = row
    now = utcnow()
    if token.used_at is not None:  # повтор уже использованного refresh: вероятная кража
        await _revoke_grant_rows(db, grant.id, now)
        raise invalid
    if token.revoked_at is not None or grant.revoked_at is not None:
        raise invalid
    if now >= refresh_ceiling(grant, max_age):  # потолок: дальше только новая авторизация (030)
        await _revoke_grant_rows(db, grant.id, now)
        raise invalid
    if token.expires_at <= now:
        raise invalid
    if form.get("client_id") not in (None, "", client.client_id):
        raise invalid
    token.used_at = now
    return await _issue(db, grant, now, max_age)


# --- проверка access-токена на /mcp ---------------------------------------------------------


@dataclass(frozen=True)
class OauthPrincipal:
    token_id: UUID
    grant_id: UUID
    user_id: UUID
    workspace_id: UUID
    login: str
    role: Role | None
    must_change_password: bool
    name: str


async def resolve_access(db: AsyncSession, raw: str, base_url: str) -> OauthPrincipal | None:
    """``gtat_`` → субъект, или ``None``: неизвестный, истёкший, отозванный, чужой audience."""
    if not raw.startswith(ACCESS_PREFIX):
        return None
    now = utcnow()
    row = (
        await db.execute(
            select(
                OauthToken.id,
                OauthGrant.id.label("grant_id"),
                OauthGrant.user_id,
                OauthGrant.workspace_id,
                OauthGrant.resource,
                OauthGrant.last_used_at,
                OauthClient.client_name,
                OauthClient.redirect_uris,
                AppUser.login_display,
                AppUser.is_blocked,
                AppUser.must_change_password,
                WorkspaceMember.role,
            )
            .join(OauthGrant, OauthGrant.id == OauthToken.grant_id)
            .join(OauthClient, OauthClient.id == OauthGrant.client_id)
            .join(AppUser, AppUser.id == OauthGrant.user_id)
            .join(
                WorkspaceMember,
                (WorkspaceMember.user_id == OauthGrant.user_id)
                & (WorkspaceMember.workspace_id == OauthGrant.workspace_id),
            )
            .where(
                OauthToken.token_hash == hash_secret(raw),
                OauthToken.kind == "access",
                OauthToken.revoked_at.is_(None),
                OauthToken.expires_at > now,
                OauthGrant.revoked_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None or row.is_blocked or row.resource.rstrip("/") != canonical_resource(base_url):
        return None
    if row.last_used_at is None or now - row.last_used_at >= LAST_USED_GRANULARITY:
        await db.execute(
            update(OauthGrant).where(OauthGrant.id == row.grant_id).values(last_used_at=now)
        )
    label = client_label(row.client_name, row.redirect_uris[0] if row.redirect_uris else "")
    return OauthPrincipal(
        token_id=row.id,
        grant_id=row.grant_id,
        user_id=row.user_id,
        workspace_id=row.workspace_id,
        login=row.login_display,
        role=None if row.role is None else Role(row.role),
        must_change_password=row.must_change_password,
        name=f"{label[:54]} (OAuth)",
    )


# --- гранты пользователя --------------------------------------------------------------------


@dataclass(frozen=True)
class GrantView:
    id: UUID
    client_name: str
    redirect_host: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


async def list_grants(db: AsyncSession, actor: Actor) -> list[GrantView]:
    rows = await db.execute(
        select(OauthGrant, OauthClient)
        .join(OauthClient, OauthClient.id == OauthGrant.client_id)
        .where(OauthGrant.user_id == actor.user_id, OauthGrant.workspace_id == actor.workspace_id)
        .order_by(OauthGrant.created_at.desc(), OauthGrant.id)
    )
    return [
        GrantView(
            id=g.id,
            client_name=client_label(c.client_name, c.redirect_uris[0] if c.redirect_uris else ""),
            redirect_host=urlsplit(c.redirect_uris[0]).hostname or "" if c.redirect_uris else "",
            created_at=g.created_at,
            last_used_at=g.last_used_at,
            revoked_at=g.revoked_at,
        )
        for g, c in rows.all()
    ]


async def revoke_grant(db: AsyncSession, actor: Actor, grant_id: UUID) -> None:
    """Отзывает грант пользователя (все токены сразу); повтор — без ошибки и без события."""
    row = (
        await db.execute(
            select(OauthGrant, OauthClient)
            .join(OauthClient, OauthClient.id == OauthGrant.client_id)
            .where(
                OauthGrant.id == grant_id,
                OauthGrant.user_id == actor.user_id,
                OauthGrant.workspace_id == actor.workspace_id,
            )
            .with_for_update(of=OauthGrant)
        )
    ).one_or_none()
    if row is None:
        raise NotFound()
    grant, client = row
    if grant.revoked_at is not None:
        return
    await _revoke_grant_rows(db, grant.id, utcnow())
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.USER_OAUTH_REVOKED,
        entity_id=actor.user_id,
        details=UserEventDetails(
            client=client_label(client.client_name, client.redirect_uris[0])[:64]
        ),
    )


async def revoke_by_token(db: AsyncSession, raw: str) -> None:
    """RFC 7009: отзыв по access- или refresh-токену; неизвестный токен — тихо (всегда 200)."""
    grant_id = await db.scalar(
        select(OauthToken.grant_id).where(OauthToken.token_hash == hash_secret(raw))
    )
    if grant_id is not None:
        await _revoke_grant_rows(db, grant_id, utcnow())


# --- обслуживание ---------------------------------------------------------------------------


async def purge(db: AsyncSession, now: datetime, *, dry_run: bool) -> dict[str, int]:
    """Неиспользуемые клиенты (> 7 суток, без грантов), просроченные коды/токены, старые попытки."""
    unused = select(OauthClient.id).where(
        OauthClient.created_at < now - UNUSED_CLIENT_AGE,
        ~select(OauthGrant.id).where(OauthGrant.client_id == OauthClient.id).exists(),
    )
    counts = {
        "oauth_clients_purged": await db.scalar(select(func.count()).select_from(unused.subquery()))
        or 0,
        "oauth_codes_purged": await db.scalar(
            select(func.count()).select_from(OauthCode).where(OauthCode.expires_at < now)
        )
        or 0,
        "oauth_tokens_purged": await db.scalar(
            select(func.count())
            .select_from(OauthToken)
            .where(OauthToken.expires_at < now - timedelta(days=1))
        )
        or 0,
    }
    if not dry_run:
        await db.execute(delete(OauthClient).where(OauthClient.id.in_(unused)))
        await db.execute(delete(OauthCode).where(OauthCode.expires_at < now))
        await db.execute(delete(OauthToken).where(OauthToken.expires_at < now - timedelta(days=1)))
        await db.execute(
            delete(OauthAttempt).where(OauthAttempt.created_at < now - timedelta(days=1))
        )
    return counts


def quote_param(value: str) -> str:
    return quote(value, safe="")
