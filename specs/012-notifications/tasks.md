# Tasks: Упоминания и уведомления (фича 012)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия
- Spec APPROVED 2026-11-08. ID — `N12-Tnn`; рамки: `python scripts/task_scope.py N12-Tnn`.
- Не трогать: `CLAUDE.md`, `AGENTS.md`, `docs/adr/**`, `spec.md`, применённые миграции. БД — `*_test`.
- Оценка пакета: ~4 дня.

## N12-T01 — Схема и разбор упоминаний
- **Статус:** TODO · **AC:** AC-2 · **Оценка:** 0,5 дня
- **Файлы:** `backend/app/domain/notifications/__init__.py`, `backend/app/domain/notifications/models.py`, `backend/app/domain/notifications/mentions.py`, `backend/app/domain/registry.py`, `backend/migrations/versions/0013_notifications.py`, `docs/data-model.md`, `backend/tests/unit/test_012_mentions.py`, `backend/tests/db/test_012_schema.py`, `backend/tests/db/test_migrations.py`, `backend/tests/db/test_007_schema.py`, `backend/tests/upgrade002_support.py`

## N12-T02 — Правила создания уведомлений
- **Статус:** TODO · **AC:** AC-1, AC-3, AC-4 · **Оценка:** 1 день · **Зависит от:** N12-T01
- **Файлы:** `backend/app/domain/notifications/producer.py`, `backend/app/domain/notifications/mentions.py` (общий `LOGIN_RE`), `backend/app/domain/tasks/service.py`, `backend/app/domain/comments/service.py`, `backend/tests/domain/test_012_producer.py`

## N12-T03 — Список, счётчик, прочтение (API)
- **Статус:** TODO · **AC:** AC-6, AC-7 · **Оценка:** 0,75 дня · **Зависит от:** N12-T02
- **Файлы:** `backend/app/domain/notifications/queries.py`, `backend/app/api/v1/notifications.py`, `backend/app/api/v1/schemas/notifications.py`, `backend/app/api/v1/__init__.py`, `backend/tests/api/test_012_notifications.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`

## N12-T04 — `gtrack notify-due` и таймер
- **Статус:** TODO · **AC:** AC-5 · **Оценка:** 0,5 дня · **Зависит от:** N12-T02
- **Файлы:** `backend/app/domain/notifications/due.py`, `backend/app/cli/commands/notify_due.py`, `backend/app/cli/main.py`, `deploy/backup/gtrack-notify-due.service`, `deploy/backup/gtrack-notify-due.timer`, `backend/tests/cli/test_012_notify_due.py`

## N12-T05 — Интерфейс: значок, список, подсказка `@`
- **Статус:** TODO · **AC:** AC-8, FR-2 · **Оценка:** 1,25 дня · **Зависит от:** N12-T03
- **Файлы:** `frontend/src/features/notifications/{NotificationsPage.tsx,Badge.tsx,api.ts}`, `frontend/src/app/router.tsx`, `frontend/src/features/comments/Comments.tsx`, `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/notifications/*.test.tsx`, `backend/tests/infra/test_frontend_scaffold.py`
