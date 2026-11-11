# Tasks: Личные проекты «Пользователя» (027)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор. Spec APPROVED 2026-11-11. Этап 1 — P27-T01, P27-T02 (создание проекта и владение), P27-T04 (create_project), P27-T05 (интерфейс создания и пустое состояние); этап 2 — остальное (spec.md §8а).

## Общие условия
- ID — `P27-Tnn`. Не трогать `CLAUDE.md`, `AGENTS.md`, `spec.md` и `docs/adr/**` без одобрения владельца.
- Миграций нет (см. plan.md §3). Проверка: `bash scripts/check.sh` и `cd frontend && npm run lint && npm run typecheck && npm test`.

## P27-T01 — Право создания проекта и управление своим проектом (домен)
- **Статус:** TODO · **AC:** AC-1, AC-2, AC-3, AC-12 · **Зависит от:** ADR-0024 принят, spec APPROVED
- **Файлы:** `backend/app/domain/access/roles.py`, `backend/app/domain/access/policy.py`, `backend/app/domain/projects/queries.py`, `backend/tests/unit/test_policy.py`, `backend/tests/unit/test_role_matrix.py`
- **Готово, когда:** матрица unit-тестов «владелец-П / участник-П / БА» по каждой функции политики зелёная.

## P27-T02 — Участники по логину или email
- **Статус:** TODO · **AC:** AC-4, AC-10 · **Зависит от:** P27-T01 · **Решение:** Q-1, Q-7
- **Файлы:** `backend/app/domain/projects/members.py`, `backend/app/domain/access/recipients.py`, `backend/app/api/v1/schemas/projects.py`, `backend/app/api/v1/projects.py`, `backend/tests/api/test_project_members.py`
- **Готово, когда:** добавление по логину и email работает, незарегистрированный даёт `recipient_not_found`, ограничение частоты работает, OpenAPI перегенерирован.

## P27-T03 — Справочник и видимость для «Пользователя»
- **Статус:** TODO · **AC:** AC-5, AC-6 · **Зависит от:** P27-T01 · **Решение:** Q-8
- **Файлы:** `backend/app/domain/users/directory.py`, `backend/tests/api/test_directory*.py`, `backend/tests/api/test_projects.py`
- **Готово, когда:** для «Пользователя» справочник — только общие проекты; для БА ответ как раньше.

## P27-T04 — Передача владения, удаление и MCP
- **Статус:** TODO · **AC:** AC-7, AC-8, AC-11 · **Зависит от:** P27-T01 · **Решение:** Q-5, Q-6
- **Файлы:** `backend/app/domain/projects/service.py`, `backend/app/api/mcp/tools/projects.py`, `backend/tests/api/test_m20_t08_mcp_tools.py`
- **Готово, когда:** передача владения и удаление работают по FR-7 и FR-8; инструмент `create_project` есть; тест числа инструментов для «Пользователя» обновлён.

## P27-T05 — Интерфейс
- **Статус:** TODO · **AC:** AC-1, AC-2, AC-4 · **Зависит от:** P27-T02, P27-T04
- **Файлы:** `frontend/src/features/projects/*`, `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/projects/*`, `frontend/src/shared/api/schema.d.ts`
- **Готово, когда:** «Создать проект» видна «Пользователю»; владелец-П видит добавление по логину или email; BA-только контролы скрыты для не-владельца.

## P27-T06 — Регрессия и приёмка
- **Статус:** TODO · **AC:** все · **Зависит от:** P27-T01…P27-T05
- **Готово, когда:** `bash scripts/check.sh` зелёный; для каждого пути (список, карточка, задачи, доска, участники, активность, вложения, комментарии, справочник, MCP) есть тест отказа для не-владельца-П; изменённые существующие тесты перечислены в PR.
