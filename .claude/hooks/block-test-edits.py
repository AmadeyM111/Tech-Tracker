#!/usr/bin/env python3
"""PreToolUse-хук для implementer: запрещает правку тестов, spec, plan и tasks.

Claude Code передаёт JSON на stdin. Код выхода 2 блокирует вызов инструмента,
а текст из stderr возвращается агенту как причина.
Шаблоны путей подстройте под свой репозиторий.
"""
import json
import re
import sys

PROTECTED = [
    r"(^|/)tests?/",            # каталоги tests/ и test/
    r"(^|/)test_[^/]*\.py$",    # test_*.py
    r"_test\.py$",              # *_test.py
    r"(^|/)conftest\.py$",
    r"(^|/)specs/.*\.md$",      # spec.md, plan.md, tasks.md, reviews
]

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # не смогли разобрать вход — не мешаем

tool_input = data.get("tool_input") or {}
path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
path = path.replace("\\", "/")

for pattern in PROTECTED:
    if re.search(pattern, path):
        print(
            f"Заблокировано: implementer не может менять '{path}'. "
            "Тесты и документы SDD меняют test-writer / spec-writer / architect. "
            "Если тест или контракт неверен — остановись и верни TEST_ISSUE или PLAN_ISSUE.",
            file=sys.stderr,
        )
        sys.exit(2)

sys.exit(0)
