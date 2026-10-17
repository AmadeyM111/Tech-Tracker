"""T97: обновление существующей установки до FR-73a (AC-131, D-66, plan §11.12.3, §11.12.8).

Сценарий: система предыдущей версии (схема 0004, v0.16.1) с первым ТА, демо-данными и учётной
записью ``ivan.petrov`` → ``alembic upgrade head`` (миграция 0005) → логины в ответах API прежние,
вход прежними паролями работает, проекты, задачи, комментарии и журнал не изменились, а учётная
запись ``Demo.BA1`` теперь занята (422 ``login_taken``).

«Предыдущая версия» получается так: данные создаются на head, затем ``downgrade 0004`` и
``upgrade head`` (как ``test_t69_*`` в ``db/test_migrations.py``): логины прежних записей строчные,
столбца ``login_display`` в промежутке нет. После миграций движок пересоздаётся
(``dispose``): asyncpg кэширует подготовленные выражения по схеме.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.core.clock import FixedClock
from app.domain.access.roles import Actor, Role
from tests.conftest import CHEAP_ARGON2, FIXED_NOW
from tests.db_support import run_alembic

if TYPE_CHECKING:
    from tests.conftest import ApiEnv

FIRST_ADMIN_PASSWORD = "Zq7Lm2Vx9FirstAdminPw"
IVAN_OTP = "Tmp-Pa55phrase-xyz-777"
NEW_PASSWORD = "Br4nd-new-Pa55phrase-uvw"
ADMIN_USERS = "/api/v1/admin/users"
AUDIT = "/api/v1/admin/audit"
LOGIN_URL = "/api/v1/auth/login"
SNAPSHOT_TABLES = ("project", "task", "comment", "domain_event")


async def _alembic_ok(url: str, *args: str) -> None:
    result = await asyncio.to_thread(run_alembic, url, *args)
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
    )


async def _snapshot(env: ApiEnv) -> dict[str, Any]:
    """app_user (id, login, hash) и md5 строк таблиц данных: сравнивается до и после обновления."""
    users = await env.execute(text("SELECT id, login, password_hash FROM app_user ORDER BY id"))
    assert users is not None
    snap: dict[str, Any] = {"app_user": [tuple(r) for r in users]}
    for table in SNAPSHOT_TABLES:
        rows = await env.execute(
            text(
                f"SELECT count(*) AS n, "  # noqa: S608
                f"coalesce(md5(string_agg(t::text, '|' ORDER BY t.id)), '') AS h FROM {table} t"
            )
        )
        assert rows is not None
        snap[table] = (rows[0].n, rows[0].h)
    return snap


def _demo_passwords(env: ApiEnv) -> dict[str, str]:
    path = env.settings.secrets_dir / "demo-passwords.txt"
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"login=([^\t]+)\tpassword=(\S+)", line)
        assert match, line
        result[match.group(1)] = match.group(2)
    return result


async def _build_previous_version_installation(env: ApiEnv) -> dict[str, str]:
    """Первый ТА (`admin`), демо-данные (seed=1), учётная запись `ivan.petrov` от имени ТА.

    Возвращает пароли: ``{логин: пароль}``. Порядок: ``demo-data`` отказывается работать, если
    в базе есть пользователи сверх первого ТА, поэтому ``ivan.petrov`` создаётся после демо.
    """
    from app.core.security.passwords import PasswordHasher
    from app.domain.ops.demo import load_demo_data
    from app.domain.system.bootstrap import run_bootstrap
    from app.domain.users.service import create_user

    settings = env.settings
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    settings.secrets_dir.chmod(0o700)
    clock = FixedClock(FIXED_NOW)
    await run_bootstrap(
        env.sessionmaker, settings, clock=clock, generate=lambda: FIRST_ADMIN_PASSWORD
    )
    await load_demo_data(env.sessionmaker, settings, clock=clock, seed=1)

    async with env.sessionmaker() as s:
        admin = (
            await s.execute(
                text(
                    "SELECT u.id, m.workspace_id FROM app_user u "
                    "JOIN workspace_member m ON m.user_id = u.id WHERE u.login = 'admin'"
                )
            )
        ).one()
    actor = Actor(
        user_id=admin.id,
        workspace_id=admin.workspace_id,
        login="admin",
        role=Role.TECH_ADMIN,
        must_change_password=False,
        session_id=b"\x01" * 32,
    )
    hasher = PasswordHasher(
        time_cost=CHEAP_ARGON2["argon2_time_cost"],
        memory_cost_kib=CHEAP_ARGON2["argon2_memory_cost_kib"],
        parallelism=CHEAP_ARGON2["argon2_parallelism"],
    )
    async with env.sessionmaker() as s, s.begin():
        created = await create_user(
            s, actor, hasher, login="ivan.petrov", one_time_password=SecretStr(IVAN_OTP)
        )
    assert created.login == "ivan.petrov"

    passwords = {"admin": FIRST_ADMIN_PASSWORD, "ivan.petrov": IVAN_OTP}
    passwords.update(_demo_passwords(env))
    return passwords


@pytest.mark.committed
async def test_ac131_upgrade_keeps_logins_passwords_data_and_makes_case_variants_taken(
    committed_api_env: ApiEnv, db_engine: Any, test_database_url: str
) -> None:
    env = committed_api_env
    passwords = await _build_previous_version_installation(env)
    assert len(passwords) == 14, sorted(passwords)  # admin + 12 демо + ivan.petrov
    before = await _snapshot(env)
    audit_before = await env.execute(text("SELECT count(*) FROM domain_event WHERE in_audit"))
    assert audit_before is not None
    audit_count = int(audit_before[0][0])
    assert audit_count > 0
    previous_logins = {row[1] for row in before["app_user"]}
    assert previous_logins == set(passwords)
    assert all(login == login.lower() for login in previous_logins)

    # --- обновление: версия до FR-73a (0004) и повторное применение head (0005) ---
    await _alembic_ok(test_database_url, "downgrade", "0004")
    await db_engine.dispose()
    gone = await env.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'app_user' AND column_name = 'login_display'"
        )
    )
    assert gone is not None and gone[0][0] == 0, (
        "на схеме 0004 столбца login_display быть не должно"
    )
    await _alembic_ok(test_database_url, "upgrade", "head")
    await db_engine.dispose()

    # --- данные не изменились; показ равен прежнему логину ---
    assert await _snapshot(env) == before
    mismatch = await env.execute(text("SELECT count(*) FROM app_user WHERE login_display <> login"))
    assert mismatch is not None and mismatch[0][0] == 0

    # --- вход прежними паролями: логин в ответе прежний ---
    for login, password in passwords.items():
        response = await env.login(login, password)
        assert response.status_code == 200, (login, response.text)
        assert response.json()["user"]["login"] == login
    upper = await env.login("DEMO.BA1", passwords["demo.ba1"])
    assert upper.status_code == 200
    assert upper.json()["user"]["login"] == "demo.ba1"

    # --- список учётных записей и журнал: прежние логины и число записей ---
    # актор — первый ТА `admin` (002/AC-28: demo.mixed больше нет; 001/AC-131 по 002 §9)
    admin_login = await env.login("admin", passwords["admin"])
    token = env.token_from(admin_login)
    assert token
    changed = await env.client.post(
        "/api/v1/auth/password",
        json={"current_password": passwords["admin"], "new_password": NEW_PASSWORD},
        headers=env.auth(token),
    )
    assert changed.status_code == 204, changed.text

    items: list[dict[str, Any]] = []
    page = 1
    while True:
        listing = await env.client.get(
            ADMIN_USERS, params={"page": page, "page_size": 100}, headers=env.auth(token)
        )
        assert listing.status_code == 200, listing.text
        items += listing.json()["items"]
        if not listing.json()["has_next"]:
            break
        page += 1
    assert {i["login"] for i in items} == previous_logins
    assert len(items) == len(previous_logins)

    audit = await env.client.get(AUDIT, params={"page_size": 100}, headers=env.auth(token))
    assert audit.status_code == 200, audit.text
    body = audit.json()
    assert body["has_next"] is False
    in_audit = await env.execute(text("SELECT count(*) FROM domain_event WHERE in_audit"))
    assert in_audit is not None
    assert len(body["items"]) == int(in_audit[0][0]) >= audit_count  # число записей прежнее
    actor_logins = {e["actor"]["login"] for e in body["items"] if e["actor"]["kind"] == "user"}
    assert actor_logins <= previous_logins
    assert "admin" in actor_logins  # ivan.petrov создан первым ТА

    # --- после обновления логин, отличающийся от занятого только регистром, занят ---
    for attempt in ("Demo.BA1", "DEMO.ba1"):
        taken = await env.client.post(
            ADMIN_USERS,
            json={"login": attempt, "one_time_password": IVAN_OTP},
            headers=env.auth(token),
        )
        assert taken.status_code == 422, taken.text
        assert taken.json()["code"] == "login_taken"
    count = await env.execute(text("SELECT count(*) FROM app_user"))
    assert count is not None and count[0][0] == len(previous_logins)

    # --- новая учётная запись после обновления: написание сохраняется ---
    fresh = await env.client.post(
        ADMIN_USERS,
        json={"login": "Ivanov.Petr", "one_time_password": IVAN_OTP},
        headers=env.auth(token),
    )
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["login"] == "Ivanov.Petr"
