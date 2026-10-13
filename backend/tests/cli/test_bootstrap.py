"""T10: первый запуск — секретный ключ, пространство, первый ТА, каркас CLI.

Покрытие: AC-23 (in-process часть), AC-114 (часть), FR-6, FR-41 (OI-110), FR-57,
D-9, D-19, D-20, D-29; plan §4.2 (``write_private_file``, ``ensure_secret_key``),
§4.7 (``run_bootstrap``, ``remove_initial_admin_file_if_for``); заметка ревью T03
(``SECRET_KEY=""`` = отсутствие ключа).

Модули ``app.core.secrets``, ``app.domain.system.bootstrap``, ``app.cli.main``
импортируются внутри тестов: отсутствие реализации даёт понятное падение каждого теста.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.core.clock import FixedClock
from app.core.config import Settings, get_settings
from tests.conftest import CHEAP_ARGON2, FIXED_NOW
from tests.db_support import ALEMBIC_INI

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

INITIAL_FILE = "initial-admin-password.txt"  # plan §4.7 (INITIAL_ADMIN_FILE)
KNOWN_PASSWORD = "Zq7Lm2Vx9TestBootstrapPw"
OTHER_PASSWORD = "Hw4Rt8Nc6OtherBootstrapPw"


# --- помощники ---------------------------------------------------------------------------


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    kwargs: dict[str, Any] = {
        "env": "test",
        "data_dir": tmp_path / "data",
        "cookie_secure": False,
        "secret_key": None,
        **CHEAP_ARGON2,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _parse_credentials(path: Path) -> dict[str, str]:
    """Формат файла: ``login=…\\npassword=…\\n`` (plan §4.7)."""
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


@pytest.fixture
def umask_zero() -> Iterator[None]:
    old = os.umask(0)
    try:
        yield
    finally:
        os.umask(old)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убирает из окружения процесса всё, что читает Settings, и сбрасывает кеш настроек."""
    for name in ("SECRET_KEY", "DATA_DIR", "DATABASE_URL", "INITIAL_ADMIN_LOGIN", "ENV"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
    tmp_path: Path,
    test_database_url: str,
) -> Path:
    """Окружение процесса для ``main(argv)``; возвращает data_dir."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_MEMORY_COST_KIB", "1024")
    monkeypatch.setenv("ARGON2_PARALLELISM", "1")
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ALEMBIC_INI))
    return data_dir


async def _scalar(sm: async_sessionmaker[AsyncSession], sql: str) -> Any:
    async with sm() as session:
        return (await session.execute(text(sql))).scalar()


async def _admin_rows(sm: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sm() as session:
        rows = await session.execute(
            text(
                "SELECT u.id AS user_id, u.login, u.password_hash, u.must_change_password, "
                "u.is_blocked, "
                "u.created_by AS user_created_by, m.workspace_id, m.role, "
                "m.created_by AS member_created_by "
                "FROM app_user u JOIN workspace_member m ON m.user_id = u.id"
            )
        )
        return [dict(r._mapping) for r in rows]


def _prepare_secrets_dir(settings: Settings) -> None:
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    settings.secrets_dir.chmod(0o700)


async def _bootstrap(
    sm: async_sessionmaker[AsyncSession],
    settings: Settings,
    password: str = KNOWN_PASSWORD,
) -> Any:
    from app.domain.system.bootstrap import run_bootstrap

    return await run_bootstrap(sm, settings, clock=FixedClock(FIXED_NOW), generate=lambda: password)


# --- write_private_file (plan §4.2) -------------------------------------------------------


def test_write_private_file_mode_0600_even_with_umask_zero(
    tmp_path: Path, umask_zero: None
) -> None:
    """FR-6, D-19: файл создаётся с режимом 0600 независимо от umask."""
    from app.core.secrets import write_private_file

    target = tmp_path / "private.txt"
    write_private_file(target, "login=admin\npassword=abc\n")
    assert target.read_text(encoding="utf-8") == "login=admin\npassword=abc\n"
    assert _mode(target) == 0o600


def test_write_private_file_leaves_no_temp_files(tmp_path: Path) -> None:
    """Атомарность: после записи в каталоге только целевой файл."""
    from app.core.secrets import write_private_file

    write_private_file(tmp_path / "a.txt", "x")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt"]


def test_write_private_file_does_not_overwrite_existing(tmp_path: Path) -> None:
    """FR-6: существующий файл не пересоздаётся (O_EXCL), содержимое и режим прежние."""
    from app.core.secrets import write_private_file

    target = tmp_path / "private.txt"
    write_private_file(target, "first")
    with pytest.raises(FileExistsError):
        write_private_file(target, "second")
    assert target.read_text(encoding="utf-8") == "first"
    assert _mode(target) == 0o600


def test_write_private_file_does_not_follow_symlink(tmp_path: Path) -> None:
    """Симлинк на месте целевого пути не разыменовывается; цель не изменяется."""
    from app.core.secrets import write_private_file

    victim = tmp_path / "victim.txt"
    victim.write_text("original", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(victim)
    with pytest.raises(OSError):
        write_private_file(link, "payload")
    assert victim.read_text(encoding="utf-8") == "original"
    assert link.is_symlink()


def test_write_private_file_does_not_follow_dangling_symlink(tmp_path: Path) -> None:
    from app.core.secrets import write_private_file

    missing = tmp_path / "not-created.txt"
    link = tmp_path / "link.txt"
    link.symlink_to(missing)
    with pytest.raises(OSError):
        write_private_file(link, "payload")
    assert not missing.exists()


def test_write_private_file_error_does_not_leak_content(tmp_path: Path) -> None:
    """FR-57: текст ошибки не содержит записываемое содержимое."""
    from app.core.secrets import write_private_file

    target = tmp_path / "private.txt"
    target.write_text("old", encoding="utf-8")
    secret = "TOPSECRET-do-not-leak-12345"
    with pytest.raises(OSError) as info:
        write_private_file(target, secret)
    assert secret not in str(info.value)
    assert secret not in repr(info.value)
    assert secret not in repr(info.value.args)


# --- ensure_secret_key (plan §4.2, D-20, FR-6) --------------------------------------------


def test_ensure_secret_key_generates_file_0600_in_dir_0700(
    tmp_path: Path, umask_zero: None
) -> None:
    """AC-23, D-20: чистый каталог → ключ ≥ 32 байт, файл 0600, каталог secrets 0700."""
    from app.core.secrets import ensure_secret_key

    settings = _settings(tmp_path)
    key = ensure_secret_key(settings)
    assert isinstance(key, bytes)
    assert len(key) >= 32
    path = settings.secrets_dir / "secret_key"
    assert path.is_file()
    assert _mode(path) == 0o600
    assert _mode(settings.secrets_dir) == 0o700
    assert key not in (b"change-me", b"")


def test_ensure_secret_key_dir_mode_0700_under_default_umask(tmp_path: Path) -> None:
    from app.core.secrets import ensure_secret_key

    old = os.umask(0o022)
    try:
        settings = _settings(tmp_path)
        ensure_secret_key(settings)
    finally:
        os.umask(old)
    assert _mode(settings.secrets_dir) == 0o700
    assert _mode(settings.secrets_dir / "secret_key") == 0o600


def test_ensure_secret_key_file_content_matches_key(tmp_path: Path) -> None:
    """D-20: файл хранит ключ (hex или как есть); значение не пустое."""
    from app.core.secrets import ensure_secret_key

    settings = _settings(tmp_path)
    key = ensure_secret_key(settings)
    raw = (settings.secrets_dir / "secret_key").read_bytes().strip()
    assert raw
    assert raw == key or bytes.fromhex(raw.decode("ascii")) == key


def test_ensure_secret_key_is_stable_and_does_not_recreate_file(tmp_path: Path) -> None:
    """FR-6, AC-23: повторный вызов — тот же ключ, файл не пересоздан."""
    from app.core.secrets import ensure_secret_key

    settings = _settings(tmp_path)
    first = ensure_secret_key(settings)
    path = settings.secrets_dir / "secret_key"
    before = path.stat()
    content = path.read_bytes()

    second = ensure_secret_key(settings)
    after = path.stat()
    assert second == first
    assert path.read_bytes() == content
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_ensure_secret_key_differs_between_installations(tmp_path: Path) -> None:
    """AC-23: ключ случаен (две чистые установки дают разные ключи)."""
    from app.core.secrets import ensure_secret_key

    a = ensure_secret_key(_settings(tmp_path / "a"))
    b = ensure_secret_key(_settings(tmp_path / "b"))
    assert a != b


def test_ensure_secret_key_env_value_has_priority(tmp_path: Path) -> None:
    """D-20: непустой SECRET_KEY из Settings — приоритетнее файла; файл не создаётся."""
    from app.core.secrets import ensure_secret_key

    value = "e" * 48
    settings = _settings(tmp_path, secret_key=SecretStr(value))
    assert ensure_secret_key(settings) == value.encode()
    assert not (settings.secrets_dir / "secret_key").exists()


def test_ensure_secret_key_env_value_wins_over_existing_file(tmp_path: Path) -> None:
    from app.core.secrets import ensure_secret_key

    file_settings = _settings(tmp_path)
    file_key = ensure_secret_key(file_settings)
    value = "f" * 48
    env_settings = _settings(tmp_path, secret_key=SecretStr(value))
    assert ensure_secret_key(env_settings) == value.encode()
    assert ensure_secret_key(file_settings) == file_key


def test_ensure_secret_key_empty_env_string_is_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    """Заметка ревью T03: ``SECRET_KEY=""`` == ключа нет → генерируется файл."""
    from app.core.secrets import ensure_secret_key

    monkeypatch.setenv("SECRET_KEY", "")
    settings = Settings(env="test", data_dir=tmp_path / "data", **CHEAP_ARGON2)
    key = ensure_secret_key(settings)
    assert len(key) >= 32
    assert key != b""
    assert (settings.secrets_dir / "secret_key").is_file()


def test_ensure_secret_key_rejects_change_me_placeholder(tmp_path: Path) -> None:
    """AC-23: значение-заглушка ``change-me`` не используется как ключ.

    Допустимо: исключение либо игнорирование и генерация файла; недопустимо — вернуть заглушку.
    """
    from app.core.secrets import ensure_secret_key

    settings = _settings(tmp_path, secret_key=SecretStr("change-me"))
    try:
        key = ensure_secret_key(settings)
    except (ValueError, RuntimeError):
        return
    assert key != b"change-me"
    assert len(key) >= 32
    assert (settings.secrets_dir / "secret_key").is_file()


def test_ensure_secret_key_concurrent_calls_agree(tmp_path: Path) -> None:
    """Атомарное создание: гонка потоков → один ключ, один файл, нет временных остатков."""
    from app.core.secrets import ensure_secret_key

    settings = _settings(tmp_path)
    workers = 8
    barrier = threading.Barrier(workers)

    def call() -> bytes:
        barrier.wait(timeout=10)
        return ensure_secret_key(settings)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        keys = list(pool.map(lambda _: call(), range(workers)))
    assert len(set(keys)) == 1
    assert [p.name for p in settings.secrets_dir.iterdir()] == ["secret_key"]
    raw = (settings.secrets_dir / "secret_key").read_bytes().strip()
    assert raw == keys[0] or bytes.fromhex(raw.decode("ascii")) == keys[0]


# --- run_bootstrap (plan §4.7, FR-6, D-9) ---------------------------------------------------


@pytest.mark.committed
async def test_bootstrap_creates_workspace_and_single_tech_admin(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """AC-23, FR-6: ровно одно пространство и один ТА с must_change_password."""
    _prepare_secrets_dir(settings)
    result = await _bootstrap(committed, settings)

    assert result.admin_created is True
    assert await _scalar(committed, "SELECT count(*) FROM workspace") == 1
    rows = await _admin_rows(committed)
    assert len(rows) == 1
    row = rows[0]
    assert row["login"] == settings.initial_admin_login
    assert row["role"] == "tech_admin"
    assert row["must_change_password"] is True
    assert row["is_blocked"] is False
    assert row["workspace_id"] == result.workspace_id
    assert await _scalar(committed, "SELECT id FROM workspace") == result.workspace_id
    # FR-41/D-9: автор «система»
    assert row["user_created_by"] is None
    assert row["member_created_by"] is None


@pytest.mark.committed
async def test_bootstrap_password_stored_only_as_argon2id_hash(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """AC-23, ADR-0004: в БД Argon2id-хеш; файл содержит логин и пароль, пароль проходит verify."""
    from app.core.security.passwords import PasswordHasher

    _prepare_secrets_dir(settings)
    await _bootstrap(committed, settings)

    (row,) = await _admin_rows(committed)
    assert row["password_hash"].startswith("$argon2id$")
    assert KNOWN_PASSWORD not in row["password_hash"]

    path = settings.secrets_dir / INITIAL_FILE
    creds = _parse_credentials(path)
    assert creds["login"] == settings.initial_admin_login
    assert creds["password"] == KNOWN_PASSWORD
    hasher = PasswordHasher(time_cost=1, memory_cost_kib=1024, parallelism=1)
    assert hasher.verify(row["password_hash"], creds["password"]) is True
    assert hasher.verify(row["password_hash"], KNOWN_PASSWORD + "x") is False


@pytest.mark.committed
async def test_bootstrap_password_file_mode_0600(
    committed: async_sessionmaker[AsyncSession], settings: Settings, umask_zero: None
) -> None:
    """AC-23, D-19: файл пароля — режим 0600 (даже при umask 000)."""
    _prepare_secrets_dir(settings)
    await _bootstrap(committed, settings)
    path = settings.secrets_dir / INITIAL_FILE
    assert path.is_file()
    assert _mode(path) == 0o600


@pytest.mark.committed
async def test_bootstrap_default_generator_password_is_valid(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """FR-6: без ``generate`` пароль генерируется generate_password (политика FR-52/53)."""
    from app.domain.system.bootstrap import run_bootstrap

    from app.core.security.passwords import PasswordHasher, validate_new_password

    _prepare_secrets_dir(settings)
    await run_bootstrap(committed, settings, clock=FixedClock(FIXED_NOW))
    creds = _parse_credentials(settings.secrets_dir / INITIAL_FILE)
    validate_new_password(creds["password"])  # не бросает
    assert len(creds["password"]) >= 12
    (row,) = await _admin_rows(committed)
    hasher = PasswordHasher(time_cost=1, memory_cost_kib=1024, parallelism=1)
    assert hasher.verify(row["password_hash"], creds["password"]) is True


@pytest.mark.committed
async def test_bootstrap_writes_no_domain_events(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """AC-114 (часть), FR-41, D-9: после первого запуска ``domain_event`` пуст."""
    _prepare_secrets_dir(settings)
    await _bootstrap(committed, settings)
    assert await _scalar(committed, "SELECT count(*) FROM domain_event") == 0


@pytest.mark.committed
async def test_bootstrap_does_not_leak_password_to_stdout_stderr_or_logs(
    committed: async_sessionmaker[AsyncSession],
    settings: Settings,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-23, FR-57: пароля нет ни в stdout/stderr, ни в логах (в т.ч. JSON-вывод)."""
    from app.core.logging import configure_logging

    configure_logging("DEBUG")
    caplog.set_level(logging.DEBUG)
    try:
        _prepare_secrets_dir(settings)
        await _bootstrap(committed, settings)
    finally:
        for handler in list(logging.getLogger().handlers):
            if type(handler).__name__ == "_StdoutHandler":
                logging.getLogger().removeHandler(handler)
    out, err = capfd.readouterr()
    assert KNOWN_PASSWORD not in out
    assert KNOWN_PASSWORD not in err
    assert KNOWN_PASSWORD not in caplog.text
    assert KNOWN_PASSWORD not in json.dumps([r.getMessage() for r in caplog.records])
    for record in caplog.records:
        assert KNOWN_PASSWORD not in repr(record.__dict__)


