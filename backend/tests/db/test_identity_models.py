"""T06: модель идентичности (plan §4.3, D-5, D-39; миграция 0001).

Покрытие: AC-116 / FR-73 / D-39 (логин: UNIQUE + CHECK по шаблону, нижний регистр),
FR-66 (не больше одной роли; допустимо «без роли», OI-6/OI-75), FR-58 (серверная сессия,
``user_session.id`` = bytea, HMAC токена), FR-13 (workspace_id, FK, NOT NULL), D-3/D-26
(все FK DEFERRABLE INITIALLY IMMEDIATE), D-5 (глобальный ``app_user`` без workspace_id),
D-4/FR-46 (метки времени из ``utcnow()``), миграция 0001 (upgrade/downgrade/upgrade, check).

Тесты работают с таблицами по именам из plan §4.3 через ``Base.metadata`` (имена классов
моделей контрактом не заданы). Пока моделей и миграции нет, тесты красные
(ImportError / отсутствие таблиц).
"""

from __future__ import annotations

import ast
import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import CheckConstraint, delete, select, text
from sqlalchemy.exc import DBAPIError

from tests.db_support import BACKEND_DIR, run_alembic
from tests.factories import ROLES, get_table, make_user, make_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.clock import FixedClock

LOGIN_PATTERN = "^[a-z0-9][a-z0-9._-]{2,63}$"
LOGIN_RE = re.compile(LOGIN_PATTERN)
TABLES = ("workspace", "app_user", "workspace_member", "user_session")

UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
FK_VIOLATION = "23503"
NOT_NULL_VIOLATION = "23502"
MIGRATION_0001 = BACKEND_DIR / "migrations" / "versions" / "0001_identity.py"


# --- вспомогательное ---------------------------------------------------------------------


def _sqlstate(exc: DBAPIError) -> str | None:
    orig: Any = exc.orig
    for obj in (orig, getattr(orig, "__cause__", None)):
        code = getattr(obj, "sqlstate", None) or getattr(obj, "pgcode", None)
        if code:
            return str(code)
    return None


async def assert_rejected(db: AsyncSession, stmt: Any, sqlstate: str) -> None:
    """Оператор отклонён БД с данным SQLSTATE; сессия остаётся рабочей (SAVEPOINT)."""
    with pytest.raises(DBAPIError) as info:
        async with db.begin_nested():
            await db.execute(stmt)
    assert _sqlstate(info.value) == sqlstate, f"ожидали {sqlstate}, получили: {info.value!r}"


def user_values(**overrides: Any) -> dict[str, Any]:
    """Корректная строка ``app_user`` (все NOT NULL заполнены), поля переопределяются."""
    now = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "login": f"u{uuid.uuid4().hex[:12]}",
        "password_hash": "$argon2id$v=19$m=1024,t=1,p=1$c2FsdA$aGFzaA",
        "must_change_password": False,
        "is_blocked": False,
        "failed_login_count": 0,
        "password_changed_at": now,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return values


