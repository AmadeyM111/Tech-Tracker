#!/usr/bin/env bash
# Восстановление стека GTrack из копии, снятой scripts/backup.sh.
# ДЕСТРУКТИВНО: БД стека пересоздаётся из дампа; тома appdata содержимое заменяется
# (если в копии есть appdata.tar и не указан --db-only). Перед запуском проверьте,
# что -p указывает на нужный стек (docker compose ls) и что копия свежая.
#
#   scripts/restore.sh -p <проект-compose> -b <каталог-копии> [--db-only] [--yes]
#
#   -p        проект Compose стека; обязателен (стек по умолчанию не выбирается).
#   -b        каталог копии: db.dump, appdata.tar (опционально), SHA256SUMS.
#   --db-only восстановить только БД; том appdata не трогать.
#   --yes     не спрашивать подтверждение. Без него введите имя проекта.
#
# Порядок: проверка SHA256SUMS и формата дампа -> stop api -> пересоздание БД
# и pg_restore -> восстановление appdata. Сервис api после скрипта остаётся
# остановленным: запустите его из клона на версии кода, которой соответствует копия
# (миграции выполнятся при старте api):
#   docker compose -p <проект> up -d --wait api
set -euo pipefail

usage() {
  cat <<'EOF'
Использование: scripts/restore.sh -p <проект-compose> -b <каталог-копии> [--db-only] [--yes]
EOF
}

PROJECT=""
BACKUP=""
DB_ONLY=0
ASSUME_YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    -p) PROJECT="${2:-}"; shift 2 ;;
    -b) BACKUP="${2:-}"; shift 2 ;;
    --db-only) DB_ONLY=1; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if [ -z "$PROJECT" ] || [ -z "$BACKUP" ]; then
  usage >&2
  exit 2
fi

compose() { docker compose -p "$PROJECT" "$@"; }

verify() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum -c --quiet "$@"; else shasum -a 256 -c --quiet "$@"; fi
}

[ -f "$BACKUP/db.dump" ] || { echo "Нет $BACKUP/db.dump" >&2; exit 1; }
[ -f "$BACKUP/SHA256SUMS" ] || { echo "Нет $BACKUP/SHA256SUMS: копия не проверяема" >&2; exit 1; }

(cd "$BACKUP" && verify SHA256SUMS) || { echo "Контрольные суммы не совпадают" >&2; exit 1; }

DB_ID="$(compose ps -q db 2>/dev/null || true)"
if [ -z "$DB_ID" ]; then
  echo "Работающий сервис db не найден в проекте '$PROJECT'. Поднимите его: docker compose -p $PROJECT up -d --wait db" >&2
  exit 1
fi
IMAGE="$(docker inspect -f '{{.Config.Image}}' "$DB_ID")"

RESTORE_APPDATA=0
if [ "$DB_ONLY" != 1 ] && [ -f "$BACKUP/appdata.tar" ]; then
  RESTORE_APPDATA=1
fi

# Формат дампа проверяется до того, как что-либо остановлено или удалено.
compose exec -T db pg_restore --list < "$BACKUP/db.dump" > /dev/null

if [ "$ASSUME_YES" != 1 ]; then
  echo "Будет ЗАМЕНЕНА БД стека '$PROJECT'$([ "$RESTORE_APPDATA" = 1 ] && echo ' и содержимое тома appdata')."
  printf 'Для подтверждения введите имя проекта: '
  answer=""
  read -r answer < /dev/tty 2>/dev/null || true
  if [ "$answer" != "$PROJECT" ]; then
    echo "Отменено" >&2
    exit 1
  fi
fi

echo "Останавливаю api"
compose stop api >/dev/null

echo "Пересоздаю БД и восстанавливаю дамп"
compose exec -T db sh -c '
  [ "$POSTGRES_DB" != postgres ] || { echo "POSTGRES_DB не может быть postgres" >&2; exit 3; }
  psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE)" \
    -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\""
'
compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges --exit-on-error' \
  < "$BACKUP/db.dump"

if [ "$RESTORE_APPDATA" = 1 ]; then
  echo "Восстанавливаю том appdata"
  # create поднимает том, если его нет; контейнер api не запускается.
  compose create api >/dev/null
  VOLUME="$(docker volume ls -q \
    --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.volume=appdata")"
  if [ -z "$VOLUME" ]; then
    echo "Том appdata не найден после create" >&2
    exit 1
  fi
  docker run --rm -i -v "$VOLUME:/data" --entrypoint sh "$IMAGE" \
    -c 'find /data -mindepth 1 -delete && tar -C /data -xf -' \
    < "$BACKUP/appdata.tar"
fi

echo
echo "Восстановление завершено. api остановлен."
echo "Запустите его из клона на версии кода, которой соответствует копия:"
echo "  docker compose -p $PROJECT up -d --wait api"
