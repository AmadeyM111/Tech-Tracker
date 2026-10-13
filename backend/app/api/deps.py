"""Зависимости запроса: субъект, гейты, проверка Origin (plan §4.5, §4.6, D-14, D-16).

Порядок проверок (plan §4.5): ``get_actor`` (401) → гейт одноразового пароля (403
``password_change_required``) → гейт «без роли» (403 ``no_role``) → гейт раздела
(``require_capability``, 403 ``forbidden``) до загрузки объекта. Роль, ``is_blocked``,
``must_change_password`` и членство читаются из БД на каждый запрос (FR-67): смена роли
действует со следующего запроса без повторного входа.

Сессия БД подключается только как ``DbSession``: ``get_actor``, ``require_capability`` и
обработчик делят одну сессию и одну транзакцию запроса.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Final
from urllib.parse import urlsplit

from fastapi import Depends, Request
from sqlalchemy import select

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.db import DbSession
from app.core.errors import (
    Forbidden,
    NoRole,
    NotAuthenticated,
    OriginMismatch,
    PasswordChangeRequired,
)
from app.domain.access.roles import Actor, Capability, Role
from app.domain.auth.sessions import SessionStore
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

BACKGROUND_HEADER: Final = "X-GT-Background"

_UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_PORTS: Final = {"http": 80, "https": 443}


def _is_background(request: Request) -> bool:
    """Фоновый опрос (D-14): только ``GET`` с ``X-GT-Background: 1``; для остальных игнорируется."""
    return request.method == "GET" and request.headers.get(BACKGROUND_HEADER) == "1"


async def get_actor(request: Request, db: DbSession) -> Actor:
    """Субъект запроса по cookie сессии; нет, истекла, заблокирован, нет членства → 401."""
    settings: Settings = request.app.state.settings
    store: SessionStore = request.app.state.session_store

    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise NotAuthenticated()

    record = await store.resolve(db, token, now=utcnow(), background=_is_background(request))
    if record is None:
        raise NotAuthenticated()

    row = (
        await db.execute(
            select(
                AppUser.login,
                AppUser.is_blocked,
                AppUser.must_change_password,
                WorkspaceMember.role,
            )
            .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
            .where(
                AppUser.id == record.user_id,
                WorkspaceMember.workspace_id == record.workspace_id,
            )
        )
    ).one_or_none()
    if row is None or row.is_blocked:
        raise NotAuthenticated()

    actor = Actor(
        user_id=record.user_id,
        workspace_id=record.workspace_id,
        login=row.login,
        role=None if row.role is None else Role(row.role),
        must_change_password=row.must_change_password,
        session_id=record.id,
    )
    request.state.user_id = actor.user_id  # access-лог (FR-57)
    return actor


async def get_active_actor(actor: Annotated[Actor, Depends(get_actor)]) -> Actor:
    """Гейты 2-3: одноразовый пароль (FR-55), затем «без роли» (FR-66)."""
    if actor.must_change_password:
        raise PasswordChangeRequired()
    if actor.role is None:
        raise NoRole()
    return actor


def require_capability(*caps: Capability) -> Callable[..., Coroutine[Any, Any, Actor]]:
    """Гейт раздела: достаточно любой из ``caps``; иначе 403 ``forbidden``.

    Включает ``get_active_actor``, поэтому 401 и гейты 2-3 срабатывают раньше.
    """

    async def dependency(actor: Annotated[Actor, Depends(get_active_actor)]) -> Actor:
        if not any(actor.can(cap) for cap in caps):
            raise Forbidden()
        return actor

    return dependency


def _host_port(netloc: str, default_port: int | None) -> tuple[str, int | None] | None:
    """(host, port) из ``host[:port]``; порт по умолчанию подставляется; ``None`` — не разобрать."""
    try:
        parsed = urlsplit("//" + netloc)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        return None
    if host is None:
        return None
    return host, port if port is not None else default_port


async def check_origin(request: Request) -> None:
    """D-16: для POST/PUT/PATCH/DELETE ``Origin`` с чужим хостом:портом → 403.

    ``Origin`` нет — проверка не применяется (защита — ``SameSite=Lax``); безопасные методы
    не проверяются; ``Referer`` не используется. Отсутствующий порт равен порту по умолчанию
    схемы ``Origin`` (80 для http, 443 для https).
    """
    if request.method not in _UNSAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None:
        return
    host_header = request.headers.get("host")
    try:
        parsed = urlsplit(origin)
    except ValueError:
        raise OriginMismatch() from None
    # Origin: ``scheme://host[:port]``; ``null`` и мусор не имеют ни схемы, ни хоста
    if not parsed.scheme or not parsed.netloc or host_header is None:
        raise OriginMismatch()
    default_port = _DEFAULT_PORTS.get(parsed.scheme)
    origin_hp = _host_port(parsed.netloc, default_port)
    own_hp = _host_port(host_header, default_port)
    if origin_hp is None or own_hp is None or origin_hp != own_hp:
        raise OriginMismatch()
