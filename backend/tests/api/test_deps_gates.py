"""T12: зависимости запроса и гейты (plan §4.5 «Порядок проверок», §4.6, D-14, D-16).

AC-4 (401 без аутентификации), AC-11 / FR-45a (403 по разделу до 404), AC-26 / AC-39
(гейты MANAGE_ACCOUNTS / ASSIGN_ROLES), AC-74 / AC-75 (роль NULL, смена роли без перелогина),
AC-79 (фоновые запросы не продлевают сессию), FR-7, FR-9, FR-10, FR-66, FR-67, D-16.

Модули ``app.api.deps`` и ``app.domain.access.roles`` импортируются внутри функций: пока их
нет, тесты падают с ImportError, а не ошибкой сбора. Поэтому в файле НЕТ
``from __future__ import annotations``: FastAPI разбирает аннотации временных обработчиков
(локальные имена) при определении функции.

Приложение — настоящий ``create_app`` с запущенным lifespan (чтобы проверить, что lifespan
собрал ``SessionStore``); затем ``app.state.sessionmaker`` подменяется фабрикой сессий
внешней транзакции теста (откат). Временные роуты добавляются через ``add_api_route`` на
приложение: так на них действует и app-level зависимость ``check_origin`` (D-16).
Токены сессий создаёт тест своим ``SessionStore`` с ключом ``ensure_secret_key(settings)``
(тот же ключ, что и у приложения: файл в ``data_dir``). Имена атрибутов ``app.state`` plan не
фиксирует, поэтому экземпляры ищутся по типу.
"""

import ast
import hashlib
import hmac
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.secrets import ensure_secret_key
from tests.conftest import FIXED_NOW
from tests.factories import PLACEHOLDER_HASH, UserRow, get_table, make_user

APP_DIR = Path(__file__).resolve().parents[2] / "app"
RANDOM_ID = "6f9619ff-8b86-4d11-b42d-00c04fc964ff"
ALL_ROLES = ("tech_admin", "business_admin", "mixed", "user")

# Явная матрица (дублирует tests/unit/test_role_matrix.py: HTTP-слой проверяется независимо).
HOLDERS: dict[str, frozenset[str]] = {
    "MANAGE_ACCOUNTS": frozenset({"tech_admin", "mixed"}),
    "ASSIGN_ROLES": frozenset({"tech_admin", "mixed"}),
    "VIEW_AUDIT": frozenset({"tech_admin", "mixed"}),
    "BUSINESS_ACCESS": frozenset({"business_admin", "mixed", "user"}),
    "PROJECT_CREATE": frozenset({"business_admin", "mixed"}),
    "PROJECT_MANAGE_ANY": frozenset({"mixed"}),
    "TASK_ASSIGN_OTHERS": frozenset({"business_admin", "mixed"}),
    "LABELS_MANAGE": frozenset({"business_admin", "mixed"}),
    "CRM_READ": frozenset({"business_admin", "mixed"}),
    "CRM_WRITE": frozenset({"business_admin", "mixed"}),
    "PIPELINE_MANAGE": frozenset({"business_admin", "mixed"}),
}
GATE_CELLS = [(r, c) for c in HOLDERS for r in ALL_ROLES]


# --- окружение теста ---------------------------------------------------------------------


class CountingSessionmaker:
    """Обёртка над фабрикой сессий: считает, сколько сессий открыто за запрос."""

    def __init__(self, inner: async_sessionmaker[AsyncSession]) -> None:
        self.inner = inner
        self.opened = 0

    def __call__(self, *args: Any, **kwargs: Any) -> AsyncSession:
        self.opened += 1
        return self.inner(*args, **kwargs)


