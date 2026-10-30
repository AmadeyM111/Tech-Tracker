# Tasks: ИИ-агент как участник трекера — ключи доступа, операции агента, инструменты MCP, метка «ИИ» (spec 007)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия для всех задач R7

- Источник истины — `specs/007-ai-agent-tools/spec.md` v0.4 (дельта к 001 v0.20, 002, 006;
  открытых вопросов нет, З-1 решён — FR-42).
  Интерфейсы и решения — `specs/007-ai-agent-tools/plan.md` (разделы указаны в задачах). Ссылки
  без префикса ведут на 007 (`AC-12` = 007/AC-12), на другие спецификации — с префиксом
  (`006/FR-23`). Решения плана — `PD-n`, замечания к spec — `З-n`. Если задача противоречит spec
  или plan — вернуть `PLAN_ISSUE` и ничего не додумывать.
- **Рамки файлов.** Менять только файлы из поля «Файлы». Проверка:
  `python scripts/task_scope.py R7-Tnn` из корня (выход 0). `docs/api/openapi.json` и
  `frontend/src/shared/api/schema.d.ts` меняются только командой `bash scripts/gen-api.sh` и
  только в задачах, где это сказано.
- **Новых файлов в `frontend/src` не создавать** (белый список
  `backend/tests/infra/test_frontend_scaffold.py::test_t21_src_files_only_expected`; plan PD-16,
  RK-11). Новые файлы в `frontend/tests`, `backend/tests`, `backend/app` разрешены, если названы в
  задаче. Новая миграция — только `backend/migrations/versions/0008_agent_api_keys.py`.
- **Не трогать:** `frontend/package.json`, `frontend/package-lock.json`, зависимости в
  `backend/pyproject.toml` (новых пакетов нет, plan §7; `[project.scripts]` меняет только
  R7-T18), `backend/tests/arch/test_dependencies_allowlist.py`, `CLAUDE.md`, `AGENTS.md`,
  `docs/STATE.md`, `docs/brief/**`, `specs/007-ai-agent-tools/spec.md`.
  `specs/001-pilot-r1/spec.md` меняет только R7-T25.
- **Секрет ключа** нигде не печатать: ни в тестовом выводе, ни в сообщениях `assert`, ни в
  отчётах. В тестах сравнивать через `in`/`not in` без вывода значения (`assert secret not in
  text, "секрет в логе"`).
- **БД.** Деструктивные операции — только в тестовой БД `*_test`. Тома Docker (`pgdata`,
  `appdata`) не удалять. Окружение — AGENTS.md, «Команды»: БД разработки
  `docker compose -p gostracker-dev -f docker-compose.yml -f deploy/compose.dev.yml up -d db`,
  `export TEST_DATABASE_URL=postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test`.
- **Время в тестах** (plan §5): `fixed_clock.set(CLOCK)`, `CLOCK = datetime(2026, 11, 2, 7, 0,
  tzinfo=UTC)`; фронтенд — `vi.setSystemTime(...)` и `vi.stubEnv("TZ", "UTC")`. Реальная дата не
  должна влиять на результат.
- **Тесты** пишет test-writer, исполнитель их не меняет. Новые тесты: бэкенд — `test_007_acN_*`
  (или `test_007_frN_*`), фронтенд — `007_acN_*` / `007_frN_*`. Мир spec §5 и помощники —
  `backend/tests/agents007_support.py` (plan §5). Существующие проверки не ослабляются; их
  дополнение — по plan §6.2 (поле «Старые тесты → AC» сверяет ревьюер).
- **Команды.**
  - «Проверки бэкенда» = `source .venv/bin/activate && ruff check backend && ruff format --check backend && mypy --config-file backend/pyproject.toml backend/app && pytest -q backend/tests`.
  - «Проверки фронтенда» = `cd frontend && npm run lint && npm run typecheck && npx vitest run`.
  - «Alembic check» = `env DATABASE_URL=$TEST_DATABASE_URL ENV=test alembic -c backend/alembic.ini check` (без расхождений).
  - «Бэкенд не тронут» = `git diff --stat HEAD -- backend docs/api frontend/src/shared/api/schema.d.ts` пуст.
  - «Фронтенд не тронут» = `git diff --stat HEAD -- frontend/src` пуст (кроме перегенерированного `schema.d.ts`, если задача его меняет).
- **Коммиты** делает оркестратор (без `git push`), по plan §8: R7-T05 + R7-T06 — один коммит,
  остальные — по одному (plan PD-21).

Порядок и критический путь (plan §8): R7-T02 → R7-T05 → R7-T06 → R7-T07 → R7-T08 → R7-T09 →
R7-T10 → R7-T12 → R7-T14 → R7-T15 → R7-T18 → R7-T24 → R7-T25 → R7-T26. Независимо: R7-T01,
R7-T03, R7-T17. R7-T04 — после R7-T02; R7-T11 — после R7-T02, R7-T03, R7-T06; R7-T13, R7-T23 —
после R7-T12; R7-T16 — после R7-T14. Интерфейс
R7-T19…R7-T22 — после R7-T06 (R7-T21 — после R7-T08, R7-T22 — после R7-T10). Задачи, меняющие
один файл, выполнять последовательно: `domain/users/service.py` (R7-T06 → R7-T07),
`api/deps.py` (R7-T06 → R7-T12), `domain/access/roles.py` (R7-T06 → R7-T11),
`domain/comments/service.py` (R7-T05 → R7-T14), `domain/projects/queries.py` (R7-T05 → R7-T13),
`domain/events/catalog.py`, `tests/unit/test_event_catalog.py`, `tests/db/test_event_log.py`
(R7-T04 → R7-T14), `docs/data-model.md` (R7-T02 → R7-T14),
`api/v1/schemas/admin.py` и `api/v1/admin_agents.py` (R7-T06 → R7-T08 → R7-T10),
`app/agent_mcp.py` (R7-T17 → R7-T18), `features/admin/UsersPage.tsx`, `ru.ts` (R7-T19 → R7-T20 →
R7-T21 → R7-T22).

---

## R7-T01 — Тест совместимости API с базой `f7f19cf` (только тесты)
- **Статус:** DONE
- **AC:** AC-47 (контракт API); NFR-1; plan PD-18
- **Файлы:** тесты: `backend/tests/api/test_api_compat_007.py` (новый), `backend/tests/api/openapi_baseline_f7f19cf.json` (новый)
- **Зависит от:** —
- **Описание:** **Только тесты; код не меняется.** Базу снять командой
  `git show f7f19cf:docs/api/openapi.json > backend/tests/api/openapi_baseline_f7f19cf.json` (без
  правок). Тест строит текущую схему `create_app(settings).openapi()` и сравнивает с базой:
  (1) каждая пара (путь, метод) базы есть; (2) каждая схема `components.schemas` базы есть, ни одно
  её свойство не удалено, у свойства не изменились `type`, `$ref`, `format`, `enum`, `items`,
  `anyOf` (поля `title`, `description`, `default` не сравниваются); (3) у схем тел запросов
  существующих операций набор `required` не вырос, у их параметров пути и запроса нет новых
  обязательных. Сравнение — чистые функции в тестовом модуле; отдельный тест на маленьких
  словарях доказывает, что каждое нарушение (удалён путь, удалено поле, сменён тип, новое
  обязательное поле запроса) обнаруживается.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_api_compat_007.py`
  зелёный на текущем коде; `git diff --stat HEAD -- backend/app frontend docs` пуст;
  `python scripts/task_scope.py R7-T01` → 0.
- **Попытки:** 0

## R7-T02 — Миграция 0008: признак агента, таблица ключей, ключ в событиях
- **Статус:** DONE
- **AC:** FR-1 (признак), FR-6 (хранится только дайджест), FR-30 (столбец события), NFR-7 (модель данных); plan §4.1, PD-1, PD-9
- **Файлы:** `backend/app/domain/users/models.py`, `backend/app/domain/api_keys/models.py` (новый),
  `backend/app/domain/api_keys/__init__.py` (новый, пустой), `backend/app/domain/events/models.py`,
  `backend/app/domain/registry.py`, `backend/migrations/versions/0008_agent_api_keys.py` (новый),
  `docs/data-model.md`;
  тесты: `backend/tests/db/test_agent_keys_schema_007.py` (новый), `backend/tests/factories.py`,
  `backend/tests/db/test_migrations.py`
  (+ `backend/tests/db/test_identity_models.py`, `backend/tests/db/test_r11_models.py`,
  `backend/tests/db/test_event_log.py` — только если перечисляют столбцы таблиц;
  `backend/tests/upgrade002_support.py` — константы `HEAD_REVISION` `0007` → `0008` и `data_fingerprint` (для `app_user` исключить `is_agent`), иначе красными
  становятся тесты апгрейда 002/006; добавлено оркестратором по отчёту test-writer, 2026-10-30)
- **Зависит от:** —
- **Описание:** Модель и миграция — одна неделимая единица (`alembic check`). По plan §4.1:
  `AppUser.is_agent` (`server_default false`), модель `ApiKey` с CHECK, UNIQUE и индексом,
  `DomainEvent.api_key_id` (FK RESTRICT, deferrable); импорт `api_keys.models` в `registry.py`.
  Миграция `revision="0008"`, `down_revision="0007"`, имена ограничений — по `NAMING_CONVENTION`
  (`ck_api_key_name_length` и т. д.), литералы без импорта кода приложения (как 0007). Откат —
  в обратном порядке. `docs/data-model.md`: столбец `app_user.is_agent`, таблица `api_key` (все
  столбцы, ограничения, индексы; «секрет не хранится, только SHA-256»), `domain_event.api_key_id`;
  при откате 0008 ключи и признак теряются. Фабрики: `make_user(..., is_agent=False)`,
  `make_api_key(...) -> ApiKeyRow(id, secret)` (секрет генерируется локально в фабрике:
  `"gtk_" + base64url(32 байт)`, в БД — `sha256`; функцию из R7-T03 фабрика не импортирует).
  Test-writer (`committed` для цикла миграций, как `test_priority_upgrade_006.py`): после head —
  пользователь без `is_agent` получает `false`; нарушения CHECK (`name` пусто и 101 символ, дайджест
  31 байт, `expires_at <= created_at`, `revoked_at` без `revoked_by`, `rate_count < 0`) → SQLSTATE
  `23514`; повтор дайджеста → `23505`; `domain_event.api_key_id` на несуществующий ключ → `23503`;
  цикл head → `downgrade 0007` (таблицы и столбцов нет, прочие данные побайтно те же) →
  `upgrade head`.
- **Старые тесты → AC:** `test_migrations.py` — голова `0008`; перечни столбцов `app_user`,
  `domain_event` — дополнение (plan §6.2).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/db backend/tests/infra/test_docs_static.py`
  зелёный (в т.ч. `test_nfr11_data_model_covers_every_table_and_column` без правок теста);
  «Alembic check»; проверки бэкенда зелёные; «Фронтенд не тронут»;
  `python scripts/task_scope.py R7-T02` → 0.
