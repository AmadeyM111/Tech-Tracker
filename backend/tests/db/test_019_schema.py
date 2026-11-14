"""R8-T01: миграция 0010 и модели самостоятельной регистрации (spec 019, plan §4.1, RG-21).

Покрытие: ``app_user.first_name/last_name/self_registered``, таблицы ``registration_request`` и
``registration_attempt`` (типы, nullable, UNIQUE, CHECK, индексы, отсутствие FK), модели,
файл миграции, цикл upgrade 0009 -> 0010 -> downgrade -> upgrade на БД с пользователем,
чистый ``alembic check``. Основа для AC-36, AC-8, AC-13, AC-18, AC-22, AC-38.
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

from tests.db_support import ALEMBIC_INI, BACKEND_DIR, database_url_from_env, run_alembic
from tests.factories import DEFAULT_PASSWORD, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MIGRATION_0010 = BACKEND_DIR / "migrations" / "versions" / "0010_self_registration.py"
NOW = datetime(2026, 11, 8, 9, 0, 0, tzinfo=UTC)
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
TS = "timestamp with time zone"


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


_REQ_SQL = (
    "INSERT INTO registration_request (id, email, login, login_display, first_name, last_name, "
    "password_hash, token_hash, created_at, expires_at) "
    "VALUES (:id, :email, 'ivan', 'Ivan', 'Иван', 'Петров', 'hash', :th, :c, :e)"
)


def _req_params(**over: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid.uuid4(),
        "email": "new@example.test",
        "th": b"\x01" * 32,
        "c": NOW,
        "e": NOW + timedelta(minutes=30),
    }
    params.update(over)
    return params


_ATT_SQL = (
    "INSERT INTO registration_attempt (id, scope, key_hash, created_at) VALUES (:id, :s, :h, :c)"
)


def _att_params(**over: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"id": uuid.uuid4(), "s": "request_ip", "h": b"\x07" * 32, "c": NOW}
    params.update(over)
    return params


# --- файл миграции ------------------------------------------------------------------------


def test_019_migration_0010_file_chain_and_no_app_imports() -> None:
    """RG-21: ``revision="0010"``, ``down_revision="0009"``, upgrade/downgrade, без ``app.*``,
    docstring со ссылкой на spec 019, голова цепочки одна и равна 0010."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    assert MIGRATION_0010.is_file(), "нет backend/migrations/versions/0010_self_registration.py"
    tree = ast.parse(MIGRATION_0010.read_text(encoding="utf-8"))
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
    assert values.get("revision") == "0010"
    assert values.get("down_revision") == "0009"
    assert {"upgrade", "downgrade"} <= {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("app"), "миграция импортирует app.*"
        if isinstance(node, ast.Import):
            assert all(not a.name.startswith("app") for a in node.names)
    assert "019" in (ast.get_docstring(tree) or ""), "docstring без ссылки на spec 019"
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    assert script.get_heads() == ["0015"]  # 009: голова 0014 (цепочка 0012 -> 0013)


# --- схема на head ------------------------------------------------------------------------


@pytest.mark.committed
async def test_019_schema_app_user_new_columns(committed: Any) -> None:
    """plan §4.1: ``first_name``/``last_name`` varchar(100) NULL, ``self_registered`` boolean
    NOT NULL DEFAULT false."""
    cols = await _columns(committed, "app_user")
    assert cols.get("first_name") == ("character varying", "YES", 100), cols.get("first_name")
    assert cols.get("last_name") == ("character varying", "YES", 100), cols.get("last_name")
    assert cols.get("self_registered") == ("boolean", "NO", None), cols.get("self_registered")
    async with committed() as s:
        default = (
            await s.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name = 'app_user' AND column_name = 'self_registered'"
                )
            )
        ).scalar_one_or_none()
    assert default == "false"


@pytest.mark.committed
async def test_019_schema_registration_request_columns(committed: Any) -> None:
    """plan §4.1: типы и nullable ``registration_request``."""
    assert await _columns(committed, "registration_request") == {
        "id": ("uuid", "NO", None),
        "email": ("character varying", "NO", 254),
        "login": ("character varying", "NO", 64),
        "login_display": ("character varying", "NO", 64),
        "first_name": ("character varying", "NO", 100),
        "last_name": ("character varying", "NO", 100),
        "password_hash": ("text", "NO", None),
        "token_hash": ("bytea", "NO", None),
        "created_at": (TS, "NO", None),
        "expires_at": (TS, "NO", None),
    }


@pytest.mark.committed
async def test_019_schema_registration_attempt_columns(committed: Any) -> None:
    """plan §4.1: типы и nullable ``registration_attempt``."""
    assert await _columns(committed, "registration_attempt") == {
        "id": ("uuid", "NO", None),
        "scope": ("text", "NO", None),
        "key_hash": ("bytea", "NO", None),
        "created_at": (TS, "NO", None),
    }


