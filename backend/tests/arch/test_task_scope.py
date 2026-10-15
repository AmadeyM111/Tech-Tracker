"""T32a: scope-guard `scripts/task_scope.py` (сверка изменений рабочего дерева с полем «Файлы»).

Контракт CLI: `python scripts/task_scope.py <T..> [--base <ref>]` (по умолчанию `HEAD`),
запуск из корня git-репозитория; задачи берутся из `specs/*/tasks.md`.
Выход 0 и «в рамках задачи» - все изменённые и неотслеженные файлы в списке;
1 - есть файлы вне списка (каждый назван в выводе); 2 - задача не найдена или не разобрана.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "task_scope.py"

TASKS_MD = """\
# Задачи

## T01 — Первая задача
- **Статус:** IN_PROGRESS
- **AC:** AC-1
- **Файлы:** `src/a.py`, `src/dir with space/b.py`, `docs/файл.md`,
  `lib/**`, `backend/pyproject.toml` (правила `ruff`: `C901`, `ARG`),
  `README.md` (+ пояснение без путей);
  тесты: `tests/test_a.py`, `tests/sub/test_b.py`
  (каталог новый, с `__init__.py`)
- **Зависит от:** —
- **Описание:** текст

## T02 — Вторая задача
- **Статус:** TODO
- **AC:** AC-2
- **Файлы:** `only/two.py`
- **Зависит от:** T01
- **Описание:** текст
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _write(root: Path, rel: str, text: str = "x\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _write(tmp_path, "specs/x/tasks.md", TASKS_MD)
    for rel in (
        "src/a.py",
        "src/dir with space/b.py",
        "docs/файл.md",
        "lib/top.py",
        "README.md",
        "tests/test_a.py",
        "other/outside.py",
        "only/two.py",
        "docs/api/openapi.json",
        "frontend/src/shared/api/schema.d.ts",
        "backend/pyproject.toml",
    ):
        _write(tmp_path, rel)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _out(r: subprocess.CompletedProcess[str]) -> str:
    return r.stdout + r.stderr


def test_script_exists() -> None:
    assert SCRIPT.is_file()


def test_no_changes_is_in_scope(repo: Path) -> None:
    r = _run(repo, "T01")
    assert r.returncode == 0, _out(r)
    assert "в рамках задачи" in _out(r)


def test_changed_and_untracked_files_in_list_exit_0(repo: Path) -> None:
    _write(repo, "src/a.py", "changed\n")  # изменён
    _write(repo, "tests/sub/test_b.py")  # неотслеженный, из «тесты: …»
    _write(repo, "README.md", "changed\n")  # путь перед «(+ …)»
    _write(repo, "backend/pyproject.toml", "changed\n")  # путь перед «(правила …)»
    r = _run(repo, "T01")
    assert r.returncode == 0, _out(r)
    assert "в рамках задачи" in _out(r)


def test_file_outside_list_exit_1_and_named(repo: Path) -> None:
    _write(repo, "src/a.py", "changed\n")
    _write(repo, "other/outside.py", "changed\n")
    r = _run(repo, "T01")
    assert r.returncode == 1, _out(r)
    assert "other/outside.py" in _out(r)
    assert "src/a.py" not in _out(r)


def test_untracked_file_outside_list_exit_1(repo: Path) -> None:
    _write(repo, "brand/new.py")
    r = _run(repo, "T01")
    assert r.returncode == 1, _out(r)
    assert "brand/new.py" in _out(r)


def test_other_tasks_files_are_outside(repo: Path) -> None:
    _write(repo, "only/two.py", "changed\n")
    assert _run(repo, "T01").returncode == 1
    assert _run(repo, "T02").returncode == 0


def test_always_allowed_paths(repo: Path) -> None:
    _write(repo, "specs/x/tasks.md", TASKS_MD + "\nправка\n")
    _write(repo, "specs/x/reviews/T01.md")
    _write(repo, "specs/y/reviews/deep/T09.md")
    _write(repo, "specs/y/tasks.md", "## T77 — другая\n- **Файлы:** `z.py`\n- **Зависит от:** —\n")
    _write(repo, "docs/api/openapi.json", "{}\n")
    _write(repo, "frontend/src/shared/api/schema.d.ts", "//\n")
    _write(repo, "backend/app/domain/projects/__init__.py", "")
    r = _run(repo, "T01")
    assert r.returncode == 0, _out(r)


def test_spec_files_other_than_tasks_and_reviews_are_not_allowed(repo: Path) -> None:
    _write(repo, "specs/x/spec.md")
    r = _run(repo, "T01")
    assert r.returncode == 1, _out(r)
    assert "specs/x/spec.md" in _out(r)


def test_unknown_task_exit_2(repo: Path) -> None:
    r = _run(repo, "T99")
    assert r.returncode == 2, _out(r)


def test_recursive_glob_covers_nested(repo: Path) -> None:
    _write(repo, "lib/a/b/c/deep.py")
    _write(repo, "lib/top.py", "changed\n")
    r = _run(repo, "T01")
    assert r.returncode == 0, _out(r)


def test_glob_does_not_cover_sibling_prefix(repo: Path) -> None:
    _write(repo, "library/x.py")
    r = _run(repo, "T01")
    assert r.returncode == 1, _out(r)
    assert "library/x.py" in _out(r)


def test_paths_with_spaces_and_cyrillic(repo: Path) -> None:
    _write(repo, "src/dir with space/b.py", "changed\n")
    _write(repo, "docs/файл.md", "changed\n")
    r = _run(repo, "T01")
    assert r.returncode == 0, _out(r)
    _write(repo, "docs/чужой файл.md")
    r = _run(repo, "T01")
    assert r.returncode == 1
    assert "docs/чужой файл.md" in _out(r)


def test_parenthetical_tokens_are_not_paths(repo: Path) -> None:
    """Токены в скобках («правила `ruff`: `C901`») не являются путями."""
    _write(repo, "C901")
    r = _run(repo, "T01")
    assert r.returncode == 1, _out(r)
    assert "C901" in _out(r)


def test_deleted_file_counts_as_changed(repo: Path) -> None:
    (repo / "src/a.py").unlink()
    assert _run(repo, "T01").returncode == 0
    (repo / "other/outside.py").unlink()
    r = _run(repo, "T01")
    assert r.returncode == 1
    assert "other/outside.py" in _out(r)


def test_rename_checks_old_and_new_path(repo: Path) -> None:
    _git(repo, "mv", "src/a.py", "lib/moved.py")  # оба пути в списке
    assert _run(repo, "T01").returncode == 0
    _git(repo, "mv", "other/outside.py", "src/a2.py")
    _git(repo, "mv", "tests/test_a.py", "other/new_place.py")
    r = _run(repo, "T01")
    assert r.returncode == 1
    out = _out(r)
    assert "other/outside.py" in out  # старый путь вне списка
    assert "other/new_place.py" in out  # новый путь вне списка


def test_base_ref_option(repo: Path) -> None:
    _write(repo, "other/outside.py", "changed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c2")
    assert _run(repo, "T01").returncode == 0  # относительно HEAD чисто
    r = _run(repo, "T01", "--base", "HEAD~1")
    assert r.returncode == 1, _out(r)
    assert "other/outside.py" in _out(r)


def test_script_uses_only_stdlib() -> None:
    assert SCRIPT.is_file()
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    non_std = mods - set(sys.stdlib_module_names) - {"__future__"}
    assert not non_std, f"внешние импорты запрещены: {sorted(non_std)}"


def test_real_tasks_md_t32_is_parsed() -> None:
    """Формат поля «Файлы» реального T32 разбирается (код не 2)."""
    r = _run(REPO_ROOT, "T32", "--base", "HEAD")
    assert r.returncode in (0, 1), _out(r)


def test_list_option_prints_parsed_patterns(repo: Path) -> None:
    """`--list`: печатает разобранные пути/шаблоны задачи, по одному в строке, код 0."""
    r = _run(repo, "T01", "--list")
    assert r.returncode == 0, _out(r)
    lines = {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
    assert {"src/a.py", "src/dir with space/b.py", "lib/**", "tests/sub/test_b.py"} <= lines
    assert "C901" not in lines
    assert "ruff" not in lines


def test_real_t32_list_is_nonempty() -> None:
    r = _run(REPO_ROOT, "T32", "--list")
    assert r.returncode == 0, _out(r)
    lines = {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
    assert "README.md" in lines
    assert "frontend/src/**" in lines
    assert "backend/tests/api/test_e2e_accounts.py" in lines


# --- T32a, попытка 2 ---------------------------------------------------------


def _set_tasks(
    repo: Path, files_field: str, rel: str = "specs/x/tasks.md", tid: str = "T01"
) -> None:
    text = f"## {tid} — Задача\n- **Файлы:** {files_field}\n- **Зависит от:** —\n"
    _write(repo, rel, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"tasks {rel}")


def test_plus_group_paths_are_included(repo: Path) -> None:
    """`(+ `path`)`: пути из группы «(+ …)» входят в список; прочие скобки игнорируются."""
    _set_tasks(
        repo,
        "`src/a.py` (+ `extra/plus.py`, `extra/two.py`); (каталог новый, с `__init__.py`) "
        "`backend/pyproject.toml` (правила `ruff`: `C901`)",
    )
    r = _run(repo, "T01", "--list")
    assert r.returncode == 0, _out(r)
    lines = {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
    assert {"src/a.py", "extra/plus.py", "extra/two.py", "backend/pyproject.toml"} <= lines
    assert "C901" not in lines
    assert "ruff" not in lines
    assert "__init__.py" not in lines
    _write(repo, "extra/plus.py")
    r = _run(repo, "T01")
    assert r.returncode == 0, _out(r)
    _write(repo, "C901")
    r = _run(repo, "T01")
    assert r.returncode == 1, _out(r)
    assert "C901" in _out(r)


def test_suffix_matching_on_slash_boundary(repo: Path) -> None:
    _set_tasks(repo, "`router.tsx`, `features/x/api.ts`")
    _write(repo, "frontend/src/app/router.tsx")
    _write(repo, "frontend/src/features/x/api.ts")
    r = _run(repo, "T01")
    assert r.returncode == 0, _out(r)
    _write(repo, "frontend/src/app/myrouter.tsx")
    r = _run(repo, "T01")
    assert r.returncode == 1, _out(r)
    assert "frontend/src/app/myrouter.tsx" in _out(r)
    assert "frontend/src/app/router.tsx" not in _out(r)


def test_unknown_base_exit_2_without_traceback(repo: Path) -> None:
    r = _run(repo, "T01", "--base", "nope")
    assert r.returncode == 2, _out(r)
    assert r.stderr.strip()
    assert "Traceback" not in r.stderr


def test_outside_git_repo_exit_2_without_traceback(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    r = _run(plain, "T01")
    assert r.returncode == 2, _out(r)
    assert r.stderr.strip()
    assert "Traceback" not in r.stderr


def test_base_option_injection_is_rejected(repo: Path) -> None:
    target = repo / "pwned.txt"
    r = _run(repo, "T01", f"--base=--output={target}")
    assert r.returncode == 2, _out(r)
    assert not target.exists()
    assert "Traceback" not in r.stderr


def test_staged_ignores_unstaged_and_untracked(repo: Path) -> None:
    _write(repo, "other/outside.py", "changed\n")  # изменён, не в индексе
    _write(repo, "brand/new.py")  # неотслеженный
    r = _run(repo, "T01", "--staged")
    assert r.returncode == 0, _out(r)
    # по умолчанию учитываются оба
    r = _run(repo, "T01")
    assert r.returncode == 1, _out(r)
    assert "other/outside.py" in _out(r)
    assert "brand/new.py" in _out(r)


def test_staged_reports_staged_file_outside_list(repo: Path) -> None:
    _write(repo, "other/outside.py", "changed\n")
    _git(repo, "add", "other/outside.py")
    _write(repo, "brand/new.py")  # неотслеженный - не должен попасть в вывод
    r = _run(repo, "T01", "--staged")
    assert r.returncode == 1, _out(r)
    assert "other/outside.py" in _out(r)
    assert "brand/new.py" not in _out(r)


def test_duplicate_task_id_in_two_tasks_md_exit_2(repo: Path) -> None:
    _write(repo, "specs/y/tasks.md", "## T01 — Дубль\n- **Файлы:** `z.py`\n- **Зависит от:** —\n")
    r = _run(repo, "T01")
    assert r.returncode == 2, _out(r)
    assert "Traceback" not in r.stderr
    assert r.stderr.strip()


def test_docstring_describes_glob_semantics() -> None:
    doc = ast.get_docstring(ast.parse(SCRIPT.read_text(encoding="utf-8"))) or ""
    assert "**" in doc
    assert "__init__" in doc
