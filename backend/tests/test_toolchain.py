"""T01: окружение Python 3.12 и конфигурация инструментов.

Покрывает NFR-10 (часть: линтер/типы/тесты одинаково настроены) и N-6 / OI-69
(эталон Python 3.12). Зависимости: plan §7.1.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[1]
PYPROJECT = BACKEND / "pyproject.toml"


@pytest.fixture(scope="module")
def cfg() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _names(deps: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for d in deps:
        m = re.match(r"^\s*([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(.*)$", d)
        assert m, d
        out[m.group(1).lower().replace("_", "-")] = m.group(2).replace(" ", "")
    return out


def test_n6_oi69_interpreter_is_python_312() -> None:
    """N-6 / OI-69: тесты идут на эталонном Python 3.12 (.venv пересоздан)."""
    assert sys.version_info[:2] == (3, 12), sys.version


def test_n6_oi69_mypy_targets_312(cfg: dict[str, Any]) -> None:
    """OI-69: mypy python_version = "3.12", плагин pydantic.mypy, strict сохранён."""
    mypy = cfg["tool"]["mypy"]
    assert mypy["python_version"] == "3.12"
    assert "pydantic.mypy" in mypy["plugins"]
    assert mypy["strict"] is True


def test_n6_oi69_ruff_and_requires_python_312(cfg: dict[str, Any]) -> None:
    assert cfg["tool"]["ruff"]["target-version"] == "py312"
    assert cfg["project"]["requires-python"].replace(" ", "").startswith(">=3.12")


def test_plan_7_1_argon2_dependency(cfg: dict[str, Any]) -> None:
    """plan §7.1: argon2-cffi>=25.1,<26 в runtime-зависимостях."""
    deps = _names(cfg["project"]["dependencies"])
    assert "argon2-cffi" in deps
    spec = deps["argon2-cffi"]
    assert ">=25.1" in spec and "<26" in spec


def test_plan_7_1_tzdata_dependency(cfg: dict[str, Any]) -> None:
    """plan §7.1: tzdata>=2025.2 в runtime-зависимостях."""
    deps = _names(cfg["project"]["dependencies"])
    assert "tzdata" in deps
    assert ">=2025.2" in deps["tzdata"]


def test_existing_runtime_dependencies_kept(cfg: dict[str, Any]) -> None:
    deps = _names(cfg["project"]["dependencies"])
    for name in ("fastapi", "uvicorn", "sqlalchemy", "alembic", "asyncpg", "pydantic-settings"):
        assert name in deps, name


def test_build_system_setuptools(cfg: dict[str, Any]) -> None:
    requires = " ".join(cfg["build-system"]["requires"]).lower()
    assert "setuptools" in requires
    assert "setuptools" in cfg["build-system"]["build-backend"]


def test_setuptools_packages_and_package_data(cfg: dict[str, Any]) -> None:
    st = cfg["tool"]["setuptools"]
    assert st["packages"]["find"]["include"] == ["app*"]
    data = st["package-data"]
    assert data.get("app.core.security") == ["data/*"], data


def test_entry_point_declared_in_pyproject(cfg: dict[str, Any]) -> None:
    assert cfg["project"]["scripts"]["gostracker"] == "app.cli.main:main"


def test_pytest_ini_options(cfg: dict[str, Any]) -> None:
    ini = cfg["tool"]["pytest"]["ini_options"]
    assert ini["pythonpath"] == ["."]
    assert ini["asyncio_mode"] == "auto"
    assert ini["asyncio_default_fixture_loop_scope"] == "session"
    assert ini["testpaths"] == ["tests"]


def test_pytest_markers_declared_in_config(cfg: dict[str, Any]) -> None:
    markers = cfg["tool"]["pytest"]["ini_options"]["markers"]
    declared = {m.split(":", 1)[0].strip() for m in markers}
    assert {"committed", "infra_static", "infra_stack"} <= declared


def test_pytest_markers_registered_in_session(pytestconfig: pytest.Config) -> None:
    """Маркеры реально зарегистрированы (иначе --strict-markers упадёт)."""
    registered = {
        line.split(":", 1)[0].split("(")[0].strip() for line in pytestconfig.getini("markers")
    }
    assert {"committed", "infra_static", "infra_stack"} <= registered


def test_app_is_regular_package() -> None:
    assert (BACKEND / "app" / "__init__.py").is_file()


def test_package_installed_with_dependencies() -> None:
    """Пакет установлен (pip install -e backend[dev]) вместе с argon2 и tzdata."""
    dist = md.distribution("tracker-backend")
    assert dist.metadata["Name"] == "tracker-backend"
    md.version("argon2-cffi")
    md.version("tzdata")
    import zoneinfo

    import argon2  # noqa: F401

    assert zoneinfo.ZoneInfo("Europe/Moscow").key == "Europe/Moscow"


def test_installed_console_script_gostracker() -> None:
    eps = [e for e in md.entry_points(group="console_scripts") if e.name == "gostracker"]
    assert len(eps) == 1
    assert eps[0].value == "app.cli.main:main"
    assert eps[0].dist is not None and eps[0].dist.metadata["Name"] == "tracker-backend"


def test_app_importable_from_installed_package() -> None:
    """Проверяет только импорт `app` из backend/; факт установки пакета — в другом тесте."""
    import app

    assert Path(app.__file__ or "").resolve().parent == BACKEND / "app"


def test_oi69_nfr10_check_sh_mypy_uses_project_config(tmp_path: Path) -> None:
    """OI-69 / NFR-10: mypy из scripts/check.sh (из корня) применяет конфиг проекта.

    Берём строку `run mypy ...` из check.sh, подменяем цель на временный файл без
    аннотаций и запускаем из корня репозитория. При strict-конфиге ожидаем no-untyped-def.
    """
    root = BACKEND.parent
    lines = (root / "scripts" / "check.sh").read_text(encoding="utf-8").splitlines()
    cmd = next(ln.split() for ln in lines if ln.strip().startswith("run mypy"))
    args = cmd[2:-1]  # без "run", "mypy" и цели (backend/app)
    assert cmd[-1] == "backend/app"
    target = tmp_path / "untyped_sample.py"
    target.write_text("def f(x):\n    return x\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", *args, str(target)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "no-untyped-def" in proc.stdout, proc.stdout + proc.stderr
