"""R7-T02: миграция 0008 (spec 007 FR-1, FR-6, FR-30, NFR-7; plan §4.1, PD-1, PD-9).

``app_user.is_agent``, таблица ``api_key`` (в БД только SHA-256 секрета),
``domain_event.api_key_id``.
Структурные проверки идут в откатываемой транзакции (``db``), цикл миграций - ``committed``
(как ``test_priority_upgrade_006.py``): head -> ``downgrade 0007`` -> ``upgrade head``.
Секрет ключа в сообщения ``assert`` не попадает.
"""

from __future__ import annotations

import ast
import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.db_support import BACKEND_DIR
from tests.factories import make_api_key, make_domain_event, make_user, make_workspace
from tests.upgrade002_support import alembic_ok, alembic_versions

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.conftest import ApiEnv

MIGRATION_0008 = BACKEND_DIR / "migrations" / "versions" / "0008_agent_api_keys.py"
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"
FK_VIOLATION = "23503"
T0 = datetime(2026, 10, 30, 9, 0, 0, tzinfo=UTC)

API_KEY_COLUMNS: dict[str, tuple[str, str]] = {
    "id": ("uuid", "NO"),
    "workspace_id": ("uuid", "NO"),
    "user_id": ("uuid", "NO"),
    "name": ("text", "NO"),
    "secret_digest": ("bytea", "NO"),
    "created_at": ("timestamp with time zone", "NO"),
    "created_by": ("uuid", "NO"),
    "expires_at": ("timestamp with time zone", "NO"),
    "revoked_at": ("timestamp with time zone", "YES"),
    "revoked_by": ("uuid", "YES"),
    "last_used_at": ("timestamp with time zone", "YES"),
    "rate_window_start": ("timestamp with time zone", "YES"),
    "rate_count": ("integer", "NO"),
}


# --- помощники ----------------------------------------------------------------------------


def _sqlstate(exc: IntegrityError) -> str | None:
    orig: Any = exc.orig
    return getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "__cause__", None), "sqlstate", None
    )


async def _expect_sqlstate(db: AsyncSession, sql: str, params: dict[str, Any], state: str) -> None:
    """Оператор отклонён БД с данным SQLSTATE; сессия жива (SAVEPOINT)."""
    with pytest.raises(IntegrityError) as info:
        async with db.begin_nested():
            await db.execute(text(sql), params)
    assert _sqlstate(info.value) == state, f"ожидали {state}, получили {_sqlstate(info.value)}"


async def _world(db: AsyncSession) -> dict[str, Any]:
    ws = await make_workspace(db)
    ta = await make_user(db, workspace=ws, role="tech_admin", login="u007.ta")
    agent = await make_user(db, workspace=ws, role="user", login="u007.agent", is_agent=True)
    return {"ws": ws, "ta": ta, "agent": agent}


_INSERT_KEY = (
    "INSERT INTO api_key (id, workspace_id, user_id, name, secret_digest, created_at, "
    "created_by, expires_at, revoked_at, revoked_by, rate_count) "
    "VALUES (:id, :ws, :u, :name, :digest, :created, :ta, :expires, :rev_at, :rev_by, :rate)"
)


def _key_params(w: dict[str, Any], **over: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid.uuid4(),
        "ws": w["ws"].id,
        "u": w["agent"].id,
        "name": "claude-laptop",
        "digest": hashlib.sha256(uuid.uuid4().bytes).digest(),
        "created": T0,
        "ta": w["ta"].id,
        "expires": T0 + timedelta(days=90),
        "rev_at": None,
        "rev_by": None,
        "rate": 0,
    }
    params.update(over)
    return params


