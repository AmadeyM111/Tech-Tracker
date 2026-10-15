"""Вспомогательные функции тестовой БД (T05, plan §5).

Модуль не импортирует ``sqlalchemy.ext.asyncio`` на уровне модуля: тесты без БД не должны
зависеть от наличия драйверов и greenlet.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test"
TEST_DB_SUFFIX = "_test"


class UnsafeTestDatabaseError(RuntimeError):
    """Имя БД не оканчивается на ``_test``: тесты отказываются с ней работать."""


def assert_test_database_url(url: str | URL) -> URL:
    """Возвращает разобранный URL или бросает ``UnsafeTestDatabaseError``."""
    parsed = make_url(url) if isinstance(url, str) else url
    name = parsed.database
    if "database" in parsed.query:
        # диалект берёт database из query и подменяет имя из пути (обход проверки)
        raise UnsafeTestDatabaseError("В query-параметрах URL тестовой БД нельзя задавать database")
    if not name or not name.endswith(TEST_DB_SUFFIX):
        raise UnsafeTestDatabaseError(
            f"Тесты работают только с БД, имя которой оканчивается на {TEST_DB_SUFFIX!r}; "
            f"получено: {name!r}"
        )
    return parsed


def database_url_from_env() -> str:
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    assert_test_database_url(url)
    return url


def run_alembic(url: str, *args: str, x_dburl: bool = True) -> subprocess.CompletedProcess[str]:
    """Запускает ``alembic -c backend/alembic.ini [-x dburl=<url>] <args>`` в подпроцессе.

    ``DATABASE_URL`` в окружении подпроцесса всегда равен ``url`` (источник — ``Settings``).
    """
    env = {**os.environ, "DATABASE_URL": url, "ENV": "test"}
    x_args = ["-x", f"dburl={url}"] if x_dburl else []
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *x_args, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
