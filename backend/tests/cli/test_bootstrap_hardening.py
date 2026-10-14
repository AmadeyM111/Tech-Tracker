"""T26: переносы из ревью T10/T20 в бэкенд первого запуска (plan §4.7, FR-6, D-19, D-29).

Пункты (нумерация из tasks.md T26, «Перенесено из ревью T10/T20»):
- (2) ошибка COMMIT после фактической фиксации не удаляет файл пароля - проверка отдельной сессией;
- (4) остатки ``.<name>.*.tmp`` удаляются под блокировкой; ``ensure_private_dir``: lstat/S_ISDIR,
  0755 -> 0700;
- (5) advisory lock на AUTOCOMMIT-соединении (не «idle in transaction»), ``_known_secrets`` из
  ``settings``, ``path_separator = os`` в alembic.ini, ``run_bootstrap(locked=<токен>)``.

Допущения о контракте, которых нет в plan.md (исполнитель обязан их выполнить или вернуть
вопрос): параметр ``run_bootstrap`` по-прежнему называется ``locked``, но принимает токен,
который отдаёт ``bootstrap_lock`` (``async with bootstrap_lock(sm) as token``); голый ``True``
отвергается ``TypeError``/``ValueError``.
"""

from __future__ import annotations

import asyncio
import configparser
import contextlib
import os
import stat
import subprocess
import sys
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.core.config import Settings
from tests.conftest import CHEAP_ARGON2, FIXED_NOW
from tests.db_support import ALEMBIC_INI, BACKEND_DIR

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

INITIAL_FILE = "initial-admin-password.txt"
PASSWORD = "Qw8Lm3Vx7HardeningPw"


def _prepare_secrets_dir(settings: Settings) -> None:
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    settings.secrets_dir.chmod(0o700)


async def _scalar(sm: async_sessionmaker[AsyncSession], sql: str) -> Any:
    async with sm() as session:
        return (await session.execute(text(sql))).scalar()


async def _run(sm: async_sessionmaker[AsyncSession], settings: Settings, **kw: Any) -> Any:
    from app.domain.system.bootstrap import run_bootstrap

    return await run_bootstrap(
        sm, settings, clock=FixedClock(FIXED_NOW), generate=lambda: PASSWORD, **kw
    )


@contextlib.contextmanager
def _commit_hook(name: str) -> Iterator[list[int]]:
    """Один раз бросает исключение в событии сессии (``before_commit``/``after_commit``)."""
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


# --- (2) ошибка COMMIT -----------------------------------------------------------------------


