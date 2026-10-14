#!/usr/bin/env bash
# Генерация API-артефактов (plan §4.14, D-33): docs/api/openapi.json и, когда появится
# фронтенд (T22), TypeScript-типы. Запускать из любого каталога после `source .venv/bin/activate`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Схема не требует БД и секретов: `gostracker openapi` их не читает.
gostracker openapi --out docs/api/openapi.json
echo "docs/api/openapi.json обновлён"

if [ -f frontend/package.json ]; then
  npm --prefix frontend run gen:api
else
  echo "frontend/package.json нет: генерация TS-типов пропущена"
fi
