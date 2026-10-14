"""T18: журнал аудита после первого запуска (AC-114 инфра, OI-110, FR-41, ADR-0006).

Первый запуск (``run_bootstrap``) и вход/смена пароля первого ТА записей в журнал не создают;
создание учётной записи — ровно одна запись ``user.created``; повторный bootstrap — без записей.
Журнал читается через ``GET /api/v1/admin/audit`` и прямым запросом к ``domain_event``.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from app.core.clock import FixedClock
from app.domain.system.bootstrap import run_bootstrap
from tests.conftest import FIXED_NOW, ApiEnv

AUDIT = "/api/v1/admin/audit"
FIRST_PASSWORD = "Zq7Lm2Vx9TestBootstrapPw"
NEW_PASSWORD = "Hw4Rt8Nc6AfterChangePw-77"
OTP = "Tmp-Pa55phrase-xyz-777"


async def _bootstrap(env: ApiEnv) -> Any:
    env.settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    env.settings.secrets_dir.chmod(0o700)
    return await run_bootstrap(
        env.sessionmaker, env.settings, clock=FixedClock(FIXED_NOW), generate=lambda: FIRST_PASSWORD
    )


async def _count(env: ApiEnv) -> int:
    rows = await env.execute(text("SELECT count(*) FROM domain_event"))
    assert rows
    return int(rows[0][0])


async def _api_entries(env: ApiEnv, token: str) -> list[dict[str, Any]]:
    r = await env.client.get(AUDIT, params={"page_size": 100}, headers=env.auth(token))
    assert r.status_code == 200, r.text
    return list(r.json()["items"])


@pytest.mark.committed
async def test_ac114_bootstrap_login_password_change_and_create_user_audit(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    result = await _bootstrap(env)
    assert result.admin_created is True
    assert await _count(env) == 0  # AC-114/OI-110: первый запуск журнал не пишет

    # первый вход ТА (по одноразовому паролю из файла) — записей нет
    login = env.settings.initial_admin_login
    ok = await env.login(login, FIRST_PASSWORD)
    assert ok.status_code == 200, ok.text
    token = env.token_from(ok)
    assert token
    assert await _count(env) == 0

    # смена своего пароля — записей нет; гейт must_change_password снят
    changed = await env.client.post(
        "/api/v1/auth/password",
        json={"current_password": FIRST_PASSWORD, "new_password": NEW_PASSWORD},
        headers=env.auth(token),
    )
    assert changed.status_code in (200, 204), changed.text
    token = env.token_from(changed) or token
    assert await _count(env) == 0
    still_empty = await env.client.get(AUDIT, headers=env.auth(token))
    assert still_empty.status_code == 200, still_empty.text
    assert still_empty.json() == {"items": [], "page": 1, "page_size": 50, "has_next": False}

    # создание учётной записи — ровно одна запись user.created, автор — первый ТА
    created = await env.client.post(
        "/api/v1/admin/users",
        json={"login": "first.created", "one_time_password": OTP},
        headers=env.auth(token),
    )
    assert created.status_code == 201, created.text
    entries = await _api_entries(env, token)
    assert len(entries) == 1
    (entry,) = entries
    assert entry["action"] == "user.created"
    assert entry["entity_type"] == "user"
    assert entry["entity_id"] == created.json()["id"]
    assert entry["actor"]["kind"] == "user"
    assert entry["actor"]["login"] == login
    assert entry["actor"]["id"] is not None

    # повторный bootstrap — идемпотентен, записей не добавляет
    again = await _bootstrap(env)
    assert again.admin_created is False
    assert await _count(env) == 1
    assert len(await _api_entries(env, token)) == 1
