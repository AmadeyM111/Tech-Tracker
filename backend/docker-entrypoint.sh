#!/bin/sh
# Запуск API: bootstrap (миграции, ключ, первый ТА) → uvicorn как PID 1 (plan §4.12, FR-6).
set -e

# Файлы секретов и данных создаются приватными (0600/0700) — до bootstrap.
umask 077

# Ошибка bootstrap (set -e) останавливает контейнер с ненулевым кодом; в stdout — только путь к файлу.
gostracker bootstrap

# exec: uvicorn становится PID 1 и получает SIGTERM для штатной остановки.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --no-access-log
