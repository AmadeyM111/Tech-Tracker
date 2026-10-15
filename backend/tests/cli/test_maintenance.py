"""T19 (заметка ревью T16a): ``gostracker maintenance`` удаляет истёкшие сессии пользователей.

Истёкшая: ``now - last_activity_at >= 8 ч`` или ``now >= absolute_expires_at`` (D-13, FR-58).
Времена сидов отсчитываются от реальных часов с запасом в минуты: команда читает текущее
время сама. T31 (D-42, plan §10.4): stdout — строки ``ключ=значение`` в порядке полей отчёта,
``--dry-run`` только считает; событий в ``domain_event`` нет.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select, text

from app.core.clock import FixedClock
from app.core.config import get_settings
from tests.db_support import ALEMBIC_INI
from tests.factories import get_table, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.conftest import ApiEnv


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_database_url: str) -> Path:
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


REPORT_KEYS = [
    "dry_run",
    "sessions_expired",
    "projects_purged",
    "tasks_purged",
    "comments_purged",
    "attachments_purged",
    "files_removed",
    "orphan_files_removed",
]


def _report(out: str) -> dict[str, int]:
    """Разбирает stdout: ровно строки ``ключ=целое`` в порядке REPORT_KEYS."""
    lines = out.strip().splitlines()
    pairs = [line.split("=", 1) for line in lines]
    assert all(len(p) == 2 for p in pairs), f"ожидаются строки ключ=значение: {lines!r}"
    assert [p[0] for p in pairs] == REPORT_KEYS, lines
    assert all(p[1].isdigit() for p in pairs), lines
    return {k: int(v) for k, v in pairs}


def _run(argv: list[str]) -> int:
    from app.cli.main import main

    try:
        return int(main(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)


async def _seed_sessions(
    sm: async_sessionmaker[AsyncSession],
) -> tuple[set[bytes], set[bytes]]:
    """Возвращает (живые id, истёкшие id): 2 живые, 2 истёкшие по простою, 1 по сроку."""
    now = datetime.now(UTC)
    table = get_table("user_session")
    live: set[bytes] = set()
    dead: set[bytes] = set()
    async with sm() as session:
        user = await make_user(session, role="tech_admin")
        specs = [
            # (last_activity, created, absolute, живая?)
            (now - timedelta(hours=1), now - timedelta(hours=1), now + timedelta(days=6), True),
            (
                now - timedelta(hours=7, minutes=50),
                now - timedelta(days=6),
                now + timedelta(days=1),
                True,
            ),
            (
                now - timedelta(hours=8, minutes=10),
                now - timedelta(days=1),
                now + timedelta(days=6),
                False,
            ),
            (now - timedelta(days=3), now - timedelta(days=3), now + timedelta(days=4), False),
            (
                now - timedelta(minutes=1),
                now - timedelta(days=7, minutes=5),
                now - timedelta(minutes=5),
                False,
            ),
        ]
        for last, created, absolute, alive in specs:
            sid = os.urandom(32)
            await session.execute(
                table.insert().values(
                    id=sid,
                    user_id=user.id,
                    workspace_id=user.workspace_id,
                    created_at=created,
                    last_activity_at=last,
                    absolute_expires_at=absolute,
                )
            )
            (live if alive else dead).add(sid)
        await session.commit()
    return live, dead


async def _session_ids(sm: async_sessionmaker[AsyncSession]) -> set[bytes]:
    table = get_table("user_session")
    async with sm() as session:
        return {bytes(r[0]) for r in (await session.execute(select(table.c.id))).all()}


async def _event_count(sm: async_sessionmaker[AsyncSession]) -> int:
    async with sm() as session:
        return int((await session.execute(text("SELECT count(*) FROM domain_event"))).scalar_one())


@pytest.mark.committed
async def test_t16a_maintenance_deletes_only_expired_sessions(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Удаляет истёкшие (простой >= 8 ч, абсолютный срок), живые не трогает; stdout — число."""
    caplog.set_level(logging.DEBUG)
    live, dead = await _seed_sessions(committed)
    capfd.readouterr()

    code = await asyncio.to_thread(_run, ["maintenance"])

    assert code == 0
    out, err = capfd.readouterr()
    report = _report(out)
    assert report["dry_run"] == 0
    assert report["sessions_expired"] == len(dead)
    assert {
        k: v for k, v in report.items() if k not in ("dry_run", "sessions_expired")
    } == dict.fromkeys(REPORT_KEYS[2:], 0)
    assert await _session_ids(committed) == live
    for sid in live | dead:
        assert sid.hex() not in out + err + caplog.text
    assert await _event_count(committed) == 0
    assert not (cli_env / "secrets").exists(), "команда не создаёт секретный ключ"


