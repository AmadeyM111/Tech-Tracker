# Plan: AI Native — подключение агентов через MCP (фича 020)

- **Spec:** `specs/020-mcp-ai-native/spec.md` (APPROVED 2026-11-07)
- **Решения:** `docs/adr/0018-mcp-agent-access.md`
- **Статус:** DRAFT, ждёт контрольной точки 2

## 1. Подход в двух словах
Агент ходит в трекер по протоколу MCP. Инструменты MCP — тонкий адаптер над существующими
доменными сервисами (`domain/tasks`, `domain/projects`, `domain/comments`). Правила прав не
дублируются: они работают так же, как для REST. Токен — персональный, принадлежит пользователю
и даёт его права. Есть два транспорта: HTTP `/mcp` и stdio через `gtrack mcp`, который
пересылает вызовы на `/mcp`. Так логика существует в одном месте.

## 2. Решения фичи (PN-n)
- **PN-1. Токен.** Формат `gtrk_` + 32 байта из `secrets.token_urlsafe`. В БД — SHA-256 hex (`token_hash`,
  уникальный индекс). Срок 90 дней (`expires_at`), максимум 10 активных на пользователя. Сравнение —
  через поиск по хешу, поэтому timing-атаки на сравнение строк не применимы.
- **PN-2. Где принимается токен.** Только `POST/GET /mcp`. Зависимость `get_actor` для REST не меняется:
  cookie-only. Маршруты `/api/v1/me/tokens*` используют cookie-зависимость и отвергают заголовок
  `Authorization`, чтобы токен не выпускал токены.
- **PN-3. Субъект агента.** `Actor` строится так же, как в `get_actor`: та же проверка блокировки,
  `must_change_password` и роли (`WorkspaceMember`). Для `must_change_password=True` или роли «без роли»
  инструменты отвечают ошибкой, а не выполняют действие. Поле `Actor.session_id` для токена —
  `None`, а новое поле `Actor.client_name` (имя токена) передаётся в `record_event`.
- **PN-4. Отзыв.** `revoke_token` ставит `revoked_at`. `block_user` (`domain/users/service.py`)
  дополнительно ставит `revoked_at` у всех активных токенов пользователя (в той же транзакции).
- **PN-5. Аудит токенов.** Новые действия `user.token_created`, `user.token_revoked` с `audit=True`,
  `entity_type=user`, `entity_id` = id владельца; `details` не нужны (имя токена не пишется в аудит,
  только в ленту задач через `client_name`). Это дополнение ADR-0006, не замена.
- **PN-6. Атрибуция.** Колонка `domain_event.client_name` (text, nullable, ≤ 64 символов,
  проверка на границе: пустая строка и управляющие символы отвергаются, Fail Fast). `record_event`
  получает необязательный аргумент `client_name`. Лента проекта (`domain/activity`) отдаёт поле
  `via_client` (null для веб-действий). Старые записи не меняются.
- **PN-7. Транспорт HTTP.** Используется Streamable HTTP из `mcp` в stateless-режиме (одна транзакция на
  запрос, без сессий на сервере). Монтирование: под `/mcp` на уровне FastAPI, с `check_origin`
  (FR-9): `Origin` отсутствует → разрешено (не браузер); присутствует и не совпадает с Host → 403.
  Проверку выполняет T07 через спайк (см. PN-9).
- **PN-8. Транспорт stdio.** `gtrack mcp` читает `GTRACK_URL` (по умолчанию `https://localhost:<HTTPS_PORT>`),
  `GTRACK_TOKEN` и необязательный `GTRACK_CA_FILE` (self-signed сертификат по ADR-0004). Токен берётся
  только из окружения, в аргументах командной строки не принимается (не попадает в историю shell).
- **PN-9. Зависимость `mcp`.** **Обновлено спайком M20-T01 (2026-11-08): `mcp>=1.30,<2`**, см. `reviews/M20-T01-spike.md`. Исходная формулировка: версия `mcp>=2.3,<3` (PyPI, MIT, Python ≥ 3.10; проверено
  `pip download` 2026-11-07). Транзитивные зависимости, которые она тянет: starlette, uvicorn,
  sse-starlette, pydantic, httpx2, pyjwt[crypto], opentelemetry-api, jsonschema, python-multipart,
  anyio, typing-extensions. Вес значительный, поэтому T01 — спайк: фиксирует фактический API
  Streamable HTTP и stdio/клиента, и проверяет, что `pyjwt`/`opentelemetry` не требуют настройки.
  Если спайк покажет, что 2.x неудобна, сначала возвращаемся сюда (на 1.x), а не меняем план молча.
- **PN-10. Инструменты R1** (имена — `snake_case`, описания — на русском в `tools/list`):
  - `list_my_tasks` (`queries.list_my_tasks`), `list_project_tasks` (`queries.list_project_tasks`),
    `get_task` (`queries.get_task`), `create_task` (`service.create_task`, `create_subtask` для
    подзадач), `update_task` (`service.update_task`), `move_task` — не в R1 (зависит от T78 доски).
  - `list_projects` (`projects.queries.list_projects`), `get_project` (`projects.queries.get_project`).
  - `list_comments` (`comments.service.list_comments`), `add_comment` (`comments.service.create_comment`).
  - Удаление, перенос владения, участники, роли, учётные записи, CRM — не открываются (spec §6).
