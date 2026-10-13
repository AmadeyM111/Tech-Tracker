"""T02: статический разбор compose-файлов (plan D-18, §4.12).

Покрывает AC-105 (статическая часть), FR-6a, AC-95 (для сервиса db).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.infra_static


def parse_env_file(path: Path) -> dict[str, str]:
    """Разбор KEY=VALUE; пустые строки и комментарии пропускаются."""
    assert path.is_file(), f"нет файла {path}"
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _db(cfg: dict[str, Any]) -> dict[str, Any]:
    assert "db" in cfg["services"]
    db = cfg["services"]["db"]
    assert isinstance(db, dict)
    return db


def _env(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment", {})
    if isinstance(env, list):
        return {k: v for k, _, v in (item.partition("=") for item in env)}
    return {k: str(v) for k, v in env.items()}


def test_ac105_db_has_no_ports_in_delivery_compose(compose: dict[str, Any]) -> None:
    """AC-105, FR-6a: у db в поставляемом compose нет ports."""
    assert "ports" not in _db(compose)


def test_ac105_no_override_files_in_repo(repo_files: list[Path]) -> None:
    """AC-105: нет файлов, которые Compose подхватывает автоматически."""
    patterns = ["docker-compose.override.y*ml", "compose.override.y*ml"]
    found = [str(p) for p in repo_files if any(fnmatch.fnmatch(p.name, pat) for pat in patterns)]
    assert found == []


@pytest.mark.parametrize(
    ("var", "default"),
    [("POSTGRES_USER", "tracker"), ("POSTGRES_PASSWORD", "tracker"), ("POSTGRES_DB", "tracker")],
)
def test_fr6a_postgres_env_from_dotenv_with_defaults(
    compose: dict[str, Any], var: str, default: str
) -> None:
    """FR-6a / plan §4.12: POSTGRES_* берутся из окружения с умолчаниями."""
    assert _env(_db(compose)).get(var) == f"${{{var}:-{default}}}"


def test_ac95_db_healthcheck_pg_isready(compose: dict[str, Any]) -> None:
    """plan §4.12: healthcheck db — pg_isready."""
    hc = _db(compose).get("healthcheck")
    assert hc, "у db нет healthcheck"
    test = hc["test"]
    cmd = test if isinstance(test, str) else " ".join(test)
    assert "pg_isready" in cmd


def test_ac95_db_logging_json_file_10m_x5(compose: dict[str, Any]) -> None:
    """AC-95 (для db): драйвер json-file, 10m x 5 файлов."""
    logging_cfg = _db(compose).get("logging")
    assert logging_cfg, "у db нет logging"
    assert logging_cfg["driver"] == "json-file"
    opts = {k: str(v) for k, v in logging_cfg["options"].items()}
    assert opts == {"max-size": "10m", "max-file": "5"}


def test_fr6a_dev_compose_publishes_only_loopback_db_port(
    compose_dev: dict[str, Any],
) -> None:
    """FR-6a, D-18: dev-файл добавляет только db.ports = 127.0.0.1:5432:5432."""
    assert list(compose_dev["services"]) == ["db"]
    assert compose_dev["services"]["db"] == {"ports": ["127.0.0.1:5432:5432"]}
    assert set(compose_dev) <= {"services", "name"}


def test_fr6a_env_example_has_postgres_vars(repo_root: Path) -> None:
    """plan §4.12: .env.example содержит POSTGRES_USER/PASSWORD/DB."""
    env = parse_env_file(repo_root / ".env.example")
    for var in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert env.get(var), f"{var} отсутствует или пуст в .env.example"


def test_fr6a_env_example_has_no_secret_key_or_cookie_secure(repo_root: Path) -> None:
    """plan §4.12: SECRET_KEY и COOKIE_SECURE в .env.example нет (даже в комментариях)."""
    text = (repo_root / ".env.example").read_text(encoding="utf-8")
    assert "SECRET_KEY" not in text
    assert "COOKIE_SECURE" not in text


def test_fr6a_dev_env_example_exists_with_dev_values(repo_root: Path) -> None:
    """plan §4.12: deploy/dev.env.example с настройками локальной разработки."""
    env = parse_env_file(repo_root / "deploy" / "dev.env.example")
    assert env["DATABASE_URL"] == ("postgresql+asyncpg://tracker:tracker@localhost:5432/tracker")
    assert env["COOKIE_SECURE"] == "false"
    assert env["ENV"] == "local"
    assert env["EXPOSE_API_DOCS"] == "true"
    assert env["DATA_DIR"] == "./.data"
