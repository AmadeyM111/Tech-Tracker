"""C25-T03: ``GET /me/overview/tasks.csv`` (spec 025, ADR-0023). AC-1…AC-3, AC-7…AC-10, AC-12.

Часы — FixedClock приложения (2026-10-13T09:00Z). Разбор файла — стандартным ``csv``.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update

from app.domain.events.models import DomainEvent
from app.domain.projects.models import Project
from app.domain.tasks.models import Task
from tests.api.test_008_overview import TASKS, _get, _task, _world
from tests.conftest import ApiEnv
from tests.factories import WorkspaceRow

CSV = "/api/v1/me/overview/tasks.csv"
AUDIT = "/api/v1/admin/audit"
TODAY = date(2026, 10, 13)


def _rows(response: Any) -> list[list[str]]:
    assert response.status_code == 200, response.text
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))


async def _events(env: ApiEnv) -> list[Any]:
    async with env.sessionmaker() as s:
        return list(
            (
                await s.execute(
                    select(DomainEvent).where(DomainEvent.action == "user.overview_exported")
                )
            ).scalars()
        )


async def test_025_ac1_ac2_all_pages_in_list_order_and_filters(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    for i in range(120):
        await _task(
            w,
            w.mine,
            title=f"Задача {i:03d}",
            priority="high" if i % 3 == 0 else "low",
            status="review" if i % 2 == 0 else "todo",
            due_date=TODAY + timedelta(days=i % 7) if i % 5 else None,
        )
    listed: list[str] = []
    for page in (1, 2, 3):
        body = (await _get(w, TASKS, page=page, page_size=50)).json()
        listed += [item["title"] for item in body["items"]]
    assert len(listed) == 120
    rows = _rows(await _get(w, CSV))
    assert [r[1] for r in rows[1:]] == listed  # порядок списка, все страницы
    assert len(rows) == 121

    high_review = _rows(await _get(w, CSV, priority="high", status="review"))
    assert len(high_review) - 1 == len([i for i in range(120) if i % 3 == 0 and i % 2 == 0])
    assert {r[3] for r in high_review[1:]} == {"Высокий"}
    assert {r[2] for r in high_review[1:]} == {"На проверке"}


async def test_025_ac3_only_business_admin_and_capability_in_me(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    user = await api_env.new_user(role="user")
    ta = await api_env.new_user(role="tech_admin")
    for who in (user, ta):
        token = await api_env.login_ok(who)
        r = await api_env.client.get(CSV, headers=api_env.auth(token))
        assert r.status_code == 403, who.id
        assert r.json()["code"] == "forbidden"
        me = (await api_env.client.get("/api/v1/me", headers=api_env.auth(token))).json()
        assert "export_overview" not in me["capabilities"]
    assert (await api_env.client.get(CSV)).status_code == 401
    me = (await _get(w, "/api/v1/me")).json()
    assert "export_overview" in me["capabilities"]
    assert (await _get(w, CSV)).status_code == 200


async def test_025_ac4_ac5_roundtrip_dates_and_assignee(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    title = 'Цена "А"; итого\nстрока'
    task = await _task(
        w,
        w.mine,
        title=title,
        due_date=date(2026, 11, 9),
        assignee_id=w.me.id,
        status="in_progress",
    )
    moment = datetime(2026, 11, 9, 21, 30, tzinfo=timezone.utc)  # noqa: UP017
    await api_env.execute(update(Task).where(Task.id == task.id).values(updated_at=moment))
    response = await _get(w, CSV)
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = _rows(response)
    assert rows[0][:3] == ["Проект", "Задача", "Статус"]
    row = rows[1]
    assert row[:3] == ["Мой", title, "В работе"]
    assert row[4] == w.me.login and row[5] == "09.11.2026"
    assert row[7] == "10.11.2026 00:30"


async def test_025_ac6_formula_titles_are_escaped(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    for t in ("=1+1", "+1", "-1", "@SUM(A1)", "обычный"):
        await _task(w, w.mine, title=t)
    titles = sorted(r[1] for r in _rows(await _get(w, CSV))[1:])
    assert titles == sorted(["'=1+1", "'+1", "'-1", "'@SUM(A1)", "обычный"])


async def test_025_ac7_only_visible_tasks(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    mine = await _task(w, w.mine, title="моя")
    await _task(w, w.shared, title="общая")
    await _task(w, w.foreign, title="чужая")
    gone = await _task(w, w.mine, title="удалённая")
    await api_env.execute(
        update(Task).where(Task.id == gone.id).values(deleted_at=api_env.clock.now())
    )
    dead = await _task(w, w.shared, title="в удалённом проекте")
    await api_env.execute(
        update(Project).where(Project.id == w.shared.id).values(deleted_at=api_env.clock.now())
    )
    assert dead and mine
    assert [r[1] for r in _rows(await _get(w, CSV))[1:]] == ["моя"]
    missing = await _get(w, CSV, project_id=str(w.foreign.id))
    assert missing.status_code == 404


async def test_025_ac8_limit_refuses_without_truncation_and_without_event(
    api_env: ApiEnv,
) -> None:
    w = await _world(api_env)
    for i in range(6):
        await _task(w, w.mine, title=f"З{i}")
    api_env.app.state.settings.csv_max_rows = 5
    refused = await _get(w, CSV)
    assert refused.status_code == 422
    assert refused.json()["code"] == "export_too_large"
    assert "6" in refused.json()["detail"] and "5" in refused.json()["detail"]
    assert await _events(api_env) == []
    api_env.app.state.settings.csv_max_rows = 6
    assert len(_rows(await _get(w, CSV))) - 1 == 6  # ровно предел — выгрузка есть
    assert len(await _events(api_env)) == 1


async def test_025_ac9_headers_and_filename_in_moscow_time(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    response = await _get(w, CSV)
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    # FixedClock 2026-10-13T09:00Z -> 12:00 МСК
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="gtrack-summary-20261013-1200.csv"'
    )


async def test_025_ac10_audit_has_author_and_row_count_only(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    for i in range(3):
        await _task(w, w.mine, title=f"секрет {i}", priority="high")
    assert len(_rows(await _get(w, CSV, priority="high", status="todo"))) == 4
    (event,) = await _events(api_env)
    assert event.actor_id == w.me.id and event.entity_id == w.me.id
    assert event.details == {"rows": "3"}
    assert "секрет" not in str(event.details) and "high" not in str(event.details)
    assert event.in_audit is True
    ws = WorkspaceRow(id=w.me.workspace_id, created_at=api_env.clock.now())
    ta = await api_env.new_user(role="tech_admin", workspace=ws)  # ТА того же пространства
    token = await api_env.login_ok(ta)
    listed = (await api_env.client.get(AUDIT, headers=api_env.auth(token))).json()["items"]
    entry = next(e for e in listed if e["action"] == "user.overview_exported")
    assert entry["actor"]["login"] == w.me.login
    assert entry["details"] == {"rows": "3"}
    # отказы событий не пишут
    user = await api_env.new_user(role="user", workspace=ws)
    utoken = await api_env.login_ok(user)
    await api_env.client.get(CSV, headers=api_env.auth(utoken))
    assert len(await _events(api_env)) == 1


async def test_025_ac12_empty_selection_gives_header_only(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    rows = _rows(await _get(w, CSV))
    assert len(rows) == 1 and rows[0][0] == "Проект"
    repeated = await api_env.client.get(
        CSV + "?status=todo&status=done", headers=api_env.auth(w.token)
    )
    assert repeated.status_code == 422


async def test_025_024_range_params_apply_to_csv_like_to_the_list(api_env: ApiEnv) -> None:
    """Спека 024 + 025: ``due_from``/``due_to`` отбирают строки выгрузки так же, как список."""
    w = await _world(api_env)
    days = {"вчера": -1, "сегодня": 0, "через 3": 3, "через 10": 10}
    for title, delta in days.items():
        await _task(w, w.mine, title=title, due_date=TODAY + timedelta(days=delta))
    await _task(w, w.mine, title="без срока")
    await _task(w, w.mine, title="готово", status="done", due_date=TODAY + timedelta(days=1))

    def titles(rows: list[list[str]]) -> set[str]:
        return {r[1] for r in rows[1:]}

    both = _rows(
        await _get(
            w, CSV, due_from=TODAY.isoformat(), due_to=(TODAY + timedelta(days=3)).isoformat()
        )
    )
    assert titles(both) == {"сегодня", "через 3", "готово"}  # границы включены, done не исключён
    listed = (
        await _get(
            w, TASKS, due_from=TODAY.isoformat(), due_to=(TODAY + timedelta(days=3)).isoformat()
        )
    ).json()
    assert titles(both) == {i["title"] for i in listed["items"]}
    only_from = _rows(await _get(w, CSV, due_from=(TODAY + timedelta(days=3)).isoformat()))
    assert titles(only_from) == {"через 3", "через 10"}  # без срока не попадает
    only_to = _rows(await _get(w, CSV, due_to=TODAY.isoformat()))
    assert titles(only_to) == {"вчера", "сегодня"}


async def test_025_024_range_validation_errors_are_422_and_write_no_event(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    cases = [
        {"due": "today", "due_from": TODAY.isoformat()},  # пресет вместе с диапазоном
        {"due_from": "2026-10-20", "due_to": "2026-10-13"},  # «с» позже «по»
        {"due_from": "13.10.2026"},  # неверный формат
    ]
    for params in cases:
        r = await _get(w, CSV, **params)
        assert r.status_code == 422, params
        assert r.json()["code"] == "validation_error"
    repeated = await api_env.client.get(
        CSV + "?due_from=2026-10-01&due_from=2026-10-02", headers=api_env.auth(w.token)
    )
    assert repeated.status_code == 422
    assert await _events(api_env) == []


async def test_025_link_column_with_and_without_public_base_url(api_env: ApiEnv) -> None:
    w = await _world(api_env)
    task = await _task(w, w.mine, title="со ссылкой")
    settings = api_env.app.state.settings
    settings.public_base_url = None
    assert _rows(await _get(w, CSV))[1][8] == f"/tasks/{task.id}"
    settings.public_base_url = "https://gt.example/"
    assert _rows(await _get(w, CSV))[1][8] == f"https://gt.example/tasks/{task.id}"
