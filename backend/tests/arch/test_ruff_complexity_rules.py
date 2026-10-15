"""T32a: правила сложности ruff (KISS/SRP) и YAGNI (ARG) закреплены в backend/pyproject.toml.

Ratchet: границы = текущие максимумы backend/app; пороги можно только уменьшать.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "backend/pyproject.toml"

REQUIRED_RULES = {"C901", "PLR0912", "PLR0913", "PLR0915", "ARG"}
MAX_MCCABE = 16
MAX_BRANCHES = 16
MAX_ARGS = 10
MAX_STATEMENTS = 34


def _lint() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["ruff"]["lint"]


def _is_selected(rule: str, selected: list[str]) -> bool:
    return any(s == rule or (s and rule.startswith(s)) for s in selected)


@pytest.mark.parametrize("rule", sorted(REQUIRED_RULES))
def test_rule_is_selected(rule: str) -> None:
    assert _is_selected(rule, _lint()["select"]), f"{rule} не выбран в [tool.ruff.lint] select"


def _threshold(section: str, key: str) -> int:
    value = _lint().get(section, {}).get(key)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"[tool.ruff.lint.{section}] {key} не задан"
    )
    assert value > 0
    return value


def test_mccabe_threshold() -> None:
    assert _threshold("mccabe", "max-complexity") <= MAX_MCCABE


def test_pylint_branches_threshold() -> None:
    assert _threshold("pylint", "max-branches") <= MAX_BRANCHES


def test_pylint_args_threshold() -> None:
    assert _threshold("pylint", "max-args") <= MAX_ARGS


def test_pylint_statements_threshold() -> None:
    assert _threshold("pylint", "max-statements") <= MAX_STATEMENTS


ALLOWED_TEST_IGNORES = {"C901", "PLR0912", "PLR0913", "PLR0915"}


def test_tests_per_file_ignores_only_complexity_rules() -> None:
    """Для tests/** можно отключать только правила сложности и ARG*."""
    pfi = _lint().get("per-file-ignores", {})
    for pattern, rules in pfi.items():
        if "tests" not in pattern:
            continue
        for rule in rules:
            ok = rule in ALLOWED_TEST_IGNORES or rule.startswith("ARG")
            assert ok, f"per-file-ignores {pattern}: недопустимо отключать {rule}"


def test_noqa_budget_for_complexity_rules() -> None:
    """Точечных noqa на правила сложности/ARG не более 5 (backend/app, migrations)."""
    count = 0
    for root in ("app", "migrations"):
        for path in (REPO_ROOT / "backend" / root).rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "noqa" in line and any(
                    r in line for r in ("C901", "PLR0912", "PLR0913", "PLR0915", "ARG0")
                ):
                    count += 1
    assert count <= 5, f"noqa на правила сложности: {count} > 5"


def test_ruff_check_passes() -> None:
    ruff = shutil.which("ruff", path=str(Path(sys.executable).parent))
    assert ruff, "ruff не найден в venv"
    r = subprocess.run(
        [ruff, "check", "--no-cache", "backend"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]


FORBIDDEN_OUTSIDE_TESTS = ("C901", "PLR09", "ARG")


def test_no_complexity_ignores_outside_tests() -> None:
    """Вне tests/** per-file-ignores для C901, PLR09*, ARG* запрещены (только точечный noqa)."""
    pfi = _lint().get("per-file-ignores", {})
    for pattern, rules in pfi.items():
        if "tests" in pattern:
            continue
        for rule in rules:
            assert not rule.startswith(FORBIDDEN_OUTSIDE_TESTS), (
                f"per-file-ignores {pattern}: {rule} запрещён вне tests/**"
            )


def test_tests_ignores_limited_to_allowed_set() -> None:
    pfi = _lint().get("per-file-ignores", {})
    allowed = {"C901", "PLR0912", "PLR0913", "PLR0915"}
    for pattern, rules in pfi.items():
        if "tests" not in pattern:
            continue
        for rule in rules:
            assert rule in allowed or rule.startswith("ARG"), f"{pattern}: {rule}"


@pytest.mark.parametrize("rel", ["app/core/errors.py", "app/cli/commands/bootstrap.py"])
def test_arg001_suppressed_by_pointed_noqa_with_reason(rel: str) -> None:
    lines = (REPO_ROOT / "backend" / rel).read_text(encoding="utf-8").splitlines()
    hits = [ln for ln in lines if "noqa: ARG001" in ln]
    assert hits, f"{rel}: нет точечного `# noqa: ARG001`"
    for ln in hits:
        tail = ln.split("noqa: ARG001", 1)[1]
        assert "#" in tail and tail.split("#", 1)[1].strip(), f"{rel}: нет причины: {ln.strip()}"
