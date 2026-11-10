# Tasks: «Сводка» — CSV (025)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор. Spec APPROVED 2026-11-10.

## Общие условия
- ID — `C25-Tnn`; рамки: `python scripts/task_scope.py C25-Tnn`. Не трогать `CLAUDE.md`, `AGENTS.md`, `spec.md`, применённые миграции, общий `ui.css`. ADR-0023 принят вместе со спекой.
- БД — только `*_test`. Проверка: `bash scripts/check.sh`. Оценка пакета ≈ 2,75 дня. Миграций нет.

## C25-T01 — Возможность `export_overview`
- **Статус:** TODO · **AC:** AC-3 · **Оценка:** 0,25 дня
- **Файлы:** `backend/app/domain/access/roles.py`, `backend/tests/unit/test_role_matrix.py`, `backend/tests/api/test_025_csv.py`, `frontend/src/shared/api/schema.d.ts`, `docs/api/openapi.json`
- **Готово, когда:** у БА возможность есть, у Пользователя и ТА нет; `GET /me` её отдаёт.

## C25-T02 — Формирование CSV (чистая функция)
- **Статус:** TODO · **AC:** AC-4, AC-5, AC-6, AC-12 · **Оценка:** 0,5 дня
- **Файлы:** `backend/app/domain/overview/csv.py`, `backend/tests/unit/test_025_csv.py`
- **Готово, когда:** `pytest -q backend/tests/unit/test_025_csv.py` зелёный; разбор `csv.reader(delimiter=";")` возвращает исходные значения.

## C25-T03 — Эндпоинт, лимит, аудит
- **Статус:** TODO · **AC:** AC-1, AC-2, AC-7, AC-8, AC-9, AC-10 · **Оценка:** 1 день · **Зависит от:** C25-T01, C25-T02
- **Файлы:** `backend/app/domain/overview/queries.py`, `backend/app/api/v1/overview.py`, `backend/app/api/v1/schemas/overview.py`, `backend/app/core/config.py`, `backend/app/core/errors.py`, `backend/app/domain/events/catalog.py`, `backend/app/domain/events/writer.py`, `backend/tests/api/test_025_csv.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`, `frontend/src/shared/i18n/ru.ts` (название действия журнала), `docs/data-model.md`, `.env.example`/`README.md` (`CSV_MAX_ROWS`)
- **Готово, когда:** API-тесты зелёные; ruff и mypy чистые; `gen-api.sh` без дифа.

## C25-T04 — Кнопка и состояния на «Сводке»
- **Статус:** TODO · **AC:** AC-11 · **Оценка:** 0,75 дня · **Зависит от:** C25-T03
- **Файлы:** `frontend/src/features/overview/SummaryPage.tsx`, `frontend/src/features/overview/api.ts`, `frontend/src/features/overview/summary.css`, `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/overview/CsvExport.test.tsx`, `backend/tests/infra/test_frontend_scaffold.py` (если новые файлы)
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` зелёный; макеты `csv-*` сверены на 1280 и 360.

## C25-T05 — Приёмка
- **Статус:** TODO · **AC:** все · **Оценка:** 0,25 дня · **Зависит от:** C25-T04
- **Файлы:** `docs/acceptance/mvp-demo.md`, `specs/025-summary-csv-export/reviews/FINAL-acceptance.md`
- **Готово, когда:** ручная проверка «файл открывается в Excel без настроек» записана, `bash scripts/check.sh` зелёный.