@dataclass
class Env:
    app: FastAPI
    client: httpx.AsyncClient
    db: AsyncSession
    settings: Settings
    clock: FixedClock
    sessionmaker: CountingSessionmaker
    handler_calls: list[str] = field(default_factory=list)

    def store(self) -> Any:
        from app.domain.auth.sessions import SessionStore

        return SessionStore(
            ensure_secret_key(self.settings),
            idle_timeout=self.settings.session_idle_timeout,
            absolute_timeout=self.settings.session_absolute_timeout,
        )

    async def login_as(
        self,
        role: str | None,
        *,
        must_change: bool = False,
        blocked: bool = False,
        now: datetime = FIXED_NOW,
        user: UserRow | None = None,
    ) -> tuple[UserRow, str]:
        """Пользователь с ролью + действующая сессия; возвращает (строка, сырой токен)."""
        if user is None:
            user = await make_user(
                self.db,
                role=role,
                must_change_password=must_change,
                blocked=blocked,
                password_hash=PLACEHOLDER_HASH,
            )
        token = await self.store().create(
            self.db, user_id=user.id, workspace_id=user.workspace_id, now=now
        )
        return user, token

    def cookie(self, token: str) -> dict[str, str]:
        return {"Cookie": f"{self.settings.cookie_name}={token}"}

    async def set_member_role(self, user: UserRow, role: str | None) -> None:
        table = get_table("workspace_member")
        await self.db.execute(table.update().where(table.c.user_id == user.id).values(role=role))

    async def set_user_flags(self, user: UserRow, **values: Any) -> None:
        table = get_table("app_user")
        await self.db.execute(table.update().where(table.c.id == user.id).values(**values))

    async def last_activity(self, token: str) -> datetime:
        table = get_table("user_session")
        row = (
            await self.db.execute(
                select(table.c.last_activity_at).where(table.c.id == self.store().token_id(token))
            )
        ).scalar_one()
        assert isinstance(row, datetime)
        return row


def _add_routes(app: FastAPI, calls: list[str]) -> None:
    """Временные роуты поверх публичного интерфейса ``app.api.deps`` (plan §4.6)."""
    from app.api.deps import get_active_actor, get_actor, require_capability
    from app.core.db import DbSession
    from app.core.errors import NotFound
    from app.domain.access.roles import Actor, Capability

    def describe(actor: Actor, request: Request) -> dict[str, Any]:
        return {
            "user_id": str(actor.user_id),
            "workspace_id": str(actor.workspace_id),
            "login": actor.login,
            "role": None if actor.role is None else str(actor.role),
            "must_change_password": actor.must_change_password,
            "session_id": actor.session_id.hex(),
            "state_user_id": str(getattr(request.state, "user_id", None)),
        }

    async def whoami(actor: Annotated[Actor, Depends(get_actor)], request: Request) -> Any:
        calls.append("whoami")
        return describe(actor, request)

    async def active(actor: Annotated[Actor, Depends(get_active_actor)], request: Request) -> Any:
        calls.append("active")
        return describe(actor, request)

    app.add_api_route("/_t/whoami", whoami, methods=["GET", "POST"])
    app.add_api_route("/_t/active", active, methods=["GET"])

    for cap in Capability:

        async def gated(actor: Annotated[Actor, Depends(get_active_actor)]) -> Any:
            calls.append("gated")
            return {"ok": True}

        app.add_api_route(
            f"/_t/cap/{cap.name}",
            gated,
            methods=["GET"],
            dependencies=[Depends(require_capability(cap))],
        )

    async def any_of() -> Any:
        calls.append("any_of")
        return {"ok": True}

    app.add_api_route(
        "/_t/any-cap",
        any_of,
        methods=["GET"],
        dependencies=[Depends(require_capability(Capability.CRM_READ, Capability.VIEW_AUDIT))],
    )

    # Раздел «учётные записи»: гейт раздела до загрузки объекта.
    admin_dependency = [Depends(require_capability(Capability.MANAGE_ACCOUNTS))]

    async def admin_item(item_id: uuid.UUID) -> Any:
        calls.append("admin_item")
        raise NotFound("нет такого объекта")

    class ItemBody(BaseModel):
        name: str = Field(min_length=3)

    async def admin_create(body: ItemBody) -> Any:
        calls.append("admin_create")
        return {"name": body.name}

    app.add_api_route(
        "/_t/admin/items/{item_id}", admin_item, methods=["GET"], dependencies=admin_dependency
    )
    app.add_api_route(
        "/_t/admin/items", admin_create, methods=["POST"], dependencies=admin_dependency
    )

    async def public_post() -> Any:
        calls.append("public_post")
        return {"ok": True}

    app.add_api_route("/_t/public", public_post, methods=["POST", "PUT", "PATCH", "DELETE", "GET"])

    # один запрос — одна сессия БД: get_actor, require_capability и обработчик делят DbSession
    async def one_session(
        actor: Annotated[Actor, Depends(require_capability(Capability.BUSINESS_ACCESS))],
        db: DbSession,
    ) -> Any:
        value = (await db.execute(select(1))).scalar_one()
        return {"value": value}

    app.add_api_route("/_t/one-session", one_session, methods=["GET"])

    # заметка ревью T05: зависимость с yield поверх DbSession объявляется со scope="function"
    async def yielding(db: DbSession) -> AsyncIterator[int]:
        yield (await db.execute(select(1))).scalar_one()

    async def with_yield(
        actor: Annotated[Actor, Depends(get_active_actor)],
        value: Annotated[int, Depends(yielding, scope="function")],
    ) -> Any:
        return {"value": value}

    app.add_api_route("/_t/with-yield", with_yield, methods=["GET"])


