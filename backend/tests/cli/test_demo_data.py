"""T87: ``gostracker demo-data`` и ``load_demo_data`` (plan §11.8, D-63, D-6, §4.13).

Покрытие: AC-41 и AC-104 (инфраструктурная часть), FR-49 (в редакции SC-13), FR-64, FR-57, BR-9,
FR-41 (создание учётных записей и назначение ролей, автор «система»), D-55 (событий проектов и
задач нет).

Ожидаемые интерфейсы (plan §11.8, tasks T87):

* ``app.domain.ops.demo.load_demo_data(sessionmaker, settings, *, clock, seed) -> DemoReport``;
  ``DemoReport`` — frozen dataclass с полями ``users``, ``projects``, ``tasks``, ``subtasks``,
  ``comments`` (int) и ``passwords_file`` (Path); при отказе — ``DemoDataRefused``.
* ``app.cli.main.main(["demo-data", "[--seed N]"])``: 0 — успех; 2 — отказ (в базе уже есть
  проекты/задачи или пользователи сверх первого ТА); 1 — ошибка БД/конфигурации.
* stdout: строки ``ключ=значение``; ``passwords_file=<путь>`` и целые счётчики; паролей нет.
* ``secrets/demo-passwords.txt``: 12 строк ``login=<логин>\\tpassword=<пароль>`` (TAB, plan §11.8).

Время сидов CLI-тестов — реальные часы (команда берёт «сейчас» сама, как ``maintenance``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import stat
import threading
import time
from collections import Counter
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

import app.cli.main  # noqa: F401  (импорт до захвата вывода: alembic пишет INFO-логи)
from app.core.clock import FixedClock, today_msk, utcnow
from app.core.config import Settings, get_settings
from tests.conftest import FIXED_NOW
from tests.db_support import ALEMBIC_INI
from tests.factories import make_project, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.conftest import ApiEnv

DEMO_FILE = "demo-passwords.txt"
FIRST_ADMIN_PASSWORD = "Zq7Lm2Vx9FirstAdminPw"
EXPECTED_LOGINS = {
    "demo.ta",
    "demo.ba4",  # 002/AC-28: вместо demo.mixed
    "demo.ba1",
    "demo.ba2",
    "demo.ba3",
    *(f"demo.user{i}" for i in range(1, 8)),
}
EXPECTED_ROLES = {
    "demo.ta": "tech_admin",
    "demo.ba4": "business_admin",
    "demo.ba1": "business_admin",
    "demo.ba2": "business_admin",
    "demo.ba3": "business_admin",
    **{f"demo.user{i}": "user" for i in range(1, 8)},
}
STEP = 1024


# --- помощники ---------------------------------------------------------------------------


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_database_url: str
) -> Iterator[Path]:
    data_dir = tmp_path / "data"
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_MEMORY_COST_KIB", "1024")
    monkeypatch.setenv("ARGON2_PARALLELISM", "1")
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ALEMBIC_INI))
    get_settings.cache_clear()
    yield data_dir
    get_settings.cache_clear()


def _run(argv: list[str]) -> int:
    from app.cli.main import main

    try:
        return int(main(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)


async def _bootstrap(sm: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    from app.domain.system.bootstrap import run_bootstrap

    await run_bootstrap(
        sm, settings, clock=FixedClock(FIXED_NOW), generate=lambda: FIRST_ADMIN_PASSWORD
    )


async def _demo(sm: async_sessionmaker[AsyncSession], settings: Settings, seed: int = 1) -> Any:
    from app.domain.ops.demo import load_demo_data

    return await load_demo_data(sm, settings, clock=FixedClock(FIXED_NOW), seed=seed)


async def _rows(sm: async_sessionmaker[AsyncSession], sql: str) -> list[dict[str, Any]]:
    async with sm() as session:
        result = await session.execute(text(sql))
        return [dict(r._mapping) for r in result]


async def _count(sm: async_sessionmaker[AsyncSession], table: str) -> int:
    rows = await _rows(sm, f"SELECT count(*) AS n FROM {table}")
    return int(rows[0]["n"])


def _passwords_path(settings: Settings) -> Path:
    return settings.secrets_dir / DEMO_FILE


def _parse_passwords(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    result: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"login=([^\t]+)\tpassword=(\S+)", line)
        assert match, "строка файла не в формате login=…<TAB>password=…"
        result[match.group(1)] = match.group(2)
    assert len(result) == len(lines), "логины в файле повторяются"
    return result


async def _snapshot(sm: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    return {
        t: await _count(sm, t)
        for t in (
            "app_user",
            "workspace_member",
            "project",
            "project_member",
            "task",
            "comment",
            "domain_event",
        )
    }


@contextlib.contextmanager
def _commit_hook(name: str) -> Iterator[list[int]]:
    """Один раз бросает исключение в событии сессии (``before_commit``)."""
    fired: list[int] = []

    def boom(session: Session) -> None:
        if not fired:
            fired.append(1)
            raise ConnectionError("simulated commit failure")

    event.listen(Session, name, boom)
    try:
        yield fired
    finally:
        event.remove(Session, name, boom)


@pytest.fixture
async def loaded(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> tuple[async_sessionmaker[AsyncSession], Settings, Any]:
    await _bootstrap(committed, settings)
    report = await _demo(committed, settings)
    return committed, settings, report


# --- состав данных (FR-49 / SC-13, FR-64) ----------------------------------------------------


@pytest.mark.committed
async def test_fr49_thirteen_accounts_with_roles(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """FR-49 (SC-13), обращён по 002/AC-28: первый ТА + 12 демо: 1 ТА, 4 БА, 7 П; без СМ."""
    sm, _, _ = loaded
    rows = await _rows(
        sm,
        "SELECT u.login, m.role FROM app_user u JOIN workspace_member m ON m.user_id = u.id",
    )
    assert len(rows) == 13
    roles = {r["login"]: r["role"] for r in rows if r["login"] in EXPECTED_LOGINS}
    assert roles == EXPECTED_ROLES
    assert Counter(r["role"] for r in rows) == {
        "tech_admin": 2,
        "business_admin": 4,
        "user": 7,
    }


@pytest.mark.committed
async def test_002_ac28_thirteen_accounts_without_mixed(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """002/AC-28 (FR-22): 13 записей: первый ТА, demo.ta, demo.ba1..4, demo.user1..7; без mixed."""
    sm, _, _ = loaded
    rows = await _rows(
        sm,
        "SELECT u.login, m.role FROM app_user u JOIN workspace_member m ON m.user_id = u.id",
    )
    first_admin = "admin"
    expected = {
        first_admin,
        "demo.ta",
        *(f"demo.ba{i}" for i in range(1, 5)),
        *(f"demo.user{i}" for i in range(1, 8)),
    }
    assert len(rows) == 13
    assert {r["login"] for r in rows} == expected
    assert "demo.mixed" not in {r["login"] for r in rows}
    assert all(r["role"] != "mixed" for r in rows)
    assert Counter(r["role"] for r in rows) == {
        "tech_admin": 2,
        "business_admin": 4,
        "user": 7,
    }


@pytest.mark.committed
async def test_002_ac28_no_mixed_in_role_assigned_events(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """002/AC-28: в событиях user.role_assigned нет mixed; demo.ba4 назначен business_admin."""
    sm, _, _ = loaded
    events = await _rows(
        sm,
        "SELECT u.login, e.details->>'role_to' AS role_to FROM domain_event e "
        "LEFT JOIN app_user u ON u.id = e.entity_id WHERE e.action = 'user.role_assigned'",
    )
    assert events, "событий user.role_assigned нет"
    assert all(e["role_to"] != "mixed" for e in events)
    assert "demo.mixed" not in {e["login"] for e in events}
    assert {e["login"]: e["role_to"] for e in events}.get("demo.ba4") == "business_admin"
    raw = await _rows(sm, "SELECT count(*) AS n FROM domain_event WHERE details::text ~ 'mixed'")
    assert raw[0]["n"] == 0


@pytest.mark.committed
async def test_002_ac28_ba4_is_ba_member_of_both_projects_not_owner(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """002/AC-28: demo.ba4 — БА, участник обоих демо-проектов, не владелец."""
    sm, _, _ = loaded
    role = await _rows(
        sm,
        "SELECT m.role FROM app_user u JOIN workspace_member m ON m.user_id = u.id "
        "WHERE u.login = 'demo.ba4'",
    )
    assert [r["role"] for r in role] == ["business_admin"]
    projects = await _rows(sm, "SELECT id, owner_id FROM project")
    assert len(projects) == 2
    ba4 = await _rows(sm, "SELECT id FROM app_user WHERE login = 'demo.ba4'")
    assert len(ba4) == 1
    member_of = {
        r["project_id"]
        for r in await _rows(
            sm,
            "SELECT pm.project_id FROM project_member pm JOIN app_user u ON u.id = pm.user_id "
            "WHERE u.login = 'demo.ba4'",
        )
    }
    assert member_of == {p["id"] for p in projects}
    assert all(p["owner_id"] != ba4[0]["id"] for p in projects)


@pytest.mark.committed
async def test_fr57_passwords_distinct_long_not_common_argon2_must_change(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """FR-57, FR-52: 12 разных паролей >= 12 символов, не частые; Argon2id, смена пароля."""
    from app.core.security.common_passwords import is_common_password
    from app.core.security.passwords import PasswordHasher

    sm, settings, _ = loaded
    creds = _parse_passwords(_passwords_path(settings))
    assert set(creds) == EXPECTED_LOGINS
    passwords = list(creds.values())
    assert len(set(passwords)) == 12
    assert all(len(p) >= 12 for p in passwords)
    assert not any(is_common_password(p) for p in passwords)

    rows = await _rows(
        sm,
        "SELECT login, password_hash, must_change_password, is_blocked FROM app_user "
        "WHERE login LIKE 'demo.%'",
    )
    assert len(rows) == 12
    hasher = PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost_kib=settings.argon2_memory_cost_kib,
        parallelism=settings.argon2_parallelism,
    )
    for row in rows:
        assert row["must_change_password"] is True
        assert row["is_blocked"] is False
        assert row["password_hash"].startswith("$argon2id$")
        assert (
            f"m={settings.argon2_memory_cost_kib},t={settings.argon2_time_cost}"
            in (row["password_hash"])
        )
        assert creds[row["login"]] not in row["password_hash"]
        assert hasher.verify(row["password_hash"], creds[row["login"]])
    assert len({r["password_hash"] for r in rows}) == 12


@pytest.mark.committed
async def test_fr6_passwords_file_mode_0600_owner_and_report(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """FR-6/D-19 (как файл первого ТА): 0600, владелец процесса, 12 строк; отчёт."""
    import os

    _, settings, report = loaded
    path = _passwords_path(settings)
    assert path.is_file() and not path.is_symlink()
    st = path.stat()
    assert stat.S_IMODE(st.st_mode) == 0o600
    assert st.st_uid == os.getuid()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 12
    assert Path(report.passwords_file) == path
    assert (report.users, report.projects, report.tasks, report.subtasks) == (12, 2, 30, 6)
    assert 15 <= report.comments <= 25


@pytest.mark.committed
async def test_fr49_projects_members_owner_row(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """FR-49: 2 проекта; владелец — участник (строка project_member, заметка ревью T71).

    Обращён по 002/AC-28: вместо ``demo.mixed`` участник обоих проектов ``demo.ba4``.
    """
    sm, _, _ = loaded
    projects = await _rows(
        sm,
        "SELECT p.id, p.name, u.login AS owner FROM project p JOIN app_user u ON u.id = p.owner_id",
    )
    assert {(p["name"], p["owner"]) for p in projects} == {
        ("Внедрение трекера", "demo.ba1"),
        ("Подготовка пилота", "demo.ba2"),
    }
    members = await _rows(
        sm,
        "SELECT pm.project_id, u.login, wm.role FROM project_member pm "
        "JOIN app_user u ON u.id = pm.user_id "
        "JOIN workspace_member wm ON wm.user_id = u.id",
    )
    by_project: dict[Any, set[str]] = {}
    for m in members:
        by_project.setdefault(m["project_id"], set()).add(m["login"])
    assert set(by_project) == {p["id"] for p in projects}
    for p in projects:
        logins = by_project[p["id"]]
        assert p["owner"] in logins
        assert {"demo.ba1", "demo.ba2", "demo.ba4"} <= logins
        assert sum(1 for x in logins if x.startswith("demo.user")) == 4
        assert "demo.ta" not in logins
    all_members = set().union(*by_project.values())
    assert {f"demo.user{i}" for i in range(1, 8)} <= all_members  # каждый П хотя бы в одном
    assert all(m["role"] != "tech_admin" for m in members)


@pytest.mark.committed
async def test_fr49_tasks_counts_statuses_positions_subtasks(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """FR-49: 30 задач (12 + 12 верхнего уровня, 6 подзадач у 3 родителей); позиции."""
    sm, _, _ = loaded
    tasks = await _rows(
        sm,
        "SELECT id, project_id, parent_id, status, priority, position, due_date, "
        "deleted_at FROM task",
    )
    assert len(tasks) == 30
    assert all(t["deleted_at"] is None for t in tasks)
    top = [t for t in tasks if t["parent_id"] is None]
    subs = [t for t in tasks if t["parent_id"] is not None]
    assert (len(top), len(subs)) == (24, 6)
    assert all(t["position"] is None for t in subs)
    assert all(t["position"] is not None for t in top)
    top_ids = {t["id"] for t in top}
    parent_counts = Counter(t["parent_id"] for t in subs)
    assert set(parent_counts) <= top_ids
    assert sorted(parent_counts.values()) == [2, 2, 2]
    per_project = Counter(t["project_id"] for t in top)
    assert sorted(per_project.values()) == [12, 12]
    sub_project = {t["id"]: t["project_id"] for t in top}
    assert all(s["project_id"] == sub_project[s["parent_id"]] for s in subs)

    columns: dict[tuple[Any, str], list[int]] = {}
    for t in top:
        columns.setdefault((t["project_id"], t["status"]), []).append(t["position"])
    for key, positions in columns.items():
        assert sorted(positions) == [STEP * i for i in range(1, len(positions) + 1)], key
    for project_id in per_project:
        statuses = {s for (p, s) in columns if p == project_id}
        assert statuses == {"todo", "in_progress", "review", "done"}
    assert {t["status"] for t in subs} <= {"todo", "in_progress", "review", "done"}

    high = sum(1 for t in tasks if t["priority"] == "high")
    assert 4 <= high <= 14  # ~1/4
    assert any(t["due_date"] is None for t in tasks)
    assert any(t["due_date"] is not None for t in tasks)


@pytest.mark.committed
async def test_006_ac17_demo_priorities_only_medium_and_high(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """006/AC-17 (FR-13): у всех задач (и подзадач) ``medium`` или ``high``; ``high`` ровно
    столько же, сколько до фичи (3 на проект, 2 проекта, seed=1); ``low`` и ``base`` нет;
    состав демо прежний (001/FR-49: 30 задач, из них 6 подзадач)."""
    from app.domain.ops import demo

    assert demo._REGULAR_PRIORITY == "medium"
    sm, _, _ = loaded
    tasks = await _rows(sm, "SELECT parent_id, priority FROM task")
    assert len(tasks) == 30
    assert sum(1 for t in tasks if t["parent_id"] is not None) == 6
    counts = Counter(t["priority"] for t in tasks)
    assert set(counts) <= {"medium", "high"}, counts
    assert counts["high"] == 6, counts
    assert counts["medium"] == 24, counts
    # подзадачи - всегда обычного приоритета
    assert {t["priority"] for t in tasks if t["parent_id"] is not None} == {"medium"}


@pytest.mark.committed
async def test_fr49_due_dates_window_around_today(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """§11.8: сроки от today_msk(clock) - 3 до today_msk(clock) + 14 дней."""
    sm, _, _ = loaded
    today = today_msk(FIXED_NOW)
    rows = await _rows(sm, "SELECT due_date FROM task WHERE due_date IS NOT NULL")
    assert rows
    for r in rows:
        assert today - timedelta(days=3) <= r["due_date"] <= today + timedelta(days=14)


@pytest.mark.committed
async def test_fr15_assignees_are_project_members_not_tech_admin_authors(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """FR-15/FR-20: исполнитель — участник проекта и не ТА; автор — владелец или «свой»."""
    sm, _, _ = loaded
    bad = await _rows(
        sm,
        "SELECT t.id FROM task t WHERE t.assignee_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM project_member pm WHERE pm.project_id = t.project_id "
        "AND pm.user_id = t.assignee_id)",
    )
    assert bad == []
    ta = await _rows(
        sm,
        "SELECT t.id FROM task t JOIN workspace_member m ON m.user_id = t.assignee_id "
        "WHERE m.role = 'tech_admin'",
    )
    assert ta == []
    assert await _rows(sm, "SELECT id FROM task WHERE assignee_id IS NOT NULL")
    foreign_authors = await _rows(
        sm,
        "SELECT t.id FROM task t JOIN project p ON p.id = t.project_id "
        "WHERE t.parent_id IS NULL AND t.created_by <> p.owner_id "
        "AND t.created_by IS DISTINCT FROM t.assignee_id",
    )
    assert foreign_authors == []
    own = await _rows(
        sm,
        "SELECT t.id FROM task t JOIN workspace_member m ON m.user_id = t.assignee_id "
        "WHERE t.created_by = t.assignee_id AND m.role = 'user'",
    )
    assert own, "часть задач П — «свои» (автор = исполнитель)"


@pytest.mark.committed
async def test_fr49_comments_on_top_level_tasks_by_project_members(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """§11.8: ~20 комментариев у задач верхнего уровня, авторы — участники проекта."""
    sm, _, report = loaded
    comments = await _rows(
        sm,
        "SELECT c.id, t.parent_id, t.project_id, c.created_by, c.body FROM comment c "
        "JOIN task t ON t.id = c.task_id",
    )
    assert 15 <= len(comments) <= 25
    assert len(comments) == report.comments
    assert all(c["parent_id"] is None for c in comments)
    assert all(c["body"].strip() for c in comments)
    members = {
        (m["project_id"], m["user_id"])
        for m in await _rows(sm, "SELECT project_id, user_id FROM project_member")
    }
    assert all((c["project_id"], c["created_by"]) in members for c in comments)


# --- журнал (FR-41, D-6, D-55, D-63) ---------------------------------------------------------


@pytest.mark.committed
async def test_fr41_events_user_created_and_role_assigned_by_system(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """FR-41: по 12 событий user.created и user.role_assigned, actor_id NULL; иных нет."""
    sm, _, _ = loaded
    events = await _rows(
        sm,
        "SELECT e.action, e.actor_id, e.entity_type, e.in_audit, u.login, "
        "e.details->>'role_to' AS role_to FROM domain_event e "
        "LEFT JOIN app_user u ON u.id = e.entity_id",
    )
    assert Counter(e["action"] for e in events) == {
        "user.created": 12,
        "user.role_assigned": 12,
    }
    assert all(e["actor_id"] is None for e in events)
    assert all(e["entity_type"] == "user" and e["in_audit"] for e in events)
    created = {e["login"] for e in events if e["action"] == "user.created"}
    assert created == EXPECTED_LOGINS
    assigned = {e["login"]: e["role_to"] for e in events if e["action"] == "user.role_assigned"}
    assert assigned == EXPECTED_ROLES


@pytest.mark.committed
async def test_d55_no_project_or_task_events(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """D-55: прямые вставки проектов, задач и комментариев событий не пишут."""
    sm, _, _ = loaded
    rows = await _rows(
        sm,
        "SELECT count(*) AS n FROM domain_event WHERE entity_type <> 'user' "
        "OR project_id IS NOT NULL",
    )
    assert rows[0]["n"] == 0


# --- вход ------------------------------------------------------------------------------------


@pytest.mark.committed
async def test_fr55_demo_user_logs_in_and_must_change_password(
    committed_api_env: ApiEnv,
) -> None:
    """Вход демо-пользователя по паролю из файла проходит; дальше 403 password_change_required."""
    env = committed_api_env
    await _bootstrap(env.sessionmaker, env.settings)
    await _demo(env.sessionmaker, env.settings)
    creds = _parse_passwords(_passwords_path(env.settings))
    for login in ("demo.user1", "demo.ba1"):
        response = await env.login(login, creds[login])
        assert response.status_code == 200, response.text
        token = env.token_from(response)
        assert token
        me = await env.me(token)
        assert me.status_code == 403
        assert me.json()["code"] == "password_change_required"
    wrong = await env.login("demo.user1", creds["demo.user2"])
    assert wrong.status_code == 401


# --- отказ и атомарность ---------------------------------------------------------------------


@pytest.mark.committed
async def test_t87_second_run_refused_data_unchanged(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Повторный запуск: отказ (DemoDataRefused), данные и файл не изменены."""
    from app.domain.ops.demo import DemoDataRefused

    await _bootstrap(committed, settings)
    await _demo(committed, settings)
    before = await _snapshot(committed)
    content = _passwords_path(settings).read_bytes()
    with pytest.raises(DemoDataRefused):
        await _demo(committed, settings)
    assert await _snapshot(committed) == before
    assert _passwords_path(settings).read_bytes() == content


