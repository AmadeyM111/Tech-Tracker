"""Спека 031: метрики пилота — только чтение (``collect``, ``render_markdown``, ``pilot-report``).

Данные синтетические. Транзакция метрик — ``READ ONLY``: запись в ней невозможна.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.cli.commands.pilot_report import _bounds, add_parser
from app.domain.ops.pilot_metrics import collect, render_markdown
from tests.factories import (
    make_comment,
    make_domain_event,
    make_project,
    make_project_member,
    make_task,
    make_user,
    make_workspace,
)

pytestmark = pytest.mark.committed

SINCE = datetime(2026, 11, 9, tzinfo=UTC)
UNTIL = datetime(2026, 11, 23, tzinfo=UTC)
D = timedelta


async def _world(sm: Any) -> None:
    async with sm() as s:
        ws = await make_workspace(s)
        owner = await make_user(s, role="business_admin", workspace=ws)
        anna = await make_user(s, role="user", workspace=ws)
        boris = await make_user(s, role="user", workspace=ws)
        await make_user(s, role=None, workspace=ws)  # без роли
        await make_user(s, role="user", workspace=ws, blocked=True)
        project = await make_project(s, workspace_id=ws.id, owner_id=owner.id)
        for m in (anna, boris):
            await make_project_member(s, project_id=project.id, user_id=m.id, workspace_id=ws.id)

        async def task(created: datetime, **kw: Any) -> Any:
            return await make_task(
                s,
                project_id=project.id,
                workspace_id=ws.id,
                created_by=owner.id,
                created_at=created,
                updated_at=created,
                **kw,
            )

        t1 = await task(SINCE + D(days=1))  # реакция комментарием через 2 часа
        t2 = await task(SINCE + D(days=2))  # реакция сменой статуса через 30 минут
        await task(SINCE + D(days=3))  # без реакции
        await task(SINCE - D(days=5))  # вне периода
        await make_comment(
            s,
            task_id=t1.id,
            workspace_id=ws.id,
            created_by=anna.id,
            created_at=SINCE + D(days=1, hours=2),
        )
        await make_comment(  # свой комментарий автора реакцией не считается
            s,
            task_id=t2.id,
            workspace_id=ws.id,
            created_by=owner.id,
            created_at=SINCE + D(days=2, minutes=1),
        )
        await make_domain_event(
            s,
            workspace_id=ws.id,
            actor_id=boris.id,
            entity_type="task",
            entity_id=t2.id,
            action="task.updated",
            changes=[{"field": "status", "old": "todo", "new": "done"}],
            project_id=project.id,
            occurred_at=SINCE + D(days=2, minutes=30),
        )
        await s.execute(  # действие агента (журнал append-only, сразу с client_name)
            text(
                "INSERT INTO domain_event (workspace_id, occurred_at, actor_id, entity_type, "
                "entity_id, action, changed_fields, in_audit, client_name) VALUES "
                "(:w, :t, :a, 'task', :e, 'task.created', '{}', false, 'Claude Code')"
            ).bindparams(w=ws.id, t=SINCE + D(days=4), a=anna.id, e=t1.id)
        )
        await s.commit()


async def test_031_collect_counts_and_reaction_time(committed: Any) -> None:
    await _world(committed)
    async with committed() as s:
        m = await collect(s, since=SINCE, until=UNTIL)
    d = m.data
    assert (
        d["users"]["total"] == 3 and d["users"]["without_role"] == 1 and d["users"]["blocked"] == 1
    )
    assert d["tasks"]["created"] == 3 and d["closed"]["closed"] == 1
    assert d["comments"]["created"] == 2
    assert d["reaction"]["tasks"] == 3 and d["reaction"]["reacted"] == 2
    assert round(d["reaction"]["median_hours"], 2) == 1.25  # между 0,5 и 2 часами
    assert d["agent_actions"] == {"actions": 1, "users": 1}
    assert m.clients == [("Claude Code", 1)]


async def test_031_metrics_transaction_is_read_only(committed: Any) -> None:
    await _world(committed)
    async with committed() as s:
        await collect(s, since=SINCE, until=UNTIL)
        with pytest.raises(DBAPIError):
            await s.execute(text("UPDATE task SET title = 'x'"))
        await s.rollback()
    async with committed() as s:
        titles = (await s.execute(text("SELECT count(*) FROM task WHERE title = 'x'"))).scalar_one()
    assert titles == 0


async def test_031_render_markdown_has_all_sections_without_personal_data(committed: Any) -> None:
    await _world(committed)
    async with committed() as s:
        m = await collect(s, since=SINCE, until=UNTIL)
    report = render_markdown(m, generated_at=UNTIL)
    for heading in (
        "# Метрики пилота GTrack",
        "## Пользователи",
        "## Работа с задачами",
        "## Время до первой реакции на новую задачу",
        "## ИИ-агенты (MCP)",
        "## Вложения, упоминания, уведомления",
        "## Выводы (заполняет человек)",
    ):
        assert heading in report, heading
    assert "| Задач создано за период | 3 |" in report
    assert "| Claude Code | 1 |" in report
    assert "Медиана | 1.3 ч" in report or "Медиана | 1.2 ч" in report
    assert "@" not in report.replace("`@логин`", "")  # ни почт, ни логинов


async def test_031_empty_database_gives_zeros_not_errors(committed: Any) -> None:
    async with committed() as s:
        m = await collect(s, since=SINCE, until=UNTIL)
    report = render_markdown(m, generated_at=UNTIL)
    assert "| Задач создано за период | 0 |" in report and "нет данных" in report


def test_031_cli_bounds_are_moscow_dates_and_validated() -> None:
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers())
    args = parser.parse_args(["pilot-report", "--from", "2026-11-09", "--to", "2026-11-23"])
    start, end = _bounds(args, UNTIL)
    assert start.isoformat() == "2026-11-09T00:00:00+03:00"
    assert end.isoformat() == "2026-11-23T00:00:00+03:00"
    bad = parser.parse_args(["pilot-report", "--from", "2026-11-23", "--to", "2026-11-09"])
    with pytest.raises(ValueError):
        _bounds(bad, UNTIL)
    default = _bounds(parser.parse_args(["pilot-report"]), UNTIL)
    assert default[1] - default[0] == timedelta(days=14)