@pytest_asyncio.fixture
async def env(
    app: FastAPI,
    settings: Settings,
    fixed_clock: FixedClock,
    db: AsyncSession,
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Env]:
    calls: list[str] = []
    _add_routes(app, calls)
    counting = CountingSessionmaker(db_sessionmaker)
    async with app.router.lifespan_context(app):
        app.state.sessionmaker = counting  # запросы идут в транзакции теста (откат)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield Env(
                app=app,
                client=c,
                db=db,
                settings=settings,
                clock=fixed_clock,
                sessionmaker=counting,
                handler_calls=calls,
            )


def _code(response: httpx.Response) -> str:
    body = response.json()
    assert isinstance(body, dict)
    return str(body["code"])


# --- get_actor: 401 ----------------------------------------------------------------------


async def test_ac4_fr7_no_cookie_is_401_not_authenticated(env: Env) -> None:
    response = await env.client.get("/_t/whoami")
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"
    assert env.handler_calls == []


async def test_ac4_empty_cookie_value_is_401(env: Env) -> None:
    response = await env.client.get("/_t/whoami", headers={"Cookie": "gt_session="})
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


async def test_ac4_unknown_token_is_401(env: Env) -> None:
    await env.login_as("user")
    response = await env.client.get(
        "/_t/whoami", headers=env.cookie("not-a-real-token-0123456789abcdef")
    )
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


async def test_ac4_idle_expired_session_is_401(env: Env) -> None:
    _, token = await env.login_as("user", now=FIXED_NOW - timedelta(hours=9))
    response = await env.client.get("/_t/whoami", headers=env.cookie(token))
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


async def test_ac4_absolute_expired_session_is_401(env: Env) -> None:
    user, token = await env.login_as("user", now=FIXED_NOW - timedelta(days=8))
    await env.db.execute(
        get_table("user_session")
        .update()
        .where(get_table("user_session").c.id == env.store().token_id(token))
        .values(last_activity_at=FIXED_NOW - timedelta(minutes=1))
    )
    response = await env.client.get("/_t/whoami", headers=env.cookie(token))
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


async def test_fr62_blocked_user_session_is_401(env: Env) -> None:
    _, token = await env.login_as("user", blocked=True)
    response = await env.client.get("/_t/whoami", headers=env.cookie(token))
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


async def test_fr62_user_blocked_after_login_loses_session_on_next_request(env: Env) -> None:
    user, token = await env.login_as("user")
    assert (await env.client.get("/_t/whoami", headers=env.cookie(token))).status_code == 200
    await env.set_user_flags(user, is_blocked=True, blocked_at=FIXED_NOW)
    response = await env.client.get("/_t/whoami", headers=env.cookie(token))
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


