# Tasks: «Сводка» — диапазон дат (024)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор. Spec APPROVED 2026-11-10.

## Общие условия
- ID — `D24-Tnn`; рамки: `python scripts/task_scope.py D24-Tnn`. Не трогать `CLAUDE.md`, `AGENTS.md`, `docs/adr/**`, `spec.md`, применённые миграции, общий `ui.css`.
- БД — только `*_test`. Проверка: `bash scripts/check.sh`. Оценка пакета ≈ 1,75 дня.

## D24-T01 — Условие диапазона (домен)
- **Статус:** TODO · **AC:** AC-1, AC-2, AC-3, AC-5 · **Оценка:** 0,25 дня
- **Файлы:** `backend/app/domain/overview/due.py`, `backend/app/domain/overview/queries.py`, `backend/tests/unit/test_024_range.py`
- **Готово, когда:** `pytest -q backend/tests/unit/test_024_range.py` зелёный.

## D24-T02 — Параметры API и проверки
- **Статус:** TODO · **AC:** AC-1…AC-6 · **Оценка:** 0,5 дня · **Зависит от:** D24-T01
- **Файлы:** `backend/app/api/v1/schemas/overview.py`, `backend/app/api/v1/overview.py`, `backend/tests/api/test_024_range.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`
- **Готово, когда:** API-тесты зелёные; `bash scripts/gen-api.sh` без дифа после коммита.

## D24-T03 — Интерфейс «с / по»
- **Статус:** TODO · **AC:** AC-7, AC-8, AC-9 · **Оценка:** 0,75 дня · **Зависит от:** D24-T02
- **Файлы:** `frontend/src/features/overview/filters.ts`, `frontend/src/features/overview/api.ts`, `frontend/src/features/overview/SummaryPage.tsx`, `frontend/src/features/overview/summary.css`, `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/overview/DateRange.test.tsx`, `backend/tests/infra/test_frontend_scaffold.py` (если появятся новые файлы)
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` зелёный; макеты `range-*` сверены на 1280 и 360.

## D24-T04 — Замер и приёмка
- **Статус:** TODO · **AC:** все · **Оценка:** 0,25 дня · **Зависит от:** D24-T03
- **Файлы:** `scripts/explain_r2_queries.py`, `docs/acceptance/mvp-demo.md`, `specs/024-summary-date-range/reviews/FINAL-acceptance.md`
- **Готово, когда:** `bash scripts/check.sh` зелёный, отчёт по AC записан.
