"""B09-T02/T03: снятие, проверка, ротация и отказы восстановления без БД (подменный runner).

AC-1…AC-4, AC-6, AC-10, AC-13 на уровне модуля; с настоящим ``pg_dump`` — ``tests/domain``.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.ops.backup import (
    BackupError,
    RestoreRefused,
    backup_name,
    create_backup,
    libpq_env,
    restore_backup,
    rotate,
    verify_backup,
)
from tests.backup_support import FakeRunner

NOW = datetime(2026, 11, 9, 23, 30, 0, tzinfo=UTC)
PASSWORD = "s3cr3t-db-pass"


@pytest.fixture
def env(tmp_path: Path) -> Settings:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("pg_dump", "pg_restore"):
        (bin_dir / name).write_text("#!/bin/sh\n")
    data = tmp_path / "data"
    (data / "secrets").mkdir(parents=True)
    (data / "secrets" / "secret_key").write_bytes(b"k" * 32)
    (data / "exports").mkdir()
    (data / "exports" / "old.tar").write_bytes(b"x")
    return Settings(
        env="test",
        database_url=f"postgresql+asyncpg://tracker:{PASSWORD}@db.local:5433/tracker_test",
        data_dir=data,
        pg_bin_dir=bin_dir,
    )


def _backup(settings: Settings, out: Path, runner: FakeRunner, *, now: datetime = NOW) -> Path:
    return create_backup(
        settings, out, schema_revision="0011", app_version="0.0.1", now=now, keep=14, runner=runner
    ).path


def test_009_ac1_archive_has_three_members_mode_0600_and_valid_manifest(
    env: Settings, tmp_path: Path
) -> None:
    out = tmp_path / "backups"
    path = _backup(env, out, FakeRunner())
    assert path.name == "gtrack-backup-20261109T233000Z.tar"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert sorted(p.name for p in out.iterdir()) == [path.name], "временных файлов не осталось"
    with tarfile.open(path) as tar:
        assert tar.getnames() == ["manifest.json", "db.dump", "appdata.tar"]
        manifest = json.loads(tar.extractfile("manifest.json").read())  # type: ignore[union-attr]
    assert manifest["format"] == "gtrack-backup"
    assert manifest["schema_revision"] == "0011"
    assert manifest["created_at"] == "2026-11-09T23:30:00.000000Z"
    check = tmp_path / "check"
    check.mkdir()
    assert verify_backup(env, path, extract_to=check, runner=FakeRunner()).schema_revision == "0011"


def test_009_ac2_exports_and_symlinks_are_not_in_appdata(env: Settings, tmp_path: Path) -> None:
    os.symlink("/etc/passwd", env.data_dir / "link")
    path = _backup(env, tmp_path / "b", FakeRunner())
    with tarfile.open(path) as tar:
        raw = tar.extractfile("appdata.tar").read()  # type: ignore[union-attr]
    with tarfile.open(fileobj=io.BytesIO(raw)) as inner:
        names = {Path(n).as_posix() for n in inner.getnames()}
    assert "secrets/secret_key" in {n.removeprefix("./") for n in names}
    assert not any("exports" in n for n in names)
    assert not any(n.endswith("link") for n in names)


@pytest.mark.parametrize(
    ("fail", "code"), [("pg_dump", "pg_dump_failed"), ("pg_restore", "verify_failed")]
)
def test_009_ac3_tool_failure_leaves_no_files(
    env: Settings, tmp_path: Path, fail: str, code: str
) -> None:
    out = tmp_path / "b"
    with pytest.raises(BackupError) as err:
        _backup(env, out, FakeRunner(fail=fail))
    assert err.value.code == code
    assert list(out.iterdir()) == []


def test_009_ac3_empty_dump_fails(env: Settings, tmp_path: Path) -> None:
    out = tmp_path / "b"
    with pytest.raises(BackupError) as err:
        _backup(env, out, FakeRunner(dump=b""))
    assert err.value.code == "pg_dump_failed"
    assert list(out.iterdir()) == []


def _seed_copies(out: Path, count: int) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    names = [backup_name(NOW - timedelta(days=d)) for d in range(count, 0, -1)]
    for name in names:
        (out / name).write_bytes(b"old")
    (out / "notes.txt").write_text("чужой файл")
    (out / "gtrack-backup-latest.tar").write_bytes(b"not a copy")
    return names


def test_009_ac4_rotation_keeps_newest_and_foreign_files(env: Settings, tmp_path: Path) -> None:
    out = tmp_path / "b"
    old = _seed_copies(out, 15)
    new = _backup(env, out, FakeRunner())
    copies = sorted(p.name for p in out.iterdir() if p.name.startswith("gtrack-backup-2"))
    assert len(copies) == 14
    assert copies[-1] == new.name
    assert copies[0] == old[2], "удалены две самые старые"
    assert (out / "notes.txt").exists()
    assert (out / "gtrack-backup-latest.tar").exists()


def test_009_ac4_failed_backup_removes_nothing(env: Settings, tmp_path: Path) -> None:
    out = tmp_path / "b"
    _seed_copies(out, 15)
    before = sorted(p.name for p in out.iterdir())
    with pytest.raises(BackupError):
        _backup(env, out, FakeRunner(fail="pg_dump"))
    assert sorted(p.name for p in out.iterdir()) == before


def test_009_rotate_rejects_zero(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="keep"):
        rotate(tmp_path, 0)


def test_009_ac6_same_device_is_reported(env: Settings, tmp_path: Path) -> None:
    result = create_backup(
        env,
        tmp_path / "b",
        schema_revision="0011",
        app_version="x",
        now=NOW,
        keep=14,
        runner=FakeRunner(),
    )
    assert result.same_device is True


def test_009_existing_target_is_refused(env: Settings, tmp_path: Path) -> None:
    out = tmp_path / "b"
    _backup(env, out, FakeRunner())
    with pytest.raises(BackupError) as err:
        _backup(env, out, FakeRunner())
    assert err.value.code == "exists"


def test_009_ac13_password_only_in_pgpassword_env(env: Settings, tmp_path: Path) -> None:
    runner = FakeRunner()
    _backup(env, tmp_path / "b", runner)
    assert runner.calls, "инструменты вызывались"
    for argv, call_env in runner.calls:
        assert all(PASSWORD not in a for a in argv)
        assert all(PASSWORD not in v for k, v in call_env.items() if k != "PGPASSWORD")
    dump_env = runner.calls[0][1]
    assert dump_env["PGPASSWORD"] == PASSWORD
    assert dump_env["PGHOST"] == "db.local" and dump_env["PGPORT"] == "5433"
    assert all("PGPASSWORD" not in e for _, e in runner.calls[1:]), "pg_restore --list без пароля"


def test_009_libpq_env_without_password() -> None:
    env = libpq_env("postgresql+asyncpg://u@h/d_test")
    assert env == {
        "PGHOST": "h",
        "PGPORT": "5432",
        "PGDATABASE": "d_test",
        "PGCONNECT_TIMEOUT": "10",
        "PGUSER": "u",
    }


def _tamper(path: Path, member: str, payload: bytes) -> Path:
    with tarfile.open(path) as tar:
        items = [(m, tar.extractfile(m).read()) for m in tar.getmembers()]  # type: ignore[union-attr]
    bad = path.with_name("tampered.tar")
    with tarfile.open(bad, "w") as tar:
        for m, data in items:
            if m.name == member:
                data = payload
                m.size = len(data)
            tar.addfile(m, io.BytesIO(data))
    return bad


def test_009_ac10_checksum_mismatch_is_detected(env: Settings, tmp_path: Path) -> None:
    path = _backup(env, tmp_path / "b", FakeRunner())
    bad = _tamper(path, "db.dump", b"PGDMP other")
    check = tmp_path / "check"
    check.mkdir()
    with pytest.raises(BackupError, match="контрольная сумма"):
        verify_backup(env, bad, extract_to=check, runner=FakeRunner())


def test_009_unsafe_appdata_member_is_rejected(env: Settings, tmp_path: Path) -> None:
    path = _backup(env, tmp_path / "b", FakeRunner())
    evil = io.BytesIO()
    with tarfile.open(fileobj=evil, mode="w") as inner:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        inner.addfile(info, io.BytesIO(b"x"))
    bad = _tamper(path, "appdata.tar", evil.getvalue())
    # манифест не совпадёт раньше: пересобираем манифест под новый член
    with tarfile.open(bad) as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read())  # type: ignore[union-attr]
    manifest["members"]["appdata.tar"] = {
        "size": len(evil.getvalue()),
        "sha256": hashlib.sha256(evil.getvalue()).hexdigest(),
    }
    bad2 = _tamper(bad, "manifest.json", json.dumps(manifest).encode())
    check = tmp_path / "check"
    check.mkdir()
    with pytest.raises(BackupError, match="недопустимый"):
        verify_backup(env, bad2, extract_to=check, runner=FakeRunner())


def test_009_ac10_restore_refuses_non_empty_targets(env: Settings, tmp_path: Path) -> None:
    path = _backup(env, tmp_path / "b", FakeRunner())
    runner = FakeRunner()
    with pytest.raises(RestoreRefused, match="БД не пуста"):
        restore_backup(env, path, db_tables=["app_user"], runner=runner)
    with pytest.raises(RestoreRefused, match="каталог данных"):
        restore_backup(env, path, db_tables=[], runner=runner)  # data_dir уже содержит файлы
    assert not any(Path(a[0]).name == "pg_restore" and "--dbname" in a for a, _ in runner.calls)


def test_009_restore_into_empty_data_dir_extracts_files(env: Settings, tmp_path: Path) -> None:
    path = _backup(env, tmp_path / "b", FakeRunner())
    target = env.model_copy(update={"data_dir": tmp_path / "fresh"})
    runner = FakeRunner()
    restore_backup(target, path, db_tables=[], runner=runner)
    assert (tmp_path / "fresh" / "secrets" / "secret_key").read_bytes() == b"k" * 32
    assert not (tmp_path / "fresh" / "exports").exists()
    restore_argv = [a for a, _ in runner.calls if "--dbname" in a]
    assert restore_argv and restore_argv[0][-1] == "tracker_test"
