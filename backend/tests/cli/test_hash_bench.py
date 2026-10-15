"""T19: ``gostracker hash-bench [--iterations N]`` (plan §4.13; AC-38 инструмент замера, FR-52).

Формат вывода plan не фиксирует; тесты закрепляют JSON-объект в stdout с ключами
``p50_ms``, ``p95_ms``, ``iterations``, ``time_cost``, ``memory_cost_kib``, ``parallelism``.
"""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path
from typing import Any

import pytest

from app.core.config import get_settings

BAD_DSN = "postgresql+asyncpg://nobody:Zz9-bench-dsn-pw@127.0.0.1:1/tracker_none"


@pytest.fixture
def bench_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", BAD_DSN)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ARGON2_TIME_COST", "2")
    monkeypatch.setenv("ARGON2_MEMORY_COST_KIB", "2048")
    monkeypatch.setenv("ARGON2_PARALLELISM", "1")
    get_settings.cache_clear()

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("hash-bench не должен обращаться к сети/БД")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def hashed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Пароли, которые попали в ``PasswordHasher.hash`` (для проверки «не печатается»)."""
    from app.core.security.passwords import PasswordHasher

    seen: list[str] = []
    original = PasswordHasher.hash

    def spy(self: PasswordHasher, password: str) -> str:
        seen.append(password)
        return original(self, password)

    monkeypatch.setattr(PasswordHasher, "hash", spy)
    return seen


def _run(argv: list[str]) -> int:
    from app.cli.main import main

    try:
        return int(main(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)


def test_ac38_hash_bench_reports_p50_p95_and_params(
    bench_env: Path, hashed: list[str], capfd: pytest.CaptureFixture[str]
) -> None:
    """AC-38: код 0; JSON с p50/p95 (мс), iterations и параметрами Argon2 из окружения."""
    assert _run(["hash-bench", "--iterations", "3"]) == 0
    out = capfd.readouterr().out
    data = json.loads(out)
    assert data["iterations"] == 3
    assert data["time_cost"] == 2
    assert data["memory_cost_kib"] == 2048
    assert data["parallelism"] == 1
    p50, p95 = data["p50_ms"], data["p95_ms"]
    assert isinstance(p50, (int, float)) and isinstance(p95, (int, float))
    assert 0 < p50 <= p95
    assert p95 < 60_000
    assert len(hashed) >= 3


def test_ac38_hash_bench_default_iterations_at_least_20(
    bench_env: Path, hashed: list[str], capfd: pytest.CaptureFixture[str]
) -> None:
    """plan §4.13: по умолчанию 20 итераций."""
    assert _run(["hash-bench"]) == 0
    data = json.loads(capfd.readouterr().out)
    assert data["iterations"] >= 20
    assert len(hashed) >= data["iterations"]


def test_ac38_hash_bench_takes_params_from_settings(
    bench_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setenv("ARGON2_MEMORY_COST_KIB", "1024")
    monkeypatch.setenv("ARGON2_PARALLELISM", "2")
    get_settings.cache_clear()
    assert _run(["hash-bench", "--iterations", "2"]) == 0
    data = json.loads(capfd.readouterr().out)
    assert (data["time_cost"], data["memory_cost_kib"], data["parallelism"]) == (1, 1024, 2)


def test_fr57_hash_bench_never_prints_password(
    bench_env: Path,
    hashed: list[str],
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Пароль (и хеши, и DSN) не попадают в stdout/stderr/логи."""
    caplog.set_level(logging.DEBUG)
    assert _run(["hash-bench", "--iterations", "2"]) == 0
    out, err = capfd.readouterr()
    assert hashed
    for stream in (out, err, caplog.text):
        for password in set(hashed):
            assert password not in stream
        assert "$argon2" not in stream
        assert "Zz9-bench-dsn-pw" not in stream


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_ac38_hash_bench_invalid_iterations_exit_2(
    bench_env: Path, capfd: pytest.CaptureFixture[str], value: str
) -> None:
    assert _run(["hash-bench", "--iterations", value]) == 2
    captured = capfd.readouterr()
    assert captured.out.strip() == ""
    assert "invalid choice" not in captured.err, "подкоманда hash-bench должна существовать"
    assert "iterations" in captured.err


def test_ac38_hash_bench_no_side_files_and_no_db(
    bench_env: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """Без БД (DSN битый, сеть запрещена) и без побочных файлов (ключ, data_dir, cwd)."""
    before = sorted(p.name for p in bench_env.iterdir())
    assert _run(["hash-bench", "--iterations", "2"]) == 0
    capfd.readouterr()
    assert sorted(p.name for p in bench_env.iterdir()) == before
    assert not (bench_env / "data").exists()


def test_ac38_hash_bench_output_structure_deterministic(
    bench_env: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """Набор ключей и порядок вывода одинаковы между запусками (значения времени — нет)."""
    assert _run(["hash-bench", "--iterations", "2"]) == 0
    first = json.loads(capfd.readouterr().out)
    assert _run(["hash-bench", "--iterations", "2"]) == 0
    second = json.loads(capfd.readouterr().out)
    assert list(first) == list(second)
    for key in ("iterations", "time_cost", "memory_cost_kib", "parallelism"):
        assert first[key] == second[key]
