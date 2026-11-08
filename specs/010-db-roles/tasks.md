# Tasks: Роли БД и защита журнала (фича 010)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия
- Источник истины — `spec.md`, решения — `plan.md` (PR-n). ID — `D10-Tnn`; рамки:
  `python scripts/task_scope.py D10-Tnn`.
- Не трогать: `CLAUDE.md`, `AGENTS.md`, `docs/adr/**`, `spec.md`, применённые миграции.
- Только БД `*_test`; тестовые роли — уникальные имена, удаляются. Пароль роли — не в выводе и логах.
- Проверки: `bash scripts/check.sh`. Оценка пакета: ~1,5 дня.

## D10-T01 — Пароль, SCRAM и роль
- **Статус:** TODO
- **AC:** AC-1, AC-2, AC-3, AC-5, AC-6 (часть)
- **Файлы:** `backend/app/core/config.py`, `backend/app/core/db.py` (`create_engine(url=)`), `backend/app/core/db_roles.py`, `backend/tests/unit/test_010_scram.py`, `backend/tests/db/test_010_app_role.py`
- **Зависит от:** —
- **Описание:** PR-3, PR-4; `ensure_app_password`, `scram_verifier`, `ensure_app_role`, `app_database_url`.
- **Готово, когда:** тесты зелёные.
- **Оценка:** 0,75 дня
- **Попытки:** 0

## D10-T02 — Bootstrap и API под рабочей ролью
- **Статус:** TODO
- **AC:** AC-4, AC-6, AC-7
- **Файлы:** `backend/app/cli/commands/bootstrap.py`, `backend/app/main.py`, `docker-compose.yml`, `README.md`, `backend/tests/api/test_010_api_runs_as_app_role.py`, `backend/tests/cli/test_010_bootstrap_role.py`, `backend/tests/unit/test_010_scram.py`, `backend/tests/infra/test_compose_static.py`
- **Зависит от:** D10-T01
- **Описание:** bootstrap создаёт пароль и роль под блокировкой; lifespan строит движок по роли (PR-5); compose передаёт `DB_APP_ROLE`; README — переход.
- **Готово, когда:** `bash scripts/check.sh` зелёный.
- **Оценка:** 0,75 дня
- **Попытки:** 0
