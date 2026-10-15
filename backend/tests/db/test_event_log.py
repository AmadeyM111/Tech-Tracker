"""T07: журнал событий (plan §4.3 ``domain_event``, §4.4, D-7, D-8; миграция 0002).

Покрытие: AC-66 (триггеры UPDATE/DELETE/TRUNCATE, журнал только дописывается), AC-67
(одно событие на действие, в транзакции изменения; откат убирает событие), AC-64 (одна
запись с автором, временем UTC, действием; пароли в запись не попадают, FR-57), AC-65 /
BR-2 (``details`` только для ``entity_type = user``), FR-35/FR-38/FR-41 (основа таблицы и
индексов), D-7, D-8.

Публичный интерфейс: ``app.domain.events.catalog`` (EntityType, EventAction, EventSpec,
EVENT_CATALOG), ``app.domain.events.writer.record_event``. Имена членов ``EventAction``
контрактом не заданы — используются значения (``EventAction("user.created")``).
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.db_support import BACKEND_DIR, run_alembic
from tests.factories import (
    get_table,
    make_domain_event,
    make_user,
    make_workspace,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.clock import FixedClock

FIXED_NOW = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
MIGRATION_0002 = BACKEND_DIR / "migrations" / "versions" / "0002_domain_event.py"
TRIGGER_FUNCTION = "gt_forbid_event_mutation"

USER_ACTIONS = {
    "user.created",
    "user.blocked",
    "user.unblocked",
    "user.password_reset",
    "user.sessions_revoked",
    "user.role_assigned",
    "user.role_changed",
    "user.role_removed",
}
COLUMNS = {
    "id",
    "workspace_id",
    "occurred_at",
    "actor_id",
    "entity_type",
    "entity_id",
    "action",
    "changed_fields",
    "project_id",
    "deal_id",
    "in_audit",
    "changes",
    "details",
}


# --- вспомогательное ---------------------------------------------------------------------


async def _count(db: AsyncSession, where: str = "true") -> int:
    return int(
        (await db.execute(text(f"SELECT count(*) FROM domain_event WHERE {where}"))).scalar_one()
    )


async def _row(db: AsyncSession, event_id: int) -> Any:
    result = await db.execute(text("SELECT * FROM domain_event WHERE id = :id"), {"id": event_id})
    return result.mappings().one()


async def _snapshot(db: AsyncSession) -> list[tuple[Any, ...]]:
    result = await db.execute(text("SELECT * FROM domain_event ORDER BY id"))
    return [tuple(r) for r in result]


async def _rejected(db: AsyncSession, sql: str, **params: Any) -> None:
    """Оператор отклонён БД; сессия остаётся рабочей (SAVEPOINT).

    Сначала убеждаемся, что таблица есть: иначе «отказ» был бы из-за её отсутствия.
    """
    exists = await db.execute(text("SELECT to_regclass('public.domain_event') IS NOT NULL"))
    assert exists.scalar_one(), "таблицы domain_event нет"
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(text(sql), params)


def _record_event() -> Any:
    from app.domain.events.writer import record_event

    return record_event


def _action(value: str) -> Any:
    from app.domain.events.catalog import EventAction

    return EventAction(value)


async def _record(db: AsyncSession, workspace_id: uuid.UUID, **kw: Any) -> int:
    kw.setdefault("actor_id", None)
    kw.setdefault("action", _action("user.created"))
    kw.setdefault("entity_id", uuid.uuid4())
    return int(await _record_event()(db, workspace_id=workspace_id, **kw))


# --- структура таблицы (plan §4.3) -------------------------------------------------------


async def test_t07_table_columns_types_and_nullability(db: AsyncSession) -> None:
    rows = await db.execute(
        text(
            "SELECT column_name, data_type, udt_name, is_nullable, is_identity, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'domain_event'"
        )
    )
    cols = {r.column_name: r for r in rows}
    assert set(cols) == COLUMNS, f"состав столбцов: {sorted(set(cols) ^ COLUMNS)}"
    expected = {
        "id": ("bigint", "NO"),
        "workspace_id": ("uuid", "NO"),
        "occurred_at": ("timestamp with time zone", "NO"),
        "actor_id": ("uuid", "YES"),
        "entity_type": ("text", "NO"),
        "entity_id": ("uuid", "NO"),
        "action": ("text", "NO"),
        "changed_fields": ("ARRAY", "NO"),
        "project_id": ("uuid", "YES"),
        "deal_id": ("uuid", "YES"),
        "in_audit": ("boolean", "NO"),
        "changes": ("jsonb", "YES"),
        "details": ("jsonb", "YES"),
    }
    for name, (data_type, nullable) in expected.items():
        assert (cols[name].data_type, cols[name].is_nullable) == (data_type, nullable), name
    assert cols["changed_fields"].udt_name == "_text"
    assert cols["id"].is_identity == "YES"
    assert "{}" in str(cols["changed_fields"].column_default)


async def test_t07_changed_fields_defaults_to_empty_array_in_db(db: AsyncSession) -> None:
    ws = await make_workspace(db)
    result = await db.execute(
        text(
            "INSERT INTO domain_event (workspace_id, occurred_at, entity_type, entity_id, "
            "action, in_audit) VALUES (:w, now(), 'user', :e, 'user.created', true) "
            "RETURNING id, changed_fields"
        ),
        {"w": ws.id, "e": uuid.uuid4()},
    )
    row = result.one()
    assert row.changed_fields == []
    assert isinstance(row.id, int)


async def test_t07_model_is_registered_in_metadata() -> None:
    table = get_table("domain_event")
    assert {c.name for c in table.columns} == COLUMNS


async def test_t07_only_workspace_and_actor_foreign_keys(db: AsyncSession) -> None:
    """D-8: FK только на workspace и app_user, на доменные сущности FK нет."""
    rows = await db.execute(
        text(
            "SELECT a.attname AS col, c.confrelid::regclass::text AS target "
            "FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
            "WHERE c.contype = 'f' AND c.conrelid = 'public.domain_event'::regclass"
        )
    )
    fks = {r.col: r.target.split(".")[-1] for r in rows}
    assert fks == {"workspace_id": "workspace", "actor_id": "app_user"}


async def test_t07_workspace_foreign_key_is_enforced(db: AsyncSession) -> None:
    await _rejected(
        db,
        "INSERT INTO domain_event (workspace_id, occurred_at, entity_type, entity_id, action, "
        "in_audit) VALUES (:w, now(), 'user', :e, 'user.created', true)",
        w=uuid.uuid4(),
        e=uuid.uuid4(),
    )


def _index_shapes(defs: list[str]) -> set[tuple[str, str]]:
    """(столбцы, предикат) в нормализованном виде: нижний регистр, без скобок и пробелов."""
    shapes: set[tuple[str, str]] = set()
    for d in defs:
        m = re.search(r"USING \w+ \((.*?)\)(?: WHERE (.*))?$", d)
        assert m, d
        cols = re.sub(r"[\s()]", "", m.group(1).lower())
        where = re.sub(r"[\s()]", "", (m.group(2) or "").lower())
        shapes.add((cols, where))
    return shapes


async def test_t07_indexes_match_plan(db: AsyncSession) -> None:
    rows = await db.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'domain_event'"
        )
    )
    shapes = _index_shapes([r.indexdef for r in rows if "UNIQUE" not in r.indexdef])
    assert ("workspace_id,project_id,iddesc", "project_idisnotnull") in shapes
    assert ("workspace_id,deal_id,iddesc", "deal_idisnotnull") in shapes
    assert ("workspace_id,iddesc", "in_audit") in shapes or (
        "workspace_id,iddesc",
        "in_audit=true",
    ) in shapes
    assert ("entity_type,entity_id", "") in shapes


async def test_t07_primary_key_is_id(db: AsyncSession) -> None:
    rows = await db.execute(
        text(
            "SELECT a.attname FROM pg_index i JOIN pg_attribute a "
            "ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey) "
            "WHERE i.indrelid = 'public.domain_event'::regclass AND i.indisprimary"
        )
    )
    assert [r.attname for r in rows] == ["id"]


async def test_t07_ids_grow_monotonically(db: AsyncSession) -> None:
    ws = await make_workspace(db)
    a = await make_domain_event(db, workspace_id=ws.id)
    b = await make_domain_event(db, workspace_id=ws.id)
    assert b > a


# --- триггеры append-only (AC-66, D-8) ---------------------------------------------------


async def test_t07_trigger_function_and_triggers_exist(db: AsyncSession) -> None:
    fn = await db.execute(
        text("SELECT count(*) FROM pg_proc WHERE proname = :n"), {"n": TRIGGER_FUNCTION}
    )
    assert fn.scalar_one() == 1
    rows = await db.execute(
        text(
            "SELECT t.tgtype::int AS tgtype, p.proname FROM pg_trigger t "
            "JOIN pg_proc p ON p.oid = t.tgfoid "
            "WHERE t.tgrelid = 'public.domain_event'::regclass AND NOT t.tgisinternal"
        )
    )
    triggers = list(rows)
    assert triggers, "на domain_event нет пользовательских триггеров"
    assert all(t.proname == TRIGGER_FUNCTION for t in triggers)
    row, stmt = 1, 0
    before, update, delete, truncate = 2, 16, 8, 32
    row_level = [t.tgtype for t in triggers if t.tgtype & 1 == row]
    assert any(t & before and t & update for t in row_level), "нет BEFORE UPDATE (строки)"
    assert any(t & before and t & delete for t in row_level), "нет BEFORE DELETE (строки)"
    stmt_level = [t.tgtype for t in triggers if t.tgtype & 1 == stmt]
    assert any(t & before and t & truncate for t in stmt_level), "нет BEFORE TRUNCATE (оператор)"


async def test_t07_insert_is_allowed(db: AsyncSession) -> None:
    ws = await make_workspace(db)
    before = await _count(db)
    await make_domain_event(db, workspace_id=ws.id)
    assert await _count(db) == before + 1


async def test_ac66_update_is_rejected_and_row_unchanged(db: AsyncSession) -> None:
    ws = await make_workspace(db)
    event_id = await make_domain_event(db, workspace_id=ws.id, action="user.blocked")
    before = await _snapshot(db)
    await _rejected(
        db, "UPDATE domain_event SET action = 'user.unblocked' WHERE id = :id", id=event_id
    )
    await _rejected(db, "UPDATE domain_event SET in_audit = false")
    await _rejected(db, "UPDATE domain_event SET details = '{}'::jsonb WHERE id = :id", id=event_id)
    assert await _snapshot(db) == before


async def test_ac66_update_to_same_values_is_rejected(db: AsyncSession) -> None:
    ws = await make_workspace(db)
    event_id = await make_domain_event(db, workspace_id=ws.id)
    await _rejected(db, "UPDATE domain_event SET action = action WHERE id = :id", id=event_id)


async def test_ac66_delete_is_rejected_and_row_kept(db: AsyncSession) -> None:
    ws = await make_workspace(db)
    event_id = await make_domain_event(db, workspace_id=ws.id)
    before = await _snapshot(db)
    await _rejected(db, "DELETE FROM domain_event WHERE id = :id", id=event_id)
    await _rejected(db, "DELETE FROM domain_event")
    assert await _snapshot(db) == before


async def test_ac66_truncate_is_rejected(db: AsyncSession) -> None:
    ws = await make_workspace(db)
    await make_domain_event(db, workspace_id=ws.id)
    before = await _snapshot(db)
    await _rejected(db, "TRUNCATE TABLE domain_event")
    await _rejected(db, "TRUNCATE TABLE domain_event RESTART IDENTITY")
    await _rejected(db, "TRUNCATE TABLE workspace CASCADE")
    assert await _snapshot(db) == before


async def test_ac66_truncate_of_empty_table_is_also_rejected(db: AsyncSession) -> None:
    """Триггер уровня оператора срабатывает независимо от наличия строк."""
    await _rejected(db, "TRUNCATE TABLE domain_event")


async def test_ac66_referenced_workspace_and_actor_cannot_be_deleted(db: AsyncSession) -> None:
    """Каскадом или SET NULL журнал не меняется: удаление родителя отклоняется."""
    ws = await make_workspace(db)
    actor = await make_user(db, workspace=ws)
    await make_domain_event(db, workspace_id=ws.id, actor_id=actor.id)
    before = await _snapshot(db)
    await _rejected(db, "DELETE FROM app_user WHERE id = :id", id=actor.id)
    await _rejected(db, "DELETE FROM workspace WHERE id = :id", id=ws.id)
    assert await _snapshot(db) == before


@pytest.mark.committed
async def test_ac66_committed_events_survive_mutation_attempts(
    committed: async_sessionmaker[AsyncSession], fixed_clock: FixedClock
) -> None:
    """AC-66: N записей зафиксированы; в новых сессиях UPDATE/DELETE/TRUNCATE падают, N прежних."""
    async with committed() as s, s.begin():
        ws = await make_workspace(s)
        actor = await make_user(s, workspace=ws)
        for _ in range(3):
            await _record(s, ws.id, actor_id=actor.id, entity_id=uuid.uuid4())
        n = await _count(s)
    assert n == 3
    async with committed() as s:
        before = await _snapshot(s)
    for sql in (
        "UPDATE domain_event SET actor_id = NULL",
        "DELETE FROM domain_event",
        "TRUNCATE TABLE domain_event",
    ):
        async with committed() as s:
            with pytest.raises(DBAPIError):
                async with s.begin():
                    await s.execute(text(sql))
    async with committed() as s:
        assert await _snapshot(s) == before
        await s.execute(text("SELECT 1"))
    # дописывать можно, прежние записи на месте
    async with committed() as s, s.begin():
        await _record(s, ws.id)
    async with committed() as s:
        after = await _snapshot(s)
    assert len(after) == n + 1
    assert after[:n] == before


# --- каталог (plan §4.4) -----------------------------------------------------------------


def test_t07_entity_type_enum_matches_plan() -> None:
    from enum import StrEnum

    from app.domain.events.catalog import EntityType

    assert issubclass(EntityType, StrEnum)
    assert {m.value for m in EntityType} == {
        "user",
        "project",
        "task",
        "comment",
        "attachment",
        "stage",
        "deal",
    }
    assert EntityType("user") == "user"


def test_t07_event_action_contains_user_actions_and_is_strenum() -> None:
    """T30: в R1.1 к ``user.*`` добавлены действия §10.5 (полный состав — unit-тест каталога)."""
    from enum import StrEnum

    from app.domain.events.catalog import EventAction

    assert issubclass(EventAction, StrEnum)
    assert {m.value for m in EventAction} >= USER_ACTIONS


def test_t07_event_spec_is_frozen_dataclass_with_plan_fields() -> None:
    from app.domain.events.catalog import EntityType, EventSpec

    assert dataclasses.is_dataclass(EventSpec)
    assert [f.name for f in dataclasses.fields(EventSpec)] == [
        "entity_type",
        "audit",
        "feed",
        "deal_history",
        "fields",
        "value_fields",
    ]
    spec = EventSpec(entity_type=EntityType("user"), audit=True, feed=None, deal_history=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.audit = False  # type: ignore[misc]


def test_t07_catalog_covers_every_action_and_user_actions_are_audited_user_events() -> None:
    from collections.abc import Mapping

    from app.domain.events.catalog import (
        EVENT_CATALOG,
        EntityType,
        EventAction,
        EventSpec,
    )

    assert isinstance(EVENT_CATALOG, Mapping)
    assert set(EVENT_CATALOG) == set(EventAction)
    for action, spec in EVENT_CATALOG.items():
        assert isinstance(spec, EventSpec)
        if action.value not in USER_ACTIONS:
            continue
        assert spec.entity_type == EntityType.USER, action
        assert spec.audit is True, action
        assert spec.feed is None, action
        assert spec.deal_history is False, action


# --- record_event (plan §4.4; AC-64, AC-67) ----------------------------------------------


async def test_ac64_record_event_writes_one_row_with_author_time_action_entity(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    actor = await make_user(db, workspace=ws, role="tech_admin")
    target = await make_user(db, workspace=ws)
    before = await _count(db)

    event_id = await _record(
        db,
        ws.id,
        actor_id=actor.id,
        action=_action("user.blocked"),
        entity_id=target.id,
    )

    assert isinstance(event_id, int)
    assert await _count(db) == before + 1
    row = await _row(db, event_id)
    assert row["workspace_id"] == ws.id
    assert row["actor_id"] == actor.id
    assert row["entity_id"] == target.id
    assert row["entity_type"] == "user"
    assert row["action"] == "user.blocked"
    assert row["in_audit"] is True
    assert row["occurred_at"] == FIXED_NOW
    assert row["occurred_at"].utcoffset() == timedelta(0)
    assert row["changed_fields"] == []
    assert row["project_id"] is None
    assert row["deal_id"] is None
    assert row["changes"] is None
    assert row["details"] is None


async def test_ac64_occurred_at_follows_clock(db: AsyncSession, fixed_clock: FixedClock) -> None:
    ws = await make_workspace(db)
    first = await _record(db, ws.id)
    fixed_clock.advance(timedelta(minutes=5))
    second = await _record(db, ws.id)
    assert (await _row(db, first))["occurred_at"] == FIXED_NOW
    assert (await _row(db, second))["occurred_at"] == FIXED_NOW + timedelta(minutes=5)
    assert second > first


async def test_ac64_system_author_is_null(db: AsyncSession, fixed_clock: FixedClock) -> None:
    ws = await make_workspace(db)
    event_id = await _record(db, ws.id, actor_id=None)
    assert (await _row(db, event_id))["actor_id"] is None


@pytest.mark.parametrize("value", sorted(USER_ACTIONS))
async def test_ac64_every_user_action_is_recorded_as_audit_user_event(
    db: AsyncSession, fixed_clock: FixedClock, value: str
) -> None:
    ws = await make_workspace(db)
    event_id = await _record(db, ws.id, action=_action(value))
    row = await _row(db, event_id)
    assert (row["action"], row["entity_type"], row["in_audit"]) == (value, "user", True)


async def test_ac64_role_details_roundtrip(db: AsyncSession, fixed_clock: FixedClock) -> None:
    ws = await make_workspace(db)
    changed = await _record(
        db,
        ws.id,
        action=_action("user.role_changed"),
        details={"role_from": "user", "role_to": "mixed"},
    )
    assigned = await _record(
        db,
        ws.id,
        action=_action("user.role_assigned"),
        details={"role_from": None, "role_to": "user"},
    )
    assert (await _row(db, changed))["details"] == {"role_from": "user", "role_to": "mixed"}
    assert (await _row(db, assigned))["details"] == {"role_from": None, "role_to": "user"}


async def test_t07_changed_fields_and_changes_roundtrip(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    pid, did = uuid.uuid4(), uuid.uuid4()
    changes = [{"field": "status", "old": "todo", "new": "done"}]
    event_id = await _record(
        db,
        ws.id,
        action=_action("task.updated"),
        changed_fields=["status", "due_date"],
        project_id=pid,
        deal_id=did,
        changes=changes,
    )
    row = await _row(db, event_id)
    assert row["changed_fields"] == ["status", "due_date"]
    assert row["project_id"] == pid
    assert row["deal_id"] == did
    assert row["changes"] == changes


@pytest.mark.parametrize(
    "bad_details",
    [
        {"password": "S3cret-value-123"},
        {"new_password": "S3cret-value-123"},
        {"one_time_password": "S3cret-value-123"},
        {"password_hash": "$argon2id$v=19$x"},
        {"role_to": "user", "password": "S3cret-value-123"},
        {"login": "someone"},
    ],
)
async def test_fr57_details_with_password_or_unknown_keys_are_rejected(
    db: AsyncSession, fixed_clock: FixedClock, bad_details: dict[str, Any]
) -> None:
    """FR-57/AC-64: в details допустимы только role_from/role_to; ничего не записано."""
    ws = await make_workspace(db)
    before = await _count(db)
    with pytest.raises((ValueError, TypeError)):
        await _record(db, ws.id, action=_action("user.password_reset"), details=bad_details)
    assert await _count(db) == before


async def test_t07_unknown_action_string_raises_value_error(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    before = await _count(db)
    with pytest.raises(ValueError):
        await _record(db, ws.id, action="user.teleported")
    assert await _count(db) == before


def _patch_catalog(monkeypatch: pytest.MonkeyPatch, catalog: dict[Any, Any]) -> None:
    import app.domain.events.catalog as catalog_module
    import app.domain.events.writer as writer_module

    monkeypatch.setattr(catalog_module, "EVENT_CATALOG", catalog, raising=False)
    monkeypatch.setattr(writer_module, "EVENT_CATALOG", catalog, raising=False)


async def test_t07_action_missing_from_catalog_raises_value_error(
    db: AsyncSession, fixed_clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.events.catalog import EVENT_CATALOG

    action = _action("user.created")
    _patch_catalog(monkeypatch, {a: s for a, s in EVENT_CATALOG.items() if a != action})
    ws = await make_workspace(db)
    before = await _count(db)
    with pytest.raises(ValueError):
        await _record(db, ws.id, action=action)
    assert await _count(db) == before


async def test_t07_in_audit_and_entity_type_come_from_catalog(
    db: AsyncSession, fixed_clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from app.domain.events.catalog import EVENT_CATALOG, EntityType

    action = _action("user.created")
    patched = dict(EVENT_CATALOG)
    patched[action] = replace(EVENT_CATALOG[action], audit=False, entity_type=EntityType("task"))
    _patch_catalog(monkeypatch, patched)
    ws = await make_workspace(db)
    row = await _row(db, await _record(db, ws.id, action=action))
    assert row["in_audit"] is False
    assert row["entity_type"] == "task"


async def test_ac65_details_allowed_only_for_user_entity_type(
    db: AsyncSession, fixed_clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BR-2: для бизнес-сущностей details не принимается, даже допустимые ключи."""
    from dataclasses import replace

    from app.domain.events.catalog import EVENT_CATALOG, EntityType

    action = _action("user.role_changed")
    patched = dict(EVENT_CATALOG)
    patched[action] = replace(EVENT_CATALOG[action], entity_type=EntityType("deal"))
    _patch_catalog(monkeypatch, patched)
    ws = await make_workspace(db)
    before = await _count(db)
    with pytest.raises(ValueError):
        await _record(db, ws.id, action=action, details={"role_from": "user", "role_to": "mixed"})
    assert await _count(db) == before