- **Попытки:** 0

## R7-T03 — Формат и секрет ключа, маскирование ключа в логах
- **Статус:** DONE
- **AC:** AC-41; NFR-3; FR-32 (логи), FR-6; plan §4.2, PD-1, PD-11
- **Файлы:** `backend/app/core/security/api_keys.py` (новый), `backend/app/core/logging.py`;
  тесты: `backend/tests/unit/test_api_key_secret_007.py` (новый), `backend/tests/unit/test_logging.py`
- **Зависит от:** —
- **Описание:** По plan §4.2: `generate_api_key`, `is_api_key_format`, `api_key_digest`
  (не по формату → `ValueError` без значения в тексте), константы формата. В `redact_text` —
  замена `API_KEY_LEAK_PATTERN` на `***` (быстрая проверка `API_KEY_PREFIX in text`), остальная
  логика без изменений.
  Test-writer: AC-41 — 1 000 ключей попарно различны, каждый `fullmatch` формата, после
  `base64.urlsafe_b64decode(k[4:] + "=")` — ровно 32 байта; подмена `secrets.token_bytes` даёт
  ожидаемую строку (источник — `secrets`, 32 байта). Формат: 46 и 48 символов, `+`, `/`, `=`,
  не-ASCII, `GTK_` — не формат. Дайджест — 32 байта, равен `hashlib.sha256`. Логи: ключ в тексте
  сообщения, в `extra` (поле `path`), в аргументах `%s`, в тексте исключения — в JSON-выводе нет
  ни одной подстроки ключа длиной ≥ 8; ключ с изменённым символом тоже маскируется; прежние
  случаи `test_logging.py` зелёные.
- **Старые тесты → AC:** `test_logging.py` — только новые случаи.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/unit/test_api_key_secret_007.py backend/tests/unit/test_logging.py backend/tests/unit/test_sanitize.py backend/tests/api/test_password_leaks.py`
  зелёный; проверки бэкенда зелёные; «Фронтенд не тронут»; `python scripts/task_scope.py R7-T03` → 0.
- **Попытки:** 0

## R7-T04 — Ошибки 429 и коды 422, действия журнала, идентификатор ключа в событиях
- **Статус:** DONE
- **AC:** FR-11 (структура записи), FR-28 (429 с `Retry-After`), FR-30 (запись `api_key_id`); plan §4.3, PD-9
- **Файлы:** `backend/app/core/errors.py`, `backend/app/domain/events/catalog.py`, `backend/app/domain/events/writer.py`;
  тесты: `backend/tests/api/test_errors.py`, `backend/tests/unit/test_event_catalog.py`, `backend/tests/db/test_event_log.py`
- **Зависит от:** R7-T02
- **Описание:** По plan §4.3: `ErrorCode` +4 кода; `TooManyRequests(retry_after=...)` (429,
  `too_many_requests`, `Retry-After` — в `_app_error_handler`; `retry_after < 1` → `ValueError`);
  `EventAction` +3 действия `user.*` в каталоге как `_USER_AUDITED`; `UserEventDetails` +
  `api_key_id`, `api_key_name`; `record_event(..., api_key_id=None)` пишет столбец. OpenAPI не
  меняется (коды ошибок и действия в нём не перечисляются).
  Test-writer: `test_errors.py` — тестовый маршрут бросает `TooManyRequests(retry_after=17)` → 429,
  тело ровно `{"detail": "Слишком много запросов", "code": "too_many_requests"}`, `Retry-After: 17`;
  `retry_after=0` → `ValueError`; новые коды в каталоге, имя = значение. `test_event_catalog.py` —
  три действия: `entity_type=user`, `audit=True`, `feed=None`. `test_event_log.py` — `api_key_id`
  записан и по умолчанию `NULL`; `details` с `api_key_id`/`api_key_name` принят для `user` и
  отклонён для `task`; неизвестный ключ `details` по-прежнему `ValueError`.
- **Старые тесты → AC:** `test_fr41_catalog_has_all_r11_actions_and_user_actions_only` — перечень
  дополнен тремя действиями `user.*` (FR-11); каталог кодов в `test_errors.py` — дополнен.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_errors.py backend/tests/unit/test_event_catalog.py backend/tests/db/test_event_log.py backend/tests/api/test_audit.py`
  зелёный; проверки бэкенда зелёные; `bash scripts/gen-api.sh` не меняет файлы;
  `python scripts/task_scope.py R7-T04` → 0.
- **Попытки:** 0

## R7-T05 — Признак «агент» в ссылках на пользователя и справочнике (домен и схема)
- **Статус:** DONE
- **AC:** AC-36; FR-31 (API: автор, исполнитель, автор комментария, участник, справочник); NFR-1; plan §4.4, PD-10
- **Файлы:** `backend/app/domain/users/directory.py`, `backend/app/domain/projects/members.py`,
  `backend/app/domain/projects/queries.py`, `backend/app/domain/comments/service.py`,
  `backend/app/api/v1/schemas/common.py`;
  тесты: `backend/tests/api/test_agent_flag_007.py` (новый)
  (+ `backend/tests/api/test_users_directory.py`, `backend/tests/api/test_projects.py`,
  `backend/tests/api/test_project_members.py`, `backend/tests/api/test_tasks.py`,
  `backend/tests/api/test_comments.py`, `backend/tests/api/test_board.py`,
  `backend/tests/domain/test_directory.py`, `backend/tests/cli/test_openapi.py` — только
  дополнение `is_agent` в проверках точного набора полей;
  `backend/tests/admin_support.py`, `backend/tests/projects_api_support.py` (общие константы точных наборов полей), `backend/tests/api/test_personal_tasks.py`, `backend/tests/api/test_subtasks.py`, `backend/tests/api/test_task_recipients.py`, `backend/tests/api/test_required_fields_006.py`, `backend/tests/api/test_sessions.py`, `backend/tests/domain/test_user_admin_service.py` — только дополнение `is_agent` в ожиданиях; добавлено оркестратором по отчёту test-writer, 2026-10-31)
- **Зависит от:** R7-T02
- **Описание:** Доменные `UserRef(id, login, is_agent)` и `DirectoryUser(..., is_agent)` — поле
  без умолчания; все места создания (mypy их найдёт) читают `AppUser.is_agent` (`user_refs`,
  `list_directory`, `members.list_members`, владелец в `projects/queries.py`); запасной
  `UserRef` в `comments/service.py` — `is_agent=False`. Схемы `UserRef`, `DirectoryUser` —
  `is_agent: bool`. Логика выборок (фильтры, порядок) не меняется. **OpenAPI и типы
  перегенерирует R7-T06; коммит — вместе с R7-T06.**
  **Правило чтения `is_agent` (plan §4.1):** у `AppUser` нет Python-умолчания и
  `eager_defaults=False`, поэтому у ORM-объекта, созданного без явного `is_agent`, после `flush()`
  атрибут не загружен (обращение → `MissingGreenlet`). Признак читать только выборкой столбца
  (`select(..., AppUser.is_agent)`) или из сущности, загруженной `select(AppUser)`; не читать
  `user.is_agent` у объекта, только что добавленного через `db.add(...)`. Модель `AppUser` не менять.
  Test-writer (`test_agent_flag_007.py`, данные через фабрики уровня БД, `make_user(is_agent=True)`):
  AC-36 — `ba1` через обычный API: карточка задачи, автор и исполнитель которой `agent.u` (и
  подзадача с исполнителем `agent.u`), комментарии с автором `agent.u`, участники P, справочник
  `/users`, список проектов (владелец `ba1`), доска P (исполнитель карточки) — у ссылок на
  `agent.u` `is_agent: true`, на `ba1` и `u1` — `false`; набор ключей ссылки — ровно `{id, login,
  is_agent}`, у элемента справочника — `{id, login, role, is_agent}`. Плюс: агент и человек,
  вставленные фабриками в том же тесте непосредственно перед запросом (без `refresh`), сразу
  видны в справочнике `/users` с верными `is_agent` (`true`/`false`).
