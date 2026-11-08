# Tasks: «Сводка» (фича 008), короткая версия F1a–F1d

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия
- Источник истины — `spec.md` (короткая: F1a–F1d). Старт кода — после статуса APPROVED и ответов на открытые Q-n,
  которые блокируют задачу (поле «Блокер»).
- ID задач с префиксом `S08-`. Проверка рамок: `python scripts/task_scope.py S08-Tnn`.
- Не трогать: `CLAUDE.md`, `AGENTS.md`, `docs/adr/**`, `specs/008-summary/spec.md`, применённые миграции.
- Тесты: `test_008_*`; БД — только `*_test` (`TEST_DATABASE_URL=…/tracker_test`). Сеть не используется.
- Проверки: `bash scripts/check.sh`.
- Оценка пакета: ~2,5 дня разработки (S08-T01…T05) + ревью.

## S08-T01 — Пресеты срока и «Горит»
- **Статус:** TODO
- **AC:** AC-6, AC-7, AC-8 (unit-часть)
- **Файлы:** `backend/app/domain/overview/__init__.py`, `backend/app/domain/overview/due.py`, `backend/tests/unit/test_008_due.py`
- **Зависит от:** —
- **Блокер (частично):** Q-14 (`done` в «Сегодня», «Завтра», «На этой неделе»), Q-4 («На этой неделе»: текущий текст
  или пн–вс), Q-18 (`done` в «Горит»). Можно начинать; открытые правила держать в одной функции, чтобы ответ менял один файл.
- **Описание:** `DuePreset`, `due_condition(preset, today)`, `is_hot(...)`; «На этой неделе» = `сегодня…воскресенье`;
  граница суток через `today_msk`; без БД.
- **Готово, когда:** `pytest -q backend/tests/unit/test_008_due.py` зелёный.
- **Оценка:** 0,5 дня
- **Попытки:** 0

## S08-T02 — Счётчики и выборка (домен)
- **Статус:** TODO
- **AC:** AC-1…AC-5, AC-9
- **Файлы:** `backend/app/domain/overview/queries.py`, `backend/tests/api/test_008_overview.py`
- **Зависит от:** S08-T01
- **Блокер (частично):** Q-7 (статус — одно значение или мультивыбор) — влияет на тип `OverviewFilter.status`.
- **Описание:** базовая выборка задач сводки (PS-1), `overview_counts` (PS-2), `overview_tasks` с фильтрами
  проект/статус/приоритет/пресет/`needs_review`, `total` и `hot`.
- **Готово, когда:** доменные тесты AC-1…AC-5, AC-9 зелёные.
- **Оценка:** 0,5 дня
- **Попытки:** 0

## S08-T03 — API
- **Статус:** TODO
- **AC:** AC-10, AC-11; API-части AC-1…AC-9
- **Файлы:** `backend/app/api/v1/overview.py`, `backend/app/api/v1/schemas/overview.py`, `backend/app/api/v1/__init__.py`,
  `backend/tests/api/test_008_overview.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`.
  Миграций нет.
- **Зависит от:** S08-T02
- **Блокер:** —
- **Описание:** два эндпоинта под `/api/v1/me/overview*`; 401/403/404/422; OpenAPI — `bash scripts/gen-api.sh`.
- **Готово, когда:** `pytest -q backend/tests/api/test_008_overview.py` зелёный, линтер и mypy чистые.
- **Оценка:** 0,5 дня
- **Попытки:** 0

## S08-T04 — Экран «Сводка»
- **Статус:** TODO
- **AC:** AC-12, AC-13, FR-1, FR-2…FR-12 (фронт), NFR-3
- **Файлы:** `frontend/src/features/overview/SummaryPage.tsx`, `frontend/src/features/overview/api.ts`,
  `frontend/src/features/overview/filters.ts`, `frontend/src/features/overview/SummaryPage.test.tsx`,
  `frontend/src/app/router.tsx`, `frontend/src/shared/i18n/ru.ts`, `frontend/src/shared/ui/ui.css`,
  `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** S08-T03
- **Блокер:** Q-9 (положение и акцент плитки «Нужно проверить»). Макет `Shared/Design/summary-r2-design.md`
  проверить на соответствие спеке до старта — решение оркестратора.
- **Описание:** плитки; фильтры: проект, статус, приоритет (мультивыбор), пресеты срока (`aria-pressed`);
  список/карточки на 360 px; «Показано N из M»; пустое состояние; опрос 15 с; пункт меню.
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` зелёный.
- **Оценка:** 0,75 дня
- **Попытки:** 0

## S08-T05 — Приёмка
- **Статус:** TODO
- **AC:** все, кроме AC-14 (замер в T-10)
- **Файлы:** `docs/acceptance/mvp-demo.md`, `specs/008-summary/reviews/FINAL-acceptance.md`
- **Зависит от:** S08-T04
- **Описание:** сценарии «Сводки» в чек-листе ручной приёмки; финальный отчёт по AC.
- **Готово, когда:** `bash scripts/check.sh` зелёный, отчёт записан.
- **Оценка:** 0,25 дня
- **Попытки:** 0
