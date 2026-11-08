"""N12-T04: ``gtrack notify-due`` и очистка уведомлений (spec 012 FR-4, FR-9; AC-5)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from app.domain.notifications.due import notify_due, purge_notifications
from app.domain.notifications.models import Notification
from app.domain.users.models import AppUser
from tests.factories import make_project, make_project_member, make_task, make_user, make_workspace

pytestmark = pytest.mark.committed

# 2026-11-09 23:59:59 МСК и 2026-11-10 00:00:00 МСК
BEFORE_MIDNIGHT = datetime(2026, 11, 9, 20, 59, 59, tzinfo=UTC)
AFTER_MIDNIGHT = datetime(2026, 11, 9, 21, 0, 0, tzinfo=UTC)


async def _world(sm: Any) -> dict[str, Any]:
    async with sm() as s:
        ws = await make_workspace(s)
        owner = await make_user(s, role="business_admin", workspace=ws)
        u = await make_user(s, role="user", workspace=ws)
        blocked = await make_user(s, role="user", workspace=ws)
        project = await make_project(s, workspace_id=ws.id, owner_id=owner.id)
        for m in (u, blocked):
            await make_project_member(s, project_id=project.id, user_id=m.id, workspace_id=ws.id)

        async def task(due: date | None, *, assignee: Any = u, status: str = "todo") -> Any:
            return await make_task(
                s,
                project_id=project.id,
                workspace_id=ws.id,
                created_by=owner.id,
                assignee_id=None if assignee is None else assignee.id,
                due_date=due,
                status=status,
            )

        t = {
            "tomorrow": await task(date(2026, 11, 10)),
            "today": await task(date(2026, 11, 9)),
            "yesterday": await task(date(2026, 11, 8)),
            "done_overdue": await task(date(2026, 11, 1), status="done"),
            "no_assignee": await task(date(2026, 11, 1), assignee=None),
            "blocked": await task(date(2026, 11, 1), assignee=blocked),
            "subtask_parent": await task(None),
        }
        t["subtask"] = await make_task(
            s,
            project_id=project.id,
            workspace_id=ws.id,
            created_by=owner.id,
            parent_id=t["subtask_parent"].id,
            assignee_id=u.id,
            due_date=date(2026, 11, 7),
        )
        await s.commit()
    async with sm() as s:
        await s.execute(update(AppUser).where(AppUser.id == blocked.id).values(is_blocked=True))
        await s.commit()
    return {"tasks": t, "u": u}


async def _kinds(sm: Any) -> list[tuple[str, Any]]:
    async with sm() as s:
        rows = (await s.execute(select(Notification.kind, Notification.task_id))).all()
    return sorted((r.kind, r.task_id) for r in rows)


async def test_012_ac5_due_reminders_once_and_moscow_midnight(committed: Any) -> None:
    w = await _world(committed)
    t = w["tasks"]
    report = await notify_due(committed, now=BEFORE_MIDNIGHT)  # сегодня 09.11
    assert (report.due_tomorrow, report.overdue) == (1, 2)
    expected = sorted(
        [
            ("due_tomorrow", t["tomorrow"].id),
            ("overdue", t["yesterday"].id),
            ("overdue", t["subtask"].id),
        ]
    )
    assert await _kinds(committed) == expected
    again = await notify_due(committed, now=BEFORE_MIDNIGHT)
    assert (again.due_tomorrow, again.overdue) == (0, 0), "повторный запуск не дублирует"

    after = await notify_due(committed, now=AFTER_MIDNIGHT)  # сегодня 10.11
    # «срок прошёл» для 09.11 — впервые; «завтра» для 10.11 уже было, новых «завтра» нет
    assert (after.due_tomorrow, after.overdue) == (0, 1)
    assert ("overdue", t["today"].id) in await _kinds(committed)


async def test_012_fr9_purge_older_than_90_days(committed: Any) -> None:
    await _world(committed)
    await notify_due(committed, now=BEFORE_MIDNIGHT)
    async with committed() as s:
        first = (await s.execute(select(Notification.id).limit(1))).scalar_one()
        await s.execute(
            update(Notification)
            .where(Notification.id == first)
            .values(created_at=BEFORE_MIDNIGHT - timedelta(days=91))
        )
        await s.commit()
    assert await purge_notifications(committed, now=BEFORE_MIDNIGHT, dry_run=True) == 1
    assert await purge_notifications(committed, now=BEFORE_MIDNIGHT, dry_run=False) == 1
    assert len(await _kinds(committed)) == 2
