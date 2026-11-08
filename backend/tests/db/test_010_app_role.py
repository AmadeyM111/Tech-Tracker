"""D10-T01: рабочая роль БД (spec 010 FR-1, FR-2, FR-6; AC-1, AC-2, AC-3, AC-5).

Роль кластера получает уникальное имя на тест и удаляется (``DROP OWNED``, ``DROP ROLE``).
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.db_roles import ensure_app_role, scram_verifier
from tests.factories import make_domain_event, make_workspace

pytestmark = pytest.mark.committed


@pytest_asyncio.fixture
async def app_role(
    committed: Any, db_engine: AsyncEngine, test_database_url: str
) -> AsyncIterator[tuple[str, AsyncEngine]]:
    role = f"gt_app_t{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(32)
    async with db_engine.begin() as conn:
        await ensure_app_role(conn, role, scram_verifier(password))
    url = make_url(test_database_url).set(username=role, password=password)
    engine = create_async_engine(url, hide_parameters=True)
    try:
        yield role, engine
    finally:
        await engine.dispose()
        async with db_engine.begin() as conn:
            await conn.execute(text(f"DROP OWNED BY {role}"))
            await conn.execute(text(f"DROP ROLE {role}"))


async def _denied(engine: AsyncEngine, sql: str) -> str:
    with pytest.raises(DBAPIError) as err:
        async with engine.begin() as conn:
            await conn.execute(text(sql))
    return str(err.value.orig)


async def test_010_ac1_role_has_no_privileged_attributes_and_owns_nothing(
    app_role: tuple[str, AsyncEngine], db_engine: AsyncEngine
) -> None:
    role, _ = app_role
    async with db_engine.connect() as conn:
        attrs = (
            await conn.execute(
                text(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, "
                    "rolcanlogin FROM pg_roles WHERE rolname = :r"
                ),
                {"r": role},
            )
        ).one()
        owned = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
                    "WHERE r.rolname = :r"
                ),
                {"r": role},
            )
        ).scalar_one()
        verifier = (
            await conn.execute(
                text("SELECT rolpassword FROM pg_authid WHERE rolname = :r"), {"r": role}
            )
        ).scalar_one()
    assert tuple(attrs) == (False, False, False, False, False, True)
    assert owned == 0
    assert verifier.startswith("SCRAM-SHA-256$")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE domain_event SET action = action",
        "DELETE FROM domain_event",
        "TRUNCATE domain_event",
        "ALTER TABLE domain_event DISABLE TRIGGER ALL",
        "DROP TRIGGER trg_domain_event_forbid_update_delete ON domain_event",
    ],
    ids=["update", "delete", "truncate", "disable-trigger", "drop-trigger"],
)
async def test_010_ac2_journal_is_protected_from_app_role(
    app_role: tuple[str, AsyncEngine], sql: str
) -> None:
    _, engine = app_role
    message = await _denied(engine, sql)
    assert "permission denied" in message or "must be owner" in message


async def test_010_ac3_app_role_can_work_with_data(
    app_role: tuple[str, AsyncEngine], committed: Any
) -> None:
    role, engine = app_role
    async with committed() as s:
        ws = await make_workspace(s)
        await s.commit()
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT current_user"))).scalar_one() == role
        await conn.execute(text("SELECT count(*) FROM domain_event"))
        await conn.execute(
            text("UPDATE workspace SET updated_at = updated_at WHERE id = :i"), {"i": ws.id}
        )
        assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        event_id = await make_domain_event(s, workspace_id=ws.id)
        await s.commit()
    assert event_id


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE public.x (id int)",
        "TRUNCATE task",
        "UPDATE alembic_version SET version_num = version_num",
    ],
    ids=["create", "truncate", "alembic"],
)
async def test_010_ac3_app_role_cannot_change_schema(
    app_role: tuple[str, AsyncEngine], sql: str
) -> None:
    message = await _denied(app_role[1], sql)
    assert "permission denied" in message


async def test_010_ac5_new_table_gets_grants_on_rerun(
    app_role: tuple[str, AsyncEngine], db_engine: AsyncEngine
) -> None:
    role, engine = app_role
    async with db_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE public.gt_010_new (id int)"))
    await _denied(engine, "SELECT * FROM public.gt_010_new")
    async with db_engine.begin() as conn:
        await ensure_app_role(conn, role, scram_verifier(secrets.token_urlsafe(32)))
    # пароль сменён: новое подключение со старым паролем не нужно — проверяем права владельцем
    async with db_engine.connect() as conn:
        allowed = (
            await conn.execute(
                text("SELECT has_table_privilege(:r, 'public.gt_010_new', 'SELECT')"), {"r": role}
            )
        ).scalar_one()
        await conn.execute(text("DROP TABLE public.gt_010_new"))
        await conn.commit()
    assert allowed is True
