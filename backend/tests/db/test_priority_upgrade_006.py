"""R6-T07: миграция 0007 «три приоритета» (spec 006 AC-14, AC-15, AC-54; FR-10, FR-11, NFR-4).

plan §5, PD-5: ``committed``-тест на head -> ``downgrade 0006`` (схема предыдущей версии, CHECK
``base``/``high``) -> данные -> ``alembic upgrade head`` подпроцессом -> проверки. Миграция
идёт одной транзакцией, ``updated_at`` не трогает и в журнал не пишет. Сбой внедряется
триггером на ``alembic_version`` (``install_failure(on="version")``): состояние после
прерванного шага совпадает с состоянием до него.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.db_support import database_url_from_env, run_alembic
from tests.upgrade002_support import (
    FAILURE_MARK,
    HEAD_REVISION,
    alembic_ok,
    alembic_versions,
    install_failure,
    remove_failure,
    try_upgrade,
)

if TYPE_CHECKING:
    from tests.conftest import ApiEnv

PRIORITY_CHECK = "ck_task_priority_valid"
CHECK_VIOLATION = "23514"
PAST = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)


# --- помощники ----------------------------------------------------------------------------


async def _to_0006(env: ApiEnv) -> None:
    """head -> ``downgrade 0006``: схема предыдущей версии (CHECK ``base``/``high``)."""
    await alembic_ok(env, "downgrade", "0006")
    assert await alembic_versions(env) == ["0006"]


async def _check_def(env: ApiEnv) -> str:
    rows = await env.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n").bindparams(
            n=PRIORITY_CHECK
        )
    )
    assert rows is not None and len(rows) == 1, f"нет ровно одного CHECK {PRIORITY_CHECK}"
    return str(rows[0][0])


def _check_values(definition: str) -> set[str]:
    """Значения из определения CHECK: ``CHECK ((priority = ANY (ARRAY['a'::text, ...])))``."""
    import re

    return set(re.findall(r"'([^']*)'", definition))


async def _assert_check_values(env: ApiEnv, expected: set[str]) -> None:
    assert _check_values(await _check_def(env)) == expected


async def _insert_task(
    env: ApiEnv,
    ws: Any,
    project: Any,
    owner: Any,
    *,
    priority: str,
    index: int,
    parent_id: uuid.UUID | None = None,
    deleted: bool = False,
) -> uuid.UUID:
    """Задача с заполненными и различными значениями всех полей, включая ``updated_at``."""
    from tests.factories import make_task

    stamp = PAST + timedelta(hours=index)
    extra: dict[str, object] = {"created_at": stamp, "updated_at": stamp + timedelta(minutes=7)}
    if deleted:
        extra["deleted_at"] = stamp + timedelta(days=1)
        extra["deleted_batch_id"] = uuid.uuid4()
    async with env.sessionmaker() as s:
        row = await make_task(
            s,
            project_id=project.id,
            workspace_id=ws.id,
            created_by=owner.id,
            parent_id=parent_id,
            title=f"Задача {index}",
            description=f"Описание {index}",
            status=("todo", "in_progress", "review", "done")[index % 4],
            priority=priority,
            due_date=date(2026, 11, 1) + timedelta(days=index),
            assignee_id=owner.id,
            **extra,
        )
        await s.commit()
    return row.id


async def _seed(env: ApiEnv, priorities: list[str]) -> dict[str, Any]:
    """Пространство, БА, проект; задачи верхнего уровня с ``priorities`` (по одной на элемент),
    у каждой третьей - подзадача, одна задача мягко удалена. Возвращает ``{ids, ...}``."""
    from tests.factories import make_project, make_user, make_workspace

    async with env.sessionmaker() as s:
        ws = await make_workspace(s)
        owner = await make_user(s, workspace=ws, role="business_admin", login="u006.owner")
        project = await make_project(s, workspace_id=ws.id, owner_id=owner.id, name="P006")
        await s.commit()
    ids: list[uuid.UUID] = []
    for i, priority in enumerate(priorities):
        ids.append(
            await _insert_task(
                env,
                ws,
                project,
                owner,
                priority=priority,
                index=i,
                deleted=(i == len(priorities) - 1),
            )
        )
    n = len(priorities)
    for j, parent in enumerate(ids[::3]):
        # подзадачи наследуют приоритет-пример из набора (по кругу)
        ids.append(
            await _insert_task(
                env,
                ws,
                project,
                owner,
                priority=priorities[j % n],
                index=n + j,
                parent_id=parent,
                deleted=(j == 1),  # мягко удалённая подзадача
            )
        )
    return {"ws": ws, "owner": owner, "project": project, "ids": ids}


async def _priorities(env: ApiEnv) -> dict[uuid.UUID, str]:
    rows = await env.execute(text("SELECT id, priority FROM task"))
    assert rows is not None
    return {r[0]: str(r[1]) for r in rows}


async def _snapshot_without_priority(env: ApiEnv) -> list[str]:
    """Все остальные столбцы каждой строки ``task`` (включая ``updated_at``) текстом."""
    rows = await env.execute(
        text("SELECT (to_jsonb(t) - 'priority')::text FROM task t ORDER BY id")
    )
    assert rows is not None
    return [str(r[0]) for r in rows]


async def _event_count(env: ApiEnv) -> int:
    rows = await env.execute(text("SELECT count(*) FROM domain_event"))
    assert rows is not None
    return int(rows[0][0])


async def _insert_fails(env: ApiEnv, seeded: dict[str, Any], priority: str) -> None:
    from tests.factories import make_task

    with pytest.raises(IntegrityError) as info:
        async with env.sessionmaker() as s:
            await make_task(
                s,
                project_id=seeded["project"].id,
                workspace_id=seeded["ws"].id,
                created_by=seeded["owner"].id,
                priority=priority,
            )
            await s.commit()
    orig: Any = info.value.orig
    code = getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "__cause__", None), "sqlstate", None
    )
    assert code == CHECK_VIOLATION, f"{priority!r}: ожидали 23514, получили {info.value!r}"


async def _insert_ok(env: ApiEnv, seeded: dict[str, Any], priority: str) -> None:
    await _insert_task(
        env, seeded["ws"], seeded["project"], seeded["owner"], priority=priority, index=40
    )


# --- AC-14: обновление ---------------------------------------------------------------------


@pytest.mark.committed
async def test_006_ac14_upgrade_base_to_medium_everything_else_byte_for_byte(
    committed_api_env: ApiEnv,
) -> None:
    """006/AC-14 (FR-10): ``base`` -> ``medium``, ``high`` -> ``high``, ``low`` нет; число строк
    и все остальные столбцы (в т.ч. ``updated_at``) совпадают; CHECK отклоняет ``base`` и
    ``normal``; записей журнала не добавилось. Мягко удалённые и подзадачи входят."""
    env = committed_api_env
    await _to_0006(env)
    await _assert_check_values(env, {"base", "high"})
    seeded = await _seed(env, ["base", "high", "base", "high", "base", "base", "high"])
    before = await _priorities(env)
    assert set(before.values()) == {"base", "high"}
    assert len(before) == 7 + 3  # 7 верхнего уровня + подзадачи у каждой третьей
    deleted = await env.execute(text("SELECT count(*) FROM task WHERE deleted_at IS NOT NULL"))
    assert deleted is not None and deleted[0][0] >= 1
    parents = await env.execute(text("SELECT count(*) FROM task WHERE parent_id IS NOT NULL"))
    assert parents is not None and parents[0][0] == 3
    snapshot = await _snapshot_without_priority(env)
    events = await _event_count(env)

    await alembic_ok(env, "upgrade", "head")

    assert await alembic_versions(env) == [HEAD_REVISION]
    after = await _priorities(env)
    assert after.keys() == before.keys()
    assert {k: ("medium" if v == "base" else v) for k, v in before.items()} == after
    assert "low" not in after.values() and "base" not in after.values()
    assert list(after.values()).count("high") == list(before.values()).count("high")
    assert await _snapshot_without_priority(env) == snapshot
    assert await _event_count(env) == events
    await _assert_check_values(env, {"low", "medium", "high"})
    await _insert_fails(env, seeded, "base")
    await _insert_fails(env, seeded, "normal")
    await _insert_ok(env, seeded, "low")
    assert await _event_count(env) == events


@pytest.mark.committed
async def test_006_ac14_upgrade_on_empty_task_table(committed_api_env: ApiEnv) -> None:
    env = committed_api_env
    await _to_0006(env)

    await alembic_ok(env, "upgrade", "head")

    assert await alembic_versions(env) == [HEAD_REVISION]
    assert await _priorities(env) == {}
    await _assert_check_values(env, {"low", "medium", "high"})


# --- AC-15: откат --------------------------------------------------------------------------


@pytest.mark.committed
async def test_006_ac15_downgrade_low_medium_to_base_then_upgrade_again(
    committed_api_env: ApiEnv,
) -> None:
    """006/AC-15 (FR-11): ``low``/``medium`` -> ``base``, ``high`` остаётся; CHECK принимает
    только ``base``/``high``; повторное обновление проходит, бывшие ``base`` -> ``medium``."""
    env = committed_api_env
    seeded = await _seed(env, ["low", "medium", "high", "low", "medium", "high", "medium"])
    before = await _priorities(env)
    assert {"low", "medium", "high"} == set(before.values())
    snapshot = await _snapshot_without_priority(env)
    events = await _event_count(env)

    await alembic_ok(env, "downgrade", "0006")

    assert await alembic_versions(env) == ["0006"]
    down = await _priorities(env)
    assert {k: ("base" if v in {"low", "medium"} else v) for k, v in before.items()} == down
    assert set(down.values()) == {"base", "high"}
    assert await _snapshot_without_priority(env) == snapshot
    assert await _event_count(env) == events
    await _assert_check_values(env, {"base", "high"})
    await _insert_fails(env, seeded, "low")
    await _insert_fails(env, seeded, "medium")
    await _insert_ok(env, seeded, "base")
    await _insert_ok(env, seeded, "high")

    await alembic_ok(env, "upgrade", "head")

    assert await alembic_versions(env) == [HEAD_REVISION]
    again = await _priorities(env)
    assert set(again.values()) == {"medium", "high"}
    assert {k: v for k, v in again.items() if k in down and down[k] == "high"} == {
        k: "high" for k, v in down.items() if v == "high"
    }
    assert all(v == "medium" for k, v in again.items() if k in down and down[k] == "base")
    await _assert_check_values(env, {"low", "medium", "high"})
    await alembic_ok(env, "check")


# --- AC-54: цикл и прерванный шаг ----------------------------------------------------------


@pytest.mark.committed
async def test_006_ac54_upgrade_downgrade_upgrade_cycle_without_errors(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    await _seed(env, ["low", "medium", "high", "medium"])

    await alembic_ok(env, "downgrade", "0006")
    await alembic_ok(env, "upgrade", "head")
    await alembic_ok(env, "downgrade", "0006")
    await alembic_ok(env, "upgrade", "head")

    assert await alembic_versions(env) == [HEAD_REVISION]
    await alembic_ok(env, "check")


@pytest.mark.committed
async def test_006_ac54_failed_upgrade_leaves_data_check_and_version(
    committed_api_env: ApiEnv,
) -> None:
    """006/AC-54 (NFR-4): сбой при отметке версии - ``base`` остаётся ``base``, CHECK прежний
    (``base``/``high``), версия 0006; после устранения сбоя шаг проходит."""
    env = committed_api_env
    await _to_0006(env)
    await _seed(env, ["base", "high", "base", "high"])
    before = await _priorities(env)
    snapshot = await _snapshot_without_priority(env)
    check_before = await _check_def(env)
    await install_failure(env, on="version")

    result = await try_upgrade(env)

    assert result.returncode != 0
    assert FAILURE_MARK in result.stdout + result.stderr
    assert await alembic_versions(env) == ["0006"]
    assert await _priorities(env) == before
    assert await _snapshot_without_priority(env) == snapshot
    assert await _check_def(env) == check_before

    await remove_failure(env)
    await alembic_ok(env, "upgrade", "head")

    assert await alembic_versions(env) == [HEAD_REVISION]
    assert await _priorities(env) == {
        k: ("medium" if v == "base" else v) for k, v in before.items()
    }


@pytest.mark.committed
async def test_006_ac54_failed_downgrade_leaves_data_check_and_version(
    committed_api_env: ApiEnv,
) -> None:
    """006/AC-54 (NFR-4): сбой при откате - ``low``/``medium`` остаются, CHECK из трёх значений,
    версия прежняя; после устранения сбоя откат проходит."""
    env = committed_api_env
    await _seed(env, ["low", "medium", "high", "medium"])
    before = await _priorities(env)
    snapshot = await _snapshot_without_priority(env)
    check_before = await _check_def(env)
    version_before = await alembic_versions(env)
    assert version_before == [HEAD_REVISION]
    await install_failure(env, on="version")

    result = await asyncio.to_thread(run_alembic, database_url_from_env(), "downgrade", "0006")
    await env.sessionmaker.kw["bind"].dispose()

    assert result.returncode != 0
    assert FAILURE_MARK in result.stdout + result.stderr
    assert await alembic_versions(env) == version_before
    assert await _priorities(env) == before
    assert await _snapshot_without_priority(env) == snapshot
    assert await _check_def(env) == check_before

    await remove_failure(env)
    await alembic_ok(env, "downgrade", "0006")

    assert await alembic_versions(env) == ["0006"]
    assert set((await _priorities(env)).values()) == {"base", "high"}
