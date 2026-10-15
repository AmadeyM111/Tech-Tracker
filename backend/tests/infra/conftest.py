"""Фикстуры статических проверок инфраструктуры (маркер infra_static).

Compose-файлы разбираются как YAML, Docker не запускается.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Все тесты каталога infra/ получают маркер infra_static."""
    for item in items:
        if "tests/infra/" in item.nodeid.replace("\\", "/") and not any(
            m.name in ("infra_static", "infra_stack") for m in item.iter_markers()
        ):
            item.add_marker(pytest.mark.infra_static)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


def _load(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"нет файла {path.relative_to(REPO_ROOT)}"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="session")
def compose(repo_root: Path) -> dict[str, Any]:
    return _load(repo_root / "docker-compose.yml")


@pytest.fixture(scope="session")
def compose_dev(repo_root: Path) -> dict[str, Any]:
    return _load(repo_root / "deploy" / "compose.dev.yml")


@pytest.fixture(scope="session")
def repo_files(repo_root: Path) -> list[Path]:
    """Все файлы репозитория (без служебных каталогов и зависимостей)."""
    out: list[Path] = []
    stack = [repo_root]
    while stack:
        d = stack.pop()
        for p in d.iterdir():
            if p.is_dir():
                if p.name not in EXCLUDED_DIRS:
                    stack.append(p)
            else:
                out.append(p)
    return out