- **Старые тесты → AC:** проверки точного набора полей `UserRef`/`DirectoryUser` → + `is_agent`
  (AC-36, plan §6.2).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_agent_flag_007.py backend/tests/api backend/tests/domain`
  зелёный (ни одного `MissingGreenlet`); `is_agent` во всех изменённых местах читается выборкой
  столбца или из загруженной `select` сущности (сверяет ревьюер, plan §4.1); mypy и ruff
  зелёные; «Фронтенд не тронут». Допустимо красные до R7-T06 только
  `backend/tests/cli/test_openapi.py::test_fr44_committed_openapi_json_matches_generation` и
  `backend/tests/infra/test_frontend_api_types.py`; `python scripts/task_scope.py R7-T05` → 0.
- **Попытки:** 0

## R7-T06 — Признак «агент» в `/me` и «Учётных записях»; OpenAPI и типы фронтенда
- **Статус:** DONE
- **AC:** AC-36 (вместе с R7-T05), FR-18 (поле признака), FR-31 (учётные записи); NFR-1; plan §4.4, PD-10
- **Файлы:** `backend/app/domain/access/roles.py`, `backend/app/api/deps.py`, `backend/app/api/v1/schemas/auth.py`,
  `backend/app/api/v1/me.py`, `backend/app/domain/users/service.py`, `backend/app/api/v1/schemas/admin.py`;
  тесты: `backend/tests/api/test_agent_flag_007.py`
  (+ `backend/tests/api/test_admin_users.py`, `backend/tests/api/test_sessions.py`,
  `backend/tests/api/test_auth_login.py`, `backend/tests/domain/test_user_admin_service.py`,
  `backend/tests/cli/test_openapi.py` — только дополнение `is_agent`;
  `backend/tests/admin_support.py`, `backend/tests/projects_api_support.py`, `backend/tests/api/test_personal_tasks.py`, `backend/tests/api/test_subtasks.py`, `backend/tests/api/test_task_recipients.py`, `backend/tests/api/test_required_fields_006.py`, `backend/tests/api/test_comments.py`, `backend/tests/api/test_projects.py`, `backend/tests/api/test_tasks.py`, `backend/tests/api/test_users_directory.py`, `backend/tests/domain/test_directory.py` — только дополнение `is_agent` в ожиданиях (тесты задачи R7-T05, коммитятся вместе); `backend/tests/unit/test_role_matrix.py` (поле `Actor.is_agent` в конце списка), `backend/tests/api/test_admin_roles.py` (`is_agent` в наборе полей `AdminUser`) — только дополнение; добавлено оркестратором, 2026-10-31;
  `frontend/tests/**` — только добавление `is_agent: false` в фикстуры, где этого требует `npm run typecheck`)
- **Зависит от:** R7-T05
- **Описание:** `Actor.is_agent: bool = False` (поле с умолчанием в конце); `get_actor` (путь
  cookie) читает `AppUser.is_agent`; `MeResponse.is_agent` (из `actor.is_agent`);
  `UserAccount.is_agent`, `_Target.is_agent` (выборки `list_accounts`, `_load_target`);
  `AdminUser.is_agent`. Затем `bash scripts/gen-api.sh`; фронтенд-код не меняется, только
  фикстуры тестов. Логику гейтов не менять.
  **Правило `is_agent` (plan §4.1):** у `AppUser` нет Python-умолчания и `eager_defaults=False` —
  у ORM-объекта, созданного без явного `is_agent`, после `flush()` атрибут не загружен
  (`MissingGreenlet`). `get_actor`, `list_accounts`, `get_account`, `_load_target` читают признак
  выборкой столбца; `create_user` (Core-вставка без `is_agent`, значение задаёт БД) возвращает
  `UserAccount(..., is_agent=False)` литералом, не читая ORM-атрибут. Модель `AppUser` не менять.
  Test-writer (дополнить `test_agent_flag_007.py`): `GET /me` человека — `is_agent: false`;
  `GET /admin/users` и `GET /admin/users/{id}` у `ta1` — `is_agent: true` у агента (БД) и `false`
  у людей; набор полей `AdminUser` — прежние шесть + `is_agent`. Сразу после записи:
  `POST /admin/users` → 201, в теле ответа `is_agent: false`, затем `GET /admin/users/{id}` того же
  пользователя — `false`; домен (`test_user_admin_service.py` или `test_agent_flag_007.py`):
  результат `create_user(...)` в той же сессии, без `refresh`/коммита, — `is_agent is False`.
- **Старые тесты → AC:** точные наборы полей `AdminUser` (`test_admin_users.py`, «ровно шесть
  полей») и `MeResponse` → + `is_agent` (FR-31, FR-18); фикстуры фронтенда — только новое поле.
- **Готово, когда:** проверки бэкенда зелёные (весь `pytest -q backend/tests`, включая
  `test_fr44_*`, `infra/test_frontend_api_types.py`, `test_api_compat_007.py`); проверки фронтенда
  зелёные; `bash scripts/gen-api.sh` повторно не меняет файлы; `git diff --stat HEAD -- frontend/src`
  показывает только `schema.d.ts`; ни одного `MissingGreenlet`, в т.ч. в проверке ответа
  `POST /admin/users` и результата `create_user` сразу после записи; `is_agent` читается только
  выборкой столбца или литералом (сверяет ревьюер, plan §4.1);
  `python scripts/task_scope.py R7-T06` → 0. Коммит R7-T05 + R7-T06 — один.
- **Попытки:** 0

## R7-T07 — Учётная запись агента: создание, роль, сброс пароля, вход, блокировка (сервис)
- **Статус:** DONE
- **Заметка ревью R7-T05/T06:** если `create_agent` создаёт агента через ORM и в том же запросе вызываются `list_members`/`list_accounts` (читают `is_agent` из `select(AppUser)`+`load_only`), добавить проверку identity map (`reviews/R7-T05-T06-1.md` п.1).
- **AC:** AC-1, AC-2 (уровень домена), AC-4 (отзыв ключей при блокировке); FR-1, FR-2, FR-4; plan §4.5, PD-4, PD-7, PD-8
- **Файлы:** `backend/app/domain/users/service.py`, `backend/app/domain/auth/service.py`;
  тесты: `backend/tests/domain/test_agent_accounts_007.py` (новый)
- **Зависит от:** R7-T04, R7-T06
- **Описание:** По plan §4.5: `create_agent` (порядок проверок из docstring plan; одно событие
  `user.agent_created`, `details={"role_to": ...}`; `must_change_password=false`; хеш случайного
  значения через `hash_in_thread`, значение не сохраняется); публичные `lock_for_account_change`
  (вызывает `_lock_for_account_change`) и `load_account`; в `set_role` — 422
  `agent_role_not_allowed` для агента и роли ТА (до изменения, без события); в
  `reset_password` — 422 `agent_password_not_allowed` после проверки 404 и до политики пароля;
  в `block_user` — отзыв действующих ключей агента (PD-7, `revoked_by` = актор), событие одно.
  `auth.service.login`: `AppUser.is_agent` в выборке, агент → `InvalidCredentials` (как
  заблокированный).
  **Правило `is_agent` (plan §4.1):** у `AppUser` нет Python-умолчания и `eager_defaults=False` —
  у ORM-объекта, созданного без явного `is_agent`, после `flush()` атрибут не загружен (обращение →
  `MissingGreenlet`). Поэтому `create_agent` вставляет `app_user` Core-вставкой
  `pg_insert(AppUser).values(..., is_agent=True, must_change_password=False, ...)` по образцу
  `create_user` (не `AppUser(...)` + `db.add`) и возвращает `UserAccount(..., is_agent=True)`
  литералом; `set_role`, `reset_password`, `block_user`, `login` читают признак выборкой столбца
  (`_load_target`, `select(..., AppUser.is_agent)`). Если всё же нужен ORM-объект — `is_agent=`
  передаётся явно либо `await db.refresh(obj)` перед чтением. Модель `AppUser` не менять.
  Test-writer (домен, `db` + фабрики): AC-1 — `create_agent(role=USER)`: результат проверяется
  сразу, в той же сессии без `refresh`/`expire`/коммита (`result.is_agent is True`, роль П,
  `must_change_password is False`), затем повторно выборкой `load_account` и
  `select(AppUser.is_agent)` — `True`; ровно одно новое событие аудита `user.agent_created` с
  `role_to="user"`; в том же тесте `create_user(...)` человека сразу после записи —
  `is_agent is False`; вход агента с любым паролем и с «угаданным» — `InvalidCredentials`
  (совпадает с неверным паролем человека); `reset_password` агента → 422
  `agent_password_not_allowed`, событий нет. AC-2 — `create_agent(role=TECH_ADMIN)` → 422
  `agent_role_not_allowed`, записи нет; `set_role(agent, TECH_ADMIN)` → 422, роль П, событий нет;
  П → БА → П выполнено. Создание без роли (`role=None`) и с ролью БА; `login_invalid`,
  `login_taken`; БА/П/без роли → 403. Блокировка агента с двумя действующими, одним истёкшим и
  одним отозванным ключом: у действующих `revoked_at`=сейчас, `revoked_by`=ТА; истёкший и
  отозванный не тронуты; одно событие `user.blocked`; разблокировка `revoked_at` не меняет.
- **Старые тесты → AC:** нет (существующие тесты `users/service`, `test_admin_roles.py` с подменой
  `_lock_for_account_change` зелёные без правок).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_agent_accounts_007.py backend/tests/domain backend/tests/api/test_admin_users.py backend/tests/api/test_admin_roles.py backend/tests/api/test_auth_login.py`
  зелёный (ни одного `MissingGreenlet`, в т.ч. в проверке результата `create_agent`/`create_user`
  сразу после записи); `create_agent` пишет `app_user` Core-вставкой с явным `is_agent=True`, ORM-
  атрибут `is_agent` нигде не читается у объекта без явного значения (сверяет ревьюер, plan §4.1);
  проверки бэкенда зелёные; «Фронтенд не тронут»; `python scripts/task_scope.py R7-T07` → 0.
- **Попытки:** 0

## R7-T08 — API создания учётной записи агента
- **Статус:** TODO
- **AC:** AC-1, AC-2, AC-3; FR-1, FR-2; plan §4.5, PD-4
- **Файлы:** `backend/app/api/v1/schemas/admin.py`, `backend/app/api/v1/admin_agents.py` (новый),
  `backend/app/api/v1/__init__.py`;
  тесты: `backend/tests/api/test_agent_accounts_007.py` (новый), `backend/tests/agents007_support.py` (новый)
- **Зависит от:** R7-T07
- **Описание:** По plan §4.5: `CreateAgentRequest`; роутер `admin_agents.py` (префикс
  `/admin/agents`, гейт `MANAGE_ACCOUNTS`, маршрут `create_agent` → 201 `AdminUser`); подключение
  в `api/v1/__init__.py`. Обработчик только вызывает `users.service.create_agent`. Затем
  `bash scripts/gen-api.sh`. `agents007_support.py`: `CLOCK`, `make_agent(env, login, role)`,
  константы адресов (plan §5).
  Test-writer: AC-1 (API: `ta1` создаёт `agent.new` с ролью П → 201, `is_agent: true`, роль П,
  `must_change_password: false`, в ответе нет пароля; журнал `/admin/audit` — ровно одна новая
  запись `user.agent_created`; вход `agent.new` → 401, тело совпадает с телом неверного пароля
  человека; `POST /admin/users/{id}/reset-password` → 422 `agent_password_not_allowed`, записей
  журнала не прибавилось). AC-2 (роль ТА при создании → 422, учётной записи нет; `PUT …/role`
  `tech_admin` → 422, роль П, журнал не изменился; П → БА → П — 200). AC-3 (`ba1` добавляет
  `agent.new` в P, создаёт задачу с исполнителем `agent.new` (полное тело 006) → 201; справочник
  `/users` у `ba1` содержит `agent.new` с `is_agent: true`). Граничные: лишнее поле → 422;
  `role` отсутствует → 422; БА, П → 403.
- **Старые тесты → AC:** нет (обход маршрутов `test_route_guards.py` автоматически включает новый
  маршрут и должен остаться зелёным без правок).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_agent_accounts_007.py backend/tests/api/test_route_guards.py backend/tests/api/test_api_compat_007.py`
  зелёный; проверки бэкенда и фронтенда зелёные; `bash scripts/gen-api.sh` повторно не меняет
  файлы; `python scripts/task_scope.py R7-T08` → 0.
- **Попытки:** 0

## R7-T09 — Ключи: выпуск, перечень, отзыв (сервис)
- **Статус:** TODO
- **Заметка ревью R7-T07 (обязательно, `reviews/R7-T07-1.md`):** выпуск и отзыв ключа вызывают `users.service.lock_for_account_change(db, ws, agent_id, actor_id)`, затем читают `is_blocked`/`is_agent` через `load_account`; иначе гонка с блокировкой оставит действующий ключ у заблокированного агента (PD-8). Проверить отдельным тестом/ревью.
- **AC:** AC-6, AC-8, AC-9, AC-11, AC-12 (уровень домена); FR-5…FR-11; plan §4.6, PD-1, PD-6, PD-8
- **Файлы:** `backend/app/domain/api_keys/service.py` (новый);
  тесты: `backend/tests/domain/test_api_keys_service_007.py` (новый)
- **Зависит от:** R7-T03, R7-T07
- **Описание:** По plan §4.6: `key_state`, `ApiKeyView`, `IssuedApiKey` (`secret` с
  `repr=False`), `issue_api_key`, `list_api_keys`, `revoke_api_key`. Порядок проверок — docstring
  plan §4.6. Блокировки — `users.service.lock_for_account_change`, цель —
  `users.service.load_account` (модуль импортируется как `from app.domain.users import service as
  accounts`). Секрет: `generate_api_key()`, в БД — `api_key_digest(...)`. События аудита
  `user.api_key_issued` / `user.api_key_revoked` с `details` `{api_key_id: str(id),
  api_key_name: name}`, `entity_id` — агент.
  Test-writer (домен, `fixed_clock`): выпуск — `IssuedApiKey.secret` по формату, в строке БД
  дайджест равен `sha256(secret)`, `repr(issued)` не содержит секрета, срок `CLOCK + 90 суток` по
  умолчанию и `+365` при 365; одна запись аудита с автором ТА, агентом, id и названием. Отказы:
  `ttl_days` −1, 0, 366 → 422 `validation_error`; название `""`, 101 символ, с NUL → 422; не агент
  → 422 `not_an_agent`; заблокированный агент → 422 `user_blocked`; 5 действующих → 422
  `api_key_limit_reached` (истёкшие и отозванные не считаются); после отказа ключей и записей не
  прибавилось; БА/П → 403; чужой `user_id` → 404. Перечень: порядок `created_at DESC`, состояния
  `active`/`revoked` (с `revoked_at`)/`expired` (после `fixed_clock.set(expires_at)`),
  `last_used_at` из строки, `created_by` — ТА; у человека — пустой список. Отзыв: `revoked_at`,
  одна запись аудита; повтор и отзыв истёкшего — без изменений и без записи; ключ другого агента
  по этому `user_id` → 404.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_api_keys_service_007.py`
  зелёный; проверки бэкенда зелёные; «Фронтенд не тронут»; `python scripts/task_scope.py R7-T09` → 0.
- **Попытки:** 0

## R7-T10 — Ключи: API техадминистратора
- **Статус:** TODO
- **AC:** AC-6, AC-7 (люди и 422), AC-8, AC-9, AC-11, AC-12; FR-5…FR-10, FR-40 (API); plan §4.6, PD-6
- **Файлы:** `backend/app/api/v1/schemas/admin.py`, `backend/app/api/v1/admin_agents.py`;
  тесты: `backend/tests/api/test_api_keys_admin_007.py` (новый), `backend/tests/agents007_support.py` (только добавить помощники)
- **Зависит от:** R7-T08, R7-T09
- **Описание:** По plan §4.6: схемы `ApiKeyInfo`, `IssueApiKeyRequest`, `IssuedApiKeyResponse`;
  маршруты `list_api_keys`, `issue_api_key` (201, заголовок `Cache-Control: no-store`),
  `revoke_api_key` (204). Обработчики только вызывают сервис R7-T09. Затем `bash scripts/gen-api.sh`.
  В `agents007_support.py` — `make_key(...)` и `bearer(secret)` (plan §5).
  Test-writer: AC-6 (`ta1` выпускает `agent.u` ключ «claude-laptop» сроком 90 → 201, есть
  `secret`, `Cache-Control: no-store`; в журнале ровно одна новая запись `user.api_key_issued`:
  автор `ta1`, `entity_id` агента, `details.api_key_id`/`api_key_name`; секрета нет ни в записи
  журнала, ни в перечне, ни в `GET /admin/users/{id}`, ни в списке учётных записей). AC-7 (`ba1`,
  `u1`: выпуск, отзыв, перечень → 403, ключей и записей не прибавилось; `ta1`: ключ `u1` → 422
  `not_an_agent`, заблокированному агенту → 422 `user_blocked`, название `""` и 101 символ → 422).
  AC-8 (три ключа: действующий с `last_used_at` = 10:00 MSK записан в БД, действующий
  неиспользованный, отозванный → у каждого `id`, `name`, `created_by`, `created_at`, `expires_at`,
  `state`; `last_used_at` 07:00Z у первого и `null` у второго; после `fixed_clock.set` за срок
  второго — `expired`; набор полей — ровно 8). AC-9 (отзыв → 204, одна запись `user.api_key_revoked`
  с автором `ta1`; повтор → 204, записей нет). AC-11 (`expires_in_days` −1, 0, 366 → 422, ключ не
  создан; 365 → 201; без поля → 201, срок `CLOCK + 90 суток`). AC-12 (5 действующих → шестой 422,
  ключей 5; отзыв одного и выпуск → 201).
- **Старые тесты → AC:** нет.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_api_keys_admin_007.py backend/tests/api/test_route_guards.py backend/tests/api/test_api_compat_007.py`
  зелёный; проверки бэкенда и фронтенда зелёные; `bash scripts/gen-api.sh` повторно не меняет
  файлы; `python scripts/task_scope.py R7-T10` → 0.
- **Попытки:** 0

## R7-T11 — Аутентификация по ключу: проверка, срок, лимит частоты (домен)
- **Статус:** TODO
- **Заметка ревью R7-T07:** аутентификация по ключу не зависит от `failed_login_count`/`login_locked_until` (перебором паролей нельзя заблокировать ключ); дополнительно проверять `app_user.is_blocked`, а не только `revoked_at`.
- **AC:** AC-10, AC-40 (уровень домена); FR-9, FR-13 (домен), FR-16, FR-33; plan §4.7, PD-5
- **Файлы:** `backend/app/domain/api_keys/auth.py` (новый), `backend/app/domain/access/roles.py`,
  `backend/app/domain/auth/service.py`;
  тесты: `backend/tests/domain/test_api_key_auth_007.py` (новый)
  (+ `backend/tests/domain/test_auth_service.py` — только если тест строит `Actor`/`SessionActor` с проверкой типа `session_id`)
- **Зависит от:** R7-T02, R7-T03, R7-T06
- **Описание:** По plan §4.7 и PD-5: `authenticate_api_key(db, digest, *, now)` — один
  `UPDATE … RETURNING` (сброс окна, `LEAST(rate_count + 1, 121)`, `last_used_at` только в пределах
  лимита), без фиксации транзакции; `RateLimited.retry_after = max(1, ceil(...))`. `Actor`:
  `session_id: bytes | None`, `api_key_id: UUID | None = None`. `SessionActor.session_id` —
  `bytes | None`; `change_own_password` первым шагом: `session_id is None` → `Forbidden()`.
  Test-writer (домен, `fixed_clock`, ключи фабрикой `make_api_key`): AC-10 — ключ с `created_at
  = CLOCK`, `expires_at = CLOCK + 90 суток`: в `expires_at − 1 с` → `KeyPrincipal`, в `expires_at` →
  `None`. Отозванный, неизвестный дайджест → `None`. AC-40 — 120 вызовов в один момент →
  `KeyPrincipal`, 121-й → `RateLimited(retry_after=60)`; через 30 с → `RateLimited(30)`; через 60 с
  → `KeyPrincipal`, счётчик 1; счётчик второго ключа не зависит от первого. FR-16 — `last_used_at`
  = момент последнего вызова в пределах лимита, 121-й его не меняет. Поток 10 000 вызовов не
  выводит `rate_count` за 121. `change_own_password` с `session_id=None` → `Forbidden`.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_api_key_auth_007.py backend/tests/domain/test_auth_service.py backend/tests/api/test_password_change.py`
  зелёный; проверки бэкенда зелёные; «Фронтенд не тронут»; `python scripts/task_scope.py R7-T11` → 0.
- **Попытки:** 0

## R7-T12 — Аутентификация по ключу: `get_actor`, объём доступа FR-17, гейты, лимит
- **Статус:** TODO
- **Заметка ревью R7-T05/T06:** `Actor.is_agent` при аутентификации по ключу заполнять из `app_user.is_agent`, не по умолчанию `False`; `/me` агента с `is_agent: true` покрыть тестом (`reviews/R7-T05-T06-1.md` п.3).
- **Заметка ревью R7-T03:** `api_key_digest` вызывать вне блока `except` с исключением, содержащим заголовок `Authorization` (иначе `__context__` несёт чужое исключение).
- **AC:** AC-4, AC-5, AC-6 («кто я» по секрету), AC-7 (агент по ключу), AC-8 (по реальному запросу), AC-9 (401 после отзыва), AC-10, AC-13, AC-14, AC-15, AC-17, AC-33, AC-40; FR-12…FR-15, FR-17, FR-18, FR-33; plan §4.7, PD-2, PD-3, PD-5
- **Файлы:** `backend/app/api/deps.py`, `backend/app/main.py`;
  тесты: `backend/tests/api/test_api_key_auth_007.py` (новый), `backend/tests/api/test_agent_scope_007.py` (новый),
  `backend/tests/agents007_support.py` (только добавить помощники)
- **Зависит от:** R7-T10, R7-T11
- **Описание:** По plan §4.7: `AGENT_OPERATIONS`, `presented_api_key`, `require_agent_scope`
  (app-level, после `check_origin`; в `main.py` — `dependencies=[Depends(check_origin),
  Depends(require_agent_scope)]`), `get_actor` с веткой ключа `_actor_from_api_key` (порядок и
  `commit_durably` — как в plan; при 429 — `TooManyRequests`). Сессии и cookie по ключу не
  трогаются. `get_actor` разбить на помощники (пороги `ruff` C901/PLR0915 не повышать). Если
  `scope["route"]` недоступен для части маршрутов — plan RK-3, план Б; иначе `PLAN_ISSUE`.
  В `agents007_support.py` — `make_world007(env)` (plan §5).
  Test-writer: `test_agent_scope_007.py` — каждое имя из `AGENT_OPERATIONS` есть среди маршрутов
  приложения; обход всех маршрутов `/api/v1` (как `test_route_guards.py`): вне перечня с
  действующим `K_ba` → 403 `forbidden`, в т.ч. `/auth/login`, `/health`, `/auth/logout`. 
  `test_api_key_auth_007.py`: AC-4, AC-5 (все 10 операций → 403 `no_role`; затем роль П → «кто
  я» 200), AC-6 («кто я» по только что выпущенному через API секрету → 200, `agent.u`), AC-7
  (`agent.ba` по `K_ba`: выпуск, отзыв `K_u`, перечень ключей `agent.u` → 403, журнал не изменился),
  AC-8 (запрос по ключу в 10:00 MSK → перечень показывает `last_used_at` 07:00Z), AC-9 (после
  отзыва → 401), AC-10 (граница через API), AC-13 (200, нет `Set-Cookie`, число строк
  `user_session` не изменилось), AC-14 (восемь случаев → тело ровно `{"detail": "Требуется вход в
  систему", "code": "not_authenticated"}`; плюс `Authorization: Basic …` и два заголовка
  `Authorization` → 401), AC-15, AC-17 (`id`, `login`, `role: "user"`, `is_agent: true`), AC-33
  (14 действий по `K_ba` → 403 `forbidden`, данные не изменились; те же действия с задачами и
  комментариями у `ba1` через обычный API — по 002), AC-40 (120 × «кто я» → 200; 121-й → 429 с
  `Retry-After`; 121-й — создание задачи → 429, задач не прибавилось; в ту же минуту `K_ba` и `u1`
  по cookie → 200; `+60 с` → 200).
- **Старые тесты → AC:** нет (`test_route_guards.py`, `test_deps_gates.py`, `test_sessions.py`
  зелёные без правок — поведение cookie не изменилось, FR-41).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_api_key_auth_007.py backend/tests/api/test_agent_scope_007.py backend/tests/api/test_route_guards.py backend/tests/api/test_deps_gates.py backend/tests/api/test_sessions.py`
  зелёный; проверки бэкенда зелёные; «Фронтенд не тронут»; `python scripts/task_scope.py R7-T12` → 0.
- **Попытки:** 0

## R7-T13 — Операции чтения по ключу: проекты по членству, права в карточке
- **Статус:** TODO
- **AC:** AC-16, AC-18, AC-19, AC-20, AC-21; FR-17 (права в карточке), FR-19…FR-22, FR-34; plan §4.8, PD-3, З-6
- **Файлы:** `backend/app/domain/projects/queries.py`, `backend/app/domain/access/policy.py`;
  тесты: `backend/tests/api/test_agent_reads_007.py` (новый), `backend/tests/unit/test_policy.py`
- **Зависит от:** R7-T12
- **Описание:** По plan §4.8: `list_projects` — фильтр участия и для `actor.api_key_id is not
  None`; `can_delete_task`, `can_edit_comment`, `can_delete_comment` — `False` для запроса по
  ключу (первой строкой). Для людей поведение прежнее.
  Test-writer: AC-16 (второе пространство W2 фабриками БД: карточка TW и задачи проекта W2 по
  `K_ba` → 404). AC-18 (по `K_u` и `K_ba`: P есть, P2 нет; у `ba1` по cookie P2 по-прежнему в
  списке). AC-19, AC-20 (включая P2 → 403, несуществующий → 404). AC-21 (права T1: `edit` false,
  `change_status` true, `change_assignee` false, `create_subtask` true, `delete` false; T2 — 200,
  `change_status` false; T9 → 403; карточка задачи P у `agent.ba`: `delete` false, а у `ba1` по
  cookie — true; комментарии агента по ключу — `edit`/`delete` false). `test_policy.py` — для
  `Actor` с `api_key_id` три функции → `False`, без `api_key_id` — прежняя таблица.
- **Старые тесты → AC:** `test_policy.py` — только новые случаи.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_agent_reads_007.py backend/tests/unit/test_policy.py backend/tests/api/test_projects.py backend/tests/api/test_ba_projects_002.py`
  зелёный; проверки бэкенда зелёные; «Фронтенд не тронут»; `python scripts/task_scope.py R7-T13` → 0.
- **Попытки:** 0

## R7-T14 — События задач и комментариев для всех авторов (FR-42) с идентификатором ключа
- **Статус:** TODO
- **Заметка ревью R7-T04:** в `events/writer.py` `record_event` включает `api_key_id` в INSERT только при `not None` (иначе падает `test_002_ac30_*` на схеме 0005); не возвращать безусловную запись; желательно тест «при None столбца в INSERT нет» (`reviews/R7-T04-1.md` п.1).
- **AC:** AC-35, AC-28 (нет события при том же статусе), AC-43 (часть «события — по AC-35»:
  реализация здесь, сквозная проверка через MCP — R7-T18), AC-49, AC-50, AC-51, AC-52, AC-53,
  AC-47 (правки существующих тестов по исключениям v0.4); FR-29, FR-30, FR-42; NFR-7
  (`docs/data-model.md`); plan §4.3, §4.8, §6.2, PD-9, PD-22, PD-23, PD-24
- **Файлы:** `backend/app/domain/tasks/service.py`, `backend/app/domain/comments/service.py`,
  `backend/app/domain/events/catalog.py`, `docs/data-model.md`;
  тесты: `backend/tests/api/test_agent_events_007.py` (новый),
  `backend/tests/agents007_support.py` (только добавить помощники)
  (+ правки существующих тестов строго по plan §6.2: `backend/tests/unit/test_event_catalog.py`,
  `backend/tests/db/test_event_log.py`, `backend/tests/domain/test_tasks_create.py`,
  `backend/tests/domain/test_tasks_update_delete.py`, `backend/tests/domain/test_tasks_move.py`,
  `backend/tests/domain/test_comments_service.py`, `backend/tests/api/test_ba_tasks_002.py`)
- **Зависит от:** R7-T12 (мир `make_world007`, ключи `K_u`/`K_ba`; транзитивно R7-T04 —
  `record_event(api_key_id)` и `catalog.py`)
- **Описание:** Решение владельца по З-1 принято (spec v0.3/v0.4, FR-42): события пишутся для
  людей и агентов одинаково. По plan §4.8 и PD-9, PD-22…PD-24:
  - `catalog.py`: у `task.updated` в `fields` и `value_fields` добавить `priority` (PD-22).
    Остальные записи каталога не менять.
  - `tasks/service.py`: константы `EVENT_FIELDS`, `EVENT_VALUE_FIELDS`, помощники `_json_value`,
    `_record_task_updated` (plan §4.8). `create_task`, `create_subtask` — `task.created` после
    `flush`. `update_task` — старые значения меняющихся полей снимаются со свежей строки (после
    `_lock_task`, второго `_changes` и `_authorize`) **до** `move_task`/`setattr`; после `flush` —
    одно `task.updated` (`changed_fields` в порядке `EVENT_FIELDS`, `changes` — по
    `EVENT_VALUE_FIELDS`, включая приоритет); пустой `changed` — без события (D-46, AC-28).
    `move` (PD-23): `_load_task` → `positions.lock_task_columns(db, task, target)` → `old =
    TaskStatus(task.status)` → `positions.move_task(...)` → `flush` → при `old != target` одно
    `task.updated` с `changed_fields=["status"]` и `changes` статуса; внутри колонки — без события.
    `delete_task` не менять (каскад событий не пишет).
  - `comments/service.py`: `create_comment` — `comment.created`; `delete_comment` —
    `comment.deleted` (только прямое удаление, PD-24). `edit_comment` не менять.
  - Везде `actor_id=actor.user_id`, `api_key_id=actor.api_key_id`, `project_id` — проект задачи.
    Событие пишется в транзакции запроса после записи изменения: отказ откатывает и его.
  - Докстринги модулей: «Событий ленты нет (D-55)» → «события по 007/FR-42».
  - `docs/data-model.md`, раздел «Мягкое удаление и события в MVP», абзац «События (D-55)», и
    раздел «Каталог событий R1.0»: с 007 пишутся `task.created`, `task.updated` (перечень полей,
    значения до/после у статуса, исполнителя, срока, приоритета; у названия и описания — только
    имя), `comment.created`, `comment.deleted` (только прямое удаление) — для всех авторов,
    `api_key_id` у запросов по ключу; не пишут: проекты и участники, удаление задач и каскады,
    правка комментария, перенос внутри колонки, снятие исполнителя при исключении участника;
    задним числом событий нет, демо-данные событий задач не пишут; лента и показ событий
    по-прежнему отложены (001/FR-38). Сохранить «D-55» (как ссылку «заменено 007/FR-42») и фразу
    вида «проекты … событий не пишут» — её проверяет `test_t88_data_model_mvp_section` (тест не
    менять, plan RK-14).
  - Правки существующих тестов — **только** перечисленные в plan §6.2 (строки R7-T14) и только
    так, как там сказано: имя теста не меняется, `== []`/`== before` заменяется точным списком
    новых событий (тип, объект, автор, `api_key_id`), проверка «после удаления/правки событий нет»
    остаётся строгой. Остальные тесты, считающие события, проверены архитектором и правок не
    требуют (plan §6.2, «Проверены и не меняются»); если какой-то из них краснеет — `PLAN_ISSUE`,
    не править.
  Test-writer (`test_agent_events_007.py`, мир `make_world007`, `CLOCK`; чтение `domain_event` —
  SQL по `workspace_id`, порядок по `id`; «новых событий нет» — сравнение числа строк до/после):
  - AC-35: по `K_u` создание задачи, статус `in_progress`, комментарий → ровно три новых события
    `task.created`, `task.updated` (`changed_fields == ["status"]`, `changes` `todo → in_progress`),
    `comment.created`; у всех `actor_id` = `agent.u`, `api_key_id` = id `K_u`, `in_audit = false`,
    секрета нет ни в одном столбце; `ba1` по cookie меняет статус T2 → `task.updated` с `actor_id`
    `ba1` и `api_key_id IS NULL`. Подзадача по ключу → `task.created`.
  - AC-28: T1 в `todo`, `agent.u` ставит `todo` → 200, событий по T1 нет.
  - AC-49: семь шагов `ba1` → ровно пять событий в заданном порядке; у `task.updated` по T5
    `changed_fields == ["due_date", "title"]` (порядок `EVENT_FIELDS`); шаги 4 и 6 событий не
    добавили; у всех автор `ba1`, `project_id` = P, `api_key_id IS NULL`. `u1` меняет статус T2 →
    одно `task.updated` (`["status"]`, автор `u1`). `GET /admin/audit` у `ta1` (все страницы) — ни
    одного из этих событий. Ключи верхнего уровня карточки T5 и элемента списка комментариев T5 —
    ровно свойства схем `TaskDetail`/`Comment` из `backend/tests/api/openapi_baseline_f7f19cf.json`
    (имена схем — по базе; plan З-12).
  - AC-50: шесть отказов (422, 422 `due_date_in_past`, 403, 403, 400, 404) — число событий не
    изменилось; `ba1` удаляет T2 → 204, новых событий нет. Демо — существующий
    `cli/test_demo_data.py::test_d55_no_project_or_task_events` (не дублировать).
  - AC-51: пять пунктов spec; первый и третий — `changed_fields == ["priority"]` и
    `["priority", "title"]`, `changes` приоритета `medium → high` и `high → low`; повтор `high` и
    `urgent` (422) — без событий; `agent.u` по `K_u` меняет у T3 только приоритет → 200, одно
    событие с `api_key_id` = `K_u`, срок и описание T3 не изменились.
  - AC-52: `POST /api/v1/tasks/{id}/move` у `ba1` и `u1` (cookie): внутри колонки выше T1 → 204,
    порядок на доске, событий нет; в «В работе» → 204, одно `task.updated` (`["status"]`,
    `todo → in_progress`, автор `ba1`, без ключа) — тип и поля те же, что в AC-49 у `u1`; `u1` в
    «На проверке» → одно событие автора `u1`; соседом карточка другой колонки → 422
    `invalid_neighbors`, статус прежний, событий нет; `u1` переносит T1 → 403, событий нет.
  - AC-53: данные фабриками уровня БД (c1, T1.1 + c7, T2.1 + c8, c10, c9 в P2); удаление T1 →
    204, T1 и T1.1 → 404, c1 и c7 с `deleted_at` (SQL), событий нет; прямое удаление c1 → 404,
    событий нет; удаление T2.1 → 204, c8 удалён, событий нет; удаление c10 → 204, ровно одно
    `comment.deleted` (`entity_id` = c10, автор `ba1`, `project_id` = P); удаление P2 → 204, c9
    удалён, событий нет.
  - `test_event_log.py` (новый тест в существующем файле): `record_event` `task.updated` с
    `changed_fields=["priority"]` и `changes` приоритета записывается (AC-51, PD-22).
- **Старые тесты → AC:** plan §6.2, строки R7-T14 — `test_event_catalog.py` (`task.updated` +
  `priority`, AC-47 v0.4, PD-22); `test_event_log.py::test_ac65_changed_field_outside_whitelist_is_rejected`
  и `::test_br2_exception_text_has_no_values_for_invalid_changed_field` (`priority` → `position`,
  AC-47 v0.4); `test_tasks_create.py::test_d55_create_writes_no_events`,
  `test_tasks_update_delete.py::test_d55_update_and_delete_write_no_events`,
  `test_tasks_move.py::test_d55_move_writes_no_events`,
  `test_comments_service.py::test_d55_no_events_and_no_mentions_written`,
  `test_ba_tasks_002.py::test_002_ac13_ba_member_deletes_foreign_comment_c1` (строка 63) — точный
  список новых событий FR-42 (AC-47: «новые события FR-42 в проверках, которые считают события»).
  `test_d55_no_project_or_task_events` (демо) и `test_d56_delete_task_cascades_…` не меняются.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_agent_events_007.py backend/tests/api backend/tests/domain backend/tests/db/test_event_log.py backend/tests/db/test_positions.py backend/tests/unit/test_event_catalog.py backend/tests/cli/test_demo_data.py backend/tests/cli/test_maintenance.py backend/tests/infra/test_docs_static.py`
  зелёный (`test_docs_static.py` — без правок теста); проверки бэкенда зелёные;
  `git diff HEAD -- backend/tests | grep -E '^-\s*(async )?def test_'` пуст (ни один тест не удалён и
  не переименован); «Фронтенд не тронут»; `python scripts/task_scope.py R7-T14` → 0.
- **Попытки:** 0

## R7-T15 — Операции записи по ключу: приёмочные тесты (только тесты)
- **Статус:** TODO
- **AC:** AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28 (422 и статус), AC-29, AC-30, AC-31, AC-32, AC-34; FR-23…FR-29
- **Файлы:** тесты: `backend/tests/api/test_agent_writes_007.py` (новый)
  (+ `backend/tests/agents007_support.py` — только добавить помощники)
- **Зависит от:** R7-T13, R7-T14
- **Описание:** **Только тесты; код не меняется** — операции записи по ключу выполняют
  существующие сервисы. Если тест краснеет из-за кода — отчёт `PLAN_ISSUE` с диагнозом, код не
  менять. Мир `make_world007`, часы `CLOCK`.
  Test-writer: AC-22 (201; автор и исполнитель `agent.u`, `todo`, `medium`; у `ba1` — карточка,
  список P, доска в колонке `todo`). AC-23 (семь случаев → 422 `validation_error`; срок
  `2026-11-01` → 422 `due_date_in_past`; число задач P не изменилось). AC-24 (шесть случаев с
  ожидаемыми кодами). AC-25. AC-26 (четыре шага, после каждого — карточка и доска у `ba1`). AC-27
  (включая незакрытую подзадачу). AC-28 (`closed`, `DONE`, `""`, `null` → 422, статус прежний; `todo`
  → 200). AC-29 (срок и описание T3 не изменились). AC-30. AC-31 (семь случаев; после каждого
  отказа все поля задачи прежние). AC-32 (HTML вырезан; порядок c1 и нового в обоих API; 10 001
  символ, пусто, `<b></b>` → 422; T9 → 403). AC-34 (T2 мягко удалена: карточка, статус,
  комментарий → 404 `not_found`; несуществующий id → 404; битый JSON → 400 `bad_request`; у всех
  ошибок ровно ключи `detail`, `code`).
- **Старые тесты → AC:** нет.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_agent_writes_007.py`
  зелёный; `git diff --stat HEAD -- backend/app frontend docs` пуст; `python scripts/task_scope.py R7-T15` → 0.
- **Попытки:** 0

## R7-T16 — Секрет не утекает: логи, ответы, журнал, события, БД, access-лог web
- **Статус:** TODO
- **Заметки ревью R7-T03 (обязательно учесть):** `reviews/R7-T03-1.md` п.1–3: имена ключей в `extra`/Mapping не маскируются в `core/logging.py`; в сквозной AC-38 добавить ключ с `/` или `+` внутри (путь и заголовок), при находке — вернуться к plan PD-11; nginx `log_format` без `$request`.
- **AC:** AC-38 (API, журнал, события), AC-39; FR-32, FR-6; plan PD-1, PD-11
- **Файлы:** `deploy/web/default.conf.template`;
  тесты: `backend/tests/api/test_api_key_leaks_007.py` (новый), `backend/tests/infra/test_web_hardening.py`
  (+ `backend/app/core/logging.py`, `backend/app/api/deps.py` — только если тест AC-38 нашёл утечку; причина — в отчёте)
- **Зависит от:** R7-T14
- **Описание:** nginx: `log_format gt_access` без строки запроса (`$remote_addr - $remote_user
  [$time_local] "$request_method $uri $server_protocol" $status $body_bytes_sent
  "$http_user_agent"`) и `access_log … gt_access` в сервере 443; `location = /healthz` без
  изменений. Код меняется только при найденной утечке.
  Test-writer: AC-38 — перехват всех логов (`capsys` JSON-вывода `configure_logging("DEBUG")` и
  `caplog`) при: выпуске ключа; «кто я», создании задачи и комментарии по ключу; запросах после
  отзыва; ключе с изменённым символом; 403 (маршрут вне перечня и чужая задача), 422, 429 по ключу;
  500 по ключу (подмена `app.domain.tasks.queries.get_task` исключением) — ни в логах, ни в телах
  ответов (кроме ответа на выпуск), ни в `domain_event` (все столбцы, текстом), ни в ответах
  `/admin/audit` нет секрета и его подстрок длиной ≥ 8. AC-39 — после выпуска выгрузить все
  таблицы схемы `public` (`SELECT * FROM <таблица>` для каждой из `information_schema.tables`,
  текстовые значения и `bytea` как байты) — секрета и подстрок ≥ 8 нет (сравнение в байтах и в
  тексте). `test_web_hardening.py` (статически, `infra_static`): у сервера 443 `access_log` с
  форматом без `$request` и `$args`/`$query_string`/`$request_uri`.
- **Старые тесты → AC:** `test_web_hardening.py` — только новый статический тест.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_api_key_leaks_007.py && pytest -q -m infra_static backend/tests/infra/test_web_hardening.py`
  зелёные; проверки бэкенда зелёные; «Фронтенд не тронут»; `python scripts/task_scope.py R7-T16` → 0.
- **Попытки:** 0

## R7-T17 — MCP: протокол stdio, транспорт, конфигурация (без инструментов)
- **Статус:** DONE
- **AC:** FR-37, FR-38 (ключ из окружения, отказ без ключа), NFR-3, NFR-6; AC-38 (stderr инструментов); plan §4.9, PD-12, PD-14, PD-15
- **Файлы:** `backend/app/agent_mcp.py` (новый);
  тесты: `backend/tests/unit/test_agent_mcp_protocol_007.py` (новый), `backend/tests/unit/test_agent_mcp_transport_007.py` (новый),
  `backend/tests/cli/test_agent_mcp_stdio_007.py` (новый)
- **Зависит от:** —
- **Описание:** По plan §4.9: `ApiResponse`, `TransportError`, `Transport`, `UrllibTransport`
  (PD-15: проверка URL, без переадресаций, `GOSTRACKER_CA_FILE`, таймаут, `Authorization: Bearer`,
  разбор тела и `Retry-After` из `HTTPError`), `ToolSpec`, `McpServer` (`initialize`, `ping`,
  `tools/list`, `tools/call`, уведомления, ошибки JSON-RPC, формат `CallToolResult`, локальная
  проверка аргументов PD-14), `serve`, `build_server`, `main`; `TOOLS = ()` (инструменты —
  R7-T18). **Только стандартная библиотека, импортов `app.*` нет.** Логи — в stderr: имя
  инструмента и HTTP-статус; аргументы, тела и ключ не логируются.
  Test-writer: протокол (`McpServer` с поддельным `Transport` и тестовым `ToolSpec`): согласование
  версии (поддержанная → она же, иная → `2025-06-18`); `capabilities.tools`; `ping` → `{}`;
  уведомление → `None`; неизвестный метод → `-32601`; массив → `-32600`; неизвестный инструмент →
  `-32602`; исключение транспорта → результат-ошибка без трассировки, следующий вызов работает;
  ответ API 422 → `isError: true`, `status`, `code`, `detail`; 429 и 503 → `retry_after_seconds`;
  без ключа (`transport=None`) → 401 `not_authenticated` без обращения к транспорту; неизвестный
  аргумент и не-UUID в параметре пути → `invalid_arguments` без обращения к транспорту.
  Транспорт (`http.server` на `127.0.0.1` в потоке): заголовок `Bearer`, JSON-тело, query; 4xx с
  телом; `Retry-After`; ответ 308 → `redirect_not_allowed`, второй запрос не отправлен;
  `http://example.org` и URL с путём → `ValueError` без ключа в тексте; `https://` допускается.
  stdio (подпроцесс `sys.executable -I backend/app/agent_mcp.py`, окружение без ключа, затем с
  ключом и `GOSTRACKER_URL=http://127.0.0.1:9`): `initialize` → ответ одной строкой; битая
  строка JSON → `-32700`, процесс продолжает; EOF → код выхода 0; в stdout только JSON-RPC; stderr
  не содержит ключа и его подстрок ≥ 8. AST-тест: все импорты модуля — из `sys.stdlib_module_names`.
- **Старые тесты → AC:** нет (`test_no_telemetry.py` зелёный без правок).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/unit/test_agent_mcp_protocol_007.py backend/tests/unit/test_agent_mcp_transport_007.py backend/tests/cli/test_agent_mcp_stdio_007.py backend/tests/unit/test_no_telemetry.py`
  зелёный; проверки бэкенда зелёные; «Фронтенд не тронут»; `python scripts/task_scope.py R7-T17` → 0.
- **Попытки:** 0

## R7-T18 — MCP: 11 инструментов агента и сквозные тесты
- **Статус:** TODO
- **Заметки ревью R7-T17 (обязательно учесть, `reviews/R7-T17-1.md`):** (1) ключ недопустимого формата → 401 `not_authenticated` без сети (`McpServer(None)`), `config_error` только для URL/CA (AC-45); (2) `Retry-After` из очень длинной строки не должен давать -32603 (try/except); (3) регрессионные тесты: системные прокси игнорируются, нечитаемый `GOSTRACKER_CA_FILE`, ключ с `\r\n`/пробелом, обходы URL; (4) снять skip в `test_agent_mcp_stdio_007.py:162`, тест утечки через `connection_error`; (5) по возможности лимит длины строки stdin.
- **AC:** AC-42, AC-43, AC-44, AC-45, AC-38 (результаты и логи инструментов); FR-35, FR-36, FR-37, FR-38; plan §4.9, PD-13, PD-14
- **Файлы:** `backend/app/agent_mcp.py`, `backend/pyproject.toml` (только `[project.scripts] gostracker-mcp`);
  тесты: `backend/tests/api/test_agent_mcp_tools_007.py` (новый), `backend/tests/mcp_support.py` (новый)
- **Зависит от:** R7-T15, R7-T17
- **Описание:** `TOOLS` — 11 `ToolSpec` по таблице plan §4.9 (имена, запросы, параметры, схемы,
  описания на русском с правилами FR-36). `[project.scripts]`: `gostracker-mcp =
  "app.agent_mcp:main"` — зависимости не меняются. `mcp_support.py` — `BridgeTransport` и
  `McpTestClient` (plan §5).
  Test-writer (мир `make_world007`, клиент через `BridgeTransport` с `K_u`): AC-42 (имена — ровно
  11 из plan §4.9; у каждого описание и `inputSchema` с `type`, `properties`, `required`,
  `additionalProperties: false`; перечисления статуса и приоритета — ровно spec; у `due_date`
  `format: date` и «YYYY-MM-DD» в описании; описание `create_task` называет название, описание,
  срок и «Europe/Moscow»; описание `set_task_status` — `done` как закрытие; у `update_task` нет
  `status`; ни у одного инструмента нет параметра для ключа). AC-43 (пять вызовов → успех; у `ba1`
  задача `done`, автор и исполнитель `agent.u`, комментарий `agent.u`; события — по AC-35). AC-44
  (создание без описания → `isError`, 422, `validation_error`, `detail`, без трассировки; затем
  `whoami` → успех в том же клиенте; 121-й вызов в минуту → `too_many_requests` и
  `retry_after_seconds`). AC-45 (без ключа, с отозванным, с искажённым → ошибка аутентификации,
  задач не прибавилось; описания, схемы и результаты всех вызовов не содержат `K_u` и подстрок ≥
  8; перехваченные логи модуля — тоже). Каждый инструмент вызван хотя бы раз и обращается ровно к
  своему методу и пути (журнал `BridgeTransport`).
- **Старые тесты → AC:** нет (`test_dependencies_allowlist.py` зелёный без правок).
- **Готово, когда:** `source .venv/bin/activate && pip install -e "backend[dev]" -q && pytest -q backend/tests/api/test_agent_mcp_tools_007.py backend/tests/unit/test_agent_mcp_protocol_007.py backend/tests/cli/test_agent_mcp_stdio_007.py backend/tests/arch/test_dependencies_allowlist.py`
  зелёный; `gostracker-mcp < /dev/null` завершается с кодом 0; проверки бэкенда зелёные;
  «Фронтенд не тронут»; `python scripts/task_scope.py R7-T18` → 0.
- **Попытки:** 0

## R7-T19 — Интерфейс: метка «ИИ» — компонент, карточка задачи (автор, исполнитель), комментарии
- **Статус:** TODO
- **AC:** FR-31 (карточка, комментарии), FR-29 (автор виден); AC-37 (автотесты компонентов, сам AC — ручной); plan §4.10, PD-16, З-7
- **Файлы:** `frontend/src/shared/ui/UserPicker.tsx`, `frontend/src/features/tasks/TaskPage.tsx`,
  `frontend/src/features/comments/Comments.tsx`, `frontend/src/shared/i18n/ru.ts`, `frontend/src/shared/ui/ui.css`;
  тесты: `frontend/tests/features/tasks/AgentMark.test.tsx` (новый)
  (+ `frontend/tests/features/tasks/TaskPage.test.tsx`, `frontend/tests/features/tasks/taskpage-helpers.tsx`,
  `frontend/tests/shared/i18n.test.ts` — только если тест перечисляет все строки `dl.ui-props` или ключи словаря: дополнить)
- **Зависит от:** R7-T06
- **Описание:** По plan §4.10: экспорт `UserName` в `UserPicker.tsx`; в карточке исполнитель —
  `UserName`, новая пара «Автор» / `dd[data-field="author"]` последней в `dl.ui-props`; автор
  комментария — `UserName`. Ключи `users.agent_mark`, `users.agent_mark_title`,
  `tasks.author_label`; `.ui-agent-mark` в `ui.css` (цвета только `var(--…)`, без `font-size`).
  Test-writer: карточка задачи с автором-агентом и исполнителем-агентом — в `data-field="author"`
  и в ячейке исполнителя текст логина и `abbr.ui-agent-mark` «ИИ» с `title` «ИИ-агент»; у людей
  метки нет; комментарии агента и человека — так же; прежний порядок строк `dl` не изменился,
  «Автор» — последняя.
- **Старые тесты → AC:** перечни строк карточки (если есть) дополняются строкой «Автор» (FR-31).
- **Готово, когда:** `cd frontend && npx vitest run tests/features/tasks tests/shared` зелёный;
  проверки фронтенда зелёные; «Бэкенд не тронут»; `python scripts/task_scope.py R7-T19` → 0.
- **Попытки:** 0

## R7-T20 — Интерфейс: метка «ИИ» на доске и в списке задач
- **Статус:** TODO
- **AC:** FR-31 (доска, списки задач); AC-37 (автотесты компонентов); plan §4.10
- **Файлы:** `frontend/src/features/boards/BoardView.tsx`, `frontend/src/features/tasks/TaskList.tsx`;
  тесты: `frontend/tests/features/boards/AgentMarkBoard.test.tsx` (новый)
- **Зависит от:** R7-T19
- **Описание:** Исполнитель на карточке доски (`data-field="assignee"`) и в
  `td[data-field="assignee"]` списка задач — через `UserName`. Фильтр исполнителей доски не
  меняется.
  Test-writer: доска и список задач проекта с карточками исполнителей-агента и человека — метка
  «ИИ» только у агента; «Не назначен» без метки.
- **Старые тесты → AC:** нет (`BoardView.test.tsx`, `TaskList.test.tsx` зелёные без правок:
  фикстуры с `is_agent: false`).
- **Готово, когда:** `cd frontend && npx vitest run tests/features/boards tests/features/tasks`
  зелёный; проверки фронтенда зелёные; «Бэкенд не тронут»; `python scripts/task_scope.py R7-T20` → 0.
- **Попытки:** 0

## R7-T21 — Интерфейс ТА: создание учётной записи агента, метка в «Учётных записях»
- **Статус:** TODO
- **AC:** FR-40 (создание агента), FR-31 («Учётные записи»), FR-2 (нет роли ТА у агента в выборе), FR-1 (нет сброса пароля); AC-37 (автотесты); plan §4.10
- **Файлы:** `frontend/src/features/admin/api.ts`, `frontend/src/features/admin/UsersPage.tsx`,
  `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/features/admin/UsersPageAgents.test.tsx` (новый)
  (+ `frontend/tests/features/admin/UsersPage.test.tsx`, `frontend/tests/features/admin/helpers.tsx`,
  `frontend/tests/shared/i18n.test.ts` — только дополнение перечней полей формы, кнопок строки и кодов ошибок)
- **Зависит от:** R7-T08, R7-T20
- **Описание:** По plan §4.10: `createAgent`; логин в строке — `UserName`; флажок «Учётная запись
  ИИ-агента» в форме создания (пароль и генерация скрыты, выбор роли П / БА / «Без роли», П по
  умолчанию, тело `{login, role}`, сообщение об успехе без окна пароля); у строки агента нет
  «Сбросить пароль», в выборе роли нет ТА, есть кнопка `data-action="keys"` «Ключи» (пока без
  действия — его даёт R7-T22; кнопка `disabled` не делается). Коды ошибок — ключи
  `error.agent_role_not_allowed`, `error.agent_password_not_allowed`, `error.not_an_agent`,
  `error.api_key_limit_reached`.
  Test-writer: флажок → поле пароля исчезает, появляется выбор роли; отправка → ровно один
  `POST /api/v1/admin/agents` с `{login, role: "user"}`; ответ 201 → сообщение, строка с меткой
  «ИИ»; 422 `agent_role_not_allowed`/`login_taken` → сообщение `errorMessage(code)`; строка
  агента: нет сброса пароля, в выборе роли нет ТА, есть «Ключи»; строка человека — как прежде.
- **Старые тесты → AC:** точные перечни кнопок строки и полей формы в `UsersPage.test.tsx` →
  дополнены для строки агента (FR-40); строка человека не меняется.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/admin tests/shared` зелёный;
  проверки фронтенда зелёные; «Бэкенд не тронут»; `python scripts/task_scope.py R7-T21` → 0.
- **Попытки:** 0

## R7-T22 — Интерфейс ТА: ключи агента (перечень, выпуск с однократным показом, отзыв); журнал аудита
- **Статус:** TODO
- **AC:** FR-40, FR-6 (интерфейс), FR-7, FR-11 (подписи журнала); AC-37 (автотесты компонентов); plan §4.10, PD-17, З-7
- **Файлы:** `frontend/src/features/admin/api.ts`, `frontend/src/features/admin/UsersPage.tsx`,
  `frontend/src/features/admin/AuditPage.tsx`, `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/features/admin/AgentKeys.test.tsx` (новый), `frontend/tests/features/admin/AuditPage.test.tsx`
  (+ `frontend/tests/features/admin/helpers.tsx`, `frontend/tests/shared/i18n.test.ts` — только добавить помощники и ключи)
- **Зависит от:** R7-T10, R7-T21
- **Описание:** По plan §4.10 и PD-17: `listApiKeys`, `issueApiKey`, `revokeApiKey`; компонент
  `AgentKeys` внутри `UsersPage.tsx` (открывается кнопкой «Ключи»): таблица с `Pagination`,
  форма выпуска (название, срок 30/90/180/365, 90 по умолчанию), окно секрета (поле только для
  чтения, «Копировать» → `navigator.clipboard.writeText`, предупреждение, «Закрыть»; секрет
  только в `useState`, без `useMutation` и кэша запросов), отзыв через `ConfirmDialog`; после
  выпуска и отзыва перечень перечитывается. `AuditPage`: три действия, `detailsText` (роль; «Ключ
  «{name}»»). Если `UsersPage.tsx` не удаётся уложить без нового файла — `PLAN_ISSUE` (RK-11).
  Test-writer: перечень — состояния «действует» / «истёк» / «отозван <время по Москве>»,
  «не использовался»; выпуск — ровно один `POST …/api-keys` с `{name, expires_in_days: 90}`;
  окно показывает секрет, «Копировать» вызывает `clipboard.writeText` с секретом; после
  «Закрыть» секрета нет в `document.body`, в кэше `QueryClient` (все запросы и мутации) и при
  повторном открытии раздела ключей; 422 `api_key_limit_reached` → сообщение; отзыв — окно
  подтверждения, «Отмена» не шлёт запрос, подтверждение → один `POST …/revoke`, затем состояние
  «отозван». Журнал: три новых действия с русскими подписями и деталями.
- **Старые тесты → AC:** `AuditPage.test.tsx` — перечень действий дополнен тремя (FR-11).
- **Готово, когда:** `cd frontend && npx vitest run tests/features/admin tests/shared` зелёный;
  проверки фронтенда зелёные; «Бэкенд не тронут»; `python scripts/task_scope.py R7-T22` → 0.
- **Попытки:** 0

## R7-T23 — Замер накладных расходов ключа (NFR-2)
- **Статус:** TODO
- **AC:** AC-48 (*вне CI*); NFR-2; plan PD-19
- **Файлы:** тесты: `backend/tests/perf/test_api_key_overhead_007.py` (новый)
- **Зависит от:** R7-T12
- **Описание:** **Только тест.** Мир `make_world007`; пользователь с ролью П — исполнитель T1 с
  cookie-сессией. Без `GT_PERF` — 20 запросов карточки T1 по `K_u` и 20 по cookie, проверяются
  только ответы 200 (CI). С `GT_PERF=1` — 20 прогревочных, затем 200 + 200 (по очереди, один
  клиент), `time.perf_counter`, p95 по ключу − p95 по сессии ≤ 20 мс; значения p95 печатаются
  (без секретов). Лимит FR-33 обходится паузой часов: `fixed_clock` сдвигается на 61 с каждые 100
  запросов по ключу.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/perf/test_api_key_overhead_007.py`
  зелёный; `GT_PERF=1 pytest -q backend/tests/perf/test_api_key_overhead_007.py -s` выполнен, p95
  приложены к отчёту (порог проверяется вне CI); `git diff --stat HEAD -- backend/app frontend docs`
  пуст; `python scripts/task_scope.py R7-T23` → 0.
- **Попытки:** 0

## R7-T24 — Документы: ADR-0015, инструкция для агентов, README, чек-лист приёмки, глоссарий
- **Статус:** TODO
- **AC:** FR-39, NFR-7 (ADR); AC-37, AC-46, AC-48 (*ручные* / *вне CI*: пункты чек-листа); plan PD-20, §4.9
- **Файлы:** `docs/adr/0015-agent-access.md` (новый), `docs/agents.md` (новый), `README.md`,
  `docs/acceptance/mvp-demo.md`, `docs/glossary.md`
- **Зависит от:** R7-T18, R7-T22
- **Описание:** ADR-0015 по `docs/adr/TEMPLATE.md`: контекст (spec 007), решения PD-1…PD-5,
  PD-12, PD-13, PD-15; последствия (дополняет ADR-0004; Basic-аутентификация прокси перед API не
  поддерживается; `http` для инструментов только loopback; откат 0008 теряет ключи); отвергнутые
  альтернативы из plan §2. `docs/agents.md` (русский, FR-39): создание учётной записи агента и
  выпуск ключа в «Учётных записях» и через API; подключение Claude Code (`claude mcp add …`
  plan §4.9, `GOSTRACKER_CA_FILE` = `deploy/tls/…` при самоподписанном сертификате, проверка
  командой «кто я»); 11 инструментов (таблица); ошибки 401/403/422/429; отзыв ключа и блокировка;
  предупреждения — ключ не вставлять в текст запроса к модели, не коммитить (в `.mcp.json` только
  `${GOSTRACKER_API_KEY}`), не пересылать; срок 90/365 суток, 5 ключей, 120 запросов в минуту.
  `README.md` — ссылка на `docs/agents.md` в русской и английской частях. `mvp-demo.md` — пункты
  `- [ ] 007/AC-37`, `- [ ] 007/AC-46`, `- [ ] 007/AC-48` (команда `GT_PERF=1 …` из R7-T23).
  `docs/glossary.md` — «Учётная запись агента», «Ключ доступа», «Операции агента», «Инструменты
  агента». Пути в обратных кавычках — только существующие.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `source .venv/bin/activate && pytest -q -m infra_static backend/tests/infra/test_docs_static.py`
  зелёный без правок теста; в чек-листе по одному пункту `007/AC-37`, `007/AC-46`, `007/AC-48`;
  код не тронут; `python scripts/task_scope.py R7-T24` → 0.
- **Попытки:** 0

## R7-T25 — Спецификация 001 v0.21 (синхронизация NFR-7)
- **Статус:** TODO
- **AC:** NFR-7 (правки 001: FR-4, FR-41, FR-57, модель данных, включая запись событий задач и
  комментариев по 007/FR-42)
- **Файлы:** `specs/001-pilot-r1/spec.md`
- **Зависит от:** R7-T24 (и R7-T14 — фактическое поведение событий)
- **Описание:** История версий v0.21 «агенты и ключи доступа; события задач и комментариев —
  дельта 007/FR-1…FR-42 (`specs/007-ai-agent-tools/spec.md` v0.4)». Места:
  - FR-4 — виды учётных записей (человек, агент) и кто их создаёт;
  - FR-41 — действия `user.agent_created`, `user.api_key_issued`, `user.api_key_revoked`;
  - FR-57 — ключ доступа — секрет наравне с паролем (маскирование, только дайджест);
  - Data Model (раздел `# Data Model`) — `app_user.is_agent`, `api_key`,
    `domain_event.api_key_id` и **запись событий задач и комментариев**: с 007 для всех авторов
    пишутся `task.created`, `task.updated` (перечень изменённых полей: название, описание, срок,
    приоритет, исполнитель, статус; перенос по доске в другую колонку — поле «статус»),
    `comment.created`, `comment.deleted` (только прямое удаление); не пишут удаление задач и
    каскады, правка комментария, перенос внутри колонки, снятие исполнителя при исключении
    участника; задним числом событий нет. Это заменяет решение plan 001 D-55 («события задач и
    комментариев не пишутся») — указать ссылкой «D-55 заменено 007/FR-42». Лента активности
    (FR-38, SC-8, UF-9, AC-90) по-прежнему отложена: события записываются, но не показываются;
    строки «Лента проекта» в сводной таблице отложенного и FR-38 не менять.
  Номера 001 не менять; тексты — из spec 007 (FR-42, раздел 6) и plan 007 (PD-9, PD-22…PD-24).
  Spec 007 не трогать: З-1 решён владельцем, раздел 0 spec 007 уже исправлен (v0.3/v0.4).
- **Старые тесты → AC:** нет.
- **Готово, когда:** `git diff --stat` затрагивает только этот файл; каждое из четырёх мест
  отражено, в Data Model есть запись событий FR-42 со ссылкой «D-55 заменено 007/FR-42» и
  пометкой, что лента FR-38 отложена (сверка ревьюером); `pytest -q -m infra_static backend/tests/infra/test_docs_static.py`
  зелёный; `python scripts/task_scope.py R7-T25` → 0.
- **Попытки:** 0

## R7-T26 — Финальная приёмка 007
- **Статус:** TODO
- **AC:** AC-47; сверка plan §6.1 и §6.2; AC-37, AC-46, AC-48 (*ручные* / *вне CI* — передаются владельцу)
- **Файлы:** нет (только проверки; дефекты — новые задачи R7-Tnn по решению оркестратора)
- **Зависит от:** R7-T01…R7-T25
- **Описание:** Выполнить и приложить итог:
  (1) `bash scripts/check.sh` (тестовая БД — «Общие условия»; включает `alembic check`, весь
  `pytest`, фронтенд `lint`, `typecheck`, `test`, `build`);
  (2) AC-47: `test_api_compat_007.py` зелёный; `git diff f7f19cf -- backend/tests frontend/tests --stat`
  — для каждого изменённого существующего тестового файла: удалённых тестов нет, ассерты не
  ослаблены, изменения — дополнения по plan §6.2; `test_route_guards.py` (в т.ч. `origin_mismatch`)
  зелёный без правок;
  (3) `git diff f7f19cf -- frontend/package.json frontend/package-lock.json` пуст,
  `git diff f7f19cf -- backend/pyproject.toml` — только `[project.scripts]`;
  `pytest -q backend/tests/arch/test_dependencies_allowlist.py` зелёный;
  (4) каждый автоматический AC из plan §6.1 сопоставлен зелёному тесту (имя);
  (5) `bash scripts/gen-api.sh` не меняет файлы;
  (6) `git grep -n -E "gtk_[A-Za-z0-9_-]{43}" -- . ':!*.lock'` — пусто (в репозитории нет
  настоящих ключей);
  (7) стековые тесты web (`pytest -q -m infra_stack backend/tests/infra/test_web_hardening.py`), если
  Docker доступен; иначе — отметка «не выполнено» с причиной;
  (8) пункты `007/AC-37`, `007/AC-46`, `007/AC-48` есть в чек-листе и отмечены как ожидающие
  владельца; в отчёте отмечено: З-1 решён владельцем 2026-10-30 (spec v0.3 FR-42, v0.4
  Q-11…Q-13), AC-49…AC-53 сопоставлены зелёным тестам `test_agent_events_007.py`;
  (9) AC-47, события: `git diff f7f19cf -- backend/tests` по файлам plan §6.2 (строки R7-T14) —
  правки только в названных там тестах, имена тестов те же, ожидания — точные списки событий
  FR-42; в `test_event_log.py` недопустимое поле проверяется на `position`; ни один тест из
  «Проверены и не меняются» plan §6.2 не изменён.
- **Старые тесты → AC:** итоговая сверка (п. 2).
- **Готово, когда:** пп. 1–9 выполнены, отчёт содержит команды и их итог; ручные AC отмечены как
  ожидающие владельца.
- **Попытки:** 0

---

## Ручные AC и замеры (сводка)

| AC | Где проверяется | Задача |
|---|---|---|
| AC-37 | `docs/acceptance/mvp-demo.md`, пункт `007/AC-37`; браузер, `ba1` и `ta1` | R7-T24, R7-T26 |
| AC-46 | пункт `007/AC-46`; Claude Code по `docs/agents.md`, стенд по README | R7-T24, R7-T26 |
| AC-48 | пункт `007/AC-48`; `GT_PERF=1 pytest -q backend/tests/perf/test_api_key_overhead_007.py -s` | R7-T23, R7-T24, R7-T26 |
