#!/usr/bin/env bash
# Резервная копия стека GOSTracker: дамп БД (pg_dump -Fc) и архив тома appdata
# (/data: secret_key и файлы секретов). Тома не удаляются и не пересоздаются.
#
#   scripts/backup.sh -p <проект-compose> [-d <каталог>]
#
#   -p  проект Compose стека (как в `docker compose ls`); обязателен, чтобы не
#       снять копию с чужого стека.
#   -d  каталог назначения; по умолчанию ~/gostracker-backups/<проект>-<UTC-метка>.
#       Каталог вне клона: в дампе хеши паролей, в репозиторий они попадать не должны.
#
# Результат: db.dump, appdata.tar (если том есть), SHA256SUMS. Права 600, каталог 700.
# Во время резервной копии не обновляйте стек (README: «Не выполняйте обновление стека
# во время резервной копии»).
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Использование: scripts/backup.sh -p <проект-compose> [-d <каталог>]
EOF
}

PROJECT=""
DEST=""
while getopts ":p:d:h" opt; do
  case "$opt" in
    p) PROJECT="$OPTARG" ;;
    d) DEST="$OPTARG" ;;
    h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if [ -z "$PROJECT" ]; then
  echo "Укажите проект Compose: -p <проект> (см. docker compose ls)" >&2
  usage >&2
  exit 2
fi

compose() { docker compose -p "$PROJECT" "$@"; }

sha() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi
}

DB_ID="$(compose ps -q db 2>/dev/null || true)"
if [ -z "$DB_ID" ]; then
  echo "Работающий сервис db не найден в проекте '$PROJECT'" >&2
  exit 1
fi
IMAGE="$(docker inspect -f '{{.Config.Image}}' "$DB_ID")"

# Имя тома appdata: Compose метит тома именем проекта и именем сервиса-тома.
appdata_volume() {
  docker volume ls -q \
    --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.volume=appdata"
}

if [ -z "$DEST" ]; then
  DEST="$HOME/gostracker-backups/$PROJECT-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p -m 700 "$DEST"
if [ -n "$(ls -A "$DEST")" ]; then
  echo "Каталог назначения не пуст: $DEST" >&2
  exit 1
fi

echo "Дамп БД -> $DEST/db.dump"
compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DEST/db.dump"
[ -s "$DEST/db.dump" ] || { echo "Дамп пуст" >&2; exit 1; }
# Проверка, что архив читается как custom-формат pg_restore (чтение через stdin).
compose exec -T db pg_restore --list < "$DEST/db.dump" > /dev/null

VOLUME="$(appdata_volume)"
if [ -n "$VOLUME" ]; then
  echo "Том appdata -> $DEST/appdata.tar"
  docker run --rm -v "$VOLUME:/data:ro" --entrypoint tar "$IMAGE" -C /data -cf - . \
    > "$DEST/appdata.tar"
  [ -s "$DEST/appdata.tar" ] || { echo "Архив appdata пуст" >&2; exit 1; }
else
  echo "ВНИМАНИЕ: том appdata не найден (api ещё ни разу не запускался); копия только БД." >&2
fi

if [ -f "$DEST/appdata.tar" ]; then
  (cd "$DEST" && sha db.dump appdata.tar > SHA256SUMS)
else
  (cd "$DEST" && sha db.dump > SHA256SUMS)
fi

echo
echo "Копия готова: $DEST"
ls -l "$DEST"
