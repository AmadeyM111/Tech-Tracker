"""T27: переносы из ревью T26 в бэкенд (plan §4.12 «Решения после ревью T26», §4.7).

- (D1) соединение блокировки bootstrap и миграции alembic выполняют ``SET lock_timeout = 0``;
- (D2) второй ``bootstrap_lock`` ждёт освобождения дольше серверного ``lock_timeout``;
- (D6) ``ensure_secret_key`` удаляет остатки ``.secret_key.*.tmp`` при старте.

Контракт (допущение, нет в plan.md дословно): ``SET [SESSION] lock_timeout = 0`` выполняется
через ``connection.execute`` на соединении блокировки (виден в ``before_cursor_execute``) и
ДО ``pg_advisory_lock``. Серверный ``lock_timeout`` в тестах задаётся только на отдельном
движке (``server_settings``) или ``ALTER DATABASE`` тестовой БД с возвратом в ``finally``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from tests.db_support import assert_test_database_url, run_alembic

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.ext.asyncio import AsyncEngine

SET_ZERO = re.compile(
    r"^\s*SET\s+(SESSION\s+)?lock_timeout\s*(=|TO)\s*('0'|'0ms'|0)\s*;?\s*$", re.I
)


def _engine(url: str, lock_timeout: str = "200ms") -> AsyncEngine:
    assert_test_database_url(url)
    return create_async_engine(
        url,
        hide_parameters=True,
        connect_args={"server_settings": {"lock_timeout": lock_timeout}},
    )


# --- D1/D2: bootstrap_lock -----------------------------------------------------------------


async def test_t27_d1_bootstrap_lock_connection_resets_lock_timeout_before_waiting(
    test_database_url: str,
    db_engine: AsyncEngine,  # создаёт БД и применяет миграции: тест самодостаточен
) -> None:
    from app.domain.system.bootstrap import bootstrap_lock

    engine = _engine(test_database_url)
    statements: list[str] = []

    def spy(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", spy)
    try:
        async with bootstrap_lock(async_sessionmaker(engine, expire_on_commit=False)):
            pass
    finally:
        await engine.dispose()

    set_idx = [i for i, s in enumerate(statements) if SET_ZERO.match(s)]
    lock_idx = [i for i, s in enumerate(statements) if "pg_advisory_lock" in s]
    assert set_idx, f"нет SET lock_timeout = 0 на соединении блокировки: {statements}"
    assert lock_idx and set_idx[0] < lock_idx[0], "SET должен идти до pg_advisory_lock"


async def test_t27_d2_second_bootstrap_lock_waits_longer_than_server_lock_timeout(
    test_database_url: str,
    db_engine: AsyncEngine,  # создаёт БД и применяет миграции: тест самодостаточен
) -> None:
    from app.domain.system.bootstrap import bootstrap_lock

    engine = _engine(test_database_url, "200ms")
    sm = async_sessionmaker(engine, expire_on_commit=False)
    acquired_second_at: list[float] = []
    try:
        async with bootstrap_lock(sm):
            started = time.monotonic()

            async def second() -> None:
                async with bootstrap_lock(sm) as token:
                    assert token is not None
                    acquired_second_at.append(time.monotonic())

            task = asyncio.ensure_future(second())
            await asyncio.sleep(1.0)  # в 5 раз больше lock_timeout сервера
            assert not task.done(), (
                "второй bootstrap не должен получить блокировку, пока она занята"
            )
        await asyncio.wait_for(task, timeout=10)  # LockNotAvailableError -> тест красный
    finally:
        await engine.dispose()
    assert acquired_second_at and acquired_second_at[0] - started >= 0.9


# --- D1: alembic ---------------------------------------------------------------------------


async def test_t27_d1_alembic_waits_for_lock_longer_than_server_lock_timeout(
    test_database_url: str,
    db_engine: AsyncEngine,  # создаёт БД и применяет миграции: тест самодостаточен
) -> None:
    """Миграции под серверным lock_timeout=200ms ждут занятую таблицу 1,5 с и проходят."""
    assert_test_database_url(test_database_url)
    first = await asyncio.to_thread(run_alembic, test_database_url, "upgrade", "head")
    assert first.returncode == 0, first.stderr[-1500:]  # схема есть, alembic_version создана
    admin = create_async_engine(test_database_url, isolation_level="AUTOCOMMIT")
    holder = create_async_engine(test_database_url)
    db = admin.url.database
    assert db is not None
    quoted = '"' + db.replace('"', '""') + '"'
    try:
        async with admin.connect() as c:
            await c.execute(text("SELECT 1 FROM alembic_version"))  # схема есть (upgrade head)
            await c.execute(text(f"ALTER DATABASE {quoted} SET lock_timeout = '200ms'"))
        try:
            async with holder.connect() as hold:
                await hold.execute(text("LOCK TABLE alembic_version IN ACCESS EXCLUSIVE MODE"))
                task = asyncio.ensure_future(
                    asyncio.to_thread(run_alembic, test_database_url, "upgrade", "head")
                )
                await asyncio.sleep(1.5)
                assert not task.done(), "alembic завершился, хотя таблица версий заблокирована"
                await hold.rollback()
            result = await asyncio.wait_for(task, timeout=60)
        finally:
            async with admin.connect() as c:
                await c.execute(text(f"ALTER DATABASE {quoted} RESET lock_timeout"))
    finally:
        await holder.dispose()
        await admin.dispose()
    assert result.returncode == 0, result.stderr[-1500:]


# --- D6: остатки временных файлов ключа ----------------------------------------------------


def _prepare(settings: Settings) -> Path:
    d = settings.secrets_dir
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)
    return d


def _populate_leftovers(d: Path, outside: Path) -> dict[str, str]:
    stale = {
        ".secret_key.0123456789abcdef.tmp": "deadbeef",
        ".secret_key.ffff.tmp": "cafebabe",
    }
    for name, body in stale.items():
        (d / name).write_text(body)
    keep = {
        "initial-admin-password.txt": "login=a\npassword=b\n",
        ".initial-admin-password.txt.1234.tmp": "x",  # чужой шаблон (чистит bootstrap)
        "other.tmp": "o",
        ".secret_key.bak": "b",  # не оканчивается на .tmp
        "secret_key.1.tmp": "no-dot-prefix",
    }
    for name, body in keep.items():
        (d / name).write_text(body)
    return {**{k: "" for k in stale}, **keep}


def _assert_cleaned(d: Path, outside: Path, link: Path) -> None:
    left = sorted(p.name for p in d.iterdir() if re.fullmatch(r"\.secret_key\..+\.tmp", p.name))
    assert left == [link.name] or left == [], f"остатки не удалены: {left}"
    assert not (d / ".secret_key.0123456789abcdef.tmp").exists()
    assert not (d / ".secret_key.ffff.tmp").exists()
    for name in ("initial-admin-password.txt", "other.tmp", ".secret_key.bak", "secret_key.1.tmp"):
        assert (d / name).exists(), f"тронут посторонний файл {name}"
    assert outside.read_text() == "precious", "цель символической ссылки изменена или удалена"


def test_t27_d6_ensure_secret_key_removes_stale_tmp_files_when_creating_key(
    settings: Settings, tmp_path: Path
) -> None:
    from app.core.secrets import ensure_secret_key

    d = _prepare(settings)
    outside = tmp_path / "outside.txt"
    outside.write_text("precious")
    _populate_leftovers(d, outside)
    link = d / ".secret_key.link.tmp"
    os.symlink(outside, link)

    key = ensure_secret_key(settings)

    assert len(key) == 32
    _assert_cleaned(d, outside, link)
    assert (d / "secret_key").read_text().strip() == key.hex()


def test_t27_d6_ensure_secret_key_removes_stale_tmp_files_when_key_exists(
    settings: Settings, tmp_path: Path
) -> None:
    """Старт при уже существующем ключе тоже чистит остатки (в них лежит ключ в hex)."""
    from app.core.secrets import ensure_secret_key

    d = _prepare(settings)
    first = ensure_secret_key(settings)
    outside = tmp_path / "outside.txt"
    outside.write_text("precious")
    _populate_leftovers(d, outside)
    link = d / ".secret_key.link.tmp"
    os.symlink(outside, link)
    before = (d / "secret_key").read_bytes()

    second = ensure_secret_key(settings)

    assert second == first
    assert (d / "secret_key").read_bytes() == before
    _assert_cleaned(d, outside, link)


def test_t27_d6_stale_directory_named_like_tmp_is_not_touched(settings: Settings) -> None:
    from app.core.secrets import ensure_secret_key

    d = _prepare(settings)
    sub = d / ".secret_key.dir.tmp"
    sub.mkdir()
    (sub / "inner").write_text("1")

    ensure_secret_key(settings)

    assert (sub / "inner").read_text() == "1"


def _logged(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def _patch_removal(monkeypatch: pytest.MonkeyPatch, target: str, exc: OSError) -> None:
    """unlink/remove файла ``target`` бросает ``exc`` (для ENOENT файл реально удаляется)."""
    real_unlink, real_remove = os.unlink, os.remove

    def wrap(real):  # type: ignore[no-untyped-def]
        def fake(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if Path(os.fspath(path)).name == target:
                if isinstance(exc, FileNotFoundError):
                    real(path, *args, **kwargs)  # «параллельный процесс уже удалил»
                raise exc
            return real(path, *args, **kwargs)

        return fake

    monkeypatch.setattr(os, "unlink", wrap(real_unlink))
    monkeypatch.setattr(os, "remove", wrap(real_remove))


def test_t27_d6_concurrent_removal_enoent_is_not_warned(
    settings: Settings, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ENOENT при удалении остатка (его убрал параллельный запуск) - не ошибка и не WARNING."""
    from app.core.secrets import ensure_secret_key

    d = _prepare(settings)
    (d / ".secret_key.aaaa.tmp").write_text("deadbeef")
    (d / ".secret_key.bbbb.tmp").write_text("cafebabe")
    _patch_removal(monkeypatch, ".secret_key.aaaa.tmp", FileNotFoundError(2, "gone"))

    with caplog.at_level(logging.DEBUG):
        key = ensure_secret_key(settings)

    assert len(key) == 32
    assert _logged(caplog) == [], [r.getMessage() for r in _logged(caplog)]
    assert not (d / ".secret_key.aaaa.tmp").exists()
    assert not (d / ".secret_key.bbbb.tmp").exists()