@pytest.mark.committed
async def test_t87_refused_when_project_exists_no_file(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Существует проект (в том числе мягко удалённый): отказ, ничего не создано, файла нет."""
    from app.domain.ops.demo import DemoDataRefused

    await _bootstrap(committed, settings)
    admin = (await _rows(committed, "SELECT user_id, workspace_id FROM workspace_member"))[0]
    async with committed() as session:
        await make_project(
            session,
            workspace_id=admin["workspace_id"],
            owner_id=admin["user_id"],
            deleted_at=utcnow(),
        )
        await session.commit()
    before = await _snapshot(committed)
    with pytest.raises(DemoDataRefused):
        await _demo(committed, settings)
    assert await _snapshot(committed) == before
    assert not _passwords_path(settings).exists()


@pytest.mark.committed
async def test_t87_refused_when_extra_user_exists_no_file(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Пользователь сверх первого ТА: отказ, ничего не создано, файла нет."""
    from app.domain.ops.demo import DemoDataRefused

    await _bootstrap(committed, settings)
    ws = (await _rows(committed, "SELECT id FROM workspace"))[0]["id"]
    async with committed() as session:
        from tests.factories import WorkspaceRow

        await make_user(session, workspace=WorkspaceRow(id=ws, created_at=utcnow()), role="user")
        await session.commit()
    before = await _snapshot(committed)
    with pytest.raises(DemoDataRefused):
        await _demo(committed, settings)
    assert await _snapshot(committed) == before
    assert not _passwords_path(settings).exists()


@pytest.mark.committed
async def test_t87_commit_failure_leaves_no_rows_and_no_file(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Ошибка фиксации: строк нет, файл с паролями удалён; повтор после этого проходит."""
    await _bootstrap(committed, settings)
    before = await _snapshot(committed)
    with _commit_hook("before_commit") as fired, pytest.raises(Exception):  # noqa: B017, PT011
        await _demo(committed, settings)
    assert fired
    assert await _snapshot(committed) == before
    assert not _passwords_path(settings).exists()
    leftovers = [p.name for p in settings.secrets_dir.iterdir() if "demo" in p.name]
    assert leftovers == [], "временные файлы с паролями не должны оставаться"
    report = await _demo(committed, settings)
    assert report.users == 12
    assert _passwords_path(settings).is_file()


@pytest.mark.committed
async def test_t87_deterministic_for_same_seed(
    committed: async_sessionmaker[AsyncSession], settings: Settings, test_database_url: str
) -> None:
    """Один seed — одни и те же логины, названия, статусы, исполнители и сроки."""
    from tests.conftest import _reset_schema

    sql = (
        "SELECT p.name AS project, t.title, t.status, t.priority, t.due_date, "
        "a.login AS assignee, c.login AS author, par.title AS parent, t.position, "
        "(SELECT count(*) FROM comment k WHERE k.task_id = t.id) AS comments "
        "FROM task t JOIN project p ON p.id = t.project_id "
        "LEFT JOIN app_user a ON a.id = t.assignee_id "
        "LEFT JOIN app_user c ON c.id = t.created_by "
        "LEFT JOIN task par ON par.id = t.parent_id "
        "ORDER BY p.name, t.title, par.title"
    )
    snapshots = []
    for _ in range(2):
        await _bootstrap(committed, settings)
        _passwords_path(settings).unlink(missing_ok=True)
        await _demo(committed, settings, seed=7)
        logins = await _rows(committed, "SELECT login FROM app_user ORDER BY login")
        snapshots.append((logins, await _rows(committed, sql)))
        engine = committed.kw["bind"]
        await _reset_schema(engine, test_database_url)
    assert snapshots[0] == snapshots[1]
    assert len(snapshots[0][1]) == 30


# --- CLI -------------------------------------------------------------------------------------


def _stdout_pairs(out: str) -> dict[str, str]:
    pairs = [line.split("=", 1) for line in out.strip().splitlines()]
    assert pairs and all(len(p) == 2 for p in pairs), f"ожидаются строки ключ=значение: {out!r}"
    return {k: v for k, v in pairs}


@pytest.mark.committed
async def test_t87_cli_success_stdout_has_path_and_counters_only(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CLI: код 0; stdout — путь к файлу и счётчики; паролей нет ни в stdout/stderr/логах."""
    settings = get_settings()
    await _bootstrap(committed, settings)
    caplog.set_level(logging.DEBUG)
    capfd.readouterr()

    code = await asyncio.to_thread(_run, ["demo-data", "--seed", "3"])

    assert code == 0
    out, err = capfd.readouterr()
    pairs = _stdout_pairs(out)
    path = _passwords_path(settings)
    assert pairs["passwords_file"] == str(path)
    counters = {k: v for k, v in pairs.items() if k != "passwords_file"}
    assert counters and all(v.isdigit() for v in counters.values()), pairs
    assert {"users", "projects", "tasks"} <= set(counters)
    assert (counters["users"], counters["projects"], counters["tasks"]) == ("12", "2", "30")
    creds = _parse_passwords(path)
    assert len(creds) == 12
    for stream in (out, err, caplog.text):
        for password in creds.values():
            assert password not in stream
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert await _count(committed, "task") == 30


@pytest.mark.committed
async def test_t87_cli_second_run_exit_2_data_unchanged(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Повторный запуск CLI: код 2, данные и файл не изменены, паролей в выводе нет."""
    settings = get_settings()
    await _bootstrap(committed, settings)
    assert await asyncio.to_thread(_run, ["demo-data"]) == 0
    path = _passwords_path(settings)
    content = path.read_bytes()
    before = await _snapshot(committed)
    capfd.readouterr()

    code = await asyncio.to_thread(_run, ["demo-data"])

    assert code == 2
    assert await _snapshot(committed) == before
    assert path.read_bytes() == content
    out, err = capfd.readouterr()
    assert err.strip(), "ожидается причина отказа в stderr"
    for password in _parse_passwords(path).values():
        assert password not in out + err


@pytest.mark.committed
async def test_t87_cli_refused_for_existing_project_exit_2_no_file(
    committed: async_sessionmaker[AsyncSession], cli_env: Path
) -> None:
    """CLI: в базе уже есть проект — код 2, файла нет, данные не тронуты."""
    assert await asyncio.to_thread(_run, ["demo-data", "--help"]) == 0  # команда существует
    settings = get_settings()
    await _bootstrap(committed, settings)
    admin = (await _rows(committed, "SELECT user_id, workspace_id FROM workspace_member"))[0]
    async with committed() as session:
        await make_project(session, workspace_id=admin["workspace_id"], owner_id=admin["user_id"])
        await session.commit()
    before = await _snapshot(committed)

    code = await asyncio.to_thread(_run, ["demo-data"])

    assert code == 2
    assert await _snapshot(committed) == before
    assert not _passwords_path(settings).exists()


def test_t87_cli_help_ok(capfd: pytest.CaptureFixture[str]) -> None:
    assert _run(["demo-data", "--help"]) == 0
    out = capfd.readouterr().out
    assert out.strip()
    assert "--seed" in out


class _FakeTime:
    def __init__(self) -> None:
        self.offset = 0.0
        self.real_start = time.monotonic()
        self._lock = threading.Lock()
        self._real_monotonic = time.monotonic
        self._real_time = time.time

    def tick(self, delta: float) -> None:
        with self._lock:
            self.offset += delta
        if self._real_monotonic() - self.real_start > 30:
            raise RuntimeError("test guard: ожидание БД идёт в реальном времени")

    def monotonic(self) -> float:
        self.tick(0.25)
        return self._real_monotonic() + self.offset

    def time(self) -> float:
        self.tick(0.25)
        return self._real_time() + self.offset

    def sleep(self, seconds: float) -> None:
        self.tick(max(float(seconds), 0.0))


def test_t87_cli_without_db_exit_1_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """БД недоступна: ожидание <= 60 с, код 1, пароль из DSN не печатается, файла нет."""
    fake = _FakeTime()
    real_async_sleep = asyncio.sleep

    async def fake_async_sleep(delay: float, result: Any = None) -> Any:
        fake.tick(max(float(delay), 0.0))
        await real_async_sleep(0)
        return result

    monkeypatch.setattr(time, "monotonic", fake.monotonic)
    monkeypatch.setattr(time, "time", fake.time)
    monkeypatch.setattr(time, "sleep", fake.sleep)
    monkeypatch.setattr(asyncio, "sleep", fake_async_sleep)

    db_password = "s3cretpw-demo-7a1c"
    data_dir = tmp_path / "data"
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL", f"postgresql+asyncpg://tracker:{db_password}@127.0.0.1:1/tracker_wb_test"
    )
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ALEMBIC_INI))
    get_settings.cache_clear()
    caplog.set_level(logging.DEBUG)
    try:
        code = _run(["demo-data"])
    finally:
        get_settings.cache_clear()

    assert code == 1
    assert fake.offset <= 75
    out, err = capfd.readouterr()
    assert out.strip() == ""
    assert err.strip() or caplog.text.strip()
    for stream in (out, err, caplog.text):
        assert db_password not in stream
    assert not (data_dir / "secrets" / DEMO_FILE).exists()


def test_t87_cli_invalid_configuration_exit_1_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Неверная конфигурация: код 1, stdout пуст, пароль из DSN не печатается."""
    password = "s3cretpw-cfg-5b3e"
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL", f"postgresql+asyncpg://tracker:{password}@127.0.0.1:1/tracker_wb_test"
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT", "not-a-duration")
    get_settings.cache_clear()
    try:
        code = _run(["demo-data"])
    finally:
        get_settings.cache_clear()
    assert code == 1
    out, err = capfd.readouterr()
    assert out.strip() == ""
    assert err.strip()
    assert password not in out + err


# --- попытка 2: мутанты и качество данных ---------------------------------------------------

_ORDER_SQL = (
    "SELECT p.name AS project, t.title, t.created_at, "
    "(SELECT array_agg(c.created_at ORDER BY c.created_at, c.id) FROM comment c "
    "WHERE c.task_id = t.id) AS comment_times "
    "FROM task t JOIN project p ON p.id = t.project_id ORDER BY p.name, t.title"
)


@pytest.mark.committed
async def test_t87_same_seed_same_data_but_different_passwords(
    committed: async_sessionmaker[AsyncSession], settings: Settings, test_database_url: str
) -> None:
    """Пароль не выводится из seed: два запуска с одним seed дают данные поровну, пароли разные."""
    from tests.conftest import _reset_schema

    runs: list[tuple[dict[str, str], list[dict[str, Any]]]] = []
    for _ in range(2):
        await _bootstrap(committed, settings)
        _passwords_path(settings).unlink(missing_ok=True)
        await _demo(committed, settings, seed=5)
        creds = _parse_passwords(_passwords_path(settings))
        runs.append((creds, await _rows(committed, _ORDER_SQL)))
        _passwords_path(settings).unlink()
        await _reset_schema(committed.kw["bind"], test_database_url)
    (creds1, data1), (creds2, data2) = runs
    assert set(creds1) == set(creds2) == EXPECTED_LOGINS
    assert len(data1) == 24 + 6
    assert data1 == data2
    assert set(creds1.values()).isdisjoint(creds2.values())


@pytest.mark.committed
async def test_t87_parallel_runs_one_succeeds_one_refused(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Два одновременных load_demo_data: один успех, один DemoDataRefused; файл по хешам."""
    from app.core.security.passwords import PasswordHasher
    from app.domain.ops.demo import DemoDataRefused, DemoReport

    await _bootstrap(committed, settings)
    results = await asyncio.gather(
        _demo(committed, settings), _demo(committed, settings), return_exceptions=True
    )
    ok = [r for r in results if isinstance(r, DemoReport)]
    refused = [r for r in results if isinstance(r, DemoDataRefused)]
    assert len(ok) == 1 and len(refused) == 1, results
    assert await _count(committed, "app_user") == 13
    assert await _count(committed, "task") == 30
    assert await _count(committed, "project") == 2
    creds = _parse_passwords(_passwords_path(settings))
    rows = await _rows(
        committed, "SELECT login, password_hash FROM app_user WHERE login LIKE 'demo.%'"
    )
    hasher = PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost_kib=settings.argon2_memory_cost_kib,
        parallelism=settings.argon2_parallelism,
    )
    assert len(rows) == 12
    assert all(hasher.verify(r["password_hash"], creds[r["login"]]) for r in rows)


@pytest.mark.committed
async def test_t87_cli_parallel_runs_exit_codes_0_and_2(
    committed: async_sessionmaker[AsyncSession], cli_env: Path
) -> None:
    """Два параллельных CLI-запуска: коды {0, 2}, в БД 13 пользователей и 30 задач."""
    settings = get_settings()
    await _bootstrap(committed, settings)
    codes = await asyncio.gather(
        asyncio.to_thread(_run, ["demo-data"]), asyncio.to_thread(_run, ["demo-data"])
    )
    assert sorted(codes) == [0, 2]
    assert await _count(committed, "app_user") == 13
    assert await _count(committed, "task") == 30
    assert len(_parse_passwords(_passwords_path(settings))) == 12


@pytest.mark.committed
async def test_sc20_subtask_author_is_owner_or_assignee(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """SC-20: подзадача «Пользователя» другому исполнителю недопустима (403 в API)."""
    sm, _, _ = loaded
    bad = await _rows(
        sm,
        "SELECT t.id FROM task t JOIN workspace_member m ON m.user_id = t.created_by "
        "JOIN project p ON p.id = t.project_id "
        "WHERE t.parent_id IS NOT NULL AND m.role = 'user' "
        "AND t.assignee_id IS NOT NULL AND t.assignee_id <> t.created_by",
    )
    assert bad == []
    not_owner = await _rows(
        sm,
        "SELECT t.id FROM task t JOIN project p ON p.id = t.project_id "
        "WHERE t.parent_id IS NOT NULL AND t.created_by <> p.owner_id "
        "AND t.created_by IS DISTINCT FROM t.assignee_id",
    )
    assert not_owner == []


@pytest.mark.committed
async def test_t87_rows_have_distinct_created_at_in_stable_order(
    loaded: tuple[async_sessionmaker[AsyncSession], Settings, Any],
) -> None:
    """Строки сдвинуты по номеру: у задач и комментариев разные created_at (порядок стабилен)."""
    sm, _, _ = loaded
    tasks = await _rows(sm, "SELECT created_at FROM task")
    assert len({r["created_at"] for r in tasks}) == 30
    comments = await _rows(sm, "SELECT created_at FROM comment")
    assert len({r["created_at"] for r in comments}) == len(comments) >= 15
    users = await _rows(sm, "SELECT created_at FROM app_user WHERE login LIKE 'demo.%'")
    assert len({r["created_at"] for r in users}) == 12


@pytest.mark.committed
async def test_t87_cli_production_env_warns_on_stderr_without_passwords(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """ENV=production: предупреждение в stderr (демо-данные в рабочей установке), код 0."""
    settings = get_settings()
    await _bootstrap(committed, settings)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    capfd.readouterr()

    code = await asyncio.to_thread(_run, ["demo-data"])

    assert code == 0
    out, err = capfd.readouterr()
    assert re.search(r"production|продакшн|рабоч|боев|боёв", err, re.IGNORECASE), err
    creds = _parse_passwords(_passwords_path(get_settings()))
    for password in creds.values():
        assert password not in out + err


@pytest.mark.committed
async def test_t87_cli_no_workspace_exit_1_hint_without_sql(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Пространства нет (bootstrap не выполнялся): код 1, подсказка про bootstrap, без SQL."""
    capfd.readouterr()
    code = await asyncio.to_thread(_run, ["demo-data"])
    assert code == 1
    out, err = capfd.readouterr()
    assert out.strip() == ""
    assert "bootstrap" in err
    assert not re.search(r"SELECT|INSERT|\[SQL|sqlalchemy|asyncpg", err, re.IGNORECASE), err
    assert not _passwords_path(get_settings()).exists()


@pytest.mark.committed
async def test_t87_cli_migrations_not_applied_exit_1_hint_without_sql(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Миграции не применены (схема пуста): код 1, короткая подсказка, без сырого SQL."""
    async with committed() as session:
        await session.execute(text("DROP SCHEMA public CASCADE"))
        await session.execute(text("CREATE SCHEMA public"))
        await session.commit()
    capfd.readouterr()
    code = await asyncio.to_thread(_run, ["demo-data"])
    assert code == 1
    out, err = capfd.readouterr()
    assert out.strip() == ""
    assert "bootstrap" in err
    assert not re.search(r"SELECT|INSERT|\[SQL|sqlalchemy|asyncpg", err, re.IGNORECASE), err
    assert len(err.strip().splitlines()) <= 5