async def test_ac4_user_without_membership_is_401(env: Env) -> None:
    user, token = await env.login_as("user")
    table = get_table("workspace_member")
    await env.db.execute(table.delete().where(table.c.user_id == user.id))
    response = await env.client.get("/_t/whoami", headers=env.cookie(token))
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


# --- get_actor: Actor и состояние запроса -------------------------------------------------


async def test_get_actor_returns_actor_from_db_and_sets_request_state(env: Env) -> None:
    user, token = await env.login_as("business_admin")
    response = await env.client.get("/_t/whoami", headers=env.cookie(token))
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["workspace_id"] == str(user.workspace_id)
    assert body["login"] == user.login
    assert body["role"] == "business_admin"
    assert body["must_change_password"] is False
    assert body["session_id"] == env.store().token_id(token).hex()
    # request.state.user_id выставлен (access-лог берёт его из scope["state"])
    assert body["state_user_id"] == str(user.id)


async def test_get_actor_role_none_is_actor_with_role_none(env: Env) -> None:
    _, token = await env.login_as(None)
    body = (await env.client.get("/_t/whoami", headers=env.cookie(token))).json()
    assert body["role"] is None


async def test_gates_2_3_not_applied_to_get_actor_only_routes(env: Env) -> None:
    """Роуты только с get_actor (смена пароля, выход) доступны при одноразовом пароле и без роли."""
    _, t_change = await env.login_as("user", must_change=True)
    _, t_norole = await env.login_as(None)
    for token in (t_change, t_norole):
        assert (await env.client.get("/_t/whoami", headers=env.cookie(token))).status_code == 200
        assert (await env.client.post("/_t/whoami", headers=env.cookie(token))).status_code == 200


# --- FR-67 / AC-75: роль и флаги читаются из БД на каждый запрос --------------------------


async def test_fr67_ac75_role_change_applies_next_request_without_relogin(env: Env) -> None:
    user, token = await env.login_as("user")
    url = "/_t/cap/MANAGE_ACCOUNTS"
    headers = env.cookie(token)

    denied = await env.client.get(url, headers=headers)
    assert (denied.status_code, _code(denied)) == (403, "forbidden")

    await env.set_member_role(user, "tech_admin")
    assert (await env.client.get(url, headers=headers)).status_code == 200
    assert (await env.client.get("/_t/whoami", headers=headers)).json()["role"] == "tech_admin"

    await env.set_member_role(user, "mixed")
    assert (await env.client.get("/_t/whoami", headers=headers)).json()["role"] == "mixed"

    await env.set_member_role(user, "business_admin")
    again = await env.client.get(url, headers=headers)
    assert (again.status_code, _code(again)) == (403, "forbidden")


async def test_fr67_ac75_role_removed_gives_no_role_next_request(env: Env) -> None:
    user, token = await env.login_as("mixed")
    headers = env.cookie(token)
    assert (await env.client.get("/_t/active", headers=headers)).status_code == 200
    await env.set_member_role(user, None)
    response = await env.client.get("/_t/active", headers=headers)
    assert (response.status_code, _code(response)) == (403, "no_role")


async def test_fr67_must_change_password_flag_read_per_request(env: Env) -> None:
    user, token = await env.login_as("user", must_change=True)
    headers = env.cookie(token)
    response = await env.client.get("/_t/active", headers=headers)
    assert (response.status_code, _code(response)) == (403, "password_change_required")
    await env.set_user_flags(user, must_change_password=False)
    assert (await env.client.get("/_t/active", headers=headers)).status_code == 200
    await env.set_user_flags(user, must_change_password=True)
    response = await env.client.get("/_t/active", headers=headers)
    assert (response.status_code, _code(response)) == (403, "password_change_required")


# --- фоновые запросы (D-14, FR-59, AC-79) ------------------------------------------------


async def test_d14_background_get_does_not_extend_session(env: Env) -> None:
    _, token = await env.login_as("user", now=FIXED_NOW - timedelta(hours=1))
    before = await env.last_activity(token)
    response = await env.client.get(
        "/_t/whoami", headers={**env.cookie(token), "X-GT-Background": "1"}
    )
    assert response.status_code == 200
    assert await env.last_activity(token) == before


