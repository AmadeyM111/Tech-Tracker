# Tasks: AI Native — подключение агентов через MCP (фича 020)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия
- Источник истины — `spec.md` (APPROVED), решения — `plan.md` (PN-n), `docs/adr/0018-mcp-agent-access.md`.
  Противоречие — `PLAN_ISSUE`, ничего не додумывать.
- **ID задач с префиксом `M20-`** (`T01…` заняты в `specs/001-pilot-r1/tasks.md`). Проверка рамок:
  `python scripts/task_scope.py M20-Tnn` (выход 0).
- **Рамки файлов.** Менять только файлы из поля «Файлы». `docs/api/openapi.json` и
  `frontend/src/shared/api/schema.d.ts` — только через `bash scripts/gen-api.sh` и только в задачах, где это указано.
- **Не трогать:** `CLAUDE.md`, `AGENTS.md`, `docs/STATE.md`, `docs/brief/**`, `docs/adr/**` (кроме ADR-0018,
  уже принятого), `specs/020-mcp-ai-native/spec.md`, применённые миграции `0001…0008`.
- **Слои (AGENTS.md).** Роутер и MCP-адаптер: схема → один вызов сервиса → схема ответа. Запросов к БД
  в адаптерах нет. `commit()` в `app/**` запрещён. Ошибки — подклассы `AppError`.
- **Секреты (NFR-1).** Токен, его хеш, пароль — не в логах, исключениях и ответах (кроме однократного
  показа токена при создании). В логах — только тип исключения.
- **Сложность (ruff):** `max-complexity=16`, `max-branches=16`, `max-args=10`, `max-statements=34`.
- **Фронтенд:** строки только из `frontend/src/shared/i18n/ru.ts`; новые файлы — в белом списке
  `backend/tests/infra/test_frontend_scaffold.py::test_t21_src_files_only_expected` в той же задаче.
- **Зависимости:** новая — только `mcp` (PN-9), и только в M20-T01.
- **Тесты.** Новые тесты именуются `test_m20_acN_*` (или `test_m20_<тема>_*`). Существующие assert-ы не
  ослабляются, только дополняются. Сеть и реальный SMTP не используются.
- **БД.** Деструктивные операции — только в `*_test`: `export TEST_DATABASE_URL=postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test`.
- **Команды.** Бэкенд: `ruff check backend && ruff format --check backend && mypy --config-file backend/pyproject.toml backend/app && pytest -q backend/tests`.
  Фронтенд: `cd frontend && npm run lint && npm run typecheck && npm test`.
- **Коммиты** — оркестратор, Conventional Commits, без `git push`.

Порядок: M20-T01 → M20-T02 → M20-T03 → M20-T04 → M20-T05 → M20-T06 → M20-T07 → M20-T08 → M20-T09 →
M20-T10 → M20-T11 → M20-T12. Задачи последовательные (CLAUDE.md, SDD).

---

## M20-T01 — Спайк MCP SDK и зависимость
- **Цель:** зафиксировать фактический API `mcp` 2.x (Streamable HTTP stateless, клиент, stdio), проверить
  установку в `.venv` на Python 3.12 и добавить зависимость.
- **Файлы:** `backend/pyproject.toml`, `backend/tests/test_toolchain.py` (только если там есть список зависимостей),
  `specs/020-mcp-ai-native/reviews/M20-T01-spike.md` (новый, результат спайка).
- **AC:** AC-11 (частично), NFR-5. Установка `pip install -e "backend[dev]"` проходит; `import mcp` работает;
  в спайке записано: имя классов и функций, которые будем вызывать, версия, список транзитивных зависимостей.
- **Тест:** `test_m20_t01_mcp_importable` — импорт нужных классов.
- **Зависит от:** —

## M20-T02 — Миграция и ORM токенов
- **Файлы:** `backend/migrations/versions/0009_mcp_agent_access.py` (новый), `backend/app/domain/tokens/__init__.py` (новый),
  `backend/app/domain/tokens/models.py` (новый), `backend/app/domain/events/models.py`.
- **AC:** схема из plan §3; `alembic upgrade head` и `downgrade -1` проходят на тестовой БД; ограничения
  длины имени и уникальность `token_hash` проверены тестом.
- **Тест:** `test_m20_t02_migration_*`.
- **Зависит от:** M20-T01

## M20-T03 — Домен токенов
- **Файлы:** `backend/app/domain/tokens/service.py` (новый), `backend/app/domain/tokens/__init__.py`,
  `backend/app/domain/events/catalog.py` (только два действия `user.token_created`, `user.token_revoked`
  с аудитом; перенесено из M20-T04, потому что сервис выдачи пишет эти события),
  `backend/tests/domain/test_m20_t03_tokens_service.py` (новый).
- **AC:** AC-1 (токен виден один раз, в БД хеш), AC-3 (отзыв), NFR-1 (хеш SHA-256, формат `gtrk_`), NFR-2
  (фильтр `workspace_id`), лимит 10 активных и срок 90 дней (PN-1). `resolve_token` отвергает
  отозванный, истёкший, неизвестный токен одним и тем же исключением.
- **Тест:** `test_m20_t03_*` — успех, отзыв, истёкший, лимит, чужой workspace.
- **Зависит от:** M20-T02

## M20-T04 — Аудит токенов и атрибуция клиента в событиях
- **Файлы:** `backend/app/domain/events/catalog.py`, `backend/app/domain/events/writer.py`,
  `backend/app/domain/events/queries.py`, `backend/app/domain/activity/service.py`,
  `backend/app/api/v1/schemas/activity.py`.
