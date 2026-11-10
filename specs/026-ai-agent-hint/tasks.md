# Tasks: Карточка «Подключить ИИ-агента» (026)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор. Spec DRAFT: задачи не берутся до APPROVED.

## Общие условия
- ID — `H26-Tnn`; рамки: `python scripts/task_scope.py H26-Tnn`. Не трогать `CLAUDE.md`, `AGENTS.md`, `spec.md`, применённые миграции, общий `ui.css`. ADR-0024 переводится в «принято» владельцем.
- БД — только `*_test`. Проверка: `bash scripts/check.sh`. Оценка пакета ≈ 2 дня.

## H26-T01 — Таблица и функции подсказок
- **Статус:** TODO · **AC:** AC-10 · **Оценка:** 0,25 дня
- **Файлы:** `backend/migrations/versions/0014_user_hint_dismissal.py`, `backend/app/domain/users/hints.py`, `backend/app/domain/registry.py`, `docs/data-model.md`, `backend/tests/db/test_026_schema.py`, `backend/tests/db/test_migrations.py`, `backend/tests/db/test_007_schema.py`, `backend/tests/upgrade002_support.py`
- **Готово, когда:** upgrade/downgrade проходят; номер миграции свериться с `docs/adr/REGISTRY.md`.

## H26-T02 — API: `GET /me` и dismiss/restore
- **Статус:** TODO · **AC:** AC-2, AC-3, AC-5, AC-6 · **Оценка:** 0,5 дня · **Зависит от:** H26-T01
- **Файлы:** `backend/app/api/v1/schemas/auth.py`, `backend/app/api/v1/me.py`, `backend/app/api/v1/hints.py`, `backend/app/api/v1/__init__.py`, `backend/tests/api/test_026_hints.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`
- **Готово, когда:** API-тесты зелёные; `gen-api.sh` без дифа.

## H26-T03 — Карточка на «Сводке»
- **Статус:** TODO · **AC:** AC-1, AC-4, AC-7, AC-8, AC-9 · **Оценка:** 0,75 дня · **Зависит от:** H26-T02
- **Файлы:** `frontend/src/features/overview/AiAgentHint.tsx`, `frontend/src/features/overview/SummaryPage.tsx`, `frontend/src/features/overview/summary.css`, `frontend/src/features/auth/session.ts` (тип профиля), `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/overview/AiAgentHint.test.tsx`, `backend/tests/infra/test_frontend_scaffold.py`
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` зелёный; макеты `ai-card-*` сверены на 1280 и 360.

## H26-T04 — Возврат подсказки и инструкция (решение Q-2, Q-3)
- **Статус:** TODO · **AC:** AC-6 · **Оценка:** 0,25 дня (+0,5 дня, если Q-3 — блок/страница в приложении) · **Зависит от:** H26-T03
- **Файлы:** `frontend/src/features/auth/ProfilePage.tsx`, `frontend/src/features/tokens/AgentAccessPage.tsx`, `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/tokens/*`
- **Готово, когда:** кнопка «Показать снова» работает; инструкция доступна по решению Q-3.

## H26-T05 — Приёмка
- **Статус:** TODO · **AC:** все · **Оценка:** 0,25 дня · **Зависит от:** H26-T04
- **Файлы:** `docs/acceptance/mvp-demo.md`, `specs/026-ai-agent-hint/reviews/FINAL-acceptance.md`
- **Готово, когда:** `bash scripts/check.sh` зелёный, отчёт по AC записан.