async def test_d14_regular_get_extends_session(env: Env) -> None:
    _, token = await env.login_as("user", now=FIXED_NOW - timedelta(hours=1))
    response = await env.client.get("/_t/whoami", headers=env.cookie(token))
    assert response.status_code == 200
    assert await env.last_activity(token) == FIXED_NOW


async def test_d14_background_header_ignored_on_non_get(env: Env) -> None:
    _, token = await env.login_as("user", now=FIXED_NOW - timedelta(hours=1))
    response = await env.client.post(
        "/_t/whoami", headers={**env.cookie(token), "X-GT-Background": "1"}
    )
    assert response.status_code == 200
    assert await env.last_activity(token) == FIXED_NOW


@pytest.mark.parametrize("value", ["0", "true", "", "2", "yes"])
async def test_d14_only_value_1_marks_background(env: Env, value: str) -> None:
    _, token = await env.login_as("user", now=FIXED_NOW - timedelta(hours=1))
    response = await env.client.get(
        "/_t/whoami", headers={**env.cookie(token), "X-GT-Background": value}
    )
    assert response.status_code == 200
    assert await env.last_activity(token) == FIXED_NOW


async def test_ac79_only_background_requests_7h59_then_action_succeeds(env: Env) -> None:
    _, token = await env.login_as("user")
    bg = {**env.cookie(token), "X-GT-Background": "1"}
    for minutes in (120, 300, 479):  # 8 ч 00 мин не достигается: 7 ч 59 мин
        env.clock.set(FIXED_NOW + timedelta(minutes=minutes))
        assert (await env.client.get("/_t/whoami", headers=bg)).status_code == 200
    action = await env.client.post("/_t/whoami", headers=env.cookie(token))
    assert action.status_code == 200


async def test_ac79_only_background_requests_8h01_then_action_is_401(env: Env) -> None:
    _, token = await env.login_as("user")
    bg = {**env.cookie(token), "X-GT-Background": "1"}
    env.clock.set(FIXED_NOW + timedelta(minutes=479))
    assert (await env.client.get("/_t/whoami", headers=bg)).status_code == 200
    env.clock.set(FIXED_NOW + timedelta(hours=8, minutes=1))
    action = await env.client.post("/_t/whoami", headers=env.cookie(token))
    assert action.status_code == 401
    assert _code(action) == "not_authenticated"


# --- get_active_actor --------------------------------------------------------------------


async def test_fr55_must_change_password_is_403_password_change_required(env: Env) -> None:
    _, token = await env.login_as("business_admin", must_change=True)
    response = await env.client.get("/_t/active", headers=env.cookie(token))
    assert response.status_code == 403
    assert _code(response) == "password_change_required"
    assert "active" not in env.handler_calls


async def test_fr66_ac75_no_role_is_403_no_role(env: Env) -> None:
    _, token = await env.login_as(None)
    response = await env.client.get("/_t/active", headers=env.cookie(token))
    assert response.status_code == 403
    assert _code(response) == "no_role"
    assert "active" not in env.handler_calls


async def test_fr55_password_change_gate_precedes_no_role_gate(env: Env) -> None:
    """Порядок plan §4.5 п.2 → п.3: пользователь без роли с одноразовым паролем."""
    _, token = await env.login_as(None, must_change=True)
    response = await env.client.get("/_t/active", headers=env.cookie(token))
    assert response.status_code == 403
    assert _code(response) == "password_change_required"


@pytest.mark.parametrize("role", ALL_ROLES)
async def test_get_active_actor_passes_every_role(env: Env, role: str) -> None:
    _, token = await env.login_as(role)
    response = await env.client.get("/_t/active", headers=env.cookie(token))
    assert response.status_code == 200
    assert response.json()["role"] == role


async def test_get_active_actor_without_cookie_is_401(env: Env) -> None:
    response = await env.client.get("/_t/active")
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


# --- require_capability ------------------------------------------------------------------


