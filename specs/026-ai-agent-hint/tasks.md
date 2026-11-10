# Tasks: Карточка «Подключить ИИ-агента» (026)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор. Spec APPROVED 2026-11-10.

## Общие условия
- ID — `H26-Tnn`; рамки: `python scripts/task_scope.py H26-Tnn`. Не трогать `CLAUDE.md`, `AGENTS.md`, `spec.md`, `docs/adr/**`, общий `ui.css`. Миграций и изменений API нет.
- Проверка: `bash scripts/check.sh`. Оценка пакета ≈ 1,25 дня.

## H26-T01 — Карточка и хранение закрытия
- **Статус:** TODO · **AC:** AC-1, AC-2, AC-3, AC-4, AC-6, AC-8 · **Оценка:** 0,75 дня
- **Файлы:** `frontend/src/features/overview/AiAgentHint.tsx`, `frontend/src/features/overview/hintStorage.ts`, `frontend/src/features/overview/SummaryPage.tsx`, `frontend/src/features/overview/summary.css`, `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/overview/AiAgentHint.test.tsx`, `backend/tests/infra/test_frontend_scaffold.py`
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` зелёный; макеты `ai-card-*` сверены на 1280 и 360.

## H26-T02 — Блок «Инструкция для Claude Code»
- **Статус:** TODO · **AC:** AC-7 · **Оценка:** 0,25 дня · **Зависит от:** H26-T01
- **Файлы:** `frontend/src/features/tokens/AgentAccessPage.tsx`, `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/tokens/*`
- **Готово, когда:** блок и якорь есть; текст совпадает с разделом Claude Code из `docs/ai-integration.md`.

## H26-T03 — Приёмка
- **Статус:** TODO · **AC:** все · **Оценка:** 0,25 дня · **Зависит от:** H26-T02
- **Файлы:** `docs/acceptance/mvp-demo.md`, `specs/026-ai-agent-hint/reviews/FINAL-acceptance.md`
- **Готово, когда:** `bash scripts/check.sh` зелёный, отчёт по AC записан.
