# Контекст 007: AI-агент как пользователь трекера (выжимка scout, 2026-10-28)

## Бэкенд
- FastAPI + SQLAlchemy 2 async + Alembic + Pydantic v2, Python >=3.12. Роутеры `/api/v1` (`backend/app/api/v1/__init__.py:18`); слои api / domain / core.
- Задачи: `backend/app/domain/tasks/models.py`. Статусы: todo / in_progress / review / done. Приоритеты: low / medium / high. Soft delete (`deleted_at`). Поля `closed_at` нет: закрытие = `status=done`.
- Переходы статусов не ограничены (`tasks/service.py:275`).
- Эндпоинты (`api/v1/tasks.py`): список проекта `:78`, создать `:93`, `/me/tasks` `:107`, получить `:116`, PATCH `:122` (в т.ч. статус), DELETE `:133`, подзадача `:145`. Перенос на доске со сменой статуса: `api/v1/boards.py:49`, сервис `tasks/service.py:430`.
- Проекты: `api/v1/projects.py`. Отдельного CRUD досок нет.
- Обязательные поля верхней задачи (006/ADR-0014): title, description (не пусто), due_date (не раньше сегодня, Europe/Moscow), исполнитель (по умолчанию создатель). Подзадача: достаточно title. Схема `api/v1/schemas/tasks.py:49-71`, `extra="forbid"`.
- Ошибки: `{"detail","code"}` (`core/errors.py`).

## Роли и права (002)
- Роли TECH_ADMIN, BUSINESS_ADMIN, USER (`domain/access/roles.py`, `policy.py`). ТА не имеет доступа к задачам.
- USER: создаёт/правит полностью только свои задачи (создатель = исполнитель = он); статус может менять, если исполнитель. BA-участник: любые задачи проекта, назначение других.
- Отдельной роли «агент» нет; права агента = права его учётки.

## Аутентификация и аудит
- Только cookie-сессии `gt_session` (HMAC, простой 8 ч, абсолют 7 сут), `deps.py:48 get_actor`. Заголовка Authorization, API-ключей, сервисных пользователей, webhook нет.
- Агента можно завести только как обычного пользователя (ТА создаёт учётку, пароль 12+ символов, смена при первом входе, блокировка после 5 неудач).
- CSRF: `deps.py:158 check_origin` (без Origin проверка не применяется).
- События: `domain/events/` (`actor_id`), `task.*` в ленте; входят ли в журнал аудита — не проверено.

## Интеграции
- MCP, агентских эндпоинтов, SDK нет. OpenAPI: `docs/api/openapi.json`, `scripts/gen-api.sh`.

## Команды и окружение
- venv `.venv`; тесты `pytest -q backend/tests` (`TEST_DATABASE_URL=...tracker_test`); полная проверка `bash scripts/check.sh` (ruff, ruff format, mypy strict, alembic upgrade/check, pytest, фронт).
- Миграции: голова `0007`. Новая модель — миграция в том же коммите.

## Ограничения
- Новые зависимости только по plan.md и allowlist (`backend/tests/arch/test_dependencies_allowlist.py:13-22`); MCP SDK там нет.
- Роутер без бизнес-логики, права в сервисе, 403 от бэкенда, мультиарендность по `workspace_id`.
- Ломающие изменения API — ADR (последний 0014).
- Код/коммиты на английском; docs и UI на русском. Секреты только в `.env`.
- Не выполнялось: проверка версии Python в .venv, прогон check.sh.
