"""Зависимости запроса: субъект, гейты, проверка Origin (plan §4.5, §4.6, D-14, D-16).

Порядок проверок (plan §4.5): ``get_actor`` (401) → гейт одноразового пароля (403
``password_change_required``) → гейт «без роли» (403 ``no_role``) → гейт раздела
(``require_capability``, 403 ``forbidden``) до загрузки объекта. Роль, ``is_blocked``,
``must_change_password`` и членство читаются из БД на каждый запрос (FR-67): смена роли
действует со следующего запроса без повторного входа.

Сессия БД подключается только как ``DbSession``: ``get_actor``, ``require_capability`` и
обработчик делят одну сессию и одну транзакцию запроса.

Запрос по ключу агента (007 plan §4.7, PD-2, PD-3): любой заголовок ``Authorization`` означает
запрос по ключу — cookie не читается и не продлевается. Объём доступа по ключу —
``AGENT_OPERATIONS`` (app-level ``require_agent_scope``: вне перечня 403 ``forbidden`` без проверки
ключа, З-4); ключ проверяет ``get_actor`` (401 / 429).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Annotated, Any, Final

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
    TooManyRequests,
)
from app.core.security.api_keys import api_key_digest, is_api_key_format
from app.domain.access.roles import Actor, Capability, Role
from app.domain.api_keys.auth import RateLimited, authenticate_api_key
from app.domain.auth.sessions import SessionStore
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.engine import Row
    from sqlalchemy.ext.asyncio import AsyncSession

BACKGROUND_HEADER: Final = "X-GT-Background"

_UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_PORTS: Final = {"http": 80, "https": 443}

# 007 plan §4.7, PD-3: имена маршрутов, доступных по ключу агента (FR-17, FR-18…FR-27)
AGENT_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "me",
        "list_projects",
        "list_my_tasks",
        "list_project_tasks",
        "get_task",
        "create_task",
        "create_subtask",
        "update_task",
        "list_comments",
        "create_comment",
    }
)
_AUTHORIZATION: Final = "authorization"
_BEARER: Final = "bearer"


def _is_background(request: Request) -> bool:
    """Фоновый опрос (D-14): только ``GET`` с ``X-GT-Background: 1``; для остальных игнорируется."""
    return request.method == "GET" and request.headers.get(BACKGROUND_HEADER) == "1"


def presented_api_key(request: Request) -> str | None:
    """Ключ из ``Authorization: Bearer <ключ>`` (007 PD-2).

    ``None`` — заголовка ``Authorization`` нет. Иначе значение после «Bearer » (регистр схемы
    не важен); пустая строка — заголовков несколько, схема не Bearer или значение пустое либо
    содержит пробелы. Путь и параметры адреса не читаются.
    """
    values = request.headers.getlist(_AUTHORIZATION)
    if not values:
        return None
    if len(values) != 1:
        return ""
    parts = values[0].split()
    if len(parts) != 2 or parts[0].lower() != _BEARER:
        return ""
    return parts[1]


async def require_agent_scope(request: Request) -> None:
    """App-level (после ``check_origin``, 007 PD-3): есть ``Authorization`` и имя маршрута не в
    ``AGENT_OPERATIONS`` → 403 ``forbidden``. Ключ здесь не проверяется (З-4), БД не трогается."""
    if _AUTHORIZATION not in request.headers:
        return
    route = request.scope.get("route")
    if getattr(route, "name", None) not in AGENT_OPERATIONS:
        raise Forbidden()


async def get_actor(request: Request, db: DbSession) -> Actor:
    """Субъект запроса: есть ``Authorization`` → ``_actor_from_api_key``; иначе по cookie.

    Роль, ``is_blocked``, ``is_agent`` и членство читаются из БД на каждый запрос (FR-67,
    007 FR-14). При запросе по ключу cookie не читается: сессии и cookie не трогаются (FR-15).
    """
    raw = presented_api_key(request)
    if raw is not None:
        return await _actor_from_api_key(request, db, raw)
    return await _actor_from_cookie(request, db)


async def _load_member(
    db: AsyncSession, user_id: UUID, workspace_id: UUID
) -> Row[str, bool, bool, bool, str | None] | None:
    """Учётная запись и её членство в пространстве; ``None`` — нет записи или членства."""
    return (
        await db.execute(
            select(
                AppUser.login_display,
                AppUser.is_blocked,
                AppUser.must_change_password,
                AppUser.is_agent,
                WorkspaceMember.role,
            )
            .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
            .where(
                AppUser.id == user_id,
                WorkspaceMember.workspace_id == workspace_id,
            )
        )
    ).one_or_none()


async def _actor_from_cookie(request: Request, db: AsyncSession) -> Actor:
    """Субъект по cookie сессии; нет, истекла, заблокирован, нет членства → 401.

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

    row = await _load_member(db, record.user_id, record.workspace_id)
    if row is None or row.is_blocked:
        raise NotAuthenticated()

    actor = Actor(
        user_id=record.user_id,
        workspace_id=record.workspace_id,
        login=row.login_display,
        role=None if row.role is None else Role(row.role),
        must_change_password=row.must_change_password,
        session_id=record.id,
        is_agent=row.is_agent,
    )
    request.state.user_id = actor.user_id  # access-лог (FR-57)
    return actor


async def _actor_from_api_key(request: Request, db: AsyncSession, raw: str) -> Actor:
    """Субъект по ключу агента (007 plan §4.7, PD-5); любой отказ — один и тот же 401.

    Не по формату → 401 без обращения к БД. Иначе ``authenticate_api_key`` (лимит и
    ``last_used_at``) и сразу ``commit_durably`` — до разбора исхода: счётчик окна переживает
    401/429 и последующие 4xx. Затем: ключа нет/отозван/истёк → 401; сверх лимита → 429
    ``Retry-After``; учётной записи нет, нет членства в пространстве ключа, заблокирована или не
    агент → 401. Роль — из БД на каждый запрос. Сессии и cookie не трогаются (FR-15); ни секрет,
    ни дайджест не попадают в исключения и логи.
    """
    if not is_api_key_format(raw):
        raise NotAuthenticated()
    digest = api_key_digest(raw)
    outcome = await authenticate_api_key(db, digest, now=utcnow())
    await commit_durably(db)
    if outcome is None:
        raise NotAuthenticated()
    if isinstance(outcome, RateLimited):
        raise TooManyRequests(retry_after=outcome.retry_after)

    row = await _load_member(db, outcome.user_id, outcome.workspace_id)
    if row is None or row.is_blocked or not row.is_agent:
        raise NotAuthenticated()

    actor = Actor(
        user_id=outcome.user_id,
        workspace_id=outcome.workspace_id,
        login=row.login_display,
        role=None if row.role is None else Role(row.role),
        must_change_password=False,
        session_id=None,
        api_key_id=outcome.key_id,
        is_agent=True,
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
