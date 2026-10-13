#!/usr/bin/env bash
# Полная проверка проекта. Должна быть зелёной перед каждым PR.
set -uo pipefail
status=0

run() { echo; echo "=== $* ==="; "$@" || status=1; }

run ruff check backend
run ruff format --check backend
run mypy backend/app
run pytest -q backend/tests

if [ -f frontend/package.json ]; then
  ( cd frontend && npm run lint && npm run typecheck && npm test ) || status=1
else
  echo; echo "=== frontend: ещё не инициализирован, пропуск ==="
fi

echo
[ $status -eq 0 ] && echo "ВСЁ ЗЕЛЁНОЕ" || echo "ЕСТЬ ОШИБКИ"
exit $status
