"""Общие помощники тестов 007 (plan §5): мир агентов.

Не тест-модуль. R7-T08 создаёт ``CLOCK``, ``make_agent`` и адреса; ``make_key``, ``bearer`` и
``make_world007`` добавляют R7-T10 и R7-T12.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.conftest import ApiEnv
    from tests.factories import UserRow, WorkspaceRow

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
