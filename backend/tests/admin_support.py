"""Общие помощники тестов API учётных записей и ролей (T17).

Не тест-модуль. Используется ``tests/api/test_admin_users.py``, ``test_admin_roles.py``,
``test_workspace_isolation.py``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tests.conftest import FIXED_NOW
from tests.factories import PLACEHOLDER_HASH, UserRow, make_user, make_workspace

if TYPE_CHECKING:
    import httpx

    from tests.conftest import ApiEnv
    from tests.factories import WorkspaceRow

ADMIN_USERS = "/api/v1/admin/users"
PW = "Sup3r-secret-Pa55phrase-xyz"
OTP = "Tmp-Pa55phrase-xyz-777"
OTP_FIELD = "one_time_password"  # plan §4.6: {login, one_time_password}
ADMIN_VIEW_FIELDS = {"id", "login", "role", "is_blocked", "must_change_password", "created_at"}


def code_of(response: httpx.Response) -> str:
    body = response.json()
    assert isinstance(body, dict), body
    return str(body["code"])


async def new_workspace(env: ApiEnv) -> WorkspaceRow:
    async with env.sessionmaker() as session:
        ws = await make_workspace(session)
        await session.commit()
    return ws


async def seed(
    env: ApiEnv,
    ws: WorkspaceRow,
    role: str | None,
    *,
    sessions: int = 1,
    password: str | None = None,
    blocked: bool = False,
    must_change_password: bool = False,
    login: str | None = None,
) -> tuple[UserRow, list[str]]:
    """Пользователь в пространстве ``ws`` + ``sessions`` действующих сессий (токены).

    Без ``password`` хеш — заглушка (быстро, вход невозможен); с ``password`` — настоящий
    дешёвый Argon2id.
    """
    from app.core.secrets import ensure_secret_key
    from app.domain.auth.sessions import SessionStore

    store = SessionStore(
        ensure_secret_key(env.settings),
        idle_timeout=env.settings.session_idle_timeout,
        absolute_timeout=env.settings.session_absolute_timeout,
    )
    async with env.sessionmaker() as session:
        kwargs: dict[str, Any] = {}
        if password is not None:
            kwargs["password"] = password
        else:
            kwargs["password_hash"] = PLACEHOLDER_HASH
        user = await make_user(
            session,
            workspace=ws,
            role=role,
            blocked=blocked,
            must_change_password=must_change_password,
            login=login,
            **kwargs,
        )
        tokens = [
            await store.create(
                session, user_id=user.id, workspace_id=user.workspace_id, now=FIXED_NOW
            )
            for _ in range(sessions)
        ]
        await session.commit()
    return user, tokens


async def admin_in_new_workspace(
    env: ApiEnv, role: str = "tech_admin"
) -> tuple[WorkspaceRow, UserRow, str]:
    """Новое пространство и один администратор с сессией (последний администратор)."""
    ws = await new_workspace(env)
    admin, (token,) = await seed(env, ws, role)
    return ws, admin, token


async def events(
    env: ApiEnv, *, entity_id: uuid.UUID | None = None, workspace_id: uuid.UUID | None = None
) -> list[Any]:
    """Строки ``domain_event`` (id, actor_id, entity_id, action, details) по порядку id."""
    sql = "SELECT id, actor_id, entity_id, action, details FROM domain_event WHERE true"
    params: dict[str, Any] = {}
    if entity_id is not None:
        sql += " AND entity_id = :e"
        params["e"] = entity_id
    if workspace_id is not None:
        sql += " AND workspace_id = :w"
        params["w"] = workspace_id
    rows = await env.execute(text(sql + " ORDER BY id").bindparams(**params))
    assert rows is not None
    return list(rows)


async def member_role(env: ApiEnv, user_id: uuid.UUID) -> str | None:
    rows = await env.execute(
        text("SELECT role FROM workspace_member WHERE user_id = :u").bindparams(u=user_id)
    )
    assert rows
    value = rows[0][0]
    return None if value is None else str(value)


async def active_admin_count(env: ApiEnv, workspace_id: uuid.UUID) -> int:
    rows = await env.execute(
        text(
            "SELECT count(*) FROM workspace_member m JOIN app_user u ON u.id = m.user_id "
            "WHERE m.workspace_id = :w AND m.role IN ('tech_admin', 'mixed') "
            "AND NOT u.is_blocked"
        ).bindparams(w=workspace_id)
    )
    assert rows
    return int(rows[0][0])


def admin_call(
    env: ApiEnv,
    token: str | None,
    action: str,
    target_id: uuid.UUID | str,
    *,
    extra: dict[str, str] | None = None,
) -> Any:
    """Корутина запроса действия администратора над ``target_id`` (имена как в plan §4.6).

    Действия: block, unblock, reset, revoke, get, role_user, role_ba, role_none, role_mixed,
    role_ta, create (``target_id`` игнорируется; логин создаётся уникальный).
    """
    headers = dict(extra or {})
    if token is not None:
        headers.update(env.auth(token))
    base = f"{ADMIN_USERS}/{target_id}"
    if action == "get":
        return env.client.get(base, headers=headers)
    if action in {"block", "unblock", "revoke"}:
        suffix = {"block": "block", "unblock": "unblock", "revoke": "revoke-sessions"}[action]
        return env.client.post(f"{base}/{suffix}", headers=headers)
    if action == "reset":
        return env.client.post(f"{base}/reset-password", json={OTP_FIELD: OTP}, headers=headers)
    roles = {
        "role_user": "user",
        "role_ba": "business_admin",
        "role_none": None,
        "role_mixed": "mixed",
        "role_ta": "tech_admin",
    }
    if action in roles:
        return env.client.put(f"{base}/role", json={"role": roles[action]}, headers=headers)
    if action == "create":
        return env.client.post(
            ADMIN_USERS,
            json={"login": f"new.{uuid.uuid4().hex[:12]}", OTP_FIELD: OTP},
            headers=headers,
        )
    raise AssertionError(action)