@pytest.mark.committed
async def test_019_schema_named_constraints_indexes_no_fk(committed: Any) -> None:
    """plan §4.1: имена ограничений и индексов; FK у новых таблиц нет."""
    async with committed() as s:
        cons = set((await s.execute(text("SELECT conname FROM pg_constraint"))).scalars())
        idx = set(
            (
                await s.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
                )
            ).scalars()
        )
        fks = (
            await s.execute(
                text(
                    "SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND conrelid IN "
                    "(to_regclass('registration_request'), to_regclass('registration_attempt'))"
                )
            )
        ).scalar_one()
    assert {
        "uq_registration_request_email",
        "ck_registration_request_email_lower",
        "uq_registration_request_token_hash",
        "ck_registration_request_token_hash_length",
        "ck_registration_attempt_scope_valid",
        "ck_registration_attempt_key_hash_length",
    } <= cons
    assert {
        "ix_registration_request_expires_at",
        "ix_registration_attempt_scope_key_hash_created_at",
        "ix_registration_attempt_created_at",
    } <= idx
    assert fks == 0


# --- app_user: значения по умолчанию ------------------------------------------------------


async def test_019_make_user_defaults(db: AsyncSession) -> None:
    """``make_user`` без новых аргументов: имена NULL, ``self_registered`` false."""
    user = await make_user(db)
    row = (
        await db.execute(
            text("SELECT first_name, last_name, self_registered FROM app_user WHERE id = :i"),
            {"i": user.id},
        )
    ).one()
    assert tuple(row) == (None, None, False)


async def test_019_make_user_stores_names_and_flag(db: AsyncSession) -> None:
    """``make_user(first_name=, last_name=, self_registered=True)`` пишет значения."""
    user = await make_user(db, first_name="Иван", last_name="Петров", self_registered=True)
    row = (
        await db.execute(
            text("SELECT first_name, last_name, self_registered FROM app_user WHERE id = :i"),
            {"i": user.id},
        )
    ).one()
    assert tuple(row) == ("Иван", "Петров", True)


async def test_019_server_default_self_registered_false(db: AsyncSession) -> None:
    """``server_default`` false: вставка без колонки даёт false (а не NULL/ошибку)."""
    await make_user(db, login="srvdef")
    uid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO app_user (id, login, login_display, password_hash, must_change_password, "
            "is_blocked, failed_login_count, password_changed_at, created_at, updated_at) "
            "VALUES (:i, 'rawuser', 'rawuser', 'h', false, false, 0, :n, :n, :n)"
        ),
        {"i": uid, "n": NOW},
    )
    flag = (
        await db.execute(text("SELECT self_registered FROM app_user WHERE id = :i"), {"i": uid})
    ).scalar_one()
    assert flag is False


async def test_019_name_length_100_ok_101_rejected(db: AsyncSession) -> None:
    """varchar(100): 100 символов принимается, 101 отвергается."""
    await make_user(db, first_name="а" * 100, last_name="б" * 100)
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await make_user(db, first_name="а" * 101)
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await make_user(db, last_name="б" * 101)


# --- registration_request -----------------------------------------------------------------


async def test_019_request_insert_ok(db: AsyncSession) -> None:
    """Корректная заявка вставляется."""
    await db.execute(text(_REQ_SQL), _req_params())
    count = (await db.execute(text("SELECT count(*) FROM registration_request"))).scalar_one()
    assert count == 1


async def test_019_request_email_unique(db: AsyncSession) -> None:
    """AC-8 (основа): ``UNIQUE(email)``."""
    await db.execute(text(_REQ_SQL), _req_params())
    await _rejected(db, _REQ_SQL, _req_params(th=b"\x02" * 32), UNIQUE_VIOLATION)


async def test_019_request_token_hash_unique(db: AsyncSession) -> None:
    """``UNIQUE(token_hash)``."""
    await db.execute(text(_REQ_SQL), _req_params())
    await _rejected(db, _REQ_SQL, _req_params(email="other@example.test"), UNIQUE_VIOLATION)


async def test_019_request_email_check_rejects_uppercase(db: AsyncSession) -> None:
    """CHECK ``lower(email COLLATE "C") = email`` отвергает ``A@x.ru``."""
    await _rejected(db, _REQ_SQL, _req_params(email="A@x.ru"), CHECK_VIOLATION)


@pytest.mark.parametrize("size", [0, 31, 33])
async def test_019_request_token_hash_must_be_32_bytes(db: AsyncSession, size: int) -> None:
    """CHECK ``octet_length(token_hash) = 32``."""
    await _rejected(db, _REQ_SQL, _req_params(th=b"\x03" * size), CHECK_VIOLATION)


async def test_019_request_email_length_254_ok_255_rejected(db: AsyncSession) -> None:
    """varchar(254)."""
    await db.execute(text(_REQ_SQL), _req_params(email="a" * 242 + "@example.com"))
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(
                text(_REQ_SQL), _req_params(email="b" * 243 + "@example.com", th=b"\x09" * 32)
            )


# --- registration_attempt -----------------------------------------------------------------