@pytest.mark.parametrize(("role", "cap"), GATE_CELLS)
async def test_fr9_fr10_require_capability_matrix_over_http(env: Env, role: str, cap: str) -> None:
    _, token = await env.login_as(role)
    response = await env.client.get(f"/_t/cap/{cap}", headers=env.cookie(token))
    if role in HOLDERS[cap]:
        assert response.status_code == 200, f"{role} x {cap}"
    else:
        assert response.status_code == 403, f"{role} x {cap}"
        assert _code(response) == "forbidden"


@pytest.mark.parametrize(
    ("role", "allowed"),
    [("tech_admin", True), ("business_admin", True), ("mixed", True), ("user", False)],
)
async def test_require_capability_any_of_listed(env: Env, role: str, allowed: bool) -> None:
    """``require_capability(a, b)``: достаточно любой из возможностей."""
    _, token = await env.login_as(role)
    response = await env.client.get("/_t/any-cap", headers=env.cookie(token))
    assert response.status_code == (200 if allowed else 403)
    if not allowed:
        assert _code(response) == "forbidden"


async def test_require_capability_without_cookie_is_401(env: Env) -> None:
    response = await env.client.get("/_t/cap/MANAGE_ACCOUNTS")
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"


# --- порядок проверок FR-45a / plan §4.5 --------------------------------------------------


async def test_order_1_401_before_everything(env: Env) -> None:
    response = await env.client.get(f"/_t/admin/items/{RANDOM_ID}")
    assert response.status_code == 401
    assert _code(response) == "not_authenticated"
    assert env.handler_calls == []


@pytest.mark.parametrize("role", ["tech_admin", "user"])
async def test_order_2_password_change_before_section_gate(env: Env, role: str) -> None:
    """require_capability сам включает гейты 2-3: роль с правом и без права — один ответ."""
    _, token = await env.login_as(role, must_change=True)
    response = await env.client.get(f"/_t/admin/items/{RANDOM_ID}", headers=env.cookie(token))
    assert response.status_code == 403
    assert _code(response) == "password_change_required"
    assert env.handler_calls == []


async def test_order_3_no_role_before_section_gate(env: Env) -> None:
    _, token = await env.login_as(None)
    response = await env.client.get(f"/_t/admin/items/{RANDOM_ID}", headers=env.cookie(token))
    assert response.status_code == 403
    assert _code(response) == "no_role"
    assert env.handler_calls == []


@pytest.mark.parametrize("role", ["user", "business_admin"])
async def test_ac11_fr45a_section_gate_403_before_object_lookup(env: Env, role: str) -> None:
    """Любой id (несуществующий тоже) в закрытом разделе — 403; обработчик не вызывается."""
    _, token = await env.login_as(role)
    for item_id in (RANDOM_ID, str(uuid.uuid4())):
        response = await env.client.get(f"/_t/admin/items/{item_id}", headers=env.cookie(token))
        assert response.status_code == 403
        assert _code(response) == "forbidden"
    assert env.handler_calls == []


async def test_fr45a_section_gate_precedes_path_validation(env: Env) -> None:
    """Нечитаемый id в закрытом разделе — тоже 403, а не 422."""
    _, token = await env.login_as("user")
    response = await env.client.get("/_t/admin/items/not-a-uuid", headers=env.cookie(token))
    assert response.status_code == 403
    assert _code(response) == "forbidden"


@pytest.mark.parametrize("role", ["tech_admin", "mixed"])
async def test_fr45a_role_with_access_gets_404_for_missing_object(env: Env, role: str) -> None:
    _, token = await env.login_as(role)
    response = await env.client.get(f"/_t/admin/items/{RANDOM_ID}", headers=env.cookie(token))
    assert response.status_code == 404
    assert _code(response) == "not_found"
    assert env.handler_calls == ["admin_item"]