def member_values(workspace_id: uuid.UUID, user_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    now = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
    values: dict[str, Any] = {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "role": "user",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return values


def session_values(user_id: uuid.UUID, workspace_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    now = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
    values: dict[str, Any] = {
        "id": uuid.uuid4().bytes + uuid.uuid4().bytes,  # 32 байта, как HMAC-SHA256
        "user_id": user_id,
        "workspace_id": workspace_id,
        "created_at": now,
        "last_activity_at": now,
        "absolute_expires_at": now + timedelta(hours=12),
    }
    values.update(overrides)
    return values


async def column_info(db: AsyncSession, table: str) -> dict[str, dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return {
        r.column_name: {
            "type": r.data_type,
            "length": r.character_maximum_length,
            "nullable": r.is_nullable == "YES",
        }
        for r in rows
    }


# --- реестр и метаданные моделей (без БД) -------------------------------------------------


def test_t06_registry_imports_identity_models() -> None:
    """Реестр подключает модули моделей: таблицы попадают в Base.metadata."""
    import app.domain.registry  # noqa: F401
    from app.core.models import Base

    missing = set(TABLES) - set(Base.metadata.tables)
    assert not missing, f"в Base.metadata нет таблиц: {sorted(missing)}"


@pytest.mark.parametrize(
    ("table", "module"),
    [
        ("workspace", "app.domain.workspaces.models"),
        ("app_user", "app.domain.users.models"),
        ("user_session", "app.domain.auth.models"),
    ],
)
def test_t06_models_live_in_planned_modules(table: str, module: str) -> None:
    import importlib

    import app.domain.registry  # noqa: F401
    from app.core.models import Base

    importlib.import_module(module)
    classes = [
        m.class_
        for m in Base.registry.mappers
        if getattr(m.class_, "__tablename__", None) == table or m.local_table.name == table
    ]
    assert classes, f"нет модели для таблицы {table}"
    assert any(c.__module__ == module for c in classes), (
        f"модель {table} ожидается в {module}, найдена в {[c.__module__ for c in classes]}"
    )


def test_t06_all_foreign_keys_are_deferrable_initially_immediate() -> None:
    """D-3/D-26: все FK identity-таблиц DEFERRABLE INITIALLY IMMEDIATE (метаданные)."""
    for name in TABLES:
        for fk in get_table(name).foreign_key_constraints:
            assert fk.deferrable is True, f"{name}: FK {fk.name} не deferrable"
            assert fk.initially == "IMMEDIATE", f"{name}: FK {fk.name} initially={fk.initially}"


def test_t06_metadata_declares_login_and_role_checks() -> None:
    """Шаблон логина и список ролей объявлены как CHECK в моделях (plan §4.3)."""
    user_checks = [
        str(c.sqltext) for c in get_table("app_user").constraints if isinstance(c, CheckConstraint)
    ]
    assert any(LOGIN_PATTERN in c for c in user_checks), f"нет CHECK по шаблону: {user_checks}"
    member_checks = [
        str(c.sqltext)
        for c in get_table("workspace_member").constraints
        if isinstance(c, CheckConstraint)
    ]
    assert any(all(role in c for role in ROLES) for c in member_checks), (
        f"нет CHECK по ролям: {member_checks}"
    )


# --- структура схемы в БД (миграция 0001 применена фикстурой) -----------------------------


async def test_t06_tables_exist_after_migration(db: AsyncSession) -> None:
    rows = await db.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    existing = {r.table_name for r in rows}
    assert set(TABLES) <= existing, f"нет таблиц: {sorted(set(TABLES) - existing)}"


async def test_t06_app_user_columns_types_nullability(db: AsyncSession) -> None:
    cols = await column_info(db, "app_user")
    expected_not_null = {
        "id": "uuid",
        "login": "character varying",
        "password_hash": "text",
        "must_change_password": "boolean",
        "is_blocked": "boolean",
        "failed_login_count": "integer",
        "created_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
    }
    for name, typ in expected_not_null.items():
        assert name in cols, f"app_user.{name} отсутствует"
        assert cols[name]["type"] == typ, f"app_user.{name}: {cols[name]['type']} != {typ}"
        assert cols[name]["nullable"] is False, f"app_user.{name} должен быть NOT NULL"
    assert cols["login"]["length"] == 64
    for name in ("blocked_at", "login_locked_until"):
        assert cols[name]["type"] == "timestamp with time zone"
        assert cols[name]["nullable"] is True
    assert cols["password_changed_at"]["type"] == "timestamp with time zone"
    assert cols["created_by"]["type"] == "uuid"
    assert cols["created_by"]["nullable"] is True


async def test_t06_app_user_is_global_without_workspace_id(db: AsyncSession) -> None:
    """D-5: пользователь — глобальная идентичность, ни workspace_id, ни role в app_user."""
    cols = await column_info(db, "app_user")
    assert cols, "таблица app_user отсутствует"
    assert "workspace_id" not in cols
    assert "role" not in cols


async def test_t06_workspace_columns(db: AsyncSession) -> None:
    cols = await column_info(db, "workspace")
    assert cols["id"]["type"] == "uuid"
    for name in ("created_at", "updated_at"):
        assert cols[name]["type"] == "timestamp with time zone"
        assert cols[name]["nullable"] is False


async def test_t06_workspace_member_columns(db: AsyncSession) -> None:
    cols = await column_info(db, "workspace_member")
    for name in ("workspace_id", "user_id"):  # FR-13: workspace_id NOT NULL
        assert cols[name]["type"] == "uuid"
        assert cols[name]["nullable"] is False
    assert cols["role"]["type"] == "text"
    assert cols["role"]["nullable"] is True  # «без роли» (FR-66, D-5)
    for name in ("created_at", "updated_at"):
        assert cols[name]["type"] == "timestamp with time zone"
        assert cols[name]["nullable"] is False
    assert cols["created_by"]["nullable"] is True


async def test_t06_user_session_columns_id_is_bytea(db: AsyncSession) -> None:
    """FR-58: id сессии — bytea (HMAC токена); токен в открытом виде не хранится."""
    cols = await column_info(db, "user_session")
    assert cols["id"]["type"] == "bytea"
    assert cols["id"]["nullable"] is False
    assert cols["user_id"]["type"] == "uuid"
    assert cols["workspace_id"]["type"] == "uuid"  # FR-13
    for name in ("user_id", "workspace_id"):
        assert cols[name]["nullable"] is False
    for name in ("created_at", "last_activity_at", "absolute_expires_at"):
        assert cols[name]["type"] == "timestamp with time zone"
        assert cols[name]["nullable"] is False


async def test_t06_all_foreign_keys_deferrable_in_database(db: AsyncSession) -> None:
    rows = await db.execute(
        text(
            "SELECT c.conrelid::regclass::text AS tbl, c.conname, c.condeferrable, c.condeferred "
            "FROM pg_constraint c WHERE c.contype = 'f' "
            "AND c.conrelid::regclass::text = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    )
    fks = list(rows)
    # member: 3 FK (workspace, user, created_by), session: 2, app_user: 1 (created_by)
    assert len(fks) >= 6, f"ожидали не менее 6 FK, найдено {len(fks)}: {[f.conname for f in fks]}"
    for fk in fks:
        assert fk.condeferrable is True, f"{fk.tbl}.{fk.conname}: не DEFERRABLE"
        assert fk.condeferred is False, f"{fk.tbl}.{fk.conname}: не INITIALLY IMMEDIATE"


async def test_t06_fk_actions(db: AsyncSession) -> None:
    """user_session.user_id -> ON DELETE CASCADE; created_by -> RESTRICT (plan §4.3, D-26)."""
    rows = await db.execute(
        text(
            "SELECT a.attname AS col, c.conrelid::regclass::text AS tbl, "
            "c.confdeltype::text AS act, c.confrelid::regclass::text AS target "
            "FROM pg_constraint c JOIN pg_attribute a "
            "ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
            "WHERE c.contype = 'f' AND c.conrelid::regclass::text = ANY(:tables)"
        ),
        {"tables": list(TABLES)},
    )
    actions = {(r.tbl, r.col): (r.act, r.target) for r in rows}
    assert actions[("user_session", "user_id")] == ("c", "app_user")
    assert actions[("user_session", "workspace_id")][1] == "workspace"
    assert actions[("workspace_member", "workspace_id")][1] == "workspace"
    assert actions[("workspace_member", "user_id")][1] == "app_user"
    assert actions[("workspace_member", "created_by")] == ("r", "app_user")
    assert actions[("app_user", "created_by")] == ("r", "app_user")


async def test_t06_indexes_per_plan(db: AsyncSession) -> None:
    """plan §4.3: индекс (workspace_id, role) у workspace_member, индекс user_id у user_session."""
    rows = await db.execute(
        text(
            "SELECT t.relname AS tbl, array_agg(a.attname ORDER BY k.ord) AS cols "
            "FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid "
            "JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON true "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
            "WHERE t.relname = ANY(:tables) GROUP BY t.relname, i.indexrelid"
        ),
        {"tables": list(TABLES)},
    )
    indexes = {(r.tbl, tuple(r.cols)) for r in rows}
    assert ("workspace_member", ("workspace_id", "role")) in indexes
    assert ("user_session", ("user_id",)) in indexes
    assert ("workspace_member", ("workspace_id", "user_id")) in indexes  # PK
    assert ("user_session", ("id",)) in indexes  # PK


# --- AC-116 / FR-73 / D-39: логин --------------------------------------------------------


@pytest.mark.parametrize(
    "login",
    [
        "ivan.petrov",  # AC-116
        "abc",  # граница: 3 символа
        "a" + "b" * 63,  # граница: 64 символа
        "0abc",  # цифра первой
        "a.-_",  # допустимые знаки
        "user_name-1",
    ],
)
async def test_ac116_valid_logins_are_accepted(db: AsyncSession, login: str) -> None:
    assert LOGIN_RE.match(login), "ошибка теста: логин не соответствует шаблону"
    await db.execute(get_table("app_user").insert().values(user_values(login=login)))
    stored = (
        await db.execute(
            select(get_table("app_user").c.login).where(get_table("app_user").c.login == login)
        )
    ).scalar_one()
    assert stored == login


@pytest.mark.parametrize(
    "login",
    [
        "ab",  # 2 символа
        "",  # пусто
        "Ivan.Petrov",  # верхний регистр (хранится только в нижнем, FR-73)
        "IVAN",
        "iv an",  # пробел внутри
        " ivan",  # пробел в начале
        "ivan ",  # пробел в конце
        "ivan\n",  # перевод строки в конце
        "иван",  # кириллица
        "ivаn",  # кириллическая «а» среди латиницы
        ".ivan",  # начинается с точки
        "-ivan",
        "_ivan",
        "iv@n",
        "ivan/petrov",
    ],
)
async def test_ac116_invalid_logins_are_rejected_by_check(db: AsyncSession, login: str) -> None:
    await assert_rejected(
        db, get_table("app_user").insert().values(user_values(login=login)), CHECK_VIOLATION
    )


async def test_ac116_too_long_login_is_rejected(db: AsyncSession) -> None:
    """65 символов: отклоняется типом varchar(64) (SQLSTATE 22001) раньше CHECK; строки нет."""
    login = "a" * 65
    table = get_table("app_user")
    await assert_rejected(db, table.insert().values(user_values(login=login)), "22001")
    assert (await db.execute(select(table.c.id).where(table.c.login == login))).first() is None


async def test_ac116_login_is_unique(db: AsyncSession) -> None:
    table = get_table("app_user")
    await db.execute(table.insert().values(user_values(login="ivan.petrov")))
    await assert_rejected(
        db, table.insert().values(user_values(login="ivan.petrov")), UNIQUE_VIOLATION
    )


async def test_ac116_logins_differing_only_by_case_cannot_coexist(db: AsyncSession) -> None:
    """Регистронезависимая уникальность достигается нижним регистром в БД (D-39)."""
    table = get_table("app_user")
    await db.execute(table.insert().values(user_values(login="ivan.petrov")))
    await assert_rejected(
        db, table.insert().values(user_values(login="Ivan.Petrov")), CHECK_VIOLATION
    )


async def test_ac116_update_to_invalid_login_is_rejected(db: AsyncSession) -> None:
    user = await make_user(db, login="ivan.petrov")
    table = get_table("app_user")
    await assert_rejected(
        db, table.update().where(table.c.id == user.id).values(login="IVAN.PETROV"), CHECK_VIOLATION
    )


# --- FR-66 / D-5: роли и членство ---------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
async def test_fr66_four_roles_are_accepted(db: AsyncSession, role: str) -> None:
    user = await make_user(db, role=role)
    stored = (
        await db.execute(
            select(get_table("workspace_member").c.role).where(
                get_table("workspace_member").c.user_id == user.id
            )
        )
    ).scalar_one()
    assert stored == role


@pytest.mark.parametrize("role", ["admin", "ADMIN", "Tech_Admin", "", "superuser", "owner"])
async def test_fr66_unknown_role_is_rejected(db: AsyncSession, role: str) -> None:
    ws = await make_workspace(db)
    other = user_values()
    await db.execute(get_table("app_user").insert().values(other))
    await assert_rejected(
        db,
        get_table("workspace_member").insert().values(member_values(ws.id, other["id"], role=role)),
        CHECK_VIOLATION,
    )


async def test_fr66_user_without_role_is_allowed(db: AsyncSession) -> None:
    """OI-6/OI-75: роль NULL — допустимое состояние (вход, выход, смена своего пароля)."""
    user = await make_user(db, role=None)
    row = (
        await db.execute(
            select(get_table("workspace_member").c.role).where(
                get_table("workspace_member").c.user_id == user.id
            )
        )
    ).all()
    assert len(row) == 1
    assert row[0].role is None


async def test_fr66_second_role_in_same_workspace_is_rejected(db: AsyncSession) -> None:
    """FR-66: PK(workspace_id, user_id) — не более одной роли у пользователя в пространстве."""
    user = await make_user(db, role="user")
    await assert_rejected(
        db,
        get_table("workspace_member")
        .insert()
        .values(member_values(user.workspace_id, user.id, role="mixed")),
        UNIQUE_VIOLATION,
    )


async def test_d5_same_global_user_may_belong_to_another_workspace(db: AsyncSession) -> None:
    """D-5: готовность к нескольким пространствам — PK по паре, а не по user_id."""
    user = await make_user(db, role="user")
    second = await make_workspace(db)
    await db.execute(
        get_table("workspace_member")
        .insert()
        .values(member_values(second.id, user.id, role="mixed"))
    )
    count = (
        await db.execute(
            text("SELECT count(*) FROM workspace_member WHERE user_id = :u"), {"u": user.id}
        )
    ).scalar_one()
    assert count == 2


# --- FR-13: workspace_id, FK, NOT NULL ---------------------------------------------------


async def test_fr13_member_with_unknown_workspace_is_rejected(db: AsyncSession) -> None:
    user = await make_user(db)
    await assert_rejected(
        db,
        get_table("workspace_member").insert().values(member_values(uuid.uuid4(), user.id)),
        FK_VIOLATION,
    )


async def test_fr13_member_with_unknown_user_is_rejected(db: AsyncSession) -> None:
    ws = await make_workspace(db)
    await assert_rejected(
        db,
        get_table("workspace_member").insert().values(member_values(ws.id, uuid.uuid4())),
        FK_VIOLATION,
    )


async def test_fr13_session_with_unknown_workspace_is_rejected(db: AsyncSession) -> None:
    user = await make_user(db)
    await assert_rejected(
        db,
        get_table("user_session").insert().values(session_values(user.id, uuid.uuid4())),
        FK_VIOLATION,
    )


async def test_fr58_session_with_unknown_user_is_rejected(db: AsyncSession) -> None:
    ws = await make_workspace(db)
    await assert_rejected(
        db,
        get_table("user_session").insert().values(session_values(uuid.uuid4(), ws.id)),
        FK_VIOLATION,
    )


@pytest.mark.parametrize(
    "column", ["login", "password_hash", "must_change_password", "is_blocked", "created_at"]
)
async def test_t06_app_user_not_null_columns(db: AsyncSession, column: str) -> None:
    await assert_rejected(
        db,
        get_table("app_user").insert().values(user_values(**{column: None})),
        NOT_NULL_VIOLATION,
    )


@pytest.mark.parametrize("column", ["workspace_id", "user_id", "created_at", "updated_at"])
async def test_t06_member_not_null_columns(db: AsyncSession, column: str) -> None:
    other = user_values()
    await db.execute(get_table("app_user").insert().values(other))
    ws = await make_workspace(db)
    values = member_values(ws.id, other["id"])
    values[column] = None
    await assert_rejected(
        db, get_table("workspace_member").insert().values(values), NOT_NULL_VIOLATION
    )


@pytest.mark.parametrize(
    "column",
    ["id", "user_id", "workspace_id", "created_at", "last_activity_at", "absolute_expires_at"],
)
async def test_t06_session_not_null_columns(db: AsyncSession, column: str) -> None:
    user = await make_user(db)
    values = session_values(user.id, user.workspace_id)
    values[column] = None
    await assert_rejected(db, get_table("user_session").insert().values(values), NOT_NULL_VIOLATION)


async def test_t06_fk_checks_can_be_deferred_to_commit(db: AsyncSession) -> None:
    """DEFERRABLE INITIALLY IMMEDIATE: с SET CONSTRAINTS ALL DEFERRED нарушение всплывает позже."""
    user = await make_user(db)
    with pytest.raises(DBAPIError) as info:
        async with db.begin_nested():
            await db.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            await db.execute(
                get_table("user_session").insert().values(session_values(user.id, uuid.uuid4()))
            )  # без ошибки: проверка отложена
            await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert _sqlstate(info.value) == FK_VIOLATION


# --- FR-58: серверная сессия -------------------------------------------------------------


async def test_fr58_session_id_roundtrips_as_32_bytes(db: AsyncSession) -> None:
    user = await make_user(db, role="user")
    values = session_values(user.id, user.workspace_id)
    await db.execute(get_table("user_session").insert().values(values))
    stored = (
        await db.execute(
            select(get_table("user_session").c.id).where(
                get_table("user_session").c.user_id == user.id
            )
        )
    ).scalar_one()
    assert isinstance(stored, bytes)
    assert stored == values["id"]
    assert len(stored) == 32


async def test_fr58_session_id_is_primary_key(db: AsyncSession) -> None:
    user = await make_user(db)
    values = session_values(user.id, user.workspace_id)
    table = get_table("user_session")
    await db.execute(table.insert().values(values))
    await assert_rejected(
        db,
        table.insert().values(session_values(user.id, user.workspace_id, id=values["id"])),
        UNIQUE_VIOLATION,
    )


async def test_fr58_deleting_user_cascades_to_sessions(db: AsyncSession) -> None:
    user = await make_user(db, role="user")
    sess = get_table("user_session")
    await db.execute(sess.insert().values(session_values(user.id, user.workspace_id)))
    await db.execute(sess.insert().values(session_values(user.id, user.workspace_id)))
    await db.execute(
        delete(get_table("workspace_member")).where(
            get_table("workspace_member").c.user_id == user.id
        )
    )
    await db.execute(delete(get_table("app_user")).where(get_table("app_user").c.id == user.id))
    left = (
        await db.execute(
            text("SELECT count(*) FROM user_session WHERE user_id = :u"), {"u": user.id}
        )
    ).scalar_one()
    assert left == 0


# --- значения по умолчанию и метки времени (D-4, FR-46) ---------------------------------


async def test_t06_failed_login_count_defaults_to_zero(db: AsyncSession) -> None:
    values = user_values()
    del values["failed_login_count"]
    await db.execute(get_table("app_user").insert().values(values))
    count = (
        await db.execute(
            select(get_table("app_user").c.failed_login_count).where(
                get_table("app_user").c.id == values["id"]
            )
        )
    ).scalar_one()
    assert count == 0


async def test_t06_timestamps_default_to_clock(db: AsyncSession, fixed_clock: FixedClock) -> None:
    """created_at/updated_at по умолчанию берутся из utcnow() (FixedClock), aware UTC."""
    ws_id = uuid.uuid4()
    await db.execute(get_table("workspace").insert().values(id=ws_id))
    row = (
        await db.execute(
            select(get_table("workspace").c.created_at, get_table("workspace").c.updated_at).where(
                get_table("workspace").c.id == ws_id
            )
        )
    ).one()
    assert row.created_at == fixed_clock.now()
    assert row.updated_at == fixed_clock.now()
    assert row.created_at.tzinfo is not None


# --- фабрики -----------------------------------------------------------------------------


async def test_t06_factories_create_consistent_rows(db: AsyncSession) -> None:
    ws = await make_workspace(db)
    admin = await make_user(
        db, workspace=ws, role="tech_admin", must_change_password=True, password="x" * 12
    )
    blocked = await make_user(db, workspace=ws, role="user", blocked=True)
    norole = await make_user(db, workspace=ws)
    assert LOGIN_RE.match(admin.login) and LOGIN_RE.match(blocked.login)
    assert len({admin.login, blocked.login, norole.login}) == 3
    rows = (
        await db.execute(
            text(
                "SELECT u.login, u.is_blocked, u.blocked_at, u.must_change_password, m.role "
                "FROM app_user u JOIN workspace_member m ON m.user_id = u.id "
                "WHERE m.workspace_id = :w ORDER BY u.login"
            ),
            {"w": ws.id},
        )
    ).all()
    by_login = {r.login: r for r in rows}
    assert by_login[admin.login].role == "tech_admin"
    assert by_login[admin.login].must_change_password is True
    assert by_login[admin.login].is_blocked is False
    assert by_login[blocked.login].is_blocked is True
    assert by_login[blocked.login].blocked_at is not None
    assert by_login[norole.login].role is None


# --- миграция 0001 -----------------------------------------------------------------------


def test_t06_migration_file_has_upgrade_and_downgrade() -> None:
    assert MIGRATION_0001.is_file(), "нет backend/migrations/versions/0001_identity.py"
    tree = ast.parse(MIGRATION_0001.read_text(encoding="utf-8"))
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"upgrade", "downgrade"} <= funcs
    assigns = {
        t.id: n.value
        for n in tree.body
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name)
    } | {
        n.target.id: n.value
        for n in tree.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None
    }
    down = assigns.get("down_revision")
    assert isinstance(down, ast.Constant) and down.value is None, "0001 — первая миграция"


async def _alembic(url: str, *args: str) -> str:
    result = await asyncio.to_thread(run_alembic, url, *args)
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
    )
    return str(result.stdout) + str(result.stderr)


async def _public_tables(maker: async_sessionmaker[AsyncSession]) -> set[str]:
    async with maker() as s:
        rows = await s.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        return {r.table_name for r in rows}


@pytest.mark.committed
async def test_t06_migration_upgrade_downgrade_upgrade_check(
    committed: async_sessionmaker[AsyncSession], test_database_url: str
) -> None:
    """Чистая схема: head создаёт 4 таблицы, base убирает их, повторный head и check — чисто."""
    assert set(TABLES) <= await _public_tables(committed)
    await _alembic(test_database_url, "downgrade", "base")
    left = await _public_tables(committed)
    assert not (set(TABLES) & left), f"downgrade оставил таблицы: {sorted(set(TABLES) & left)}"
    await _alembic(test_database_url, "upgrade", "head")
    assert set(TABLES) <= await _public_tables(committed)
    await _alembic(test_database_url, "check")


@pytest.mark.committed
async def test_t06_downgrade_leaves_no_foreign_objects(
    committed: async_sessionmaker[AsyncSession], test_database_url: str
) -> None:
    """После downgrade base в public нет ничего, кроме alembic_version."""
    assert set(TABLES) <= await _public_tables(committed)
    await _alembic(test_database_url, "downgrade", "base")
    assert await _public_tables(committed) <= {"alembic_version"}


@pytest.mark.committed
async def test_t06_committed_rows_survive_and_violations_fail_on_commit(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    """Реальные фиксации: логин уникален между транзакциями; нарушение откатывает транзакцию."""
    user_table = get_table("app_user")
    async with committed() as s, s.begin():
        await s.execute(user_table.insert().values(user_values(login="ivan.petrov")))
    with pytest.raises(DBAPIError) as info:
        async with committed() as s, s.begin():
            await s.execute(user_table.insert().values(user_values(login="ivan.petrov")))
    assert _sqlstate(info.value) == UNIQUE_VIOLATION
    async with committed() as s:
        count = (await s.execute(text("SELECT count(*) FROM app_user"))).scalar_one()
    assert count == 1