@pytest.mark.committed
async def test_t16a_maintenance_is_idempotent(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    live, _dead = await _seed_sessions(committed)
    assert await asyncio.to_thread(_run, ["maintenance"]) == 0
    capfd.readouterr()
    assert await asyncio.to_thread(_run, ["maintenance"]) == 0
    second = _report(capfd.readouterr().out)
    assert second["sessions_expired"] == 0
    assert second["dry_run"] == 0
    assert await _session_ids(committed) == live
    assert await _event_count(committed) == 0


@pytest.mark.committed
async def test_t16a_maintenance_empty_database_prints_all_zeros(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    assert await asyncio.to_thread(_run, ["maintenance"]) == 0
    report = _report(capfd.readouterr().out)
    assert report == {**dict.fromkeys(REPORT_KEYS, 0)}


@pytest.mark.committed
async def test_fr25b_maintenance_dry_run_counts_and_deletes_nothing(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """AC-63 (каркас): --dry-run печатает dry_run=1 и те же числа, не удаляя."""
    live, dead = await _seed_sessions(committed)
    before = live | dead
    capfd.readouterr()

    assert await asyncio.to_thread(_run, ["maintenance", "--dry-run"]) == 0
    dry = _report(capfd.readouterr().out)
    assert dry["dry_run"] == 1
    assert dry["sessions_expired"] == len(dead)
    assert await _session_ids(committed) == before
    assert await _event_count(committed) == 0

    assert await asyncio.to_thread(_run, ["maintenance"]) == 0
    real = _report(capfd.readouterr().out)
    assert real["dry_run"] == 0
    assert real["sessions_expired"] == dry["sessions_expired"]
    assert await _session_ids(committed) == live


@pytest.mark.committed
async def test_fr25b_maintenance_dry_run_empty_database(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    assert await asyncio.to_thread(_run, ["maintenance", "--dry-run"]) == 0
    assert _report(capfd.readouterr().out) == {**dict.fromkeys(REPORT_KEYS, 0), "dry_run": 1}


@pytest.mark.committed
async def test_t31_run_maintenance_report_and_clock(
    committed: async_sessionmaker[AsyncSession],
    settings: Any,
) -> None:
    """plan §10.4: ``run_maintenance`` -> frozen ``MaintenanceReport``; время берётся из clock."""
    import dataclasses

    from app.domain.ops.maintenance import MaintenanceReport, run_maintenance

    assert [f.name for f in dataclasses.fields(MaintenanceReport)] == REPORT_KEYS
    default = MaintenanceReport()
    assert default.dry_run is False
    assert all(getattr(default, k) == 0 for k in REPORT_KEYS[1:])
    with pytest.raises(dataclasses.FrozenInstanceError):
        default.sessions_expired = 1  # type: ignore[misc]

    now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    table = get_table("user_session")
    async with committed() as session:
        user = await make_user(session, role="tech_admin")
        for last, absolute in (
            (now - settings.session_idle_timeout, now + timedelta(days=1)),  # граница: истекла
            (now, now),  # граница абсолютного срока: истекла
            (
                now - settings.session_idle_timeout + timedelta(microseconds=1),
                now + timedelta(days=1),
            ),
        ):
            await session.execute(
                table.insert().values(
                    id=os.urandom(32),
                    user_id=user.id,
                    workspace_id=user.workspace_id,
                    created_at=now - timedelta(days=1),
                    last_activity_at=last,
                    absolute_expires_at=absolute,
                )
            )
        await session.commit()

    clock = FixedClock(now)
    dry = await run_maintenance(committed, settings, clock=clock, dry_run=True)
    assert isinstance(dry, MaintenanceReport)
    assert dry == MaintenanceReport(dry_run=True, sessions_expired=2)
    assert len(await _session_ids(committed)) == 3

    real = await run_maintenance(committed, settings, clock=clock, dry_run=False)
    assert real == MaintenanceReport(dry_run=False, sessions_expired=2)
    assert len(await _session_ids(committed)) == 1


@pytest.mark.committed
async def test_t16a_maintenance_parallel_with_user_requests_no_deadlock(
    committed_api_env: ApiEnv,
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Параллельные запросы пользователей (me, вход) и maintenance: все ответы 200, нет 500."""
    env = committed_api_env
    env.clock.set(datetime.now(UTC))  # часы приложения = реальные, чтобы сессии были живыми
    env.settings.data_dir.mkdir(parents=True, exist_ok=True)
    user = await env.new_user(role="tech_admin")
    other = await env.new_user(role="tech_admin")
    token = await env.login_ok(user)
    live, dead = await _seed_sessions(env.sessionmaker)
    capfd.readouterr()

    stop = threading.Event()
    results: list[int] = []

    async def hammer() -> None:
        while not stop.is_set():
            responses = await asyncio.gather(
                *(env.me(token) for _ in range(5)),
                env.login(other.login, other.password),
            )
            results.extend(r.status_code for r in responses)

    task = asyncio.create_task(hammer())
    try:
        codes = [await asyncio.to_thread(_run, ["maintenance"]) for _ in range(3)]
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=30)

    assert codes == [0, 0, 0]
    assert results and set(results) == {200}, set(results)
    ids = await _session_ids(env.sessionmaker)
    assert live <= ids
    assert not (dead & ids)
    assert env.token_id(token) in ids


# --- ошибки ----------------------------------------------------------------------------------


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


def test_t16a_maintenance_without_db_fails_within_60s_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Как bootstrap: ожидание БД <= 60 с, код != 0, в сообщении нет пароля из DSN."""
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

    db_password = "s3cretpw-maint-4c1e"
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL", f"postgresql+asyncpg://tracker:{db_password}@127.0.0.1:1/tracker_test"
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ALEMBIC_INI))
    get_settings.cache_clear()
    caplog.set_level(logging.DEBUG)

    code = _run(["maintenance"])

    assert code == 1
    assert code != 2, "2 — ошибка аргументов; подкоманда должна существовать"
    assert fake.offset <= 75, f"ожидание БД превысило 60 с (учтено {fake.offset:.0f} с)"
    out, err = capfd.readouterr()
    assert err.strip() or caplog.text.strip(), "ожидается сообщение об ошибке"
    assert out.strip() == ""
    for stream in (out, err, caplog.text):
        assert db_password not in stream
    get_settings.cache_clear()


def test_t16a_maintenance_help_ok(capfd: pytest.CaptureFixture[str]) -> None:
    assert _run(["maintenance", "--help"]) == 0
    out = capfd.readouterr().out
    assert out.strip()
    assert "--dry-run" in out


def test_t31_maintenance_invalid_configuration_exits_1_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Неверная конфигурация: код 1, stderr без пароля из DSN, stdout пуст."""
    password = "s3cretpw-cfg-9d2f"
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL", f"postgresql+asyncpg://tracker:{password}@127.0.0.1:1/tracker_test"
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT", "not-a-duration")
    get_settings.cache_clear()
    try:
        code = _run(["maintenance"])
    finally:
        get_settings.cache_clear()
    assert code == 1
    out, err = capfd.readouterr()
    assert out.strip() == ""
    assert err.strip()
    assert password not in out + err
