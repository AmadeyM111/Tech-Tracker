"""Общие помощники тестов 007 (plan §5): мир агентов.

Не тест-модуль. R7-T08 создаёт ``CLOCK``, ``make_agent`` и адреса; ``make_key``, ``bearer`` и
``make_world007`` добавляют R7-T10 и R7-T12.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.conftest import ApiEnv
    from tests.factories import ApiKeyRow, UserRow, WorkspaceRow

# 2026-11-02 07:00 UTC = 10:00 по Москве (spec §5, plan §5)
CLOCK = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)

API = "/api/v1"
ADMIN_AGENTS = f"{API}/admin/agents"
ADMIN_USERS = f"{API}/admin/users"
AUDIT = f"{API}/admin/audit"
USERS_DIRECTORY = f"{API}/users"
LOGIN_URL = f"{API}/auth/login"
ME_URL = f"{API}/me"


async def make_agent(
    env: ApiEnv, login: str, role: str | None, *, workspace: WorkspaceRow | None = None
) -> UserRow:
    """Учётная запись агента напрямую в БД (с фиксацией): ``is_agent=true``, хеш случайного
    значения (пароль не известен), без сессий. Без ``workspace`` создаётся новое пространство."""
    import secrets

    kwargs: dict[str, object] = {"password": secrets.token_urlsafe(32)}
    return await env.new_user(workspace=workspace, login=login, role=role, is_agent=True, **kwargs)


async def make_key(
    env: ApiEnv,
    user: UserRow,
    *,
    created_by: UserRow,
    name: str = "k",
    created_at: datetime = CLOCK,
    ttl: timedelta = timedelta(days=90),
    revoked_at: datetime | None = None,
    last_used_at: datetime | None = None,
    secret: str | None = None,
) -> ApiKeyRow:
    """Ключ агента напрямую в БД (с фиксацией): ``expires_at = created_at + ttl``; при
    ``revoked_at`` отозвавшим записывается ``created_by``. В БД попадает только ``sha256``."""
    from tests.factories import make_api_key

    async with env.sessionmaker() as session:
        row = await make_api_key(
            session,
            user=user,
            created_by=created_by,
            secret=secret,
            name=name,
            created_at=created_at,
            expires_at=created_at + ttl,
            revoked_at=revoked_at,
            revoked_by=created_by if revoked_at is not None else None,
            last_used_at=last_used_at,
        )
        await session.commit()
    return row


def bearer(secret: str) -> dict[str, str]:
    """Заголовок ``Authorization: Bearer <ключ>`` (cookie не нужна)."""
    return {"Authorization": f"Bearer {secret}"}