- **PN-11. Фильтр `tools/list` (FR-6).** Инструмент показывается, если capability, нужная сервису,
  есть у роли владельца. Для задач и проектов — `BUSINESS_ACCESS`; при отсутствии — инструмент
  скрыт. Объектные проверки остаются в сервисах.
- **PN-12. Ошибки.** Доменные `AppError` превращаются в результат инструмента `isError=true` с
  текстом JSON `{"detail": ..., "code": ...}` (тот же формат, что и REST). Неожиданные исключения
  — `internal_error` без трассировки в ответе; в лог пишется только тип.
- **PN-13. Слои.** MCP-код живёт в `backend/app/api/mcp/` (адаптер, как роутеры): `server.py`
  (сборка сервера и маршрут), `auth.py` (токен → Actor), `tools/*.py` (адаптеры по доменам),
  `errors.py`. Логики в `domain/` не появляется, кроме `domain/tokens/`.
- **PN-14. Домен токенов.** `backend/app/domain/tokens/` — `models.py` (ORM `ApiToken`),
  `service.py` (`create_token`, `list_tokens`, `revoke_token`, `resolve_token`, `revoke_all_for_user`).
  Все запросы фильтруются по `workspace_id` (AGENTS.md, мультиарендность).
- **PN-15. Фронтенд.** Раздел «Доступ для агентов» в профиле пользователя (`features/tokens/`).
  Список (имя, создан, срок, последнее использование), создание (показ токена один раз, кнопка
  «Скопировать»), отзыв. Строки — только в `ru.ts`. Новые файлы — в белом списке
  `test_frontend_scaffold.py`. Типы — из OpenAPI (`gen-api.sh`).
- **PN-16. Документация.** `docs/ai-integration.md` (по-русски): создание токена, фрагменты для
  Claude Code (`claude mcp add`), Codex CLI (`config.toml`), ограничения (ChatGPT — не в R1, ADR-0018).
  README — короткий раздел на двух языках.

## 3. Схема данных (миграция `0009_mcp_agent_access`)
```
api_token(
  id uuid pk, workspace_id uuid fk, user_id uuid fk app_user,
  name text not null check(char_length(name) between 1 and 64),
  token_hash text not null unique,
  created_at timestamptz, expires_at timestamptz, last_used_at timestamptz null,
  revoked_at timestamptz null
)
index (user_id) where revoked_at is null
domain_event.client_name text null check (char_length(client_name) <= 64)
```
Миграции `0001…0008` не меняются (AGENTS.md).

## 4. Интерфейсы (кратко)
- `POST /api/v1/me/tokens` {name} → 201 {id, name, token, expires_at}. Токен только здесь.
- `GET /api/v1/me/tokens` → список без токена и хеша.
- `DELETE /api/v1/me/tokens/{id}` → 204 (идемпотентно для уже отозванного: 204).
- `POST|GET /mcp` — Streamable HTTP, `Authorization: Bearer gtrk_…`. Без токена или с неверным → 401
  `{"detail","code":"not_authenticated"}`. Чужой Origin → 403 `origin_mismatch`.
- `gtrack mcp` — stdio-мост.

## 5. Трассировка AC → задачи
| AC | Задачи |
|---|---|
| AC-1 | M20-T03, M20-T06 |
| AC-2 | M20-T07 |
| AC-3 | M20-T03, M20-T06 |
| AC-4 | M20-T05 |
| AC-5 | M20-T08 |
| AC-6 | M20-T07 |
| AC-7 | M20-T08 |
| AC-8 | M20-T04, M20-T08 |
| AC-9 | M20-T09 (ручная проверка) |
| AC-10 | M20-T07 |
| AC-11 | M20-T01, M20-T12 |
| AC-12 | M20-T11 |
(NFR-1 — M20-T03/T07; NFR-2 — M20-T03/T08; NFR-5 — M20-T01.)

## 6. Риски
- **R-1. Вес `mcp` и совместимость с Python 3.12 venv.** Спайк T01 до любого кода.
- **R-2. Stateless Streamable HTTP внутри FastAPI.** Если SDK требует собственного цикла, используем
  ASGI-монтирование; спайк T01 покажет.
- **R-3. Утечка токена в логах.** Access-лог не пишет заголовки; тест на отсутствие токена в логах (T07).
- **R-4. Регрессия REST.** `get_actor` не меняется; существующие тесты — обязательны.

## 7. Открытые пункты для контрольной точки 2
- Подтвердить PN-5 (токены — в аудит). Альтернатива: не аудировать.
- Подтвердить PN-9 (`mcp` 2.x, вес). Альтернатива: 1.x, если спайк покажет неудобство.
- Подтвердить, что `move_task` (доска) не входит в R1 до T78.
