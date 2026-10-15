"""T32a: allowlist зависимостей (добавление - только по plan.md, с правкой списков здесь)."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

BACKEND_RUNTIME = {
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "asyncpg",
    "pydantic-settings",
    "argon2-cffi",
    "tzdata",
    "greenlet",
}
BACKEND_DEV = {
    "pytest",
    "pytest-asyncio",
    "httpx",
    "ruff",
    "mypy",
    "pyyaml",
    "types-pyyaml",
}
FRONTEND_RUNTIME = {
    "@tanstack/react-query",
    "openapi-fetch",
    "react",
    "react-dom",
    "react-router-dom",
}
FRONTEND_DEV = {
    "@testing-library/dom",
    "@testing-library/react",
    "@types/node",
    "@types/react",
    "@types/react-dom",
    "@vitejs/plugin-react",
    "eslint",
    "eslint-plugin-react-hooks",
    "jsdom",
    "openapi-typescript",
    "typescript",
    "typescript-eslint",
    "vite",
    "vitest",
}

HINT = (
    "Добавляйте зависимость только по plan.md и обновите список в тесте "
    "backend/tests/arch/test_dependencies_allowlist.py."
)


def _py_name(spec: str) -> str:
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
    assert m, f"не разобрана зависимость: {spec!r}"
    return re.sub(r"[-_.]+", "-", m.group(1).lower())


def _compare(actual: set[str], allowed: set[str], where: str) -> None:
    extra, missing = sorted(actual - allowed), sorted(allowed - actual)
    assert actual == allowed, f"{where}: лишние {extra}, отсутствуют {missing}. {HINT}"


def _pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))


def _package_json() -> dict:
    return json.loads((REPO_ROOT / "frontend/package.json").read_text(encoding="utf-8"))


def test_backend_runtime_dependencies_allowlist() -> None:
    actual = {_py_name(s) for s in _pyproject()["project"]["dependencies"]}
    _compare(actual, BACKEND_RUNTIME, "backend [project.dependencies]")


def test_backend_dev_dependencies_allowlist() -> None:
    actual = {_py_name(s) for s in _pyproject()["project"]["optional-dependencies"]["dev"]}
    _compare(actual, BACKEND_DEV, "backend optional-dependencies.dev")


def test_backend_has_no_other_optional_groups() -> None:
    groups = set(_pyproject()["project"].get("optional-dependencies", {}))
    assert groups == {"dev"}, f"новые группы зависимостей: {sorted(groups - {'dev'})}. {HINT}"


def test_frontend_dependencies_allowlist() -> None:
    actual = set(_package_json().get("dependencies", {}))
    _compare(actual, FRONTEND_RUNTIME, "frontend dependencies")


def test_frontend_dev_dependencies_allowlist() -> None:
    actual = set(_package_json().get("devDependencies", {}))
    _compare(actual, FRONTEND_DEV, "frontend devDependencies")


def test_frontend_has_no_other_dependency_sections() -> None:
    extra = {"peerDependencies", "optionalDependencies"} & set(_package_json())
    assert not extra, f"новые секции зависимостей: {sorted(extra)}. {HINT}"