@pytest.mark.committed
async def test_t10_p2_commit_acknowledgement_lost_keeps_password_file(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """(2): COMMIT дошёл до БД, но вызов упал (сеть оборвалась после фиксации). Пространство
    зафиксировано, пароль в БД действует - файл удалять нельзя, иначе пароль потерян."""
    from app.core.security.passwords import PasswordHasher

    _prepare_secrets_dir(settings)
    # вернуть результат или бросить исключение - оба исхода допустимы
    with _commit_hook("after_commit") as fired, contextlib.suppress(Exception):
        await _run(committed, settings)
    assert fired, "хук фиксации не сработал: тест не проверяет сценарий"

    assert await _scalar(committed, "SELECT count(*) FROM workspace") == 1
    path = settings.secrets_dir / INITIAL_FILE
    assert path.is_file(), "файл пароля удалён, хотя пространство и ТА зафиксированы"
    password = path.read_text(encoding="utf-8").split("password=", 1)[1].strip()
    stored = await _scalar(committed, "SELECT password_hash FROM app_user")
    hasher = PasswordHasher(time_cost=1, memory_cost_kib=1024, parallelism=1)
    assert hasher.verify(stored, password) is True


@pytest.mark.committed
async def test_t10_p2_commit_failure_before_commit_removes_file_and_leaves_nothing(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """(2): COMMIT реально не состоялся - файла нет, пространства и ТА нет, повтор создаёт."""
    _prepare_secrets_dir(settings)
    with _commit_hook("before_commit") as fired, pytest.raises(Exception):  # noqa: B017, PT011
        await _run(committed, settings)
    assert fired
    assert not (settings.secrets_dir / INITIAL_FILE).exists()
    assert await _scalar(committed, "SELECT count(*) FROM workspace") == 0
    assert await _scalar(committed, "SELECT count(*) FROM app_user") == 0

    result = await _run(committed, settings)
    assert result.admin_created is True
    assert (settings.secrets_dir / INITIAL_FILE).is_file()


# --- (4) остатки временных файлов, каталог секретов ------------------------------------------


@pytest.mark.committed
async def test_t10_p4_stale_tmp_files_of_password_file_are_removed_under_lock(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """(4): остатки ``.initial-admin-password.txt.<hex>.tmp`` (с паролем!) от упавшего запуска
    удаляются при первом запуске; посторонние файлы не трогаются."""
    _prepare_secrets_dir(settings)
    stale = [
        settings.secrets_dir / f".{INITIAL_FILE}.{suffix}.tmp"
        for suffix in ("0123456789abcdef", "fedcba9876543210")
    ]
    for p in stale:
        p.write_text("login=admin\npassword=StalePasswordLeftover1\n", encoding="utf-8")
        p.chmod(0o600)
    foreign = settings.secrets_dir / "operator-notes.tmp"
    foreign.write_text("keep me", encoding="utf-8")

    result = await _run(committed, settings)

    assert result.admin_created is True
    assert [p.name for p in stale if p.exists()] == []
    assert foreign.read_text(encoding="utf-8") == "keep me"
    assert (settings.secrets_dir / INITIAL_FILE).is_file()


def test_t10_p4_ensure_private_dir_tightens_existing_0755_to_0700(tmp_path: Path) -> None:
    """(4): существующий каталог секретов с правами 0755 приводится к 0700."""
    from app.core.secrets import ensure_private_dir

    target = tmp_path / "secrets"
    target.mkdir()
    target.chmod(0o755)
    ensure_private_dir(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_t10_p4_ensure_private_dir_rejects_symlink_to_directory(tmp_path: Path) -> None:
    """(4): проверка через lstat/S_ISDIR - символьная ссылка на каталог не принимается
    (иначе секреты уедут по ссылке в чужой каталог); цель не меняется."""
    from app.core.secrets import ensure_private_dir

    real = tmp_path / "elsewhere"
    real.mkdir()
    real.chmod(0o755)
    link = tmp_path / "secrets"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        ensure_private_dir(link)
    assert stat.S_IMODE(real.stat().st_mode) == 0o755
    assert link.is_symlink()


def test_t10_p4_ensure_private_dir_rejects_regular_file(tmp_path: Path) -> None:
    from app.core.secrets import ensure_private_dir

    target = tmp_path / "secrets"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        ensure_private_dir(target)


def test_t10_p4_ensure_private_dir_creates_0700_even_with_umask_zero(tmp_path: Path) -> None:
    from app.core.secrets import ensure_private_dir

    old = os.umask(0)
    try:
        ensure_private_dir(tmp_path / "a" / "secrets")
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "a" / "secrets").stat().st_mode) == 0o700


# --- (5) advisory lock, токен, секреты, alembic ---------------------------------------------


@pytest.mark.committed
async def test_t10_p5_advisory_lock_connection_is_not_idle_in_transaction(
    committed: async_sessionmaker[AsyncSession],
) -> None:
    """(5): блокировка держится на AUTOCOMMIT-соединении: открытая транзакция на всё время
    миграций попала бы под idle_in_transaction_session_timeout (заметка T16)."""
    from app.domain.system.bootstrap import bootstrap_lock

    async with bootstrap_lock(committed):
        await asyncio.sleep(0.2)
        states = [
            r[0]
            for r in await _all_rows(
                committed,
                "SELECT a.state FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                "WHERE l.locktype = 'advisory' AND l.granted AND l.pid <> pg_backend_pid()",
            )
        ]
    assert states, "advisory-блокировка не видна в pg_locks"
    assert set(states) == {"idle"}, f"соединение блокировки: {states}"


async def _all_rows(sm: async_sessionmaker[AsyncSession], sql: str) -> list[Any]:
    async with sm() as session:
        return list((await session.execute(text(sql))).all())


@pytest.mark.committed
async def test_t10_p5_bootstrap_lock_yields_token_accepted_by_run_bootstrap(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """(5): ``bootstrap_lock`` отдаёт токен; ``run_bootstrap(locked=token)`` не берёт блокировку
    повторно (иначе взаимная блокировка) и создаёт ТА."""
    from app.domain.system.bootstrap import bootstrap_lock

    _prepare_secrets_dir(settings)
    async with bootstrap_lock(committed) as token:
        assert token is not None and token is not True and token is not False
        result = await asyncio.wait_for(_run(committed, settings, locked=token), timeout=30)
    assert result.admin_created is True


@pytest.mark.committed
async def test_t10_p5_run_bootstrap_rejects_plain_bool_locked(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """(5): голый ``locked=True`` не принимается: «я держу блокировку» можно доказать только
    токеном от ``bootstrap_lock``."""
    _prepare_secrets_dir(settings)
    with pytest.raises((TypeError, ValueError)):
        await asyncio.wait_for(_run(committed, settings, locked=True), timeout=30)
    assert await _scalar(committed, "SELECT count(*) FROM workspace") == 0


@pytest.mark.committed
async def test_t10_p5_run_bootstrap_without_token_takes_lock_itself(
    committed: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """(5): без токена ``run_bootstrap`` по-прежнему берёт блокировку сам."""
    _prepare_secrets_dir(settings)
    result = await asyncio.wait_for(_run(committed, settings), timeout=30)
    assert result.admin_created is True


def test_t10_p5_known_secrets_come_from_settings_not_only_environ(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """(5): значения секретов для маскирования берутся из ``settings`` (ключ и пароль из DSN),
    а не только из os.environ: настройки могли прийти не из окружения процесса."""
    from app.cli.commands import bootstrap as cmd

    key = "k" * 8 + "SettingsOnlySecretKeyValue0123456789"
    db_password = "Db9xQ7SettingsOnlyPw"
    for name in ("SECRET_KEY", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(
        env="test",
        data_dir=tmp_path,
        database_url=f"postgresql+asyncpg://tracker:{db_password}@db:5432/tracker",
        secret_key=SecretStr(key),
        cookie_secure=False,
        **CHEAP_ARGON2,
    )

    async def no_wait(*_a: Any, **_k: Any) -> None:
        return None

    def explode(_settings: Settings) -> bytes:
        raise RuntimeError(f"cannot start with key {key} and password {db_password}")

    monkeypatch.setattr(cmd, "get_settings", lambda: settings)
    monkeypatch.setattr(cmd, "wait_for_database", no_wait)
    monkeypatch.setattr(cmd, "ensure_secret_key", explode)

    code = cmd.run(Namespace())

    captured = capsys.readouterr()
    assert code != 0
    assert key not in captured.err + captured.out
    assert db_password not in captured.err + captured.out
    assert "RuntimeError" in captured.err, "диагностика должна остаться"


def test_t10_p5_alembic_ini_declares_path_separator_os() -> None:
    """(5): ``path_separator = os`` в alembic.ini (иначе DeprecationWarning при каждом запуске)."""
    parser = configparser.RawConfigParser()
    parser.read(ALEMBIC_INI, encoding="utf-8")
    assert parser.get("alembic", "path_separator", fallback=None) == "os"


def test_t10_p5_alembic_config_loads_without_path_separator_warning() -> None:
    """(5): загрузка конфигурации alembic не даёт предупреждения (в логах контейнера нет шума);
    БД не нужна: ``alembic heads`` читает только каталог миграций."""
    code = (
        "import warnings; warnings.simplefilter('always');"
        "from alembic import command; from alembic.config import Config;"
        f"command.heads(Config({str(ALEMBIC_INI)!r}))"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert res.returncode == 0, res.stderr[-800:]
    assert "path_separator" not in res.stderr + res.stdout