@pytest.mark.parametrize("scope", ["request_ip", "confirm_ip", "confirm_token"])
async def test_019_attempt_accepts_known_scopes(db: AsyncSession, scope: str) -> None:
    """``scope`` из трёх значений принимается."""
    await db.execute(text(_ATT_SQL), _att_params(s=scope))


@pytest.mark.parametrize("scope", ["", "email", "ip", "REQUEST_IP", "confirm_ip "])
async def test_019_attempt_scope_check_rejects_other(db: AsyncSession, scope: str) -> None:
    """CHECK ``scope IN (...)`` отвергает остальное."""
    await _rejected(db, _ATT_SQL, _att_params(s=scope), CHECK_VIOLATION)


@pytest.mark.parametrize("size", [0, 31, 33])
async def test_019_attempt_key_hash_must_be_32_bytes(db: AsyncSession, size: int) -> None:
    """CHECK ``octet_length(key_hash) = 32``."""
    await _rejected(db, _ATT_SQL, _att_params(h=b"\x07" * size), CHECK_VIOLATION)


# --- модели (Base.metadata) ---------------------------------------------------------------


def test_019_models_declare_new_columns_and_tables() -> None:
    """Модели объявляют те же объекты, что миграция (``alembic check`` чист)."""
    import app.domain.registry  # noqa: F401  (регистрирует все модели)
    from app.core.models import Base

    tables = Base.metadata.tables
    user = tables["app_user"]
    assert user.c.first_name.nullable is True
    assert user.c.last_name.nullable is True
    assert user.c.first_name.type.length == 100
    assert user.c.last_name.type.length == 100
    assert user.c.self_registered.nullable is False
    assert user.c.self_registered.server_default is not None
    assert {"registration_request", "registration_attempt"} <= set(tables)
    assert set(tables["registration_request"].c.keys()) == {
        "id",
        "email",
        "login",
        "login_display",
        "first_name",
        "last_name",
        "password_hash",
        "token_hash",
        "created_at",
        "expires_at",
    }
    assert set(tables["registration_attempt"].c.keys()) == {
        "id",
        "scope",
        "key_hash",
        "created_at",
    }
    assert not tables["registration_request"].foreign_keys
    assert not tables["registration_attempt"].foreign_keys


def test_019_models_exported_from_auth_and_users() -> None:
    """``RegistrationRequest``, ``RegistrationAttempt`` - в ``app.domain.auth.models``;
    поля ``AppUser`` - в ``app.domain.users.models``."""
    from app.domain.auth.models import RegistrationAttempt, RegistrationRequest
    from app.domain.users.models import AppUser

    assert RegistrationRequest.__tablename__ == "registration_request"
    assert RegistrationAttempt.__tablename__ == "registration_attempt"
    for name in ("first_name", "last_name", "self_registered"):
        assert hasattr(AppUser, name), name


# --- upgrade / downgrade ------------------------------------------------------------------


@pytest.mark.committed
async def test_019_upgrade_downgrade_upgrade_cycle_and_alembic_check(
    committed: Any, db_engine: Any, test_database_url: str
) -> None:
    """AC-36: head(0010) -> downgrade 0009 (колонки и таблицы исчезли, пользователь цел) ->
    upgrade head: имена NULL, ``self_registered=false``, прочие колонки прежние, пароль
    проверяется; ``alembic check`` чист."""
    assert await _version(committed) == ["0015"]
    async with committed() as s, s.begin():
        user = await make_user(
            s, role="tech_admin", login="Keeper", email="keep@example.test", first_name="Имя"
        )

    other_sql = text(
        "SELECT id, login, login_display, password_hash, must_change_password, is_blocked, "
        "failed_login_count, password_changed_at, created_at, email FROM app_user WHERE id = :i"
    )
    async with committed() as s:
        before = tuple((await s.execute(other_sql, {"i": user.id})).one())

    await _alembic_ok(test_database_url, "downgrade", "0009")
    await db_engine.dispose()
    assert await _version(committed) == ["0009"]
    cols = await _columns(committed, "app_user")
    assert not {"first_name", "last_name", "self_registered"} & set(cols)
    assert await _columns(committed, "registration_request") == {}
    assert await _columns(committed, "registration_attempt") == {}
    async with committed() as s:
        assert tuple((await s.execute(other_sql, {"i": user.id})).one()) == before

    await _alembic_ok(test_database_url, "upgrade", "head")
    await db_engine.dispose()
    assert await _version(committed) == ["0015"]
    async with committed() as s:
        row = (
            await s.execute(
                text("SELECT first_name, last_name, self_registered FROM app_user WHERE id = :i"),
                {"i": user.id},
            )
        ).one()
        assert tuple(row) == (None, None, False)
        assert tuple((await s.execute(other_sql, {"i": user.id})).one()) == before
        stored_hash = before[3]
    from argon2 import PasswordHasher

    assert PasswordHasher().verify(stored_hash, DEFAULT_PASSWORD)
    assert set(await _columns(committed, "registration_request")) >= {"email", "token_hash"}
    assert set(await _columns(committed, "registration_attempt")) >= {"scope", "key_hash"}
    await _alembic_ok(database_url_from_env(), "check")