async def test_order_5_gate_403_before_body_validation_then_422(env: Env) -> None:
    _, denied_token = await env.login_as("user")
    denied = await env.client.post(
        "/_t/admin/items", json={"name": "x"}, headers=env.cookie(denied_token)
    )
    assert denied.status_code == 403
    assert _code(denied) == "forbidden"

    _, ok_token = await env.login_as("tech_admin")
    invalid = await env.client.post(
        "/_t/admin/items", json={"name": "x"}, headers=env.cookie(ok_token)
    )
    assert invalid.status_code == 422
    assert _code(invalid) == "validation_error"

    valid = await env.client.post(
        "/_t/admin/items", json={"name": "abcd"}, headers=env.cookie(ok_token)
    )
    assert valid.status_code == 200
    assert env.handler_calls == ["admin_create"]


# --- check_origin (D-16) -----------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_d16_foreign_origin_on_unsafe_method_is_403_origin_mismatch(
    env: Env, method: str
) -> None:
    _, token = await env.login_as("user")
    response = await env.client.request(
        method, "/_t/public", headers={**env.cookie(token), "Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert _code(response) == "origin_mismatch"
    assert env.handler_calls == []


async def test_d16_origin_checked_for_authenticated_route_too(env: Env) -> None:
    _, token = await env.login_as("user")
    response = await env.client.post(
        "/_t/whoami", headers={**env.cookie(token), "Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert _code(response) == "origin_mismatch"
    assert env.handler_calls == []


async def test_d16_same_port_other_host_is_mismatch(env: Env) -> None:
    response = await env.client.post("/_t/public", headers={"Origin": "http://localhost"})
    assert response.status_code == 403
    assert _code(response) == "origin_mismatch"


async def test_d16_other_port_same_host_is_mismatch(env: Env) -> None:
    """Lax не защищает от запросов с других портов того же сайта: сравнивается host:port."""
    response = await env.client.post("/_t/public", headers={"Origin": "http://testserver:8080"})
    assert response.status_code == 403
    assert _code(response) == "origin_mismatch"


async def test_d16_matching_origin_passes(env: Env) -> None:
    response = await env.client.post("/_t/public", headers={"Origin": "http://testserver"})
    assert response.status_code == 200
    assert env.handler_calls == ["public_post"]


async def test_d16_missing_origin_passes(env: Env) -> None:
    """Origin отсутствует: проверка не применяется (защита — SameSite=Lax)."""
    response = await env.client.post("/_t/public")
    assert response.status_code == 200


async def test_d16_safe_method_with_foreign_origin_not_checked(env: Env) -> None:
    _, token = await env.login_as("user")
    headers = {**env.cookie(token), "Origin": "http://evil.example"}
    assert (await env.client.get("/_t/whoami", headers=headers)).status_code == 200
    assert (await env.client.get("/api/v1/health", headers=headers)).status_code == 200


# --- одна сессия БД на запрос; scope="function" (ревью T05) -------------------------------


async def test_t05_one_db_session_per_request_with_actor_and_handler(env: Env) -> None:
    _, token = await env.login_as("user")
    before = env.sessionmaker.opened
    response = await env.client.get("/_t/one-session", headers=env.cookie(token))
    assert response.status_code == 200
    assert response.json() == {"value": 1}
    assert env.sessionmaker.opened - before == 1


async def test_t05_yield_dependency_over_dbsession_has_function_scope(env: Env) -> None:
    _, token = await env.login_as("user")
    before = env.sessionmaker.opened
    response = await env.client.get("/_t/with-yield", headers=env.cookie(token))
    assert response.status_code == 200
    assert response.json() == {"value": 1}
    assert env.sessionmaker.opened - before == 1


def test_t05_deps_module_does_not_reference_get_db_and_yield_deps_use_function_scope() -> None:
    """AST: в ``app/api/deps.py`` нет имени ``get_db`` (только ``DbSession``); любая
    зависимость-генератор подключается через ``Depends(..., scope="function")``."""
    path = APP_DIR / "api" / "deps.py"
    assert path.exists(), "app/api/deps.py не создан"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id != "get_db"
        elif isinstance(node, ast.Attribute):
            assert node.attr != "get_db"
        elif isinstance(node, ast.alias):
            assert node.name != "get_db"
            assert node.asname != "get_db"

    generators = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(isinstance(n, ast.Yield | ast.YieldFrom) for n in ast.walk(fn))
    }
    for call in ast.walk(tree):
        if not (
            isinstance(call, ast.Call)
            and (
                (isinstance(call.func, ast.Name) and call.func.id == "Depends")
                or (isinstance(call.func, ast.Attribute) and call.func.attr == "Depends")
            )
            and call.args
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id in generators
        ):
            continue
        scopes = [
            kw.value.value
            for kw in call.keywords
            if kw.arg == "scope" and isinstance(kw.value, ast.Constant)
        ]
        assert scopes == ["function"], f"Depends({call.args[0].id}) без scope='function'"


# --- lifespan собирает SessionStore (ревью T11) ------------------------------------------


def _state_values(application: FastAPI) -> list[Any]:
    return list(application.state._state.values())


def _first(application: FastAPI, cls: type) -> Any:
    found = [v for v in _state_values(application) if isinstance(v, cls)]
    assert len(found) == 1, f"ожидался один {cls.__name__} в app.state, найдено {len(found)}"
    return found[0]


async def test_t11_lifespan_builds_session_store_from_ensure_secret_key_generated(
    app: FastAPI, settings: Settings
) -> None:
    from app.domain.auth.sessions import SessionStore

    assert settings.secret_key is None  # ключ будет сгенерирован в data_dir/secrets
    async with app.router.lifespan_context(app):
        store = _first(app, SessionStore)
        key = ensure_secret_key(settings)  # тот же файл: повторный вызов возвращает тот же ключ
        assert len(key) >= 32
        expected = hmac.new(key, b"probe-token", hashlib.sha256).digest()
        assert store.token_id("probe-token") == expected


async def test_t11_lifespan_builds_session_store_from_explicit_key(
    test_database_url: str, tmp_path: Path, fixed_clock: FixedClock
) -> None:
    from app.domain.auth.sessions import SessionStore
    from app.main import create_app

    raw = "explicit-secret-key-0123456789-abcdefghij"
    cfg = Settings(
        env="test",
        database_url=test_database_url,
        data_dir=tmp_path,
        secret_key=raw,  # type: ignore[arg-type]
        cookie_secure=False,
    )
    application = create_app(cfg, clock=fixed_clock)
    async with application.router.lifespan_context(application):
        store = _first(application, SessionStore)
        expected = hmac.new(raw.encode(), b"probe-token", hashlib.sha256).digest()
        assert store.token_id("probe-token") == expected


async def test_t11_lifespan_assembles_hasher_and_local_provider(app: FastAPI) -> None:
    from app.core.security.passwords import PasswordHasher
    from app.domain.auth.provider import LocalPasswordProvider
    from app.domain.auth.sessions import SessionStore

    async with app.router.lifespan_context(app):
        assert isinstance(_first(app, PasswordHasher), PasswordHasher)
        assert isinstance(_first(app, LocalPasswordProvider), LocalPasswordProvider)
        assert isinstance(_first(app, SessionStore), SessionStore)


async def test_t11_short_secret_key_does_not_start_application(
    test_database_url: str, tmp_path: Path, fixed_clock: FixedClock
) -> None:
    """Ключ короче 32 байт не принимается молча: запуск завершается ошибкой."""
    from app.main import create_app

    cfg = Settings(
        env="test",
        database_url=test_database_url,
        data_dir=tmp_path,
        secret_key="too-short-key",  # type: ignore[arg-type]
        cookie_secure=False,
    )
    application = create_app(cfg, clock=fixed_clock)
    with pytest.raises(Exception):  # noqa: B017, PT011 - тип ошибки plan не фиксирует
        async with application.router.lifespan_context(application):
            pass


async def test_t11_created_session_resolves_through_app_store(env: Env) -> None:
    """Токен, созданный ключом ensure_secret_key, принимается приложением: ключи совпали."""
    _, token = await env.login_as("user")
    response = await env.client.get("/_t/whoami", headers=env.cookie(token))
    assert response.status_code == 200
