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

import re
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Final

from fastapi import Depends, Request
from sqlalchemy import select

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.db import DbSession, commit_durably
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
    """Субъект запроса по cookie сессии; нет, истекла, заблокирован, нет членства → 401.

    Обычный запрос: ``resolve`` обновляет ``last_activity_at`` (или удаляет истёкшую строку), и
    сразу после него ``commit_durably`` фиксирует это. Причины (T16a, D-14): (1) строка
    ``user_session`` освобождается до обработчика; иначе администратор A держал бы её до конца
    запроса, ожидая advisory-блокировку, а администратор C, держа блокировку, ждал бы строку A
    (block/reset/revoke над работающим пользователем, ``POST /auth/password``) -> deadlock, 500;
    (2) активность и удаление истёкшей сессии не откатываются ``get_db`` при 4xx/401/5xx.
    Фоновый запрос (``GET`` с ``X-GT-Background: 1``) сессию не обновляет и ничего не
    фиксирует: итоговый COMMIT остаётся единственным. Дальнейшая работа запроса идёт в новой
    транзакции той же сессии БД (autobegin) и откатывается целиком при исключении (D-3);
    к строке сессии после фиксации запрос не обращается.
    """
    settings: Settings = request.app.state.settings
    store: SessionStore = request.app.state.session_store

    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise NotAuthenticated()

    background = _is_background(request)
    record = await store.resolve(db, token, now=utcnow(), background=background)
    if not background:
        # до возможного 401: удаление истёкшей строки не должно откатиться
        await commit_durably(db)
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

    Включает ``get_active_actor``, поэтому 401 и гейты 2-3 срабатывают раньше. Без аргументов
    гейт закрыл бы раздел для всех: это ошибка программиста, она проявляется при создании
    зависимости (не ``assert``: он исчезает под ``-O``).
    """
    if not caps:
        raise ValueError("require_capability() требует хотя бы одну возможность")

    async def dependency(actor: Annotated[Actor, Depends(get_active_actor)]) -> Actor:
        if not any(actor.can(cap) for cap in caps):
            raise Forbidden()
        return actor

    return dependency


# ``host[:port]``: имя из ASCII (punycode для IDN), ``[IPv6]``; без userinfo и пути.
_HOST_PORT_RE: Final = re.compile(
    r"(?P<host>[A-Za-z0-9._-]+|\[[0-9A-Fa-f:.]+\])(?::(?P<port>[0-9]{1,5}))?", re.ASCII
)
# Origin = ``scheme://host[:port]`` целиком: без userinfo, пути (в т.ч. ``/``), query, fragment.
_ORIGIN_RE: Final = re.compile(r"(?P<scheme>https?)://(?P<authority>[^/?#@\s]+)", re.ASCII)
_MAX_PORT: Final = 65535


def _host_port(authority: str, default_port: int | None) -> tuple[str, int | None] | None:
    """(host, port) из ``host[:port]``; порт по умолчанию подставляется; ``None`` — не разобрать."""
    match = _HOST_PORT_RE.fullmatch(authority)
    if match is None:
        return None
    port_text = match.group("port")
    if port_text is None:
        port = default_port
    else:
        port = int(port_text)
        if port > _MAX_PORT:
            return None
    return match.group("host").lower(), port


async def check_origin(request: Request) -> None:
    """D-16: для POST/PUT/PATCH/DELETE ``Origin`` с чужой схемой, хостом или портом → 403.

    ``Origin`` нет — проверка не применяется (защита — ``SameSite=Lax``); безопасные методы
    не проверяются; ``Referer`` не используется. Заголовок разбирается строго:
    ``scheme://host[:port]`` без userinfo, пути, query и fragment; ``null``, пустое значение и
    мусор, повторный заголовок ``Origin`` → 403. Схема Origin должна совпадать со схемой
    запроса (``request.url.scheme``; за прокси — из ``X-Forwarded-Proto`` при
    ``--proxy-headers``), порт по умолчанию (80 для http, 443 для https) определяется по
    схеме запроса.
    """
    if request.method not in _UNSAFE_METHODS:
        return
    origins = request.headers.getlist("origin")
    if not origins:
        return
    if len(origins) > 1:
        raise OriginMismatch()  # повторный заголовок: какое значение увидит браузер, неясно
    origin = origins[0]
    host_header = request.headers.get("host")
    match = _ORIGIN_RE.fullmatch(origin)
    if match is None or host_header is None:
        raise OriginMismatch()
    request_scheme = request.url.scheme
    if match.group("scheme") != request_scheme:
        raise OriginMismatch()
    default_port = _DEFAULT_PORTS.get(request_scheme)
    origin_hp = _host_port(match.group("authority"), default_port)
    own_hp = _host_port(host_header, default_port)
    if origin_hp is None or own_hp is None or origin_hp != own_hp:
        raise OriginMismatch()