async def _columns(db: AsyncSession, table: str) -> dict[str, tuple[str, str, str | None]]:
    rows = await db.execute(
        text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return {r.column_name: (r.data_type, r.is_nullable, r.column_default) for r in rows}


# --- файл миграции ------------------------------------------------------------------------


def test_007_migration_0008_file_chain_and_literals_only() -> None:
    """NFR-7, plan §4.1: ``revision="0008"``, ``down_revision="0007"``, upgrade/downgrade,
    без импорта кода приложения; имена ограничений по NAMING_CONVENTION."""
    assert MIGRATION_0008.is_file(), "нет backend/migrations/versions/0008_agent_api_keys.py"
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
            assert not any(a.name.startswith("app") for a in node.names)
    for name in (
        "ck_api_key_name_length",
        "ck_api_key_digest_length",
        "ck_api_key_expires_after_created",
        "ck_api_key_rate_count_nonnegative",
        "ck_api_key_revoked_pair",
        "uq_api_key_secret_digest",
        "ix_api_key_workspace_id_user_id",
    ):
        assert name in source, f"в миграции нет имени {name}"


# --- FR-1: признак агента -----------------------------------------------------------------


async def test_007_fr1_is_agent_column_boolean_not_null_default_false(db: AsyncSession) -> None:
    cols = await _columns(db, "app_user")
    assert "is_agent" in cols, "нет столбца app_user.is_agent"
    data_type, nullable, default = cols["is_agent"]
    assert (data_type, nullable) == ("boolean", "NO")
    assert default is not None and default.lower() == "false"


async def test_007_fr1_user_inserted_without_flag_is_not_agent(db: AsyncSession) -> None:
    """Вставка без ``is_agent`` (как делали прежние версии кода) даёт ``false``."""
    w = await _world(db)
    flags = {
        r.id: r.is_agent
        for r in await db.execute(text("SELECT id, is_agent FROM app_user"))
        if r.id in {w["ta"].id, w["agent"].id}
    }
    assert flags == {w["ta"].id: False, w["agent"].id: True}
    plain = await make_user(db, workspace=w["ws"], role="user")
    value = (
        await db.execute(text("SELECT is_agent FROM app_user WHERE id = :i"), {"i": plain.id})
    ).scalar_one()
    assert value is False


# --- NFR-7: структура api_key -------------------------------------------------------------


async def test_007_nfr7_api_key_columns_types_nullability(db: AsyncSession) -> None:
    cols = await _columns(db, "api_key")
    assert cols, "таблицы api_key нет"
    assert {k: (v[0], v[1]) for k, v in cols.items()} == API_KEY_COLUMNS
    assert cols["rate_count"][2] is not None and cols["rate_count"][2].strip("()") == "0"


async def test_007_nfr7_api_key_constraints_and_index_names(db: AsyncSession) -> None:
    rows = await db.execute(
        text(
            "SELECT conname, contype::text AS contype FROM pg_constraint "
            "WHERE conrelid = to_regclass('public.api_key')"
        )
    )
    found = {(r.conname, r.contype) for r in rows}
    assert found >= {
        ("ck_api_key_name_length", "c"),
        ("ck_api_key_digest_length", "c"),
        ("ck_api_key_expires_after_created", "c"),
        ("ck_api_key_rate_count_nonnegative", "c"),
        ("ck_api_key_revoked_pair", "c"),
        ("uq_api_key_secret_digest", "u"),
        ("pk_api_key", "p"),
    }
    idx = (
        await db.execute(
            text(
                "SELECT pg_get_indexdef(indexrelid) FROM pg_index "
                "JOIN pg_class c ON c.oid = indexrelid WHERE c.relname = :n"
            ),
            {"n": "ix_api_key_workspace_id_user_id"},
        )
    ).scalar_one_or_none()
    assert idx is not None, "нет индекса ix_api_key_workspace_id_user_id"
    assert re.search(r"\(workspace_id, user_id\)", str(idx)), idx


async def test_007_nfr7_api_key_foreign_keys_restrict(db: AsyncSession) -> None:
    rows = await db.execute(
        text(
            "SELECT a.attname AS col, c.confrelid::regclass::text AS target, "
            "c.confdeltype::text AS deltype, c.condeferrable AS deferrable "
            "FROM pg_constraint c JOIN pg_attribute a "
            "ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
            "WHERE c.contype = 'f' AND c.conrelid = to_regclass('public.api_key')"
        )
    )
    fks = {r.col: (r.target.split(".")[-1], r.deltype, r.deferrable) for r in rows}
    assert fks == {
        "workspace_id": ("workspace", "r", True),
        "user_id": ("app_user", "r", True),
        "created_by": ("app_user", "r", True),
        "revoked_by": ("app_user", "r", True),
    }


async def test_007_fr30_domain_event_api_key_id_column_and_fk(db: AsyncSession) -> None:
    cols = await _columns(db, "domain_event")
    assert "api_key_id" in cols, "нет столбца domain_event.api_key_id"
    assert cols["api_key_id"][:2] == ("uuid", "YES")
    assert cols["api_key_id"][2] is None, "у api_key_id не должно быть DEFAULT"
    row = (
        await db.execute(
            text(
                "SELECT c.confrelid::regclass::text AS target, c.confdeltype::text AS deltype, "
                "c.condeferrable AS deferrable FROM pg_constraint c "
                "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
                "WHERE c.contype = 'f' AND a.attname = 'api_key_id' "
                "AND c.conrelid = 'public.domain_event'::regclass"
            )
        )
    ).one()
    assert (row.target.split(".")[-1], row.deltype, row.deferrable) == ("api_key", "r", True)


# --- CHECK -> 23514 -----------------------------------------------------------------------


async def test_007_nfr7_valid_key_row_is_accepted_with_boundary_values(db: AsyncSession) -> None:
    """Контрольная вставка: граничные допустимые значения проходят (тесты отказов не пустые)."""
    w = await _world(db)
    for name in ("к", "x" * 100):
        await db.execute(text(_INSERT_KEY), _key_params(w, name=name))
    await db.execute(
        text(_INSERT_KEY),
        _key_params(w, expires=T0 + timedelta(microseconds=1), rate=0),
    )
    await db.execute(
        text(_INSERT_KEY),
        _key_params(w, rev_at=T0 + timedelta(days=1), rev_by=w["ta"].id, rate=5),
    )
    count = (await db.execute(text("SELECT count(*) FROM api_key"))).scalar_one()
    assert count == 4


@pytest.mark.parametrize(
    ("label", "over"),
    [
        ("name_empty", {"name": ""}),
        ("name_101", {"name": "x" * 101}),
        ("digest_31_bytes", {"digest": b"\x01" * 31}),
        ("digest_33_bytes", {"digest": b"\x01" * 33}),
        ("expires_equals_created", {"expires": T0}),
        ("expires_before_created", {"expires": T0 - timedelta(seconds=1)}),
        ("revoked_at_without_by", {"rev_at": T0 + timedelta(days=1)}),
        ("revoked_by_without_at", {"rev_by": "ta"}),
        ("rate_count_negative", {"rate": -1}),
    ],
)
async def test_007_nfr7_check_violations_give_23514(
    db: AsyncSession, label: str, over: dict[str, Any]
) -> None:
    w = await _world(db)
    over = {k: (w["ta"].id if v == "ta" else v) for k, v in over.items()}
    await _expect_sqlstate(db, _INSERT_KEY, _key_params(w, **over), CHECK_VIOLATION)


# --- FR-6: хранится только дайджест; уникальность -----------------------------------------


async def test_007_fr6_duplicate_digest_gives_23505(db: AsyncSession) -> None:
    w = await _world(db)
    digest = hashlib.sha256(b"same").digest()
    await db.execute(text(_INSERT_KEY), _key_params(w, digest=digest))
    await _expect_sqlstate(db, _INSERT_KEY, _key_params(w, digest=digest), UNIQUE_VIOLATION)


async def test_007_fr6_only_sha256_digest_is_stored_never_the_secret(db: AsyncSession) -> None:
    w = await _world(db)
    key = await make_api_key(db, user=w["agent"], created_by=w["ta"], created_at=T0)
    assert re.fullmatch(r"gtk_[A-Za-z0-9_-]{43}", key.secret), "формат секрета фабрики"
    row = (
        await db.execute(
            text("SELECT secret_digest, to_jsonb(k)::text AS dump FROM api_key k WHERE id = :i"),
            {"i": key.id},
        )
    ).one()
    assert bytes(row.secret_digest) == hashlib.sha256(key.secret.encode("ascii")).digest()
    assert key.secret not in row.dump, "секрет в строке api_key"
    assert key.secret[4:12] not in row.dump, "часть секрета в строке api_key"
    dump_all = (await db.execute(text("SELECT to_jsonb(u)::text FROM app_user u"))).scalars().all()
    assert not any(key.secret in d for d in dump_all), "секрет в app_user"


async def test_007_fr6_make_api_key_secrets_differ(db: AsyncSession) -> None:
    w = await _world(db)
    a = await make_api_key(db, user=w["agent"], created_by=w["ta"])
    b = await make_api_key(db, user=w["agent"], created_by=w["ta"])
    assert a.id != b.id and a.secret != b.secret


# --- FR-30: ссылка из события -------------------------------------------------------------


async def test_007_fr30_event_with_unknown_api_key_gives_23503(db: AsyncSession) -> None:
    w = await _world(db)
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    with pytest.raises(IntegrityError) as info:
        async with db.begin_nested():
            await make_domain_event(db, workspace_id=w["ws"].id, api_key_id=uuid.uuid4())
    assert _sqlstate(info.value) == FK_VIOLATION


async def test_007_fr30_event_with_existing_key_ok_and_default_null(db: AsyncSession) -> None:
    w = await _world(db)
    key = await make_api_key(db, user=w["agent"], created_by=w["ta"], created_at=T0)
    with_key = await make_domain_event(db, workspace_id=w["ws"].id, api_key_id=key.id)
    without = await make_domain_event(db, workspace_id=w["ws"].id)
    rows = {
        r.id: r.api_key_id
        for r in await db.execute(text("SELECT id, api_key_id FROM domain_event"))
        if r.id in {with_key, without}
    }
    assert rows == {with_key: key.id, without: None}


async def test_007_fr30_key_referenced_by_event_cannot_be_deleted(db: AsyncSession) -> None:
    """PD-9: ключи не удаляются (FK RESTRICT)."""
    w = await _world(db)
    key = await make_api_key(db, user=w["agent"], created_by=w["ta"], created_at=T0)
    await make_domain_event(db, workspace_id=w["ws"].id, api_key_id=key.id)
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await _expect_sqlstate(db, "DELETE FROM api_key WHERE id = :i", {"i": key.id}, FK_VIOLATION)


async def test_007_nfr7_user_with_key_cannot_be_deleted(db: AsyncSession) -> None:
    w = await _world(db)
    await make_api_key(db, user=w["agent"], created_by=w["ta"], created_at=T0)
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await _expect_sqlstate(
        db, "DELETE FROM app_user WHERE id = :i", {"i": w["agent"].id}, FK_VIOLATION
    )


# --- модель и миграция согласованы; цикл head -> 0007 -> head -----------------------------


def test_007_nfr7_models_registered_in_metadata() -> None:
    import app.domain.registry  # noqa: F401
    from app.core.models import Base

    assert "api_key" in Base.metadata.tables
    assert {c.name for c in Base.metadata.tables["api_key"].columns} == set(API_KEY_COLUMNS)
    assert "is_agent" in Base.metadata.tables["app_user"].columns
    assert "api_key_id" in Base.metadata.tables["domain_event"].columns


async def _fingerprint(env: ApiEnv, table: str, drop: str) -> list[str]:
    rows = await env.execute(
        text(f"SELECT (to_jsonb(t) - '{drop}')::text FROM {table} t ORDER BY 1")  # noqa: S608
    )
    assert rows is not None
    return [str(r[0]) for r in rows]


@pytest.mark.committed
async def test_007_nfr7_upgrade_downgrade_upgrade_cycle_keeps_other_data(
    committed_api_env: ApiEnv,
) -> None:
    """head -> ``downgrade 0007`` (таблицы и столбцов нет, прочие данные побайтно те же) ->
    ``upgrade head`` (ключи и признак агента потеряны, остальное прежнее) -> ``alembic check``."""
    env = committed_api_env
    async with env.sessionmaker() as s:
        w = await _world(s)
        key = await make_api_key(s, user=w["agent"], created_by=w["ta"], created_at=T0)
        await make_domain_event(
            s, workspace_id=w["ws"].id, actor_id=w["agent"].id, api_key_id=key.id
        )
        await make_domain_event(s, workspace_id=w["ws"].id, actor_id=w["ta"].id)
        await s.commit()
    users_before = await _fingerprint(env, "app_user", "is_agent")
    events_before = await _fingerprint(env, "domain_event", "api_key_id")
    assert len(users_before) == 2 and len(events_before) == 2

    await alembic_ok(env, "downgrade", "0007")

    assert await alembic_versions(env) == ["0007"]
    gone = await env.execute(text("SELECT to_regclass('public.api_key') IS NULL"))
    assert gone is not None and gone[0][0] is True
    cols = await env.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name IN ('is_agent', 'api_key_id')"
        )
    )
    assert cols == []
    assert await _fingerprint(env, "app_user", "nonexistent") == users_before
    assert await _fingerprint(env, "domain_event", "nonexistent") == events_before

    await alembic_ok(env, "upgrade", "head")

    assert await alembic_versions(env) == ["0008"]
    count = await env.execute(text("SELECT count(*) FROM api_key"))
    assert count is not None and count[0][0] == 0
    flags = await env.execute(text("SELECT DISTINCT is_agent FROM app_user"))
    assert flags is not None and [r[0] for r in flags] == [False]
    keys = await env.execute(text("SELECT DISTINCT api_key_id FROM domain_event"))
    assert keys is not None and [r[0] for r in keys] == [None]
    assert await _fingerprint(env, "app_user", "is_agent") == users_before
    assert await _fingerprint(env, "domain_event", "api_key_id") == events_before
    await alembic_ok(env, "check")


@pytest.mark.committed
async def test_007_nfr7_alembic_check_clean_at_head(committed_api_env: ApiEnv) -> None:
    """Модель и миграция 0008 не расходятся (``alembic check`` чист)."""
    assert await alembic_versions(committed_api_env) == ["0008"]
    await alembic_ok(committed_api_env, "check")
