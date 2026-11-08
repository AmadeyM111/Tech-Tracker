# Протокол учения восстановления (spec 009, AC-14, R2-36)

## Учение 1 — 2026-11-08, сервер пилота (временный скрипт хоста)

- **Кто:** агент разработки R2 (GTrack R2), по одобрению владельца (T-01).
- **Копия:** `deploy/backup/host/gtrack-backup` (pg_dump -Fc + том appdata), снята в 14:36:53Z,
  `/var/backups/gtrack/20261108T143653Z/`, 72 КБ, ревизия схемы `0009`.
- **Стенд:** временный контейнер `postgres:16` на том же сервере, без сети (`--network none`),
  256 МБ, отдельный каталог данных; рабочие контейнеры не менялись.
- **Шаги:** sha256 по `SHA256SUMS` → `pg_restore --no-owner --no-privileges --exit-on-error` в
  пустую БД → распаковка `appdata.tar` → сверка числа строк всех таблиц `public` с рабочей БД.
- **Результат:** sha256 OK; ревизия `0009`; число строк совпало во всех 13 таблицах (app_user 11,
  workspace 1, workspace_member 11, user_session 2, project 6, project_member 9, task 7,
  comment 4, domain_event 39, api_token 1, password_reset_token 1, password_reset_attempt 2,
  alembic_version 1); appdata распакован (1 файл).
- **Время:** копия 3 с, запуск PostgreSQL 6 с, восстановление < 1 с; всего 9 с (≤ 60 мин).
- **Уборка:** контейнер и каталог удалены, висячих томов не добавилось.
- **Не проверено:** запуск api на восстановленной БД (полный стек). Выполнить в учении 2.

## Учение 2 — после выкатки spec 009 (запланировать)

Чистый стенд: `docker compose -p drill up -d --wait db` → `gtrack restore … --yes` →
`docker compose -p drill up -d --wait` → вход ТА, открытие проекта и задачи; `gtrack export` до и
после совпадает (AC-9). Записать время от начала до входа в систему.
