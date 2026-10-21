"""R3-T15: обновление установки с демо-данными до трёх ролей (spec 002 AC-30, FR-13...FR-15, FR-22).

«Предыдущая версия» по plan D-13: ``downgrade 0005`` -> первый ТА (``run_bootstrap``) -> в
``app.domain.ops.demo`` подменяются ``("demo.ba4", "business_admin")`` на
``("demo.mixed", "mixed")`` и ``_ALL_PROJECTS_BA`` на ``"demo.mixed"`` ->
``load_demo_data(seed=1)``.
Обновление - командой оператора ``gostracker bootstrap`` (``app.cli.main.main(["bootstrap"])``
в отдельном потоке, окружение тестовой БД), как в контейнере. В демо первый ТА ``admin`` активен,
поэтому бывший СМ только теряет роль и ТА не получает (FR-16 не срабатывает).
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from app.core.clock import FixedClock
from app.core.config import get_settings
from tests.conftest import FIXED_NOW
from tests.db_support import ALEMBIC_INI
from tests.upgrade002_support import (
    HEAD_REVISION,
    alembic_versions,
    audit_rows,
    db_now,
    member_updated_at,
    roles_by_login,
    to_schema_0005,
)

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ApiEnv

FIRST_ADMIN_PASSWORD = "Zq7Lm2Vx9FirstAdminPw"
NEW_PASSWORD = "Br4nd-new-Pa55phrase-uvw"
FORMER_MIXED = "demo.mixed"
ADMIN_USERS = "/api/v1/admin/users"
AUDIT = "/api/v1/admin/audit"
SNAPSHOT_TABLES = ("project", "task", "comment", "project_member")
EXPECTED_DEMO_ROLES: dict[str, str | None] = {
    "admin": "tech_admin",
    "demo.ta": "tech_admin",
    "demo.ba1": "business_admin",
    "demo.ba2": "business_admin",
    "demo.ba3": "business_admin",
    **{f"demo.user{i}": "user" for i in range(1, 8)},
}


async def _snapshot(env: ApiEnv) -> dict[str, Any]:
    """app_user (id, login, hash) и md5 строк project, task, comment, project_member."""
    users = await env.execute(text("SELECT id, login, password_hash FROM app_user ORDER BY id"))
    assert users is not None
    snap: dict[str, Any] = {"app_user": [tuple(r) for r in users]}
    for table in SNAPSHOT_TABLES:
        order = "t.project_id, t.user_id" if table == "project_member" else "t.id"
        # 006/PD-18: у task приоритет приводится по FR-10 (base -> medium), остальное - побайтно
        row_text = (
            "(to_jsonb(t) || jsonb_build_object('priority', "
            "CASE t.priority WHEN 'base' THEN 'medium' ELSE t.priority END))::text"
            if table == "task"
            else "t::text"
        )
        rows = await env.execute(
            text(
                f"SELECT count(*) AS n, "  # noqa: S608
                f"coalesce(md5(string_agg({row_text}, '|' ORDER BY {order})), '') AS h "
                f"FROM {table} t"
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


async def _build_previous_version_installation(
    env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> dict[str, str]:
    """Схема 0005, первый ТА ``admin``, демо-данные прежнего состава (``demo.mixed``, seed=1)."""
    from app.domain.ops import demo
    from app.domain.system.bootstrap import run_bootstrap

    await to_schema_0005(env)
    settings = env.settings
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    settings.secrets_dir.chmod(0o700)
    clock = FixedClock(FIXED_NOW)
    await run_bootstrap(
        env.sessionmaker, settings, clock=clock, generate=lambda: FIRST_ADMIN_PASSWORD
    )

    assert ("demo.ba4", "business_admin") in demo._USERS, "plan D-13: demo.ba4 на месте demo.mixed"
    previous_users = tuple(
        ("demo.mixed", "mixed") if entry == ("demo.ba4", "business_admin") else entry
        for entry in demo._USERS
    )
    assert previous_users != demo._USERS
    with monkeypatch.context() as mp:
        mp.setattr(demo, "_USERS", previous_users)
        mp.setattr(demo, "_ALL_PROJECTS_BA", FORMER_MIXED)
        # 006/PD-18: в прежней версии обычный приоритет демо-задач - base
        mp.setattr(demo, "_REGULAR_PRIORITY", "base")
        await demo.load_demo_data(env.sessionmaker, settings, clock=clock, seed=1)

    passwords = {"admin": FIRST_ADMIN_PASSWORD}
    passwords.update(_demo_passwords(env))
    return passwords


def _operator_env(monkeypatch: pytest.MonkeyPatch, env: ApiEnv, database_url: str) -> None:
    """Окружение процесса для ``main(["bootstrap"])`` (по образцу ``cli/test_bootstrap.py``)."""
    for name in ("SECRET_KEY", "INITIAL_ADMIN_LOGIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATA_DIR", str(env.settings.data_dir))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_MEMORY_COST_KIB", "1024")
    monkeypatch.setenv("ARGON2_PARALLELISM", "1")
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ALEMBIC_INI))
    get_settings.cache_clear()


async def _run_operator_bootstrap(env: ApiEnv) -> int:
    from app.cli.main import main

    await env.sessionmaker.kw["bind"].dispose()  # без открытых соединений перед миграцией
    try:
        return await asyncio.to_thread(main, ["bootstrap"])
    finally:
        get_settings.cache_clear()
        # asyncpg кэширует подготовленные выражения по схеме: пересоздать соединения
        await env.sessionmaker.kw["bind"].dispose()


@pytest.mark.committed
async def test_002_ac30_demo_installation_upgrade_by_operator_bootstrap(
    committed_api_env: ApiEnv,
    monkeypatch: pytest.MonkeyPatch,
    test_database_url: str,
    tmp_path: Path,
) -> None:
    """002/AC-30 (FR-13, FR-14, FR-15, FR-22): обновление демо-установки командой bootstrap.

    ``demo.mixed`` теряет роль и остаётся участником обоих проектов; роли остальных 12
    пользователей прежние (ТА не добавляется); журнал N + 1 («снятие роли», автор «система»);
    проекты, задачи, комментарии, пароли и логины не изменены; вход прежними паролями работает.
    """
    env = committed_api_env
    passwords = await _build_previous_version_installation(env, monkeypatch)
    assert set(passwords) == {FORMER_MIXED, *EXPECTED_DEMO_ROLES}, sorted(passwords)

    # --- состояние «до»: предыдущая версия ---
    assert await alembic_versions(env) == ["0005"]
    roles_before = await roles_by_login(env)
    assert roles_before == {**EXPECTED_DEMO_ROLES, FORMER_MIXED: "mixed"}
    journal_before = await audit_rows(env)
    n = len(journal_before)
    assert n > 0, "в демо-установке есть записи журнала (N > 0)"
    snapshot_before = await _snapshot(env)
    members_before = await env.execute(
        text(
            "SELECT p.name, u.login FROM project_member pm JOIN project p ON p.id = pm.project_id "
            "JOIN app_user u ON u.id = pm.user_id ORDER BY p.name, u.login"
        )
    )
    assert members_before is not None
    member_pairs_before = [tuple(r) for r in members_before]
    projects_with_former = {p for p, login in member_pairs_before if login == FORMER_MIXED}
    all_projects = {p for p, _ in member_pairs_before}
    assert len(all_projects) == 2
    assert projects_with_former == all_projects, "demo.mixed - участник обоих демо-проектов"
    updated_before = await member_updated_at(env)
    ids = await env.execute(text("SELECT id, login FROM app_user"))
    assert ids is not None
    id_of = {str(r.login): r.id for r in ids}
    active_ta = await env.execute(
        text(
            "SELECT count(*) FROM workspace_member m JOIN app_user u ON u.id = m.user_id "
            "WHERE m.role = 'tech_admin' AND NOT u.is_blocked AND u.login = 'admin'"
        )
    )
    assert active_ta is not None and active_ta[0][0] == 1, "первый ТА admin активен"

    # --- обновление: команда оператора ---
    _operator_env(monkeypatch, env, test_database_url)
    t0 = await db_now(env)
    code = await _run_operator_bootstrap(env)
    t1 = await db_now(env)
    assert code == 0, "gostracker bootstrap завершился с ошибкой"

    # --- версия схемы и роли ---
    assert await alembic_versions(env) == [HEAD_REVISION]
    roles_after = await roles_by_login(env)
    assert roles_after[FORMER_MIXED] is None, "demo.mixed без роли"
    assert roles_after[FORMER_MIXED] != "tech_admin"
    assert {k: v for k, v in roles_after.items() if k != FORMER_MIXED} == EXPECTED_DEMO_ROLES
    assert list(roles_after.values()).count("tech_admin") == 2, "ТА: admin и demo.ta, без новых"
    assert "mixed" not in roles_after.values()

    # --- журнал: N + 1, запись «снятие роли» от «системы» ---
    journal_after = await audit_rows(env)
    assert len(journal_after) == n + 1
    assert journal_after[:n] == journal_before, "прежние записи журнала не изменены"
    (event,) = journal_after[n:]
    assert event.id > journal_before[-1].id
    assert event.action == "user.role_removed"
    assert event.actor_id is None, "автор записи - «система»"
    assert event.entity_type == "user"
    assert event.entity_id == id_of[FORMER_MIXED]
    assert event.in_audit is True
    assert list(event.changed_fields) == []
    assert event.project_id is None and event.deal_id is None and event.changes is None
    assert event.details == {"role_from": "mixed", "role_to": None}
    assert t0 <= event.occurred_at <= t1, f"{event.occurred_at} вне окна [{t0}, {t1}]"

    # --- updated_at: только у demo.mixed (равен времени записи), у остальных прежний ---
    updated_after = await member_updated_at(env)
    assert updated_after.keys() == updated_before.keys()
    former_key = (event.workspace_id, id_of[FORMER_MIXED])
    assert updated_after[former_key] == event.occurred_at
    for key, value in updated_before.items():
        if key != former_key:
            assert updated_after[key] == value, f"updated_at изменился у {key}"

    # --- участие в проектах, проекты, задачи, комментарии, пароли ---
    members_after = await env.execute(
        text(
            "SELECT p.name, u.login FROM project_member pm JOIN project p ON p.id = pm.project_id "
            "JOIN app_user u ON u.id = pm.user_id ORDER BY p.name, u.login"
        )
    )
    assert members_after is not None
    assert [tuple(r) for r in members_after] == member_pairs_before
    assert {p for p, login in member_pairs_before if login == FORMER_MIXED} == all_projects
    assert await _snapshot(env) == snapshot_before

    # --- вход прежними паролями; логины в ответах прежние ---
    for login, password in passwords.items():
        response = await env.login(login, password)
        assert response.status_code == 200, (login, response.text)
        body = response.json()
        assert body["user"]["login"] == login
        assert body["user"]["role"] == roles_after[login], login
    upper = await env.login("DEMO.MIXED", passwords[FORMER_MIXED])
    assert upper.status_code == 200
    assert upper.json()["user"]["login"] == FORMER_MIXED

    # --- логины в списке учётных записей и записи журнала в API ---
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
    assert {i["login"] for i in items} == set(passwords)
    assert {i["login"]: i["role"] for i in items} == roles_after

    audit = await env.client.get(AUDIT, params={"page_size": 100}, headers=env.auth(token))
    assert audit.status_code == 200, audit.text
    entries = audit.json()["items"]
    removed = [e for e in entries if e["action"] == "user.role_removed"]
    assert len(removed) == 1
    assert removed[0]["entity_id"] == str(id_of[FORMER_MIXED])
    assert removed[0]["actor"]["kind"] == "system"
