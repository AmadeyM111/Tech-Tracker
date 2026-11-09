"""D10-T01/T02: пароль рабочей роли, SCRAM, DSN API (spec 010 FR-4, FR-7; AC-6, AC-7)."""

from __future__ import annotations

import base64
import stat
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.db_roles import (
    AppRoleError,
    app_database_url,
    check_role_name,
    ensure_app_password,
    scram_verifier,
)


def _settings(tmp_path: Path, **kw: object) -> Settings:
    return Settings(
        env=kw.pop("env", "test"),  # type: ignore[arg-type]
        database_url="postgresql+asyncpg://owner:ownerpw@db:5432/tracker",
        data_dir=tmp_path / "data",
        **kw,  # type: ignore[arg-type]
    )


def test_010_scram_format_and_determinism() -> None:
    v1 = scram_verifier("pw", salt=b"\x01" * 16)
    v2 = scram_verifier("pw", salt=b"\x01" * 16)
    assert v1 == v2
    head, keys = v1.split("$", 1)[1].split("$")
    iterations, salt = head.split(":")
    stored, server = keys.split(":")
    assert v1.startswith("SCRAM-SHA-256$4096:")
    assert iterations == "4096" and base64.b64decode(salt) == b"\x01" * 16
    assert len(base64.b64decode(stored)) == 32 and len(base64.b64decode(server)) == 32
    assert "pw" not in v1
    assert scram_verifier("pw") != scram_verifier("pw"), "соль случайная"


def test_010_ac6_password_file_created_once_0600(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = ensure_app_password(settings)
    path = settings.secrets_dir / "db_app_password"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(first) >= 32
    assert ensure_app_password(settings) == first


@pytest.mark.parametrize("name", ["Gtrack", "1app", "app-role", "a;drop", "x" * 64, ""])
def test_010_role_name_is_validated(name: str) -> None:
    with pytest.raises(AppRoleError):
        check_role_name(name)


def test_010_app_url_uses_role_and_file_password(tmp_path: Path) -> None:
    settings = _settings(tmp_path, db_app_role="gtrack_app")
    password = ensure_app_password(settings)
    url = app_database_url(settings)
    assert url == f"postgresql+asyncpg://gtrack_app:{password}@db:5432/tracker"


def test_010_app_url_without_password_file_fails_with_hint(tmp_path: Path) -> None:
    settings = _settings(tmp_path, db_app_role="gtrack_app")
    with pytest.raises(AppRoleError, match="gtrack bootstrap"):
        app_database_url(settings)


def test_010_ac7_production_requires_app_role(tmp_path: Path) -> None:
    with pytest.raises(AppRoleError, match="DB_APP_ROLE"):
        app_database_url(_settings(tmp_path, env="production"))
    assert (
        app_database_url(_settings(tmp_path))
        == "postgresql+asyncpg://owner:ownerpw@db:5432/tracker"
    )


def test_010_backup_run_is_read_only_for_app_role() -> None:
    """API только читает статус копий; пишет CLI оператора (ревью 010, п. 5)."""
    from app.core.db_roles import READ_ONLY

    assert "backup_run" in READ_ONLY


def test_010_compose_allows_explicit_empty_role() -> None:
    """``${DB_APP_ROLE-…}``: пустое значение достижимо (FR-7), а не подменяется умолчанием."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${DB_APP_ROLE-gtrack_app}" in text
