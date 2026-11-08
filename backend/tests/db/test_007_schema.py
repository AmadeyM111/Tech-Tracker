"""R7-T01: миграция 0008 и модели сброса пароля по email (spec 007, NFR-4; plan §4.1, PR-1, PR-7).

Покрытие: ``app_user.email`` (varchar(254) NULL, UNIQUE, CHECK нижнего регистра), таблицы
``password_reset_token`` и ``password_reset_attempt`` (типы, nullable, CHECK длины хешей и
``scope``, каскад FK, индексы), цикл upgrade 0007 -> 0008 -> downgrade -> upgrade, чистый
``alembic check``, файл миграции без импорта ``app.*``. Основа для AC-1, AC-5, AC-10.
"""

from __future__ import annotations

import ast
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.db_support import BACKEND_DIR, database_url_from_env, run_alembic
from tests.factories import make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MIGRATION_0008 = BACKEND_DIR / "migrations" / "versions" / "0008_password_reset_email.py"
NOW = datetime(2026, 11, 5, 9, 0, 0, tzinfo=UTC)
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"


def _sqlstate(exc: DBAPIError) -> str | None:
    orig: Any = exc.orig
    for obj in (orig, getattr(orig, "__cause__", None)):
        code = getattr(obj, "sqlstate", None) or getattr(obj, "pgcode", None)
        if code:
            return str(code)
    return None


async def _rejected(db: AsyncSession, sql: str, params: dict[str, Any], sqlstate: str) -> None:
    """Оператор отклонён БД с данным SQLSTATE; сессия остаётся рабочей (SAVEPOINT)."""
    with pytest.raises(DBAPIError) as info:
        async with db.begin_nested():
            await db.execute(text(sql), params)
    assert _sqlstate(info.value) == sqlstate, f"ожидали {sqlstate}, получили: {info.value!r}"


async def _columns(maker: Any, table: str) -> dict[str, tuple[str, str, int | None]]:
    async with maker() as s:
        rows = await s.execute(
            text(
                "SELECT column_name, data_type, is_nullable, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t"
            ),
            {"t": table},
        )
        return {r[0]: (r[1], r[2], r[3]) for r in rows}


async def _version(maker: Any) -> list[str]:
    async with maker() as s:
        return list((await s.execute(text("SELECT version_num FROM alembic_version"))).scalars())


async def _alembic_ok(url: str, *args: str) -> None:
    result = await asyncio.to_thread(run_alembic, url, *args)
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
    )


async def _insert_token(db: AsyncSession, user_id: uuid.UUID, token_hash: bytes) -> None:
    await db.execute(
        text(
            "INSERT INTO password_reset_token (id, user_id, token_hash, created_at, expires_at) "
            "VALUES (:id, :u, :h, :c, :e)"
        ),
        {
            "id": uuid.uuid4(),
            "u": user_id,
            "h": token_hash,
            "c": NOW,
            "e": NOW + timedelta(hours=1),
        },
    )


# --- файл миграции ------------------------------------------------------------------------