def test_t27_d6_concurrent_removal_enoent_on_lstat_is_not_warned(
    settings: Settings, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Остаток исчез между scandir и lstat/unlink: тоже без WARNING."""
    from app.core.secrets import ensure_secret_key

    d = _prepare(settings)
    (d / ".secret_key.aaaa.tmp").write_text("deadbeef")
    real_lstat = os.lstat

    def fake_lstat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(os.fspath(path)).name == ".secret_key.aaaa.tmp":
            os.unlink(path)
            raise FileNotFoundError(2, "gone")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", fake_lstat)
    with caplog.at_level(logging.DEBUG):
        key = ensure_secret_key(settings)

    assert len(key) == 32
    assert _logged(caplog) == [], [r.getMessage() for r in _logged(caplog)]


def test_t27_d6_real_removal_error_is_still_warned_without_secret_leak(
    settings: Settings, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.secrets import ensure_secret_key

    d = _prepare(settings)
    (d / ".secret_key.aaaa.tmp").write_text("deadbeef")
    (d / ".secret_key.bbbb.tmp").write_text("cafebabe")
    _patch_removal(monkeypatch, ".secret_key.aaaa.tmp", PermissionError(13, "denied"))

    with caplog.at_level(logging.DEBUG):
        key = ensure_secret_key(settings)

    assert len(key) == 32, "сбой чистки не должен мешать запуску"
    warned = _logged(caplog)
    assert len(warned) >= 1, "реальная ошибка удаления должна давать WARNING"
    assert all(r.levelno == logging.WARNING for r in warned)
    text = " ".join(r.getMessage() for r in warned)
    assert key.hex() not in text and "deadbeef" not in text
    assert not (d / ".secret_key.bbbb.tmp").exists(), "остальные остатки удаляются"


def test_t27_d6_cleanup_does_not_follow_symlinked_secrets_dir(
    settings: Settings, tmp_path: Path
) -> None:
    """``secrets`` - символьная ссылка на чужой каталог: чужие файлы не удаляются."""
    from app.core.secrets import ensure_secret_key

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    victim = foreign / ".secret_key.x.tmp"
    victim.write_text("precious")
    settings.secrets_dir.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(foreign, settings.secrets_dir)

    with pytest.raises(NotADirectoryError):  # ссылка отвергается (ensure_private_dir)
        ensure_secret_key(settings)

    assert victim.exists(), "чистка зашла по ссылке в чужой каталог"
    assert victim.read_text() == "precious"
    assert not (foreign / "secret_key").exists(), "ключ записан по ссылке"


@pytest.fixture(autouse=True)
def _no_leftover_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    yield
