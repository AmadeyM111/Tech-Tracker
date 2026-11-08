# Tasks: «Сводка» (фича 008)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия
- Источник истины — `spec.md`; старт кода — после статуса APPROVED и ответов на открытые Q-n, которые блокируют задачу (поле «Блокер»).
- ID задач с префиксом `S08-`. Проверка рамок: `python scripts/task_scope.py S08-Tnn`.
- Не трогать: `CLAUDE.md`, `AGENTS.md`, `docs/adr/**`, `specs/008-summary/spec.md`, применённые миграции.
- Тесты: `test_008_*`; БД — только `*_test` (`TEST_DATABASE_URL=…/tracker_test`). Сеть не используется.
- Проверки: `bash scripts/check.sh`. Оценка всего пакета: ~4 дня разработки (S08-T01…T05) + ревью.

## S08-T01 — Пресеты срока, диапазон дат и «Горит»
- **Статус:** TODO
- **AC:** AC-6, AC-7, AC-8, AC-15 (unit-часть)
- **Файлы:** `backend/app/domain/overview/__init__.py`, `backend/app/domain/overview/due.py`, `backend/tests/unit/test_008_due.py`
- **Зависит от:** —
- **Блокер (частично):** Q-12 (пресет вместе с диапазоном), Q-13 (пустая граница), Q-14 (`done` в «Сегодня», «Завтра», «На этой неделе»). Пресеты и `is_hot` можно начинать; правила сочетания — после ответа.
- **Описание:** `DuePreset`, `due_condition(preset, due_from, due_to, today)`, `is_hot(...)` (статус `done` не горит, Q-3); «На этой неделе» = `сегодня…воскресенье`; граница суток через `today_msk`; без БД.
- **Готово, когда:** `pytest -q backend/tests/unit/test_008_due.py` зелёный.
- **Оценка:** 0,75 дня
- **Попытки:** 0

## S08-T02 — Счётчики и выборка (домен)
- **Статус:** TODO
- **AC:** AC-1…AC-5, AC-9, AC-15 (доменная часть)
- **Файлы:** `backend/app/domain/overview/queries.py`, `backend/tests/api/test_008_overview.py`
- **Зависит от:** S08-T01
- **Блокер (частично):** Q-15 — для ветки выборки CSV (`params=None`, лимит строк).
- **Описание:** базовая выборка задач сводки (PS-1), `overview_counts` (PS-2), `overview_tasks` с фильтрами, диапазоном дат, `total` и `hot`.
- **Готово, когда:** доменные тесты AC-1…AC-5, AC-9, AC-15 зелёные.
- **Оценка:** 0,75 дня
- **Попытки:** 0

## S08-T03 — API, CSV и аудит выгрузки
- **Статус:** TODO
- **AC:** AC-1…AC-11, AC-16…AC-19
- **Файлы:** `backend/app/api/v1/overview.py`, `backend/app/api/v1/schemas/overview.py`, `backend/app/api/v1/__init__.py`, `backend/app/domain/overview/csv.py`, `backend/tests/api/test_008_overview.py`, `backend/tests/api/test_008_overview_csv.py`, `backend/tests/unit/test_008_csv.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`. Миграция — только по Q-16 (`0011+`, номер по REGISTRY).
- **Зависит от:** S08-T02
- **Блокер:** Q-15 (лимит и вид выборки CSV), Q-16 (тип сущности аудита и место для числа строк), Q-17 (экранирование ячеек).
- **Описание:** два эндпоинта под `/api/v1/me/overview*` и `GET /api/v1/me/overview/tasks.csv` (только БА); 401/403/404/422; `render_csv`: BOM, «;», колонки FR-13; событие аудита выгрузки (FR-14); OpenAPI — `bash scripts/gen-api.sh`.
- **Готово, когда:** `pytest -q backend/tests/api/test_008_overview.py backend/tests/api/test_008_overview_csv.py backend/tests/unit/test_008_csv.py` зелёный, линтер и mypy чистые.
- **Оценка:** 1 день
- **Попытки:** 0

## S08-T04 — Экран «Сводка»
- **Статус:** TODO
- **AC:** AC-12, AC-13, FR-1, FR-10, FR-12, FR-13 (кнопка «Скачать CSV» видна только БА), NFR-3
- **Файлы:** `frontend/src/features/overview/SummaryPage.tsx`, `frontend/src/features/overview/api.ts`, `frontend/src/features/overview/filters.ts`, `frontend/src/features/overview/SummaryPage.test.tsx`, `frontend/src/app/router.tsx`, `frontend/src/shared/i18n/ru.ts`, `frontend/src/shared/ui/ui.css`, `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** S08-T03
- **Блокер:** Q-9 (положение и акцент плитки «Нужно проверить»). Макет `Shared/Design/summary-r2-design.md` и `Shared/Design/gtrack-summary/` нужно обновить: кнопка «Скачать CSV» и диапазон дат сейчас помечены R3. Обновление макета — решение оркестратора до старта задачи.
- **Описание:** плитки, фильтры (чекбоксы приоритета, пресеты `aria-pressed`, диапазон «с/по» с проверкой «с» ≤ «по»), кнопка «Скачать CSV» для БА, список/карточки на 360 px, «Показано N из M», пустое состояние, опрос 15 с, пункт меню.
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` зелёный.
- **Оценка:** 1,25 дня
- **Попытки:** 0

## S08-T05 — Приёмка
- **Статус:** TODO
- **AC:** все, кроме AC-14 (замер в T-10)
- **Файлы:** `docs/acceptance/mvp-demo.md`, `specs/008-summary/reviews/FINAL-acceptance.md`
- **Зависит от:** S08-T04
- **Описание:** сценарии «Сводки» и выгрузки CSV в чек-листе ручной приёмки; финальный отчёт по AC.
- **Готово, когда:** `bash scripts/check.sh` зелёный, отчёт записан.
- **Оценка:** 0,25 дня
- **Попытки:** 0
