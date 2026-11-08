"""Помощники тестов 009: поиск клиента PostgreSQL 16 и подменный ``Runner``."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO

import pytest

from app.core.config import Settings
from app.domain.ops.backup import BackupError


def pg_bin_dir() -> Path | None:
    """Каталог ``pg_dump`` 16: ``PG_BIN_DIR``, затем PATH, затем Homebrew ``postgresql@16``."""
    candidates = [os.environ.get("PG_BIN_DIR")]
    found = shutil.which("pg_dump")
    candidates.append(str(Path(found).parent) if found else None)
    candidates.append("/opt/homebrew/opt/postgresql@16/bin")
    for raw in candidates:
        if not raw:
            continue
        pg_dump = Path(raw) / "pg_dump"
        if not pg_dump.is_file():
            continue
        version = subprocess.run(  # noqa: S603
            [str(pg_dump), "--version"], capture_output=True, text=True, check=False
        ).stdout
        if " 16." in version:
            return Path(raw)
    return None


requires_pg16 = pytest.mark.skipif(
    pg_bin_dir() is None, reason="нет клиента PostgreSQL 16 (pg_dump); задайте PG_BIN_DIR"
)


def with_pg(settings: Settings, **overrides: object) -> Settings:
    return settings.model_copy(update={"pg_bin_dir": pg_bin_dir(), **overrides})


class FakeRunner:
    """Пишет фиктивный дамп для ``pg_dump``, принимает ``pg_restore``; запоминает вызовы."""

    def __init__(self, *, fail: str | None = None, dump: bytes = b"PGDMP fake") -> None:
        self.fail = fail
        self.dump = dump
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(
        self,
        argv: Sequence[str],
        env: Mapping[str, str],
        stdin: IO[bytes] | None,
        stdout: IO[bytes] | None,
    ) -> None:
        name = Path(argv[0]).name
        self.calls.append((list(argv), dict(env)))
        if self.fail == name:
            raise BackupError(f"{name}_failed", f"{name}: код 1")
        if name == "pg_dump" and stdout is not None:
            stdout.write(self.dump)
        if stdin is not None:
            stdin.read()