def test_007_migration_0008_file_chain_and_no_app_imports() -> None:
    """NFR-4: файл 0008 на месте, ``revision="0008"``, ``down_revision="0007"``, есть upgrade и
    downgrade, импорта ``app.*`` нет, голова цепочки одна и равна 0008."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from tests.db_support import ALEMBIC_INI

    assert MIGRATION_0008.is_file(), "нет backend/migrations/versions/0008_password_reset_email.py"
    source = MIGRATION_0008.read_text(encoding="utf-8")
    tree = ast.parse(source)
    values: dict[str, Any] = {}
    for n in tree.body:
        if (
            isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name)
            and isinstance(n.value, ast.Constant)
        ):
            values[n.target.id] = n.value.value
        elif isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    values[t.id] = n.value.value
    assert values.get("revision") == "0008"
    assert values.get("down_revision") == "0007"
    assert {"upgrade", "downgrade"} <= {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("app"), "миграция импортирует app.*"
        if isinstance(node, ast.Import):
            assert all(not a.name.startswith("app") for a in node.names)
    assert "007" in (ast.get_docstring(tree) or ""), "docstring без ссылки на spec 007"
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    assert script.get_heads() == ["0012"]  # 011: голова 0012


# --- схема на head ------------------------------------------------------------------------


@pytest.mark.committed
async def test_007_schema_app_user_email_column(committed: Any) -> None:
    """plan §4.1: ``app_user.email`` varchar(254) NULL."""
    cols = await _columns(committed, "app_user")
    assert cols.get("email") == ("character varying", "YES", 254), cols.get("email")


@pytest.mark.committed
async def test_007_schema_reset_token_columns(committed: Any) -> None:
    """plan §4.1: типы и nullable ``password_reset_token``."""
    cols = await _columns(committed, "password_reset_token")
    assert cols == {
        "id": ("uuid", "NO", None),
        "user_id": ("uuid", "NO", None),
        "token_hash": ("bytea", "NO", None),
        "created_at": ("timestamp with time zone", "NO", None),
        "expires_at": ("timestamp with time zone", "NO", None),
        "used_at": ("timestamp with time zone", "YES", None),
    }


@pytest.mark.committed
async def test_007_schema_reset_attempt_columns(committed: Any) -> None:
    """plan §4.1: типы и nullable ``password_reset_attempt``."""
    cols = await _columns(committed, "password_reset_attempt")
    assert cols == {
        "id": ("uuid", "NO", None),
        "scope": ("text", "NO", None),
        "key_hash": ("bytea", "NO", None),
        "created_at": ("timestamp with time zone", "NO", None),
    }


@pytest.mark.committed
async def test_007_schema_named_constraints_and_indexes(committed: Any) -> None:
    """plan §4.1: имена по naming convention (PR-1, PR-7)."""
    async with committed() as s:
        cons = set((await s.execute(text("SELECT conname FROM pg_constraint"))).scalars())
        idx = set(
            (
                await s.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
                )
            ).scalars()
        )
    assert {"uq_app_user_email", "ck_app_user_email_lower"} <= cons
    assert "uq_password_reset_token_token_hash" in cons
    assert "ix_password_reset_token_user_id" in idx
    assert "ix_password_reset_attempt_scope_key_hash_created_at" in idx
    assert "ix_password_reset_attempt_created_at" in idx


@pytest.mark.committed
async def test_007_schema_token_user_fk_cascade_deferrable(committed: Any) -> None:
    """plan §4.1: FK ``user_id`` ON DELETE CASCADE, DEFERRABLE INITIALLY IMMEDIATE."""
    async with committed() as s:
        row = (
            await s.execute(
                text(
                    "SELECT confdeltype::text, condeferrable, condeferred FROM pg_constraint "
                    "WHERE contype = 'f' AND conrelid = 'password_reset_token'::regclass"
                )
            )
        ).all()
    assert [tuple(r) for r in row] == [("c", True, False)]


# --- UNIQUE и CHECK email -----------------------------------------------------------------


async def test_007_email_unique_rejects_duplicate(db: AsyncSession) -> None:
    """AC-1 (основа): два одинаковых адреса - нарушение UNIQUE."""
    await make_user(db, email="dup@example.test")
    with pytest.raises(DBAPIError) as info:
        async with db.begin_nested():
            await make_user(db, email="dup@example.test")
    assert _sqlstate(info.value) == UNIQUE_VIOLATION


async def test_007_email_allows_many_nulls(db: AsyncSession) -> None:
    """AC-1 (основа): сколько угодно пользователей без email (NULL не конфликтует)."""
    await make_user(db)
    await make_user(db, email=None)
    await make_user(db)
    count = (
        await db.execute(text("SELECT count(*) FROM app_user WHERE email IS NULL"))
    ).scalar_one()
    assert count >= 3


async def test_007_email_make_user_stores_email_as_passed(db: AsyncSession) -> None:
    """``make_user(email=...)`` пишет значение как передано."""
    user = await make_user(db, email="stored@example.test")
    stored = (
        await db.execute(text("SELECT email FROM app_user WHERE id = :i"), {"i": user.id})
    ).scalar_one()
    assert stored == "stored@example.test"


async def test_007_email_check_rejects_uppercase(db: AsyncSession) -> None:
    """PR-1: CHECK ``lower(email COLLATE "C") = email`` отвергает ``A@x.ru``."""
    with pytest.raises(DBAPIError) as info:
        async with db.begin_nested():
            await make_user(db, email="A@x.ru")
    assert _sqlstate(info.value) == CHECK_VIOLATION


async def test_007_email_check_accepts_lowercase(db: AsyncSession) -> None:
    """PR-1: нижний регистр проходит CHECK."""
    user = await make_user(db, email="a@x.ru")
    assert user.id is not None


async def test_007_email_length_254_ok_255_rejected(db: AsyncSession) -> None:
    """plan §4.1: varchar(254) - 254 символа принимается, 255 отвергается."""
    ok = "a" * 242 + "@example.com"  # 254
    assert len(ok) == 254
    await make_user(db, email=ok)
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await make_user(db, email="b" * 243 + "@example.com")


# --- token / attempt ----------------------------------------------------------------------


async def test_007_token_hash_must_be_32_bytes(db: AsyncSession) -> None:
    """CHECK ``octet_length(token_hash) = 32``: 31 и 33 байта отвергаются, 32 - нет."""
    user = await make_user(db)
    await _insert_token(db, user.id, b"\x01" * 32)
    for size in (0, 31, 33):
        with pytest.raises(DBAPIError) as info:
            async with db.begin_nested():
                await _insert_token(db, user.id, b"\x02" * size)
        assert _sqlstate(info.value) == CHECK_VIOLATION, size


async def test_007_token_hash_unique(db: AsyncSession) -> None:
    """``token_hash`` UNIQUE."""
    user = await make_user(db)
    await _insert_token(db, user.id, b"\x03" * 32)
    with pytest.raises(DBAPIError) as info:
        async with db.begin_nested():
            await _insert_token(db, user.id, b"\x03" * 32)
    assert _sqlstate(info.value) == UNIQUE_VIOLATION


async def test_007_token_cascades_on_user_delete(db: AsyncSession) -> None:
    """AC-5/AC-10 (основа): удаление пользователя каскадно удаляет только его токены."""
    victim = await make_user(db)
    other = await make_user(db)
    await _insert_token(db, victim.id, b"\x04" * 32)
    await _insert_token(db, victim.id, b"\x05" * 32)
    await _insert_token(db, other.id, b"\x06" * 32)
    await db.execute(text("DELETE FROM workspace_member WHERE user_id = :u"), {"u": victim.id})
    await db.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": victim.id})
    left = (await db.execute(text("SELECT user_id FROM password_reset_token"))).scalars().all()
    assert left == [other.id]


@pytest.mark.parametrize("size", [0, 31, 33])
async def test_007_attempt_key_hash_must_be_32_bytes(db: AsyncSession, size: int) -> None:
    """PR-7: CHECK ``octet_length(key_hash) = 32``."""
    await _rejected(
        db,
        "INSERT INTO password_reset_attempt (id, scope, key_hash, created_at) "
        "VALUES (:id, 'email', :h, :c)",
        {"id": uuid.uuid4(), "h": b"\x07" * size, "c": NOW},
        CHECK_VIOLATION,
    )


@pytest.mark.parametrize("scope", ["email", "ip"])
async def test_007_attempt_accepts_known_scopes(db: AsyncSession, scope: str) -> None:
    """PR-7: ``scope`` из ('email', 'ip') принимается."""
    await db.execute(
        text(
            "INSERT INTO password_reset_attempt (id, scope, key_hash, created_at) "
            "VALUES (:id, :s, :h, :c)"
        ),
        {"id": uuid.uuid4(), "s": scope, "h": b"\x08" * 32, "c": NOW},
    )


@pytest.mark.parametrize("scope", ["", "user", "EMAIL", "ip "])
async def test_007_attempt_scope_check_rejects_other(db: AsyncSession, scope: str) -> None:
    """PR-7: CHECK ``scope IN ('email','ip')`` отвергает остальное."""
    await _rejected(
        db,
        "INSERT INTO password_reset_attempt (id, scope, key_hash, created_at) "
        "VALUES (:id, :s, :h, :c)",
        {"id": uuid.uuid4(), "s": scope, "h": b"\x09" * 32, "c": NOW},
        CHECK_VIOLATION,
    )


# --- модели (Base.metadata) ---------------------------------------------------------------


def test_007_models_declare_email_and_reset_tables() -> None:
    """Модели объявляют те же объекты, что миграция (``alembic check`` чист)."""
    import app.domain.registry  # noqa: F401  (регистрирует все модели)
    from app.core.models import Base

    tables = Base.metadata.tables
    assert "email" in tables["app_user"].c
    assert tables["app_user"].c.email.nullable is True
    assert {"password_reset_token", "password_reset_attempt"} <= set(tables)
    assert set(tables["password_reset_token"].c.keys()) == {
        "id",
        "user_id",
        "token_hash",
        "created_at",
        "expires_at",
        "used_at",
    }
    assert set(tables["password_reset_attempt"].c.keys()) == {
        "id",
        "scope",
        "key_hash",
        "created_at",
    }


def test_007_models_exported_from_auth_and_users() -> None:
    """``PasswordResetToken``, ``PasswordResetAttempt`` - в ``app.domain.auth.models``;
    ``AppUser.email`` - в ``app.domain.users.models``."""
    from app.domain.auth.models import PasswordResetAttempt, PasswordResetToken
    from app.domain.users.models import AppUser

    assert PasswordResetToken.__tablename__ == "password_reset_token"
    assert PasswordResetAttempt.__tablename__ == "password_reset_attempt"
    assert hasattr(AppUser, "email")


# --- upgrade / downgrade ------------------------------------------------------------------


@pytest.mark.committed
async def test_007_upgrade_downgrade_upgrade_cycle_and_alembic_check(
    committed: Any, db_engine: Any, test_database_url: str
) -> None:
    """NFR-4: head(0008) -> downgrade 0007 (email и таблицы исчезли, пользователь цел) ->
    upgrade head (всё вернулось, email NULL) -> ``alembic check`` чист."""
    assert await _version(committed) == ["0012"]
    async with committed() as s, s.begin():
        user = await make_user(s, role="tech_admin", email="keep@example.test")

    await _alembic_ok(test_database_url, "downgrade", "0007")
    await db_engine.dispose()
    assert await _version(committed) == ["0007"]
    assert "email" not in await _columns(committed, "app_user")
    assert await _columns(committed, "password_reset_token") == {}
    assert await _columns(committed, "password_reset_attempt") == {}
    async with committed() as s:
        assert (
            await s.execute(text("SELECT count(*) FROM app_user WHERE id = :i"), {"i": user.id})
        ).scalar_one() == 1

    await _alembic_ok(test_database_url, "upgrade", "head")
    await db_engine.dispose()
    assert await _version(committed) == ["0012"]
    assert (await _columns(committed, "app_user")).get("email") == (
        "character varying",
        "YES",
        254,
    )
    assert set(await _columns(committed, "password_reset_token")) >= {"token_hash", "used_at"}
    assert set(await _columns(committed, "password_reset_attempt")) >= {"scope", "key_hash"}
    async with committed() as s:
        email = (
            await s.execute(text("SELECT email FROM app_user WHERE id = :i"), {"i": user.id})
        ).scalar_one()
    assert email is None
    await _alembic_ok(database_url_from_env(), "check")