- **AC:** AC-8 (поле `via_client` в ленте проекта), PN-5 (`user.token_created`, `user.token_revoked` — аудит),
  PN-6 (`client_name` ≤ 64, пустая строка и управляющие символы отвергаются на границе — Fail Fast).
  Существующие записи ленты не меняются.
- **Тест:** `test_m20_t04_*`; существующие тесты каталога и ленты — без изменения assert-ов.
- **Зависит от:** M20-T02

## M20-T05 — Блокировка отзывает токены
- **Файлы:** `backend/app/domain/users/service.py` (только `block_user`), `backend/app/domain/tokens/service.py`.
- **AC:** AC-4 — после блокировки токен отвергается (PN-4). Повторная блокировка — без ошибки.
  Блокировка и отзыв токенов — одна транзакция.
- **Тест:** `test_m20_t05_block_revokes_tokens`.
- **Зависит от:** M20-T03

## M20-T06 — REST управления токенами
- **Файлы:** `backend/app/api/v1/tokens.py` (новый), `backend/app/api/v1/schemas/tokens.py` (новый),
  `backend/app/api/v1/__init__.py`, `docs/api/openapi.json` (только через `gen-api.sh`),
  `frontend/src/shared/api/schema.d.ts` (только через `gen-api.sh`).
- **AC:** AC-1, AC-3 (API). Маршруты cookie-only (PN-2): запрос с `Authorization: Bearer` → 401.
  Ошибки в формате `{"detail","code"}`. Каждый сценарий: успех, 401, валидация, граничный случай.
- **Тест:** `test_m20_t06_*`.
- **Зависит от:** M20-T03, M20-T04

## M20-T07 — Ядро MCP-сервера: `/mcp`, токен, Origin
- **Файлы:** `backend/app/api/mcp/__init__.py` (новый), `backend/app/api/mcp/server.py` (новый),
  `backend/app/api/mcp/auth.py` (новый), `backend/app/api/mcp/errors.py` (новый), `backend/app/main.py`.
- **AC:** AC-2 (401 без токена или с неверным), AC-6 (`tools/list` без инструментов для роли без доступа
  к задачам; PN-11), AC-10 (чужой Origin → 403), PN-3 (блокировка, `must_change_password`, роль «без роли»
  → отказ), PN-7, PN-12, NFR-1 (токен не в логах: тест на access-лог).
- **Тест:** `test_m20_t07_*`.
- **Зависит от:** M20-T03, M20-T01

## M20-T08 — Инструменты MCP
- **Файлы:** `backend/app/api/mcp/tools/__init__.py` (новый), `backend/app/api/mcp/tools/tasks.py` (новый),
  `backend/app/api/mcp/tools/projects.py` (новый), `backend/app/api/mcp/tools/comments.py` (новый),
  `backend/app/api/mcp/server.py` (только регистрация инструментов).
- **AC:** AC-5 (создание задачи другому → 403 `forbidden`, задача не создана), AC-7 (изменения видны в REST),
  AC-8 (`client_name` передаётся в `record_event` через `Actor`), PN-10 (список инструментов), PN-12.
- **Тест:** `test_m20_t08_*` — по одному успешному вызову на инструмент и по одному отказу.
- **Зависит от:** M20-T04, M20-T07

## M20-T09 — Команда `gtrack mcp` (stdio-мост)
- **Файлы:** `backend/app/cli/commands/mcp.py` (новый), `backend/app/cli/main.py`.
- **AC:** AC-9 (ручная проверка с Claude Code), PN-8 (токен только из окружения; `GTRACK_CA_FILE`;
  отказ при отсутствии `GTRACK_TOKEN` с понятной причиной — Fail Fast).
- **Тест:** `test_m20_t09_*` — отказ без токена; мост пересылает вызов `tools/list` на тестовый `/mcp`.
- **Зависит от:** M20-T07

## M20-T10 — Фронтенд: «Доступ для агентов»
- **Файлы:** `frontend/src/features/tokens/` (новые), `frontend/src/shared/i18n/ru.ts`,
  `backend/tests/infra/test_frontend_scaffold.py` (только белый список файлов этой задачи).
- **AC:** PN-15: список, создание с однократным показом и копированием, отзыв. Строки — только `ru.ts`.
  Типы — из `schema.d.ts`, сгенерированного в M20-T06.
- **Тест:** `frontend/tests/features/tokens/m20_*`.
- **Зависит от:** M20-T06

## M20-T11 — Документация интеграции
- **Файлы:** `docs/ai-integration.md` (новый), `README.md` (новый короткий раздел на двух языках).
- **AC:** AC-12 (фрагменты Claude Code и Codex CLI, ограничения ChatGPT из ADR-0018).
- **Тест:** `test_m20_t11_docs_*` — файл существует и содержит фрагменты для обоих клиентов.
- **Зависит от:** M20-T09

## M20-T12 — Финальная проверка
- **Файлы:** только отчёт `specs/020-mcp-ai-native/reviews/FINAL-acceptance.md` (новый).
- **AC:** все AC; `bash scripts/check.sh` зелёный; AC-9 — ручная проверка, результат записывается владельцем.
- **Зависит от:** M20-T01…M20-T11

---

## Таблица статусов
| Задача | Статус |
|---|---|
| M20-T01 | TODO |
| M20-T02 | TODO |
| M20-T03 | TODO |
| M20-T04 | TODO |
| M20-T05 | TODO |
| M20-T06 | TODO |
| M20-T07 | TODO |
| M20-T08 | TODO |
| M20-T09 | TODO |
| M20-T10 | TODO |
| M20-T11 | TODO |
| M20-T12 | TODO |
