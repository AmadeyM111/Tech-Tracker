#!/usr/bin/env bash
# Полная проверка проекта. Должна быть зелёной перед каждым PR.
set -uo pipefail
status=0

run() { echo; echo "=== $* ==="; "$@" || status=1; }

run ruff check backend
run ruff format --check backend
run mypy --config-file backend/pyproject.toml backend/app
run pytest -q backend/tests

# Версия Node для фронтенда: `^22.12 || ^24 || >=26` (frontend/package.json, engines).
node_version_ok() {
  # из frontend/: именно та версия, которую увидят npm-скрипты
  ( cd frontend && node -e '
    const [maj, min] = process.versions.node.split(".").map(Number);
    process.exit((maj === 22 && min >= 12) || maj === 24 || maj >= 26 ? 0 : 1);
  ' ) >/dev/null 2>&1
}

if [ -f frontend/package.json ] && ! node_version_ok; then
  echo; echo "=== frontend: нужна Node.js ^22.12 || ^24 || >=26 (найдено: $(cd frontend && node --version 2>/dev/null || echo нет)) ==="
  status=1
elif [ -f frontend/package.json ] && [ ! -d frontend/node_modules ]; then
  echo; echo "=== frontend: нет frontend/node_modules — выполните \`cd frontend && npm ci\` ==="
  status=1
elif [ -f frontend/package.json ]; then
  ( cd frontend && npm run lint && npm run typecheck && npm test ) || status=1
else
  echo; echo "=== frontend: ещё не инициализирован, пропуск ==="
fi

echo
[ $status -eq 0 ] && echo "ВСЁ ЗЕЛЁНОЕ" || echo "ЕСТЬ ОШИБКИ"
exit $status
