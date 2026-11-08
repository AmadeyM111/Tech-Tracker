# Tasks: Резервная копия и восстановление (фича 009)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия
- Источник истины — `spec.md`, решения — `plan.md` (PB-n). ID задач — `B09-Tnn`; рамки:
  `python scripts/task_scope.py B09-Tnn`.
- Не трогать: `CLAUDE.md`, `AGENTS.md`, `docs/adr/**`, `spec.md`, применённые миграции `0001…0009`.
- БД — только `*_test`. Сеть не используется. Пароль БД не попадает в argv, лог, исключения.
- Проверки: `bash scripts/check.sh`. Оценка пакета: ~3,5 дня.

## B09-T01 — Настройки, модель и миграция `backup_run`
- **Статус:** TODO
- **AC:** AC-5 (схема)
- **Файлы:** `backend/app/core/config.py`, `backend/app/domain/ops/models.py`, `backend/app/domain/registry.py`, `backend/migrations/versions/0011_backup_run.py`, `docs/data-model.md`, `backend/tests/db/test_009_backup_run_schema.py`, `backend/tests/db/test_migrations.py`, `backend/tests/db/test_007_schema.py`, `backend/tests/upgrade002_support.py` (голова цепочки `0009` → `0011`)
- **Зависит от:** —
- **Описание:** поля настроек PB-9; таблица `backup_run` (id, started_at, finished_at, status CHECK ok|failed, size_bytes, schema_revision, file_name, error_code); индекс по `finished_at`.
- **Готово, когда:** миграция вверх/вниз на `*_test`, тест схемы зелёный.
- **Оценка:** 0,5 дня
- **Попытки:** 0

## B09-T02 — Снятие, проверка, ротация
- **Статус:** TODO
- **AC:** AC-1…AC-6, AC-13
- **Файлы:** `backend/app/domain/ops/backup.py`, `backend/app/core/config.py` (`pg_bin_dir`), `backend/app/domain/ops/archive.py` (`backup_run` не экспортируется), `backend/tests/backup_support.py`, `backend/tests/unit/test_009_backup_unit.py`, `backend/tests/domain/test_009_backup.py`
- **Зависит от:** B09-T01
- **Описание:** `create_backup`, `verify_backup`, `rotate`, `record_run` (PB-2…PB-4), `Runner` с `PGPASSWORD`.
- **Готово, когда:** тесты зелёные (интеграционные — при наличии `pg_dump` 16).
- **Оценка:** 1 день
- **Попытки:** 0

## B09-T03 — Восстановление
- **Статус:** TODO
- **AC:** AC-9, AC-10
- **Файлы:** `backend/app/domain/ops/backup.py`, `backend/tests/domain/test_009_backup.py`, `backend/tests/unit/test_009_backup_unit.py`
- **Зависит от:** B09-T02
- **Описание:** `restore_backup` (PB-8): проверки пустоты, sha256, `pg_restore`, распаковка с защитой от обхода путей.
- **Готово, когда:** круг «export → backup → restore в чистую БД → export» даёт одинаковый `data.json`.
- **Оценка:** 0,5 дня
- **Попытки:** 0

## B09-T04 — CLI и предупреждение bootstrap
- **Статус:** TODO
- **AC:** AC-1, AC-3, AC-9…AC-11
- **Файлы:** `backend/app/cli/commands/backup.py`, `backend/app/cli/commands/restore.py`, `backend/app/cli/main.py`, `backend/app/cli/commands/bootstrap.py`, `backend/app/domain/ops/backup_status.py` (`last_success_at`, `bootstrap_warning`), `backend/tests/cli/test_009_cli.py`
- **Зависит от:** B09-T03
- **Описание:** `gtrack backup [--out]`, `gtrack restore ARCHIVE --yes`; вывод `ключ=значение`; FR-9.
- **Готово, когда:** CLI-тесты зелёные.
- **Оценка:** 0,5 дня
- **Попытки:** 0

## B09-T05 — API статуса
- **Статус:** TODO
- **AC:** AC-7, AC-8
- **Файлы:** `backend/app/domain/ops/backup_status.py`, `backend/app/api/v1/admin_system.py`, `backend/app/api/v1/schemas/admin_system.py`, `backend/app/api/v1/__init__.py`, `backend/tests/api/test_009_backup_status.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`
- **Зависит от:** B09-T01
- **Описание:** `backup_status` (PB-6), роутер под гейтом PB-7.
- **Готово, когда:** API-тесты зелёные, OpenAPI перегенерирован.
- **Оценка:** 0,25 дня
- **Попытки:** 0

## B09-T06 — Плашка ТА
- **Статус:** TODO
- **AC:** AC-12
- **Файлы:** `frontend/src/features/admin/BackupBanner.tsx`, `frontend/src/features/admin/BackupBanner.test.tsx`, `frontend/src/features/admin/api.ts`, `frontend/src/app/router.tsx`, `frontend/src/shared/i18n/ru.ts`, `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** B09-T05
- **Описание:** плашка в оболочке экранов ТА, опрос статуса; тексты Q-2.
- **Готово, когда:** `npm run lint && npm run typecheck && npm test` зелёный.
- **Оценка:** 0,25 дня
- **Попытки:** 0

## B09-T07 — Эксплуатация: образ, compose, таймер, README, протокол
- **Статус:** TODO
- **AC:** FR-10, AC-14, NFR-4
- **Файлы:** `backend/Dockerfile`, `docker-compose.yml`, `deploy/backup/gtrack-backup.service`, `deploy/backup/gtrack-backup.timer`, `deploy/backup/host/gtrack-backup`, `deploy/backup/host/README.md`, `README.md`, `.github/workflows/ci.yml`, `docs/acceptance/backup-restore-drill.md`, `backend/tests/infra/test_009_backup_ops.py`
- **Зависит от:** B09-T04
- **Описание:** PGDG-клиент 16 в образе; том `backups`; юниты таймера для CLI; временный скрипт хоста (как на проде с 2026-11-08); раздел README; протокол учения 2026-11-08.
- **Готово, когда:** `bash scripts/check.sh` зелёный; `docker build backend` проходит, `pg_dump --version` в образе — 16.
- **Оценка:** 0,5 дня
- **Попытки:** 0
