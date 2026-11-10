"""Замер запросов «Сводки» и счётчика уведомлений на 50 000 задач (R2, ревью 008/012).

Запуск (ТОЛЬКО локальная БД ``*_test``; миграции применены, ``alembic upgrade head``):

    cd backend && DATABASE_URL=postgresql+asyncpg://user:pw@localhost:5432/perf_test \
        python ../scripts/explain_r2_queries.py [--keep]

Скрипт засевает синтетические данные (1 пространство, 21 пользователь, 50 проектов, 50 000
задач, 50 000 уведомлений), собирает SQL настоящих доменных функций через событие SQLAlchemy и
печатает ``EXPLAIN (ANALYZE, BUFFERS)`` для каждого запроса, а также время вызова функции.
Данные вымышлены. Повторный запуск не пересоздаёт данные, если задач уже >= 50 000.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
import uuid
from datetime import UTC, date, datetime, timedelta

from app.core.pagination import PageParams
from app.domain.access.roles import Actor, Role
from app.domain.notifications import queries as nq
from app.domain.overview.due import DuePreset
from app.domain.overview.queries import OverviewFilter, overview_counts, overview_tasks
from app.domain.tasks.models import TaskPriority, TaskStatus
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TASKS = 50_000
PROJECTS = 50


async def seed(session: AsyncSession) -> dict[str, uuid.UUID]:
    n = (await session.execute(text("SELECT count(*) FROM task"))).scalar_one()
    if n >= TASKS:
        row = (
            await session.execute(
                text("SELECT id FROM workspace ORDER BY created_at LIMIT 1")
            )
        ).scalar_one()
        users = {
            r[0]: r[1]
            for r in await session.execute(
                text(
                    "SELECT login, id FROM app_user WHERE login IN ('perf.all','perf.some')"
                )
            )
        }
        return {"ws": row, "all": users["perf.all"], "some": users["perf.some"]}
    ws = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO workspace(id, created_at, updated_at) VALUES (:i, now(), now())"
        ),
        {"i": ws},
    )
    await session.execute(
        text(
            "INSERT INTO app_user(id, login, login_display, password_hash, must_change_password,"
            " is_blocked, failed_login_count, password_changed_at, created_at, updated_at)"
            " SELECT gen_random_uuid(), 'perf.u' || g, 'perf.u' || g, 'x', false, false, 0,"
            " now(), now(), now() FROM generate_series(1, 19) g"
        )
    )
    for login in ("perf.all", "perf.some"):
        await session.execute(
            text(
                "INSERT INTO app_user(id, login, login_display, password_hash,"
                " must_change_password, is_blocked, failed_login_count, password_changed_at,"
                " created_at, updated_at) VALUES (gen_random_uuid(), :l, :l, 'x', false, false, 0,"
                " now(), now(), now())"
            ),
            {"l": login},
        )
    await session.execute(
        text(
            "INSERT INTO workspace_member(workspace_id, user_id, role, created_at, updated_at)"
            " SELECT :w, id, 'business_admin', now(), now() FROM app_user WHERE login LIKE 'perf.%'"
        ),
        {"w": ws},
    )
    await session.execute(
        text(
            "INSERT INTO project(id, workspace_id, name, description, owner_id, created_at,"
            " updated_at) SELECT gen_random_uuid(), :w, 'Проект ' || lpad(g::text, 3, '0'), '',"
            " (SELECT id FROM app_user WHERE login = 'perf.u' || (1 + g % 19)), now(), now()"
            " FROM generate_series(1, :p) g"
        ),
        {"w": ws, "p": PROJECTS},
    )
    # perf.all — участник всех проектов (худший случай: видны все 50 000 задач);
    # perf.some — участник 10 проектов.
    await session.execute(
        text(
            "INSERT INTO project_member(project_id, user_id, workspace_id, created_at, updated_at)"
            " SELECT p.id, u.id, :w, now(), now() FROM project p, app_user u"
            " WHERE u.login = 'perf.all'"
        ),
        {"w": ws},
    )
    await session.execute(
        text(
            "INSERT INTO project_member(project_id, user_id, workspace_id, created_at, updated_at)"
            " SELECT p.id, u.id, :w, now(), now() FROM"
            " (SELECT id FROM project ORDER BY name LIMIT 10) p, app_user u"
            " WHERE u.login = 'perf.some'"
        ),
        {"w": ws},
    )
    top = int(TASKS * 0.9)
    await session.execute(
        text(
            "INSERT INTO task(id, workspace_id, project_id, parent_id, title, description, status,"
            " priority, due_date, assignee_id, position, created_by, created_at, updated_at)"
            " SELECT gen_random_uuid(), :w, p.id, NULL, 'Задача ' || g, '',"
            " (ARRAY['todo','in_progress','review','done'])[1 + floor(random()*4)::int],"
            " (ARRAY['low','medium','high'])[1 + floor(random()*3)::int],"
            " CASE WHEN random() < 0.2 THEN NULL"
            " ELSE current_date + (floor(random()*90) - 45)::int END,"
            " u.id, g, u.id, now() - (g || ' seconds')::interval, now()"
            " FROM generate_series(1, :n) g"
            " JOIN LATERAL (SELECT id FROM project ORDER BY id OFFSET (g % :p) LIMIT 1) p ON true"
            " JOIN LATERAL (SELECT id FROM app_user WHERE login LIKE 'perf.u%' OFFSET (g % 19)"
            " LIMIT 1) u ON true"
        ),
        {"w": ws, "n": top, "p": PROJECTS},
    )
    await session.execute(
        text(
            "INSERT INTO task(id, workspace_id, project_id, parent_id, title, description, status,"
            " priority, due_date, assignee_id, position, created_by, created_at, updated_at)"
            " SELECT gen_random_uuid(), :w, t.project_id, t.id, 'Подзадача ' || t.title, '',"
            " 'todo', 'medium', CASE WHEN random() < 0.2 THEN NULL ELSE current_date"
            " + (floor(random()*90) - 45)::int END, t.assignee_id, NULL, t.created_by, now(), now()"
            " FROM (SELECT * FROM task WHERE parent_id IS NULL ORDER BY id LIMIT :n) t"
        ),
        {"w": ws, "n": TASKS - top},
    )
    # Уведомления: 20 000 — у perf.all (60 % прочитано, за последние 200 дней), остальные — у других.
    await session.execute(
        text(
            "INSERT INTO notification(id, workspace_id, recipient_id, kind, task_id, project_id,"
            " dedup_key, created_at, read_at)"
            " SELECT gen_random_uuid(), :w,"
            " CASE WHEN g <= 20000 THEN (SELECT id FROM app_user WHERE login = 'perf.all')"
            " ELSE (SELECT id FROM app_user WHERE login = 'perf.u' || (1 + g % 19)) END,"
            " (ARRAY['assigned','review_requested','review_returned','mentioned','commented',"
            "'due_tomorrow','overdue'])[1 + g % 7], t.id, t.project_id, g::text,"
            " now() - (floor(random()*200) || ' days')::interval,"
            " CASE WHEN random() < 0.6 THEN now() ELSE NULL END"
            " FROM generate_series(1, 50000) g"
            " JOIN LATERAL (SELECT id, project_id FROM task OFFSET (g * 7) % 50000 LIMIT 1) t"
            " ON true"
        ),
        {"w": ws},
    )
    await session.commit()
    await session.execute(text("ANALYZE"))
    ids = {
        r[0]: r[1]
        for r in await session.execute(
            text(
                "SELECT login, id FROM app_user WHERE login IN ('perf.all','perf.some')"
            )
        )
    }
    return {"ws": ws, "all": ids["perf.all"], "some": ids["perf.some"]}


def actor(ws: uuid.UUID, user: uuid.UUID, login: str) -> Actor:
    return Actor(
        user_id=user,
        workspace_id=ws,
        login=login,
        role=Role.BUSINESS_ADMIN,
        must_change_password=False,
        session_id=b"perf",
    )


async def explain(session: AsyncSession, title: str, run) -> None:  # type: ignore[no-untyped-def]
    captured: list[tuple[str, tuple[object, ...]]] = []

    def grab(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        if statement.lstrip().upper().startswith("SELECT"):
            captured.append((statement, tuple(parameters)))

    engine = session.bind.sync_engine  # type: ignore[union-attr]
    event.listen(engine, "before_cursor_execute", grab)
    try:
        times = []
        for _ in range(7):
            captured.clear()
            t0 = time.perf_counter()
            await run(session)
            times.append((time.perf_counter() - t0) * 1000)
    finally:
        event.remove(engine, "before_cursor_execute", grab)
    print(f"\n### {title}")
    print(
        f"время вызова функции, мс: min {min(times):.1f} / median "
        f"{statistics.median(times):.1f} / max {max(times):.1f} (7 запусков, прогретый кэш)"
    )
    raw = await session.connection()
    for statement, params in captured:
        if "FROM task" not in statement and "FROM notification" not in statement:
            continue
        rows = await raw.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS) " + statement, params
        )
        print("\n```")
        print(statement.strip().split("\n")[0][:110] + " ...")
        for (line,) in rows:
            print(line)
        print("```")


async def main() -> int:
    url = os.environ["DATABASE_URL"]
    if not make_url(url).database or not str(make_url(url).database).endswith("_test"):
        print("DATABASE_URL должен указывать на БД *_test", file=sys.stderr)
        return 2
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        ids = await seed(session)
        counts = {
            t: (await session.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
            for t in ("task", "project", "notification", "app_user")
        }
        print(f"Данные: {counts}; PostgreSQL: ", end="")
        print((await session.execute(text("SHOW server_version"))).scalar_one())
        now = datetime.now(UTC)
        today = date.today()
        for label, key in (
            ("perf.all (член 50 проектов, видны 50 000 задач)", "all"),
            ("perf.some (член 10 проектов)", "some"),
        ):
            a = actor(ids["ws"], ids[key], f"perf.{key}")
            print(f"\n## Актор {label}")
            await explain(
                session, "Плитки: overview_counts", lambda s, a=a: overview_counts(s, a)
            )
            page = PageParams(page=1, page_size=50)
            cases = {
                "список без фильтров": OverviewFilter(),
                "статус in_progress": OverviewFilter(status=TaskStatus.IN_PROGRESS),
                "приоритет high+medium + срок «Просрочено»": OverviewFilter(
                    priorities=frozenset({TaskPriority.HIGH, TaskPriority.MEDIUM}),
                    due=DuePreset.OVERDUE,
                ),
                "срок «Без срока»": OverviewFilter(due=DuePreset.NONE),
                "диапазон срока «с / по» (неделя, 024)": OverviewFilter(
                    due_from=today, due_to=today + timedelta(days=6)
                ),
                "«Нужно проверить»": OverviewFilter(needs_review=True),
            }
            for name, flt in cases.items():
                await explain(
                    session,
                    f"Сводка, {name}",
                    lambda s, a=a, f=flt, pg=page: overview_tasks(
                        s, a, f, pg, today=today
                    ),
                )
            await explain(
                session,
                "Сводка, последняя страница без фильтров (OFFSET)",
                lambda s, a=a: overview_tasks(
                    s,
                    a,
                    OverviewFilter(),
                    PageParams(page=800, page_size=50),
                    today=today,
                ),
            )
            await explain(
                session,
                "Уведомления: unread_count",
                lambda s, a=a: nq.unread_count(s, a, now=now),
            )
            await explain(
                session,
                "Уведомления: list (стр. 1, 20)",
                lambda s, a=a: nq.list_notifications(
                    s, a, PageParams(page=1, page_size=20), now=now
                ),
            )
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
