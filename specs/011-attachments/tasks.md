# Tasks: Вложения (фича 011)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия
- Spec APPROVED 2026-11-08. ID — `A11-Tnn`; рамки: `python scripts/task_scope.py A11-Tnn`.
- Не трогать: `CLAUDE.md`, `AGENTS.md`, `docs/adr/**`, `spec.md`, применённые миграции.
- Тестовые файлы — синтетические (сигнатуры), без реальных документов. БД — `*_test`.
- Оценка пакета: ~4 дня.

## A11-T01 — Модель, миграция 0012, определение типа
- **Статус:** TODO · **AC:** AC-2, AC-6 · **Оценка:** 0,75 дня
- **Файлы:** `backend/app/domain/attachments/__init__.py`, `backend/app/domain/attachments/models.py`, `backend/app/domain/attachments/types.py`, `backend/app/domain/registry.py`, `backend/migrations/versions/0012_attachments.py`, `docs/data-model.md`, `backend/tests/unit/test_011_types.py`, `backend/tests/attachments_support.py`, `backend/tests/db/test_011_schema.py`, `backend/tests/db/test_migrations.py`, `backend/tests/db/test_007_schema.py`, `backend/tests/upgrade002_support.py`

## A11-T02 — Хранилище и сервис
- **Статус:** TODO · **AC:** AC-1, AC-3, AC-4, AC-7, AC-8, AC-9 · **Оценка:** 1 день · **Зависит от:** A11-T01
- **Файлы:** `backend/app/domain/attachments/storage.py`, `backend/app/domain/attachments/service.py`, `backend/app/domain/attachments/queries.py`, `backend/app/core/config.py`, `backend/app/core/errors.py`, `backend/app/domain/activity/service.py` (имя файла в ленте, Q-4), `backend/tests/unit/test_011_storage.py`, `backend/tests/api/test_011_attachments.py`

## A11-T03 — API и отдача
- **Статус:** TODO · **AC:** AC-1…AC-9 · **Оценка:** 0,75 дня · **Зависит от:** A11-T02
- **Файлы:** `backend/app/api/v1/attachments.py`, `backend/app/api/v1/schemas/attachments.py`, `backend/app/api/v1/__init__.py`, `backend/app/api/openapi.py` (описания 413/507), `backend/tests/api/test_011_attachments.py`, `backend/tests/cli/test_openapi.py` (400 — только у JSON-тела; загрузка — octet-stream), `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`

## A11-T04 — Очистка, экспорт и импорт файлов
- **Статус:** TODO · **AC:** AC-7, AC-10 · **Оценка:** 0,75 дня · **Зависит от:** A11-T02
- **Файлы:** `backend/app/domain/attachments/purge.py`, `backend/app/domain/ops/maintenance.py`, `backend/app/domain/ops/export.py`, `backend/app/domain/ops/importer.py`, `backend/app/domain/ops/archive.py`, `backend/tests/cli/test_011_maintenance.py`, `backend/tests/cli/test_export_import.py`

## A11-T05 — Интерфейс карточки
- **Статус:** TODO · **AC:** AC-11 · **Оценка:** 0,75 дня · **Зависит от:** A11-T03
- **Файлы:** `frontend/src/features/attachments/Attachments.tsx`, `frontend/src/features/attachments/api.ts`, `frontend/src/features/tasks/TaskPage.tsx`, `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/attachments/Attachments.test.tsx`, `backend/tests/infra/test_frontend_scaffold.py`
