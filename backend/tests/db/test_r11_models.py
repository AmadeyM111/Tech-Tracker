"""T69: модели MVP и миграция 0004 (plan §11.6, D-2…D-4, D-22, D-25, D-26, D-41, D-52, D-56…D-58).

Покрытие: FR-13 (workspace_id), FR-14/FR-18 (длины названий, D-52 — пустое отсекает сервис, БД
проверяет длину >= 1), FR-18a (статус/приоритет), FR-21 (позиция только у задач верхнего
уровня), FR-23 (длина комментария), AC-108 (уровень БД: ограничения длин), AC-66 (CHECK журнала
не меняет строки, append-only триггеры целы), D-58 (нет label/task_label/mention/attachment,
pg_trgm, project.status).

Тесты идут по именам таблиц/столбцов из §11.6 (через БД и ``Base.metadata``), имена классов
моделей контрактом не заданы. Частичные индексы ищутся по (таблица, столбцы, предикат), а не по
имени. Пока моделей и миграции нет, тесты красные.
"""

from __future__ import annotations

import importlib
import re
import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import CheckConstraint, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.factories import (
    get_table,
    make_comment,
    make_domain_event,
    make_project,
    make_project_member,
    make_task,
    make_user,
    make_workspace,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CHECK_VIOLATION = "23514"
FK_VIOLATION = "23503"
NOT_NULL_VIOLATION = "23502"
UNIQUE_VIOLATION = "23505"
RESTRICT_VIOLATION = "23001"

MVP_TABLES = ("project", "project_member", "task", "comment")
ENTITY_TYPES = ("user", "project", "task", "comment", "attachment", "stage", "deal")
CHECK_NAME = "ck_domain_event_entity_type_valid"

# (тип information_schema, длина, допускает NULL)
TS = ("timestamp with time zone", None, False)
TS_N = ("timestamp with time zone", None, True)
UUID_ = ("uuid", None, False)
UUID_N = ("uuid", None, True)
TEXT = ("text", None, False)
V255 = ("character varying", 255, False)

EXPECTED_COLUMNS: dict[str, dict[str, tuple[str, int | None, bool]]] = {
    "project": {
        "id": UUID_,
        "workspace_id": UUID_,
        "name": V255,
        "description": TEXT,
        "owner_id": UUID_,
        "created_by": UUID_N,
        "created_at": TS,
        "updated_at": TS,
        "deleted_at": TS_N,
        "deleted_batch_id": UUID_N,
    },
    "project_member": {
        "project_id": UUID_,
        "user_id": UUID_,
        "workspace_id": UUID_,
        "created_at": TS,
        "updated_at": TS,
        "created_by": UUID_N,
    },
    "task": {
        "id": UUID_,
        "workspace_id": UUID_,
        "project_id": UUID_,
        "parent_id": UUID_N,
        "title": V255,
        "description": TEXT,
        "status": TEXT,
        "priority": TEXT,
        "due_date": ("date", None, True),
        "assignee_id": UUID_N,
        "position": ("bigint", None, True),
        "created_by": UUID_,
        "created_at": TS,
        "updated_at": TS,
        "deleted_at": TS_N,
        "deleted_batch_id": UUID_N,
    },
    "comment": {
        "id": UUID_,
        "workspace_id": UUID_,
        "task_id": UUID_,
        "body": TEXT,
        "edited_at": TS_N,
        "created_by": UUID_N,
        "created_at": TS,
        "updated_at": TS,
        "deleted_at": TS_N,
        "deleted_batch_id": UUID_N,
    },
}

EXPECTED_PK = {
    "project": ["id"],
    "project_member": ["project_id", "user_id"],
    "task": ["id"],
    "comment": ["id"],
}

# (таблица, столбец, целевая таблица, ON DELETE: 'c' CASCADE / 'r' RESTRICT)
EXPECTED_FK = [
    ("project", "owner_id", "app_user", "r"),
    ("project", "created_by", "app_user", "r"),
    ("project_member", "project_id", "project", "c"),
    ("project_member", "user_id", "app_user", "r"),
    ("project_member", "created_by", "app_user", "r"),
    ("task", "project_id", "project", "c"),
    ("task", "parent_id", "task", "c"),
    ("task", "assignee_id", "app_user", "r"),
    ("task", "created_by", "app_user", "r"),
    ("comment", "task_id", "task", "c"),
    ("comment", "created_by", "app_user", "r"),
]

# (таблица, столбцы, предикат или None) — без учёта индексов workspace_id и PK
EXPECTED_INDEXES: list[tuple[str, str, str | None]] = [
    ("project_member", "user_id", None),
    (
        "task",
        "project_id, status, position, created_at",
        "deleted_at IS NULL AND parent_id IS NULL",
    ),
    ("task", "workspace_id, assignee_id, due_date", "deleted_at IS NULL"),
    ("task", "project_id, created_at DESC", "deleted_at IS NULL"),
    ("task", "parent_id", None),
    ("comment", "task_id, created_at", None),
]


# --- вспомогательное ---------------------------------------------------------------------


def _sqlstate(exc: DBAPIError) -> str | None:
    orig: Any = exc.orig
    for obj in (orig, getattr(orig, "__cause__", None)):
        code = getattr(obj, "sqlstate", None) or getattr(obj, "pgcode", None)
        if code:
            return str(code)
    return None


async def assert_too_long(db: AsyncSession, coro: Any) -> None:
    """Значение > varchar(255) отклонено БД: 22001 (или 23514 CHECK); сессия жива (SAVEPOINT)."""
    with pytest.raises(DBAPIError) as info:
        async with db.begin_nested():
            await coro
    code = getattr(info.value.orig, "sqlstate", None) or getattr(info.value.orig, "pgcode", None)
    assert code in ("22001", "23514"), f"ожидался 22001/23514, получен {code}: {info.value}"


async def assert_integrity(db: AsyncSession, coro: Any, sqlstate: str) -> None:
    """Операция отклонена БД как IntegrityError с данным SQLSTATE; сессия жива (SAVEPOINT)."""
    with pytest.raises(IntegrityError) as info:
        async with db.begin_nested():
            await coro
    assert _sqlstate(info.value) == sqlstate, f"ожидали {sqlstate}, получили: {info.value!r}"


async def column_info(db: AsyncSession, table: str) -> dict[str, tuple[str, int | None, bool]]:
    rows = await db.execute(
        text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return {
        r.column_name: (r.data_type, r.character_maximum_length, r.is_nullable == "YES")
        for r in rows
    }


async def _base(db: AsyncSession) -> dict[str, Any]:
    """Пространство, владелец, проект и задача верхнего уровня."""
    ws = await make_workspace(db)
    owner = await make_user(db, workspace=ws, role="business_admin")
    project = await make_project(db, workspace_id=ws.id, owner_id=owner.id)
    task = await make_task(db, project_id=project.id, workspace_id=ws.id, created_by=owner.id)
    return {"ws": ws, "owner": owner, "project": project, "task": task}


def _norm_pred(pred: str) -> set[str]:
    return {p.strip() for p in pred.replace("(", " ").replace(")", " ").split(" AND ") if p.strip()}


def _norm_cols(cols: str) -> list[str]:
    return [re.sub(r"\s+", " ", c.strip().replace('"', "")) for c in cols.split(",")]


async def index_defs(db: AsyncSession, table: str) -> list[tuple[list[str], set[str] | None, str]]:
    rows = await db.execute(
        text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = :t"),
        {"t": table},
    )
    result = []
    for (definition,) in rows:
        m = re.search(r"USING \w+ \((.*?)\)(?: WHERE (.*))?$", definition)
        assert m, f"не разобран индекс: {definition}"
        pred = _norm_pred(m.group(2)) if m.group(2) else None
        result.append((_norm_cols(m.group(1)), pred, definition))
    return result


# --- реестр и модули ---------------------------------------------------------------------


def test_t69_registry_exposes_mvp_tables() -> None:
    import app.domain.registry  # noqa: F401
    from app.core.models import Base

    missing = set(MVP_TABLES) - set(Base.metadata.tables)
    assert not missing, f"в Base.metadata нет таблиц: {sorted(missing)}"


@pytest.mark.parametrize(
    ("table", "module"),
    [
        ("project", "app.domain.projects.models"),
        ("project_member", "app.domain.projects.models"),
        ("task", "app.domain.tasks.models"),
        ("comment", "app.domain.comments.models"),
    ],
)
def test_t69_models_live_in_planned_modules(table: str, module: str) -> None:
    mod = importlib.import_module(module)
    names = {
        getattr(obj, "__tablename__", None)
        for obj in vars(mod).values()
        if isinstance(obj, type) and obj.__module__ == module
    }
    assert table in names, f"{module} не объявляет модель таблицы {table!r}"


def test_t69_task_enums_are_strenums_with_values() -> None:
    from app.domain.tasks.models import TaskPriority, TaskStatus

    assert issubclass(TaskStatus, StrEnum)
    assert issubclass(TaskPriority, StrEnum)
    assert {m.value for m in TaskStatus} == {"todo", "in_progress", "review", "done"}
    assert {m.value for m in TaskPriority} == {"base", "high"}


def test_t69_domain_event_model_has_entity_type_check_over_all_entity_types() -> None:
    import app.domain.registry  # noqa: F401
    from app.domain.events.catalog import EntityType

    table = get_table("domain_event")
    checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
    matching = [c for c in checks if "entity_type" in str(c.sqltext)]
    assert matching, "в модели DomainEvent нет CHECK по entity_type"
    sql = str(matching[0].sqltext)
    assert all(f"'{e.value}'" in sql for e in EntityType), sql
    assert {e.value for e in EntityType} == set(ENTITY_TYPES)


# --- столбцы, PK, FK ---------------------------------------------------------------------


@pytest.mark.parametrize("table", MVP_TABLES)
async def test_t69_columns_exactly_as_in_plan(db: AsyncSession, table: str) -> None:
    """§11.6: набор столбцов, типы, длины, NULL; FR-13 — workspace_id у всех; D-25 — soft delete."""
    assert await column_info(db, table) == EXPECTED_COLUMNS[table]


@pytest.mark.parametrize("table", MVP_TABLES)
async def test_t69_no_server_defaults(db: AsyncSession, table: str) -> None:
    """D-4: серверных DEFAULT нет ни у меток времени, ни у description."""
    rows = await db.execute(
        text(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = :t AND column_default IS NOT NULL"
        ),
        {"t": table},
    )
    assert [r.column_name for r in rows] == []


@pytest.mark.parametrize("table", MVP_TABLES)
async def test_t69_primary_keys(db: AsyncSession, table: str) -> None:
    rows = await db.execute(
        text(
            "SELECT a.attname FROM pg_constraint c "
            "JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(attnum, ord) ON true "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
            "WHERE c.contype = 'p' AND c.conrelid = CAST(:t AS regclass) ORDER BY k.ord"
        ),
        {"t": f"public.{table}"},
    )
    assert [r.attname for r in rows] == EXPECTED_PK[table]


async def _foreign_keys(db: AsyncSession) -> dict[tuple[str, str], tuple[str, str, bool, bool]]:
    rows = await db.execute(
        text(
            "SELECT c.conrelid::regclass::text AS tbl, a.attname AS col, "
            "c.confrelid::regclass::text AS ref, c.confdeltype::text AS on_del, "
            "c.condeferrable, c.condeferred "
            "FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
            "WHERE c.contype = 'f' AND c.conrelid::regclass::text = ANY(:tables)"
        ),
        {"tables": list(MVP_TABLES)},
    )
    return {(r.tbl, r.col): (r.ref, r.on_del, r.condeferrable, r.condeferred) for r in rows}


async def test_t69_foreign_keys_and_on_delete(db: AsyncSession) -> None:
    """D-26: FK на app_user RESTRICT, дочерние объекты CASCADE; FR-13: FK на workspace."""
    fks = await _foreign_keys(db)
    for table, column, ref, on_delete in EXPECTED_FK:
        assert (table, column) in fks, f"нет FK {table}.{column}"
        got_ref, got_del, _, _ = fks[(table, column)]
        assert got_ref == ref, f"{table}.{column}: ссылается на {got_ref}"
        assert got_del == on_delete, f"{table}.{column}: ON DELETE {got_del}, ожидали {on_delete}"
    for table in MVP_TABLES:
        assert fks[(table, "workspace_id")][0] == "workspace"
        assert fks[(table, "workspace_id")][1] in {"a", "r"}  # не CASCADE и не SET NULL


async def test_t69_all_fks_deferrable_initially_immediate(db: AsyncSession) -> None:
    fks = await _foreign_keys(db)
    assert fks
    bad = {k: v for k, v in fks.items() if not (v[2] and not v[3])}
    assert not bad, f"FK не DEFERRABLE INITIALLY IMMEDIATE: {bad}"


async def test_t69_workspace_id_has_index_on_every_table(db: AsyncSession) -> None:
    for table in MVP_TABLES:
        defs = await index_defs(db, table)
        assert any(cols[0] == "workspace_id" and pred is None for cols, pred, _ in defs), table


# --- индексы -----------------------------------------------------------------------------


@pytest.mark.parametrize(("table", "columns", "predicate"), EXPECTED_INDEXES)
async def test_t69_indexes_with_exact_predicates(
    db: AsyncSession, table: str, columns: str, predicate: str | None
) -> None:
    want_cols = _norm_cols(columns)
    want_pred = _norm_pred(predicate) if predicate else None
    defs = await index_defs(db, table)
    found = [d for d in defs if d[0] == want_cols and d[1] == want_pred]
    assert found, f"нет индекса {table}({columns}) WHERE {predicate}; есть: {[d[2] for d in defs]}"


async def test_t69_no_gin_or_trigram_indexes_and_no_pg_trgm(db: AsyncSession) -> None:
    """D-58: расширений и GIN-индексов нет."""
    ext = await db.execute(text("SELECT extname FROM pg_extension"))
    assert "pg_trgm" not in {r.extname for r in ext}
    gin = await db.execute(
        text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexdef ILIKE :p"),
        {"p": "%USING gin%"},
    )
    assert [r.indexname for r in gin] == []


@pytest.mark.parametrize("table", ["label", "task_label", "mention", "attachment"])
async def test_t69_deferred_tables_are_absent(db: AsyncSession, table: str) -> None:
    """D-58: отложенные таблицы не создаются."""
    found = await db.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    assert found.first() is None


async def test_t69_project_has_no_status_column(db: AsyncSession) -> None:
    """D-57: архива нет, столбца project.status нет."""
    assert "status" not in await column_info(db, "project")


# --- CHECK: проект, задача, комментарий --------------------------------------------------


async def test_t69_project_name_length_bounds(db: AsyncSession) -> None:
    """FR-14, AC-108: name 1..255 символов (char_length, а не байты)."""
    b = await _base(db)
    ws, owner = b["ws"], b["owner"]
    await make_project(db, workspace_id=ws.id, owner_id=owner.id, name="я")
    await make_project(db, workspace_id=ws.id, owner_id=owner.id, name="я" * 255)
    # D-52: хранится как введено, пробельное допускается на уровне БД (отсекает сервис)
    await make_project(db, workspace_id=ws.id, owner_id=owner.id, name="   ")
    await assert_integrity(
        db, make_project(db, workspace_id=ws.id, owner_id=owner.id, name=""), CHECK_VIOLATION
    )
    await assert_too_long(
        db, make_project(db, workspace_id=ws.id, owner_id=owner.id, name="я" * 256)
    )


async def test_t69_project_description_length_bounds(db: AsyncSession) -> None:
    """FR-14, AC-108: description <= 10000 символов, пустая допустима."""
    b = await _base(db)
    ws, owner = b["ws"], b["owner"]
    await make_project(db, workspace_id=ws.id, owner_id=owner.id, description="")
    await make_project(db, workspace_id=ws.id, owner_id=owner.id, description="ы" * 10000)
    await assert_integrity(
        db,
        make_project(db, workspace_id=ws.id, owner_id=owner.id, description="ы" * 10001),
        CHECK_VIOLATION,
    )


async def test_t69_task_title_and_description_length_bounds(db: AsyncSession) -> None:
    """FR-18, AC-108: title 1..255, description <= 10000."""
    b = await _base(db)
    kw = {
        "project_id": b["project"].id,
        "workspace_id": b["ws"].id,
        "created_by": b["owner"].id,
    }
    await make_task(db, title="я", **kw)
    await make_task(db, title="я" * 255, description="ы" * 10000, **kw)
    for overrides in ({"title": ""}, {"description": "ы" * 10001}):
        await assert_integrity(db, make_task(db, **{**kw, **overrides}), CHECK_VIOLATION)
    await assert_too_long(db, make_task(db, **{**kw, "title": "я" * 256}))


@pytest.mark.parametrize("status", ["todo", "in_progress", "review", "done"])
async def test_t69_task_status_accepts_known_values(db: AsyncSession, status: str) -> None:
    b = await _base(db)
    await make_task(
        db,
        project_id=b["project"].id,
        workspace_id=b["ws"].id,
        created_by=b["owner"].id,
        status=status,
    )


@pytest.mark.parametrize("status", ["", "TODO", "blocked", "archived", "in-progress"])
async def test_t69_task_status_rejects_unknown(db: AsyncSession, status: str) -> None:
    b = await _base(db)
    await assert_integrity(
        db,
        make_task(
            db,
            project_id=b["project"].id,
            workspace_id=b["ws"].id,
            created_by=b["owner"].id,
            status=status,
        ),
        CHECK_VIOLATION,
    )


@pytest.mark.parametrize("priority", ["base", "high"])
async def test_t69_task_priority_accepts_known_values(db: AsyncSession, priority: str) -> None:
    b = await _base(db)
    await make_task(
        db,
        project_id=b["project"].id,
        workspace_id=b["ws"].id,
        created_by=b["owner"].id,
        priority=priority,
    )


@pytest.mark.parametrize("priority", ["", "low", "normal", "HIGH"])
async def test_t69_task_priority_rejects_unknown(db: AsyncSession, priority: str) -> None:
    b = await _base(db)
    await assert_integrity(
        db,
        make_task(
            db,
            project_id=b["project"].id,
            workspace_id=b["ws"].id,
            created_by=b["owner"].id,
            priority=priority,
        ),
        CHECK_VIOLATION,
    )


async def test_t69_position_only_for_top_level_tasks(db: AsyncSession) -> None:
    """FR-21, D-22: (parent_id IS NULL) = (position IS NOT NULL)."""
    b = await _base(db)
    kw = {
        "project_id": b["project"].id,
        "workspace_id": b["ws"].id,
        "created_by": b["owner"].id,
    }
    parent = b["task"]
    sub = await make_task(db, parent_id=parent.id, position=None, **kw)
    assert sub.position is None
    await make_task(db, position=0, **kw)  # позиция 0 допустима
    bad_sub = make_task(db, parent_id=parent.id, position=1024, **kw)
    await assert_integrity(db, bad_sub, CHECK_VIOLATION)
    bad_top = make_task(db, parent_id=None, position=None, **kw)
    await assert_integrity(db, bad_top, CHECK_VIOLATION)


async def test_t69_comment_body_length_bounds(db: AsyncSession) -> None:
    """FR-23, AC-108: body 1..10000 символов."""
    b = await _base(db)
    kw = {"task_id": b["task"].id, "workspace_id": b["ws"].id, "created_by": b["owner"].id}
    await make_comment(db, body="я", **kw)
    await make_comment(db, body="ы" * 10000, **kw)
    for bad in ("", "ы" * 10001):
        await assert_integrity(db, make_comment(db, body=bad, **kw), CHECK_VIOLATION)


# --- NOT NULL и целостность --------------------------------------------------------------


async def test_t69_not_null_columns_reject_null(db: AsyncSession) -> None:
    b = await _base(db)
    ws, owner, project, task = b["ws"], b["owner"], b["project"], b["task"]
    task_kw = {"project_id": project.id, "workspace_id": ws.id}
    await assert_integrity(
        db,
        make_task(db, created_by=None, **task_kw),
        NOT_NULL_VIOLATION,  # type: ignore[arg-type]
    )
    await assert_integrity(
        db,
        make_project(db, workspace_id=ws.id, owner_id=None, name="x"),
        NOT_NULL_VIOLATION,  # type: ignore[arg-type]
    )
    await assert_integrity(
        db,
        make_project(db, workspace_id=ws.id, owner_id=owner.id, description=None),  # type: ignore[arg-type]
        NOT_NULL_VIOLATION,
    )
    await assert_integrity(
        db,
        make_task(db, created_by=owner.id, description=None, **task_kw),  # type: ignore[arg-type]
        NOT_NULL_VIOLATION,
    )
    await assert_integrity(
        db,
        make_comment(db, task_id=task.id, workspace_id=ws.id, body=None),  # type: ignore[arg-type]
        NOT_NULL_VIOLATION,
    )


async def test_t69_project_member_pk_is_composite_unique(db: AsyncSession) -> None:
    b = await _base(db)
    ws, owner, project = b["ws"], b["owner"], b["project"]
    other = await make_user(db, workspace=ws, role="user")
    await make_project_member(db, project_id=project.id, user_id=owner.id, workspace_id=ws.id)
    await make_project_member(
        db, project_id=project.id, user_id=other.id, workspace_id=ws.id, created_by=owner.id
    )
    await assert_integrity(
        db,
        make_project_member(db, project_id=project.id, user_id=other.id, workspace_id=ws.id),
        UNIQUE_VIOLATION,
    )
    project2 = await make_project(db, workspace_id=ws.id, owner_id=owner.id)
    await make_project_member(db, project_id=project2.id, user_id=other.id, workspace_id=ws.id)


async def test_t69_fk_to_unknown_rows_rejected_immediately(db: AsyncSession) -> None:
    b = await _base(db)
    ws, owner = b["ws"], b["owner"]
    ghost = uuid.uuid4()
    await assert_integrity(db, make_project(db, workspace_id=ws.id, owner_id=ghost), FK_VIOLATION)
    await assert_integrity(
        db,
        make_task(db, project_id=ghost, workspace_id=ws.id, created_by=owner.id),
        FK_VIOLATION,
    )
    await assert_integrity(
        db,
        make_task(
            db,
            project_id=b["project"].id,
            workspace_id=ws.id,
            created_by=owner.id,
            assignee_id=ghost,
        ),
        FK_VIOLATION,
    )
    await assert_integrity(
        db, make_comment(db, task_id=ghost, workspace_id=ws.id, created_by=owner.id), FK_VIOLATION
    )
    await assert_integrity(
        db,
        make_project_member(db, project_id=b["project"].id, user_id=ghost, workspace_id=ws.id),
        FK_VIOLATION,
    )
    await assert_integrity(
        db, make_project(db, workspace_id=ghost, owner_id=owner.id), FK_VIOLATION
    )


async def test_t69_app_user_is_not_deletable_while_referenced(db: AsyncSession) -> None:
    """D-26: FK на app_user — RESTRICT (владелец, автор задачи, исполнитель, участник)."""
    b = await _base(db)
    ws = b["ws"]
    member = await make_user(db, workspace=ws, role="user")
    await make_project_member(db, project_id=b["project"].id, user_id=member.id, workspace_id=ws.id)
    for user_id in (b["owner"].id, member.id):
        with pytest.raises(DBAPIError):
            async with db.begin_nested():
                await db.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": user_id})


async def test_t69_deleting_project_cascades_to_members_tasks_subtasks_comments(
    db: AsyncSession,
) -> None:
    """D-26: ON DELETE CASCADE по цепочке проект → задача → подзадача → комментарий."""
    b = await _base(db)
    ws, owner, project, task = b["ws"], b["owner"], b["project"], b["task"]
    sub = await make_task(
        db, project_id=project.id, workspace_id=ws.id, created_by=owner.id, parent_id=task.id
    )
    await make_comment(db, task_id=task.id, workspace_id=ws.id, created_by=owner.id)
    await make_comment(db, task_id=sub.id, workspace_id=ws.id, created_by=owner.id)
    await make_project_member(db, project_id=project.id, user_id=owner.id, workspace_id=ws.id)
    await db.execute(text("DELETE FROM project WHERE id = :p"), {"p": project.id})
    for table in ("project_member", "task", "comment"):
        count = (await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608
        assert count == 0, table
    users = (await db.execute(text("SELECT count(*) FROM app_user"))).scalar_one()
    assert users == 1


async def test_t69_deleting_parent_task_cascades_to_subtasks(db: AsyncSession) -> None:
    b = await _base(db)
    ws, owner, project, task = b["ws"], b["owner"], b["project"], b["task"]
    sub = await make_task(
        db, project_id=project.id, workspace_id=ws.id, created_by=owner.id, parent_id=task.id
    )
    await db.execute(text("DELETE FROM task WHERE id = :t"), {"t": task.id})
    left = (
        await db.execute(text("SELECT count(*) FROM task WHERE id = :t"), {"t": sub.id})
    ).scalar_one()
    assert left == 0


async def test_t69_soft_delete_columns_roundtrip_and_row_stays(db: AsyncSession) -> None:
    """D-25, D-56: мягкое удаление — deleted_at + deleted_batch_id, строка остаётся."""
    b = await _base(db)
    ws, owner, project, task = b["ws"], b["owner"], b["project"], b["task"]
    comment = await make_comment(db, task_id=task.id, workspace_id=ws.id, created_by=owner.id)
    batch = uuid.uuid4()
    for table, row_id in (("project", project.id), ("task", task.id), ("comment", comment.id)):
        await db.execute(
            text(
                f"UPDATE {table} SET deleted_at = now(), deleted_batch_id = :b WHERE id = :i"  # noqa: S608
            ),
            {"b": batch, "i": row_id},
        )
        row = (
            await db.execute(
                text(f"SELECT deleted_at, deleted_batch_id FROM {table} WHERE id = :i"),  # noqa: S608
                {"i": row_id},
            )
        ).one()
        assert row.deleted_at is not None
        assert row.deleted_batch_id == batch


# --- CHECK журнала (D-41, D-58, AC-66) ---------------------------------------------------


async def test_t69_domain_event_check_exists_with_all_entity_types(db: AsyncSession) -> None:
    row = (
        await db.execute(
            text(
                "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint "
                "WHERE conname = :n AND conrelid = 'public.domain_event'::regclass"
            ),
            {"n": CHECK_NAME},
        )
    ).first()
    assert row is not None, f"нет CHECK {CHECK_NAME}"
    assert all(f"'{value}'" in row.d for value in ENTITY_TYPES), row.d


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
async def test_t69_domain_event_accepts_known_entity_types(
    db: AsyncSession, entity_type: str
) -> None:
    ws = await make_workspace(db)
    event_id = await make_domain_event(db, workspace_id=ws.id, entity_type=entity_type)
    assert event_id > 0


@pytest.mark.parametrize("entity_type", ["bogus", "", "User", "label", "mention"])
async def test_t69_domain_event_rejects_unknown_entity_type(
    db: AsyncSession, entity_type: str
) -> None:
    ws = await make_workspace(db)
    await assert_integrity(
        db,
        make_domain_event(db, workspace_id=ws.id, entity_type=entity_type),
        CHECK_VIOLATION,
    )


async def test_t69_domain_event_append_only_triggers_intact(db: AsyncSession) -> None:
    """AC-66: после 0004 журнал по-прежнему неизменяем (UPDATE/DELETE отклоняются)."""
    ws = await make_workspace(db)
    event_id = await make_domain_event(db, workspace_id=ws.id, entity_type="task")
    for sql in (
        "UPDATE domain_event SET action = 'x' WHERE id = :i",
        "DELETE FROM domain_event WHERE id = :i",
    ):
        with pytest.raises(DBAPIError) as info:
            async with db.begin_nested():
                await db.execute(text(sql), {"i": event_id})
        assert _sqlstate(info.value) == RESTRICT_VIOLATION, info.value  # type: ignore[arg-type]
    row = (
        await db.execute(
            text("SELECT entity_type, action FROM domain_event WHERE id = :i"), {"i": event_id}
        )
    ).one()
    assert (row.entity_type, row.action) == ("task", "user.created")
