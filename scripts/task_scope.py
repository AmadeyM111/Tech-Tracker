#!/usr/bin/env python3
"""Scope-guard: сверяет изменения рабочего дерева с полем «Файлы» задачи.

Использование (из git-репозитория):
    python scripts/task_scope.py <T..> [--base <ref>] [--staged] [--list]

Что входит в список задачи: токены в обратных кавычках вне круглых скобок и пути-токены
(содержат `/` или расширение, без пробелов) из групп `(+ ...)`; прочие пояснения в скобках
игнорируются. Сопоставление:
- `dir/**` и `dir/` - всё под каталогом (граница по `/`);
- `*` и `?` - как fnmatch: `*` пересекает `/`, `**` вне конца шаблона равен `*`;
- токен, чей первый сегмент не есть каталог/файл корня репозитория (`router.tsx`,
  `features/x/api.ts`), сопоставляется как суффикс пути с границей по `/`;
- иначе - точное совпадение пути.
Всегда допустимы: `**/__init__.py` (любой), `specs/**/tasks.md`, `specs/**/reviews/**`,
`docs/api/openapi.json` и `frontend/src/shared/api/schema.d.ts`.
По умолчанию учитываются изменённые (относительно `--base`) и неотслеженные файлы;
`--staged` - только индекс (режим перед коммитом).

Выход: 0 - всё в рамках задачи; 1 - есть файлы вне рамок (печатаются); 2 - задача не найдена,
неоднозначна (ID в нескольких tasks.md), поле «Файлы» не разобрано или ошибка git.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ALWAYS_EXACT = {"docs/api/openapi.json", "frontend/src/shared/api/schema.d.ts"}


class ScopeError(Exception):
    """Ошибка, после которой выход с кодом 2 и сообщением в stderr."""


def _git(*args: str) -> bytes:
    r = subprocess.run(["git", *args], capture_output=True, check=True)
    return r.stdout


def _split_z(raw: bytes) -> list[str]:
    return [t.decode("utf-8") for t in raw.split(b"\0") if t]


def find_files_field(task_id: str, root: Path) -> str | None:
    """Текст поля «Файлы» задачи из `specs/*/tasks.md` (или None)."""
    heading = re.compile(rf"^## {re.escape(task_id)}(\s|$)")
    found: list[str] = []
    for tasks_md in sorted(root.glob("specs/*/tasks.md")):
        lines = tasks_md.read_text(encoding="utf-8").splitlines()
        in_task = False
        field: list[str] | None = None
        for line in lines:
            if line.startswith("## "):
                if in_task:
                    break
                in_task = bool(heading.match(line))
                continue
            if not in_task:
                continue
            if field is None and line.startswith("- **Файлы:**"):
                field = [line.split("**Файлы:**", 1)[1]]
            elif field is not None:
                if line.startswith("- **Зависит от:**"):
                    break
                field.append(line)
        if in_task and field is not None:
            found.append("\n".join(field))
    if len(found) > 1:
        raise ScopeError(f"задача {task_id} описана в нескольких specs/*/tasks.md")
    return found[0] if found else None


def _is_path_like(token: str) -> bool:
    return " " not in token and ("/" in token or re.search(r"\.\w+$", token) is not None)


def parse_patterns(field: str) -> list[str]:
    """Токены в обратных кавычках вне скобок и пути из групп `(+ ...)`."""
    patterns: list[str] = []
    depth = 0
    plus = False
    token: list[str] | None = None
    for i, ch in enumerate(field):
        if ch == "`":
            if token is None:
                token = []
                continue
            text = "".join(token).strip()
            token = None
            if text and (depth == 0 or (plus and _is_path_like(text))):
                patterns.append(text)
        elif token is not None:
            token.append(ch)
        elif ch == "(":
            if depth == 0:
                plus = field[i + 1 :].lstrip().startswith("+")
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
    return patterns


def changed_paths(base: str, staged: bool = False) -> set[str]:
    if base.startswith("-"):
        raise ScopeError(f"--base не может начинаться с «-»: {base}")
    cmd = ["diff", "--name-status", "-z"]
    tokens = _split_z(_git(*cmd, *(["--cached"] if staged else []), base, "--"))
    paths: set[str] = set()
    i = 0
    while i < len(tokens):
        n = 2 if tokens[i][0] in "RC" else 1
        paths.update(tokens[i + 1 : i + 1 + n])
        i += 1 + n
    if not staged:
        paths.update(_split_z(_git("ls-files", "--others", "--exclude-standard", "-z")))
    return paths


def always_allowed(path: str) -> bool:
    if path in ALWAYS_EXACT:
        return True
    name = PurePosixPath(path).name
    if name == "__init__.py":
        return True
    if path.startswith("specs/"):
        return name == "tasks.md" or "/reviews/" in path
    return False


def matches(path: str, pattern: str, top: set[str]) -> bool:
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if "*" in pattern or "?" in pattern:
        return fnmatch.fnmatchcase(path, pattern)
    if pattern.split("/", 1)[0] not in top:
        return path == pattern or path.endswith("/" + pattern)
    return path == pattern


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Проверка изменений в рамках файлов задачи")
    ap.add_argument("task", help="ID задачи, например T32a")
    ap.add_argument("--base", default="HEAD", help="база сравнения (по умолчанию HEAD)")
    ap.add_argument("--staged", action="store_true", help="только индекс (без неотслеженных)")
    ap.add_argument("--list", action="store_true", help="напечатать разобранные шаблоны")
    args = ap.parse_args(argv)
    try:
        return _check(args)
    except ScopeError as e:
        print(str(e), file=sys.stderr)
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or b"").decode("utf-8", "replace").strip()
        print(f"ошибка git: {msg or e}", file=sys.stderr)
    except OSError as e:
        print(f"ошибка запуска git: {e}", file=sys.stderr)
    return 2


def _check(args: argparse.Namespace) -> int:
    root = Path(_git("rev-parse", "--show-toplevel").decode("utf-8").strip())
    os.chdir(root)  # ls-files --others печатает пути относительно cwd
    field = find_files_field(args.task, root)
    if field is None:
        print(f"задача {args.task} не найдена в specs/*/tasks.md", file=sys.stderr)
        return 2
    patterns = parse_patterns(field)
    if not patterns:
        print(f"поле «Файлы» задачи {args.task} не разобрано", file=sys.stderr)
        return 2
    if args.list:
        print("\n".join(patterns))
        return 0

    top = {p.name for p in root.iterdir()}
    outside = sorted(
        p
        for p in changed_paths(args.base, args.staged)
        if not always_allowed(p) and not any(matches(p, pat, top) for pat in patterns)
    )
    if outside:
        print(f"файлы вне рамок задачи {args.task}:")
        print("\n".join(f"  {p}" for p in outside))
        return 1
    print(f"{args.task}: изменения в рамках задачи")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