@pytest.mark.committed
async def test_bootstrap_rerun_is_idempotent(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """FR-6, AC-23: повтор не создаёт второго ТА, не меняет файл и хеш."""
    _prepare_secrets_dir(settings)
    first = await _bootstrap(committed, settings)
    path = settings.secrets_dir / INITIAL_FILE
    content = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    (row_before,) = await _admin_rows(committed)

    second = await _bootstrap(committed, settings, OTHER_PASSWORD)

    assert second.admin_created is False
    assert second.workspace_id == first.workspace_id
    assert path.read_bytes() == content
    assert path.stat().st_mtime_ns == mtime
    rows = await _admin_rows(committed)
    assert len(rows) == 1
    assert rows[0]["password_hash"] == row_before["password_hash"]
    assert await _scalar(committed, "SELECT count(*) FROM workspace") == 1
    assert await _scalar(committed, "SELECT count(*) FROM domain_event") == 0


@pytest.mark.committed
async def test_bootstrap_with_existing_workspace_does_nothing(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """plan §4.7: если пространство уже есть — ничего не делать (ТА и файл не создаются)."""
    from tests.factories import make_workspace

    async with committed() as session:
        await make_workspace(session)
        await session.commit()
    _prepare_secrets_dir(settings)

    result = await _bootstrap(committed, settings)

    assert result.admin_created is False
    assert await _scalar(committed, "SELECT count(*) FROM workspace") == 1
    assert await _scalar(committed, "SELECT count(*) FROM app_user") == 0
    assert not (settings.secrets_dir / INITIAL_FILE).exists()


@pytest.mark.committed
async def test_bootstrap_concurrent_runs_create_single_admin(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """AC-23, D-29 (pg_advisory_lock): конкурентные запуски → один ТА, один файл, согласованный."""
    from app.domain.system.bootstrap import run_bootstrap

    from app.core.security.passwords import PasswordHasher

    _prepare_secrets_dir(settings)
    passwords = [f"Cc{i}RaceBootstrapPassword{i}" for i in range(4)]
    results = await asyncio.gather(
        *(
            run_bootstrap(committed, settings, clock=FixedClock(FIXED_NOW), generate=lambda p=p: p)
            for p in passwords
        )
    )

    assert sum(1 for r in results if r.admin_created) == 1
    assert len({r.workspace_id for r in results}) == 1
    assert await _scalar(committed, "SELECT count(*) FROM workspace") == 1
    rows = await _admin_rows(committed)
    assert len(rows) == 1
    creds = _parse_credentials(settings.secrets_dir / INITIAL_FILE)
    assert creds["password"] in passwords
    hasher = PasswordHasher(time_cost=1, memory_cost_kib=1024, parallelism=1)
    assert hasher.verify(rows[0]["password_hash"], creds["password"]) is True


# --- remove_initial_admin_file_if_for (plan §4.7, FR-6) -----------------------------------


def _write_initial_file(settings: Settings, login: str) -> Path:
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    path = settings.secrets_dir / INITIAL_FILE
    path.write_text(f"login={login}\npassword={KNOWN_PASSWORD}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_remove_initial_admin_file_for_matching_login(tmp_path: Path) -> None:
    """FR-6: после смены пароля первого ТА файл удаляется."""
    from app.domain.system.bootstrap import remove_initial_admin_file_if_for

    settings = _settings(tmp_path)
    path = _write_initial_file(settings, "admin")
    remove_initial_admin_file_if_for(settings, "admin")
    assert not path.exists()


def test_remove_initial_admin_file_is_idempotent(tmp_path: Path) -> None:
    from app.domain.system.bootstrap import remove_initial_admin_file_if_for

    settings = _settings(tmp_path)
    path = _write_initial_file(settings, "admin")
    remove_initial_admin_file_if_for(settings, "admin")
    remove_initial_admin_file_if_for(settings, "admin")  # файла уже нет: без ошибки
    assert not path.exists()


def test_remove_initial_admin_file_without_secrets_dir_is_noop(tmp_path: Path) -> None:
    from app.domain.system.bootstrap import remove_initial_admin_file_if_for

    settings = _settings(tmp_path)
    remove_initial_admin_file_if_for(settings, "admin")
    assert not (settings.secrets_dir / INITIAL_FILE).exists()


def test_remove_initial_admin_file_keeps_file_for_other_login(tmp_path: Path) -> None:
    """FR-6: пароль другого пользователя файл не удаляет."""
    from app.domain.system.bootstrap import remove_initial_admin_file_if_for

    settings = _settings(tmp_path)
    path = _write_initial_file(settings, "admin")
    remove_initial_admin_file_if_for(settings, "someone-else")
    assert path.is_file()
    assert _parse_credentials(path)["password"] == KNOWN_PASSWORD


@pytest.mark.committed
async def test_remove_file_after_real_bootstrap(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """AC-23: файл, созданный run_bootstrap, удаляется для логина первого ТА, и только для него."""
    from app.domain.system.bootstrap import remove_initial_admin_file_if_for

    _prepare_secrets_dir(settings)
    await _bootstrap(committed, settings)
    path = settings.secrets_dir / INITIAL_FILE
    remove_initial_admin_file_if_for(settings, "nobody")
    assert path.is_file()
    remove_initial_admin_file_if_for(settings, settings.initial_admin_login)
    assert not path.exists()


# --- CLI: main(argv) -> int (D-29) ---------------------------------------------------------


def _run_cli(argv: list[str]) -> int:
    from app.cli.main import main

    try:
        code = main(argv)
    except SystemExit as exc:  # argparse завершает процесс сам
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return int(code)


def test_cli_help_does_not_fail(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run_cli(["--help"]) == 0
    out = capsys.readouterr().out
    assert "bootstrap" in out


def test_cli_bootstrap_help_does_not_fail(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run_cli(["bootstrap", "--help"]) == 0
    assert capsys.readouterr().out.strip()


def test_cli_unknown_subcommand_exit_code_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run_cli(["no-such-command"]) == 2


class _FakeTime:
    """Подмена часов и пауз: ожидание БД «проходит» мгновенно, но учитывается."""

    def __init__(self) -> None:
        self.offset = 0.0
        self.real_start = time.monotonic()
        self._lock = threading.Lock()
        self._real_monotonic = time.monotonic
        self._real_time = time.time

    def _tick(self, delta: float) -> None:
        with self._lock:
            self.offset += delta
        if self._real_monotonic() - self.real_start > 30:
            raise RuntimeError("test guard: ожидание БД идёт в реальном времени")

    def monotonic(self) -> float:
        self._tick(0.25)
        return self._real_monotonic() + self.offset

    def time(self) -> float:
        self._tick(0.25)
        return self._real_time() + self.offset

    def sleep(self, seconds: float) -> None:
        self._tick(max(float(seconds), 0.0))


def test_cli_bootstrap_without_db_fails_within_60s_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: None,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D-29, plan §4.7: БД недоступна → ожидание ≤ 60 с, код ≠ 0, сообщение без секретов."""
    fake = _FakeTime()
    real_async_sleep = asyncio.sleep

    async def fake_async_sleep(delay: float, result: Any = None) -> Any:
        fake._tick(max(float(delay), 0.0))
        await real_async_sleep(0)
        return result

    monkeypatch.setattr(time, "monotonic", fake.monotonic)
    monkeypatch.setattr(time, "time", fake.time)
    monkeypatch.setattr(time, "sleep", fake.sleep)
    monkeypatch.setattr(asyncio, "sleep", fake_async_sleep)

    db_password = "s3cretpw-db-9f3a"
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL", f"postgresql+asyncpg://tracker:{db_password}@127.0.0.1:1/tracker_test"
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALEMBIC_CONFIG", str(ALEMBIC_INI))
    get_settings.cache_clear()
    caplog.set_level(logging.DEBUG)

    code = _run_cli(["bootstrap"])

    assert code != 0
    assert fake.offset <= 75, f"ожидание БД превысило 60 с (учтено {fake.offset:.0f} с)"
    out, err = capfd.readouterr()
    assert (out + err + caplog.text).strip(), "ожидается сообщение об ошибке"
    for stream in (out, err, caplog.text):
        assert db_password not in stream


@pytest.mark.committed
async def test_cli_bootstrap_full_flow_and_rerun(
    committed: async_sessionmaker[AsyncSession],
    cli_env: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """AC-23 (in-process): ключ + файл 0600 + один ТА; stdout — путь, пароля нет; повтор код 0."""
    from app.cli.main import main

    code = await asyncio.to_thread(main, ["bootstrap"])
    assert code == 0

    secrets_dir = cli_env / "secrets"
    key_path = secrets_dir / "secret_key"
    pw_path = secrets_dir / INITIAL_FILE
    assert _mode(secrets_dir) == 0o700
    assert _mode(key_path) == 0o600
    assert _mode(pw_path) == 0o600

    rows = await _admin_rows(committed)
    assert len(rows) == 1
    assert rows[0]["role"] == "tech_admin"
    assert rows[0]["must_change_password"] is True
    assert await _scalar(committed, "SELECT count(*) FROM domain_event") == 0

    creds = _parse_credentials(pw_path)
    out, err = capfd.readouterr()
    assert str(pw_path) in out
    assert creds["password"] not in out
    assert creds["password"] not in err
    key_text = key_path.read_text(encoding="utf-8").strip()
    assert key_text
    assert key_text not in out
    assert key_text not in err

    # повторный запуск (перезапуск контейнера): код 0, ничего не меняется
    key_before = key_path.read_bytes()
    pw_before = pw_path.read_bytes()
    code2 = await asyncio.to_thread(main, ["bootstrap"])
    assert code2 == 0
    assert key_path.read_bytes() == key_before
    assert pw_path.read_bytes() == pw_before
    rows_after = await _admin_rows(committed)
    assert len(rows_after) == 1
    assert rows_after[0]["password_hash"] == rows[0]["password_hash"]
    out2, err2 = capfd.readouterr()
    assert creds["password"] not in out2
    assert creds["password"] not in err2