# --- T30: белые списки полей (plan D-41, §10.5; BR-2, AC-65) ----------------------------

SECRET = "TOP-SECRET-value-9f3a"


async def _assert_rejected(db: AsyncSession, ws_id: uuid.UUID, **kw: Any) -> ValueError:
    """``ValueError``, строка не записана, транзакция сессии рабочая."""
    before = await _count(db)
    with pytest.raises(ValueError) as info:
        await _record(db, ws_id, **kw)
    assert await _count(db) == before
    assert (await db.execute(text("SELECT 1"))).scalar_one() == 1  # транзакция не испорчена
    return info.value


async def test_ac65_changed_field_outside_whitelist_is_rejected(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    exc = await _assert_rejected(
        db,
        ws.id,
        action=_action("task.updated"),
        project_id=uuid.uuid4(),
        changed_fields=["status", "priority"],
    )
    assert "task.updated" in str(exc)
    assert "priority" in str(exc)


async def test_ac65_changed_fields_for_event_without_fields_are_rejected(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    exc = await _assert_rejected(
        db, ws.id, action=_action("user.created"), changed_fields=["login"]
    )
    assert "user.created" in str(exc)
    assert "login" in str(exc)


async def test_ac65_duplicate_changed_field_is_rejected(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    exc = await _assert_rejected(
        db,
        ws.id,
        action=_action("task.updated"),
        project_id=uuid.uuid4(),
        changed_fields=["status", "status"],
    )
    assert "task.updated" in str(exc)
    assert "status" in str(exc)


async def test_br2_changes_for_event_with_empty_value_fields_are_rejected(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    exc = await _assert_rejected(
        db,
        ws.id,
        action=_action("project.updated"),
        project_id=uuid.uuid4(),
        changed_fields=["name"],
        changes=[{"field": "name", "old": SECRET, "new": "x"}],
    )
    assert "project.updated" in str(exc)
    assert "name" in str(exc)
    assert SECRET not in str(exc)


async def test_br2_change_field_outside_value_fields_is_rejected_without_values(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    exc = await _assert_rejected(
        db,
        ws.id,
        action=_action("task.updated"),
        project_id=uuid.uuid4(),
        changed_fields=["title"],
        changes=[{"field": "title", "old": SECRET, "new": SECRET + "-2"}],
    )
    text_ = str(exc)
    assert "task.updated" in text_
    assert "title" in text_
    assert SECRET not in text_
    assert SECRET not in repr(exc)


async def test_br2_exception_text_has_no_values_for_invalid_changed_field(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    exc = await _assert_rejected(
        db,
        ws.id,
        action=_action("task.updated"),
        project_id=uuid.uuid4(),
        changed_fields=["priority"],
        changes=[{"field": "status", "old": SECRET, "new": "done"}],
    )
    assert SECRET not in str(exc)


async def test_fr41_project_feed_event_without_project_id_is_rejected(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    exc = await _assert_rejected(db, ws.id, action=_action("task.created"), project_id=None)
    assert "task.created" in str(exc)


async def test_fr41_every_project_feed_action_requires_project_id(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    from app.domain.events.catalog import EVENT_CATALOG

    ws = await make_workspace(db)
    project_actions = [a for a, s in EVENT_CATALOG.items() if s.feed == "project"]
    assert project_actions, "в каталоге нет событий ленты проекта"
    for action in project_actions:
        await _assert_rejected(db, ws.id, action=action, project_id=None)


async def test_fr41_every_r11_event_is_recorded_with_catalog_attributes(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    """Валидные события R1.1: максимум полей из белых списков; строка пишется и читается."""
    from app.domain.events.catalog import EVENT_CATALOG

    ws = await make_workspace(db)
    pid = uuid.uuid4()
    recorded = 0
    for action, spec in EVENT_CATALOG.items():
        if spec.feed != "project":
            continue
        fields = sorted(spec.fields)
        changes = [{"field": f, "old": "a", "new": "b"} for f in sorted(spec.value_fields)] or None
        event_id = await _record(
            db, ws.id, action=action, project_id=pid, changed_fields=fields, changes=changes
        )
        row = await _row(db, event_id)
        assert row["action"] == action.value
        assert row["entity_type"] == spec.entity_type.value
        assert row["in_audit"] is spec.audit
        assert row["project_id"] == pid
        assert row["changed_fields"] == fields
        assert row["changes"] == changes
        recorded += 1
    assert recorded == 15


async def test_t30_valid_event_with_subset_of_fields_and_no_changes(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    event_id = await _record(
        db,
        ws.id,
        action=_action("task.updated"),
        project_id=uuid.uuid4(),
        changed_fields=["description"],
    )
    row = await _row(db, event_id)
    assert row["changed_fields"] == ["description"]
    assert row["changes"] is None


async def test_t30_user_event_without_project_id_still_valid(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    event_id = await _record(db, ws.id, action=_action("user.blocked"))
    assert (await _row(db, event_id))["project_id"] is None


async def test_t30_rejection_does_not_break_following_valid_write(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    await _assert_rejected(
        db, ws.id, action=_action("task.updated"), project_id=uuid.uuid4(), changed_fields=["zzz"]
    )
    before = await _count(db)
    await _record(db, ws.id, action=_action("user.created"))
    assert await _count(db) == before + 1


# --- транзакционность (AC-67) ------------------------------------------------------------


async def test_ac67_one_action_one_row(db: AsyncSession, fixed_clock: FixedClock) -> None:
    ws = await make_workspace(db)
    entity = uuid.uuid4()
    await _record(db, ws.id, entity_id=entity, action=_action("user.blocked"))
    assert await _count(db, f"entity_id = '{entity}'") == 1
    await _record(db, ws.id, entity_id=entity, action=_action("user.unblocked"))
    assert await _count(db, f"entity_id = '{entity}'") == 2


async def test_ac67_event_is_rolled_back_with_transaction(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    ws = await make_workspace(db)
    before = await _count(db)
    nested = await db.begin_nested()
    await _record(db, ws.id)
    assert await _count(db) == before + 1
    await nested.rollback()
    assert await _count(db) == before


async def test_ac67_rejected_change_leaves_no_event(
    db: AsyncSession, fixed_clock: FixedClock
) -> None:
    """Событие записано, затем действие отклонено исключением — события нет."""
    ws = await make_workspace(db)
    before = await _count(db)

    class Rejected(Exception):
        pass

    with pytest.raises(Rejected):
        async with db.begin_nested():
            await _record(db, ws.id)
            raise Rejected
    assert await _count(db) == before


@pytest.mark.committed
async def test_ac67_event_invisible_until_commit_and_gone_after_rollback(
    committed: async_sessionmaker[AsyncSession], fixed_clock: FixedClock
) -> None:
    async with committed() as s, s.begin():
        ws = await make_workspace(s)

    async with committed() as writer, committed() as reader:
        await writer.begin()
        await _record(writer, ws.id)
        assert await _count(writer) == 1
        assert await _count(reader) == 0
        await writer.rollback()
    async with committed() as s:
        assert await _count(s) == 0

    async with committed() as writer, committed() as reader:
        await writer.begin()
        await _record(writer, ws.id)
        await writer.commit()
        assert await _count(reader) == 1


@pytest.mark.committed
async def test_ac67_exception_inside_transaction_block_removes_event(
    committed: async_sessionmaker[AsyncSession], fixed_clock: FixedClock
) -> None:
    async with committed() as s, s.begin():
        ws = await make_workspace(s)
    with pytest.raises(RuntimeError):
        async with committed() as s, s.begin():
            await _record(s, ws.id)
            raise RuntimeError("422")
    async with committed() as s:
        assert await _count(s) == 0


# --- миграция 0002 -----------------------------------------------------------------------


def test_t07_migration_file_chain_and_functions() -> None:
    assert MIGRATION_0002.is_file(), "нет backend/migrations/versions/0002_domain_event.py"
    tree = ast.parse(MIGRATION_0002.read_text(encoding="utf-8"))
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"upgrade", "downgrade"} <= funcs
    values: dict[str, Any] = {}
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant):
                    values[t.id] = n.value.value
        elif (
            isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name)
            and isinstance(n.value, ast.Constant)
        ):
            values[n.target.id] = n.value.value
    assert values.get("revision") == "0002"
    assert values.get("down_revision") == "0001"


async def _alembic(url: str, *args: str) -> None:
    result = await asyncio.to_thread(run_alembic, url, *args)
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
    )


async def _public_objects(maker: async_sessionmaker[AsyncSession]) -> tuple[set[str], int]:
    async with maker() as s:
        rows = await s.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        fn = await s.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = :n"), {"n": TRIGGER_FUNCTION}
        )
        return {r.table_name for r in rows}, int(fn.scalar_one())


@pytest.mark.committed
async def test_t07_migration_0002_upgrade_downgrade_upgrade_check(
    committed: async_sessionmaker[AsyncSession], test_database_url: str
) -> None:
    tables, fn = await _public_objects(committed)
    assert "domain_event" in tables and fn == 1
    await _alembic(test_database_url, "downgrade", "0001")
    tables, fn = await _public_objects(committed)
    assert "domain_event" not in tables, "downgrade 0002 оставил domain_event"
    assert fn == 0, "downgrade 0002 оставил функцию gt_forbid_event_mutation"
    assert {"workspace", "app_user", "workspace_member", "user_session"} <= tables
    await _alembic(test_database_url, "upgrade", "head")
    tables, fn = await _public_objects(committed)
    assert "domain_event" in tables and fn == 1
    await _alembic(test_database_url, "check")


@pytest.mark.committed
async def test_t07_downgrade_to_base_leaves_no_function(
    committed: async_sessionmaker[AsyncSession], test_database_url: str
) -> None:
    tables, fn = await _public_objects(committed)
    assert "domain_event" in tables and fn == 1
    await _alembic(test_database_url, "downgrade", "base")
    tables, fn = await _public_objects(committed)
    assert tables <= {"alembic_version"}
    assert fn == 0
