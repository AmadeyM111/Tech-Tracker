#!/usr/bin/env bash
# Полная проверка проекта. Должна быть зелёной перед каждым PR.
set -uo pipefail
status=0

run() { echo; echo "=== $* ==="; "$@" || status=1; }

run ruff check --no-cache backend
run ruff format --check backend
run mypy --config-file backend/pyproject.toml backend/app

# Модели совпадают с миграциями (как в CI): только тестовая БД *_test, те же переменные, что у pytest.
TEST_DB_URL="${TEST_DATABASE_URL:-postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test}"

# Гард тот же, что у тестов (tests.db_support): имя БД из пути URL оканчивается на _test, подмена
# имени через query (?database=...) запрещена. URL передаётся через окружение, в вывод не попадает.
test_db_url_is_safe() {
  ( cd backend && GT_CHECK_DB_URL="$TEST_DB_URL" python -c '
import os
import sys

from tests.db_support import UnsafeTestDatabaseError, assert_test_database_url

try:
    assert_test_database_url(os.environ["GT_CHECK_DB_URL"])
except UnsafeTestDatabaseError as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
except Exception:
    print("TEST_DATABASE_URL не разбирается как URL базы данных", file=sys.stderr)
    sys.exit(1)
' )
}

alembic_check() {
  if ! test_db_url_is_safe; then
    echo "TEST_DATABASE_URL должен указывать на БД с именем *_test: миграции на другой БД не запускаются"
    return 1
  fi
  env DATABASE_URL="$TEST_DB_URL" ENV=test alembic -c backend/alembic.ini upgrade head \
    && env DATABASE_URL="$TEST_DB_URL" ENV=test alembic -c backend/alembic.ini check \
    || { echo "alembic: ошибка; проверьте, что тестовая БД доступна (TEST_DATABASE_URL, по умолчанию tracker_test на localhost:5432) и модели соответствуют миграциям"; return 1; }
}
run alembic_check

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
  ( cd frontend && npm run lint && npm run typecheck && npm test && npm run build ) || status=1
else
  echo; echo "=== frontend: ещё не инициализирован, пропуск ==="
fi

echo
[ $status -eq 0 ] && echo "ВСЁ ЗЕЛЁНОЕ" || echo "ЕСТЬ ОШИБКИ"
exit $status
