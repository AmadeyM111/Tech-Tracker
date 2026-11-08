# Tasks: Самостоятельная регистрация по email (spec 019)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия для всех задач R8

- Источник истины — `specs/019-self-registration-email/spec.md` v0.4 (APPROVED). Интерфейсы и решения —
  `specs/019-self-registration-email/plan.md`: решения `RG-n` (§2), интерфейсы §4, трассировка §6, вопросы `Q-n`
  (§9). Если задача противоречит spec или plan, вернуть `PLAN_ISSUE` и ничего не додумывать.
- **Ветка:** `feat/self-registration` от `origin/work3` (020 MCP), голова миграций там `0009`
  (`0009_mcp_agent_access`). Миграция регистрации — `0010` (plan RG-21). В `work3` нет последних коммитов `main`
  (PR #7, GTrack): CLI называется `gostracker`, справка `/login` — по 005 v0.1. Слияние с `main` — R8-T00 (plan §7, R-12).
- **Решения владельца 2026-11-08** (plan §9): события `user.self_registered`/`user.name_changed`; 422 входят в лимит
  заявок с IP; второй абзац справки `/login` только при включённой регистрации; у ТА нет `onboard_accounts`; не ровно
  одно пространство → 404 `feature_disabled`.
- **Предусловие запуска, не разработки:** до решения ИБ по К-4 (ADR-0019) функцию не включают на стенде с
  реальным доступом. На код и тесты это не влияет.
- **ID задач с префиксом `R8-`**: `scripts/task_scope.py` требует уникальный ID во всех `specs/*/tasks.md`.
- **Рамки файлов.** Менять только файлы из поля «Файлы». Проверка: `python scripts/task_scope.py R8-Tnn` из корня
  (выход 0). `docs/api/openapi.json` и `frontend/src/shared/api/schema.d.ts` меняются только командой
  `source .venv/bin/activate && bash scripts/gen-api.sh` и только в задачах, где это сказано.
- **Не трогать:** `backend/pyproject.toml`, `frontend/package.json`, `frontend/package-lock.json` (новых
  зависимостей нет, NFR-6), `backend/app/core/config.py`, `.env.example`, `docker-compose.yml` (новых настроек нет,
  AC-32), `CLAUDE.md`, `AGENTS.md`, `docs/STATE.md`, `docs/adr/**`, `docs/brief/**`, `specs/**/spec.md`, применённые
  миграции `0001…0009` (в том числе `0009_mcp_agent_access.py` из 020).
- **Слои (AGENTS.md).** Роутер: схема → один вызов сервиса `domain/` → схема ответа. Запросов к БД в роутерах нет.
  `commit()` в `app/**` запрещён. `commit_durably` разрешён только в `domain/auth/service.py`, `api/deps.py` и
  (с R8-T09) `domain/auth/registration.py`, там ровно в местах RG-6. Ошибки — только подклассы `AppError`.
- **Секреты и ПДн (NFR-1).** Email, имя, фамилия, логин из заявки, токен и его хеш, пароль и его хеш, текст
  письма не попадают в логи, тексты исключений, ответы API и журнал аудита. Исключения: `email` в ответах
  `/admin/users*` (ТА) и данные своего профиля в `/me`. В ответах для БА email нет.
- **Сложность (ruff):** `max-complexity=16`, `max-branches=16`, `max-args=10`, `max-statements=34`. Длинные
  функции дробить на приватные помощники (plan §4.3).
- **Строки интерфейса** — только из `frontend/src/shared/i18n/ru.ts` (ключи — plan §4.7). Кириллица в
  `frontend/src` вне словаря запрещена. Код и комментарии во фронтенде на английском, в бэкенде — на языке
  окружения файла (там русский). Письмо — по-русски.
- **Новые файлы в `frontend/src`** допускаются только перечисленные в задачах. Каждый добавляется в белый список
  `backend/tests/infra/test_frontend_scaffold.py::test_t21_src_files_only_expected` в той же задаче.
- **БД.** Деструктивные операции — только в тестовой БД `*_test`:
  `export TEST_DATABASE_URL=postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test`. Тома Docker не удалять.
- **Время в тестах:** бэкенд — `fixed_clock` (`advance`, `set`), фронтенд — `vi.setSystemTime`.
- **SMTP в тестах** только подменённый: фикстура `reset_api_env` (`backend/tests/conftest.py`), письма в
  `env.app.state.mailer.sent` (`tests/mail_support.py::RecordingMailer`). Сеть не используется. В тестах регистрации
  в БД ровно одно пространство (RG-9).
- **Тесты** пишет test-writer, исполнитель их не меняет. Новые тесты: бэкенд — `test_019_acN_*` (или
  `test_019_<тема>_*` для FR без AC), фронтенд — `019_acN_*`. Существующие assert-ы не ослабляются, только
  дополняются (списки маршрутов, голова миграций, белые списки, аргументы имён в вызовах создания учётной записи).
- **Красный typecheck фронтенда (plan R-3).** После перегенерации API в R8-T04…T11 `npm run typecheck` может
  падать на `frontend/src/features/admin/UsersPage.tsx` до R8-T20. Это ожидаемо: бэкенд-задачи фронтенд-код не
  правят. Типизированные моки (`frontend/tests/features/admin/helpers.tsx`, `frontend/tests/app/startPath.test.ts`)
  правятся в задаче, где меняется тип, если они перечислены в её файлах.
- **Команды.**
  - «Линт бэкенда» = `source .venv/bin/activate && ruff check backend && ruff format --check backend && mypy --config-file backend/pyproject.toml backend/app`.
  - «Линт фронтенда» = `cd frontend && npm run lint && npm run typecheck`.
  - «Перегенерация API» = `source .venv/bin/activate && bash scripts/gen-api.sh`, затем
    `pytest -q backend/tests/infra/test_frontend_api_types.py backend/tests/cli/test_openapi.py backend/tests/cli/test_openapi_roles.py` зелёный.
- **Коммиты** делает оркестратор (Conventional Commits, без `git push`).

Порядок и критический путь:
R8-T01 → R8-T02 → R8-T08 → R8-T09 → R8-T10 → R8-T11 → R8-T14 → R8-T15 → R8-T16 → R8-T17 → R8-T18 → R8-T22 → R8-T00.
R8-T00 (проверка слияния с `main`) выполняется последней, перед выпуском, после того как 020 влита в `main`.
Параллельно: R8-T03 (после T01, T02) → R8-T04 → R8-T05; R8-T06 (после T02, T03) → R8-T07; R8-T12 и R8-T13 (после
T01); фронтенд R8-T19 (после T05, T15, T18), R8-T20 (после T04, T15), R8-T21 (после T07, T15, T19, T20).
Задачи, которые перегенерируют API (T02, T04, T05, T07, T11) или меняют `test_openapi.py`, выполнять
последовательно. Задачи, которые меняют `router.tsx` (T16, T17, T19, T21), `features/auth/api.ts` (T16, T19),
`features/admin/api.ts` (T20, T21), `backend/app/domain/users/service.py` (T03, T04) и `test_frontend_scaffold.py` (T16,
T17, T19, T20, T21), тоже последовательно.

---

## R8-T01 — Миграция 0010 и модели: имена, `self_registered`, `registration_request`, `registration_attempt`
- **Статус:** DONE
- **AC:** AC-36; основа для AC-8, AC-13, AC-18, AC-22, AC-38
- **Файлы:** `backend/migrations/versions/0010_self_registration.py` (новый), `backend/app/domain/users/models.py`, `backend/app/domain/auth/models.py`;
  тесты: `backend/tests/db/test_019_schema.py` (новый), `backend/tests/upgrade002_support.py`, `backend/tests/db/test_migrations.py`, `backend/tests/db/test_007_schema.py`, `backend/tests/factories.py`
- **Зависит от:** —
- **Описание:** По plan §4.1. В `AppUser` добавить `first_name`/`last_name` (`String(100)`, nullable) и
  `self_registered` (`Boolean`, `nullable=False`, `default=False`, `server_default=false()`). В `auth/models.py`
  добавить модели `RegistrationRequest` и `RegistrationAttempt` с полями, `UNIQUE`, CHECK и индексами из §4.1,
  время через `utcnow`, без FK. Миграция `0010_self_registration.py` по образцу `0008_password_reset_email.py`:
  docstring со ссылкой на spec 019, `revision="0010"`, `down_revision="0009"` (ревизия `0009_mcp_agent_access.py`),
  без импорта `app.*`, downgrade удаляет всё созданное. `0009_mcp_agent_access.py` не менять. Голова
  `"0009"` → `"0010"`: `upgrade002_support.py:67` (`HEAD_REVISION`), `test_migrations.py` (строки ~962, 996, 1010,
  1070, включая тексты сообщений и комментарии о голове), `test_007_schema.py` (строки ~127, 377, 394).
  `test_m20_t02_mcp_schema.py` не трогать (его `downgrade 0008` проходит через `0010`). Если в базе ветки голова не
  `"0009"` (`alembic heads`), вернуть `PLAN_ISSUE` (RG-21).
  `make_user` получает необязательные `first_name`, `last_name` (`None`) и `self_registered` (`False`).
  Test-writer: upgrade 0009→0010 на БД с пользователем → имена NULL, `self_registered=false`, прочие колонки
  прежние, вход работает; downgrade → upgrade; `UNIQUE(email)` и `UNIQUE(token_hash)` заявки; CHECK нижнего
  регистра email, длины `token_hash`/`key_hash`, `scope`.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/db/test_019_schema.py backend/tests/db/test_migrations.py backend/tests/db/test_identity_models.py backend/tests/db/test_007_schema.py backend/tests/db/test_m20_t02_mcp_schema.py` зелёный; `alembic -c backend/alembic.ini heads` выводит одну голову `0010`;
  `alembic -c backend/alembic.ini upgrade head && alembic -c backend/alembic.ini check` на `*_test` БД чисты; «Линт бэкенда» чист
- **Попытки:** 1

## R8-T02 — Ошибки, возможность БА `onboard_accounts`, каталог событий
- **Статус:** DONE
- **AC:** основа для AC-18, AC-19, AC-28, AC-29, AC-30, AC-34, AC-35, AC-38
- **Файлы:** `backend/app/core/errors.py`, `backend/app/domain/access/roles.py`, `backend/app/domain/events/catalog.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` (перегенерация);
  тесты: `backend/tests/unit/test_019_errors.py` (новый), `backend/tests/unit/test_role_matrix.py`, `backend/tests/unit/test_event_catalog.py`, `backend/tests/api/test_sessions.py`, `backend/tests/api/test_deps_gates.py`
- **Зависит от:** —
- **Описание:** По plan §4.2: классы `RateLimited` (429 `rate_limited`), `RegistrationTokenInvalid` (400
  `registration_token_invalid`), `LoginTakenConflict` (409 `login_taken`), члены `ErrorCode.first_name_invalid` и
  `last_name_invalid` (раздел `# [019]`). `Capability.ONBOARD_ACCOUNTS` добавляется только в `_BUSINESS_ADMIN_CAPS`
  (RG-11), у ТА и П её нет. В `backend/app/domain/events/catalog.py` после `USER_TOKEN_REVOKED`:
  `EventAction.USER_SELF_REGISTERED = "user.self_registered"` (`_USER_AUDITED`) и
  `USER_NAME_CHANGED = "user.name_changed"` (`EntityType.USER`, audit, без ленты, `fields={"first_name","last_name"}`).
  Именно с точкой: вариант `user_self_registered` из текста spec не использовать (решение владельца, RG-10).
  В `test_event_catalog.py` оба значения добавить в `USER_ACTIONS` блоком `# 019 (plan RG-10)`, для
  `user.name_changed` — строку в `EXPECTED`, если таблица перечисляет действия с полями. Перегенерировать API
  (меняется enum `Capability`). Существующие списки возможностей БА в тестах дополнить `onboard_accounts`.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/unit/test_019_errors.py backend/tests/unit/test_role_matrix.py backend/tests/unit/test_event_catalog.py backend/tests/unit/test_policy.py backend/tests/api/test_sessions.py backend/tests/api/test_deps_gates.py` зелёный; «Перегенерация API» выполнена; «Линт бэкенда» чист
- **Попытки:** 1

## R8-T03 — Домен: нормализация имени, поля учётной записи, `set_name` (ТА)
- **Статус:** DONE
- **AC:** AC-29 (правила), AC-35 (домен); основа для AC-22, AC-33
- **Файлы:** `backend/app/domain/users/names.py` (новый), `backend/app/domain/users/service.py`;
  тесты: `backend/tests/unit/test_019_names.py` (новый), `backend/tests/domain/test_019_user_names.py` (новый)
- **Зависит от:** R8-T01, R8-T02
- **Описание:** `normalize_person_name` по plan §4.3 (`strip()`, 1…100, `isprintable`). В `UserAccount`, `_Target`,
  `to_account`, `_load_target`, `list_accounts` (`load_only`) добавить `first_name`, `last_name`, `self_registered`.
  Новый `set_name(db, actor, user_id, first_name, last_name, /)` по §4.3: `MANAGE_ACCOUNTS`, 422
  `first_name_invalid`/`last_name_invalid`, протокол `_lock_for_account_change`, 404, без изменений — без события,
  иначе UPDATE и `user.name_changed` с изменёнными полями. `create_user` в этой задаче НЕ менять (R8-T04).
  Test-writer: юнит — края, пробелы, 100/101 символ, `\n` внутри, кириллица и дефис; домен — `set_name` (403 для
  БА/П, 404 чужое пространство, 422, событие без значений, повтор без события), `list_accounts` отдаёт новые поля.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/unit/test_019_names.py backend/tests/domain/test_019_user_names.py backend/tests/domain/test_user_admin_service.py backend/tests/domain/test_007_user_email.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1

## R8-T04 — Имя и фамилия при создании ТА и в Admin API
- **Статус:** DONE
- **AC:** AC-33, AC-35 (API), AC-22 (поля в списке)
- **Файлы:** `backend/app/domain/users/service.py`, `backend/app/api/v1/schemas/admin.py`, `backend/app/api/v1/admin_users.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` (перегенерация);
  тесты: `backend/tests/api/test_019_admin_names.py` (новый), `backend/tests/cli/test_openapi.py`, `frontend/tests/features/admin/helpers.tsx`, а также вызовы создания учётной записи (добавить `first_name`/`last_name`, assert-ы не менять): `backend/tests/admin_support.py`, `backend/tests/api/test_admin_users.py`, `backend/tests/api/test_audit.py`, `backend/tests/api/test_auth_login.py`, `backend/tests/api/test_login_display.py`, `backend/tests/api/test_password_change.py`, `backend/tests/api/test_route_guards.py`, `backend/tests/api/test_session_row_lock.py`, `backend/tests/api/test_sessions.py`, `backend/tests/api/test_tech_admins_002.py`, `backend/tests/api/test_users_directory.py`, `backend/tests/api/test_workspace_isolation.py`, `backend/tests/api/test_e2e_accounts.py`, `backend/tests/cli/test_bootstrap_audit.py`, `backend/tests/db/test_event_log.py`, `backend/tests/db/test_login_display_upgrade.py`, `backend/tests/db/test_three_roles_after_upgrade.py`, `backend/tests/domain/test_user_admin_service.py`, `backend/tests/domain/test_auth_service.py`, `backend/tests/domain/test_007_user_email.py`
- **Зависит от:** R8-T03
- **Описание:** `create_user(..., first_name: str, last_name: str, email=None)`: проверки в порядке RG-17,
  значения пишутся в `app_user`, `self_registered=False`. `CreateUserRequest` получает обязательные `first_name`,
  `last_name` (`str`, `max_length=MAX_CREDENTIAL_LENGTH`). `AdminUser` получает `first_name`, `last_name`,
  `self_registered`, docstring «ровно десять полей». Новый `SetNameRequest` (`extra=forbid`) и
  `PUT /admin/users/{user_id}/name` → `AdminUser` (`set_user_name`, `error_responses(400, 404, 422)`).
  `BODY_ROUTES_400` += `PUT /api/v1/admin/users/{user_id}/name`. Перегенерировать API. Список тестовых файлов
  составлен grep'ом `one_time_password` на 2026-11-08. Если найдутся ещё вызовы, добавить их и указать в отчёте.
  `UsersPage.tsx` не трогать (R8-T20, plan R-3).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api backend/tests/domain backend/tests/db backend/tests/cli` зелёный; «Перегенерация API» выполнена; «Линт бэкенда» чист
- **Попытки:** 2

## R8-T05 — Свой профиль: имена в `GET /me`, `PUT /me/name`
- **Статус:** DONE (ревью повторно: PASS, 2026-11-08; тесты T05-набора 575 passed; scope и линт — см. «Попытки»)
- **AC:** AC-34 (API)
- **Файлы:** `backend/app/domain/users/profile.py` (новый), `backend/app/api/v1/me.py`, `backend/app/api/v1/schemas/auth.py`, `backend/app/api/v1/schemas/admin.py` (поправка по ревью: у `SetNameRequest` снят `max_length`, длину проверяет домен, см. «Попытки»), `specs/019-self-registration-email/plan.md` (синхронизация §4.4 с принятым решением по длине имени), `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` (перегенерация), `docs/data-model.md` (добавлено по решению владельца 2026-11-08: имена и `self_registered` в описании `app_user`, секции `registration_request` и `registration_attempt`);
  тесты: `backend/tests/api/test_019_profile_api.py` (новый), `backend/tests/cli/test_openapi.py`, `frontend/tests/app/startPath.test.ts`, `backend/tests/api/test_route_guards.py` (правка вызова `me`, по решению владельца, test-writer); `test_sessions.py` правился в T02-коммите `b43842e`; `startPath.test.ts` не менялся (нужен только если меняется тип фронтенда)
- **Зависит от:** R8-T04
- **Описание:** По plan §4.3–4.4: `get_own_profile`, `set_own_name` (событие `user.name_changed`, актор и объект —
  сам пользователь). `MeResponse` += `first_name: str | None`, `last_name: str | None`. `GET /me` получает
  `DbSession` и берёт имена из `get_own_profile`. Новый `PUT /me/name` (`SetNameRequest` из `schemas/admin.py`) →
  `MeResponse`, гейт `get_active_actor`. `BODY_ROUTES_400` += `PUT /api/v1/me/name`. Перегенерировать API.
  Test-writer: П и БА меняют свои имена → 200 и `GET /me`; 422; без роли → 403 `no_role`; с обязательной сменой
  пароля → 403 `password_change_required`; событие без значений; `PUT /admin/users/{other}/name` от П и БА → 403.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_019_profile_api.py backend/tests/api/test_deps_gates.py backend/tests/api/test_sessions.py backend/tests/api/test_route_guards.py` зелёный; «Перегенерация API» выполнена; «Линт бэкенда» чист
- **Попытки:** 2. Поправки после ревью: (a) `SetNameRequest` без `max_length` (`schemas/admin.py`): длину 1…100 проверяет домен, поэтому 101+ даёт `first_name_invalid`; `openapi.json` перегенерирован; (c) добавлены тесты: повтор того же имени без события, 422 без эха значения в теле, NFR-1 (в логах нет значения имени) — `test_019_profile_api.py`, 33 теста в файле. **Долг (b), до T14/T22:** гонка двух одинаковых `PUT /me/name` — второе событие `user.name_changed` no-op; решение: `SELECT … FOR UPDATE` в `profile.set_own_name` перед сравнением. Предыдущая попытка: тесты: 518 passed (T05-набор + openapi + docs static), линт (ruff, mypy) чист. Ревью (reviewer): FAIL по процессу — `python scripts/task_scope.py R8-T05` сообщает файлы вне рамок (незакоммиченные T01–T04 в той же рабочей копии; коммиты делает оркестратор). Замечания по коду (minor): (a) `SetNameRequest.max_length=1024` (`schemas/admin.py`) против RG-3 (1…100): значения 101–1024 дают `first_name_invalid`, длиннее 1024 — `validation_error`; решить, поправить схему или зафиксировать в plan; (b) гонка двух одинаковых `PUT /me/name` (`profile.py`, чтение без `FOR UPDATE`): второе событие no-op, данные верны; (c) пробелы тестов: нет проверки отсутствия события при повторе тех же имён, нет проверки, что тело 422 не содержит введённое значение, нет проверки логов (NFR-1).

## R8-T06 — Домен: учётные записи без роли для БА
- **Статус:** DONE (ревью: PASS, 2026-11-08)
- **AC:** AC-30 (домен), AC-26 (БА, домен)
- **Файлы:** `backend/app/domain/users/onboarding.py` (новый); `specs/019-self-registration-email/plan.md` (примечание о режиме блокировки, см. «Попытки»);
  тесты: `backend/tests/domain/test_019_onboarding.py` (новый)
- **Зависит от:** R8-T02, R8-T03
- **Описание:** `UnassignedAccount`, `list_unassigned`, `assign_user_role`, `_lock_for_onboarding` по plan §4.3 и
  RG-11, RG-12. Advisory-ключ — та же константа `_ACCOUNT_LOCK_NAMESPACE` из `users/service.py`, импорт без
  копирования значения. Ответы: нет возможности → `Forbidden`; роль не `user` (в том числе `None`) → `Forbidden`; у
  цели есть роль → `Forbidden`; цели нет в пространстве актора → `NotFound`. Событие `user.role_assigned`,
  `details` `role_from=None`, `role_to="user"`. Email не читается.
  Test-writer: БА видит обе записи без роли (своя регистрация через `make_user(self_registered=True)` и созданная
  ТА), записей с ролью нет, чужого пространства нет; назначение «user» и событие с автором-БА; BA/TA-роль → 403;
  повтор для уже назначенной → 403; П и ТА → 403; заблокированный БА (состояние после `get_actor`) → 403.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_019_onboarding.py backend/tests/domain/test_user_admin_service.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1. Тесты: test_019_onboarding.py 25 passed; с test_user_admin_service.py 149 passed; ruff, mypy чисты; task_scope exit 0. Отклонение: plan §4.3 просит FOR NO KEY UPDATE, в коде `with_for_update(key_share=True)` (SQLAlchemy даёт FOR NO KEY UPDATE этим вызовом; text() не используется). Сериализация обеспечивается advisory-ключом. Принято ревью. Долг: тест на вызов pg_advisory_xact_lock не добавлен (minor).

## R8-T07 — API: `/unassigned-accounts`
- **Статус:** DONE (ревью: PASS, 2026-11-08)
- **AC:** AC-30, AC-26 (API)
- **Файлы:** `backend/app/api/v1/unassigned_accounts.py` (новый), `backend/app/api/v1/schemas/accounts.py` (новый), `backend/app/api/v1/__init__.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` (перегенерация);
  тесты: `backend/tests/api/test_019_onboarding_api.py` (новый), `backend/tests/cli/test_openapi.py`, `backend/tests/cli/test_openapi_roles.py`
- **Зависит от:** R8-T05, R8-T06
- **Описание:** Роутер по plan §4.4: `GET /unassigned-accounts` → `Page[UnassignedAccountOut]` и
  `PUT /unassigned-accounts/{user_id}/role` (`SetRoleRequest`) → 204, гейт роутера
  `require_capability(ONBOARD_ACCOUNTS)`. Подключить в `api/v1/__init__.py`. `BODY_ROUTES_400` += PUT. Если
  `test_openapi_roles.py` перечисляет схемы с полем роли, дополнить его использованием `SetRoleRequest` (схема
  та же). Перегенерировать API.
  Test-writer: весь AC-30 через HTTP, включая отказы БА на `/admin/users*` (block, reset-password, POST, name, role)
  и `GET /admin/audit`; ответ списка без ключа `email`; AC-26: после назначения от БА `GET /projects` той же сессией
  пользователя → 200, в `/admin/audit` (от ТА) `user.role_assigned` с `actor_id` = БА.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_019_onboarding_api.py backend/tests/api/test_route_guards.py backend/tests/api/test_admin_roles.py` зелёный; «Перегенерация API» выполнена; «Линт бэкенда» чист
- **Попытки:** 1. Тесты: 193 passed (наборы из задачи), ruff, mypy чисты, task_scope exit 0. Ревью PASS. Долг (minor, добавить в T22): тест AC-30 через /admin/users/{id}/role для записи, назначенной БА; тест роль-less → 403 no_role; заблокированный БА → 401 not_authenticated (поведение deps, план §4.4 даёт 401); docstring unassigned_accounts.py про 403 «для любого тела» уточнить (битый JSON даёт 400).

## R8-T08 — Лимиты регистрации и шаблон письма
- **Статус:** DONE (ревью: PASS, 2026-11-08)
- **AC:** AC-18, AC-38 (домен), AC-8 (шаблон)
- **Файлы:** `backend/app/domain/auth/registration_limits.py` (новый), `backend/app/domain/auth/registration_mail.py` (новый);
  тесты: `backend/tests/domain/test_019_registration_limits.py` (новый), `backend/tests/unit/test_019_registration_mail.py` (новый)
- **Зависит от:** R8-T01
- **Описание:** `registration_limits.register_attempt` по plan §4.3 и RG-4: три области, окно 1 час, удаление
  старых строк, advisory-блокировки в порядке возрастания номера (своё пространство ключей `0x72656769`), отказ без
  записи. `build_registration_mail` по RG-19: тема «Подтверждение регистрации», ссылка, «Ссылка действует 30
  минут.», «Если вы не регистрировались, ничего не делайте: учётная запись не будет создана.» В письме только
  ссылка и эти строки.
  Test-writer: 10 `request_ip` → True, 11-я → False; 20 `confirm_ip`; 5 `confirm_token`; отклонённые не пишутся;
  через 61 минуту снова True; разные значения не мешают друг другу; `key_hash` длиной 32 байта, не равен открытому
  значению; шаблон без логина, имени, фамилии и пароля.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_019_registration_limits.py backend/tests/unit/test_019_registration_mail.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1. Тесты: 27 passed; ruff, mypy чисты; task_scope exit 0. Ревью PASS. Долг (minor, в T22): (a) «нет IP/токена в дампе» сравнивать с сырыми байтами key_hash, не подстрокой; (b) тест порядка блокировок по возрастанию (удаление sorted() не ловится); (c) тест шаблона письма с другим ttl (TTL «30» жёстко зашит). Плюрализация «минут» фиксирована — при других TTL поправить.

## R8-T09 — Домен: заявка на регистрацию, политика в `lifespan`
- **Статус:** DONE (ревью: FAIL по client_ip=None → исправлено; ждёт подтверждения владельца, 2026-11-08)
- **AC:** AC-4, AC-5, AC-6, AC-7 (домен), AC-8, AC-9 (upsert), AC-11, AC-15, AC-18, AC-27, AC-29
- **Файлы:** `backend/app/domain/auth/registration.py` (новый), `backend/app/main.py`, `backend/app/core/db.py` (только docstring `commit_durably`);
  тесты: `backend/tests/domain/test_019_request_registration.py` (новый), `backend/tests/db/test_migrations.py` (разрешённый список `commit_durably`);
  `specs/019-self-registration-email/plan.md` — только примечание к RG-5 о `client_ip=None` (ревью R8-T09, добавлено в рамки задачи)
- **Зависит от:** R8-T08, R8-T02
- **Описание:** `RegistrationPolicy`, `RegistrationForm`, `confirm_link`, `ACCEPTED_DETAIL`, `request_registration`
  строго в порядке RG-7: после успешного `register_attempt` вызывается `commit_durably(db)` (RG-5, RG-6), затем
  валидация. Нормализация email — `normalize_email`, логина — `normalize_login`, имени — `normalize_person_name`.
  Argon2 через `hash_in_thread` во всех ветках после валидации. Адрес занят (любая запись `app_user`) → `None` без
  записи заявки. Иначе: удалить заявки с `expires_at <= now`, upsert по email (RG-1), письмо
  `build_registration_mail`. Пространство — RG-9, иначе `FeatureDisabled`. Токен — `password_reset.new_token()`. В
  `_lifespan` создать `state.registration_policy` по plan §4.2. В `test_commit_durably_used_only_by_auth_service`
  `allowed_users` += `"domain/auth/registration.py"`. Логов в модуле нет.
  Test-writer: каждый код ошибки и порядок проверок (AC-27: `login_taken` при свободном и занятом адресе, `Ab_c`);
  адрес занят активной и заблокированной записью → `None`, заявки нет; повторная заявка заменяет токен и данные;
  `policy=None` → `FeatureDisabled`; 422 после `commit_durably` оставляет попытку в `registration_attempt`; 11-я
  заявка → `RateLimited`, в том числе когда предыдущие 10 получили 422 (`login_taken`, `email_invalid`, пароль) —
  решение владельца, RG-5; два пространства и ноль пространств → `FeatureDisabled` (RG-9).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_019_request_registration.py backend/tests/db/test_migrations.py::test_commit_durably_used_only_by_auth_service backend/tests/unit/test_config.py backend/tests/api/test_007_password_reset_api.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 2. Тесты: 101 passed (T09 + T08 + миграции-список + unit); ruff, mypy, task_scope чисты. Исправления ревью: (1) client_ip=None → общая корзина «no-ip» (тест test_019_ac18_unknown_ip_shares_one_bucket), требует подтверждения владельца; (2) repr=False у полей _Checked; (3) шаблон письма зафиксирован явными строками; (4) контрольная проверка caplog. Открыто: вопрос владельцу о client_ip=None (вариант A — общая корзина, принят по умолчанию).

## R8-T10 — Домен: подтверждение регистрации
- **Статус:** DONE (ревью: FAIL по порядку пространства → исправлено; 2026-11-08)
- **AC:** AC-9, AC-10, AC-13, AC-14, AC-16 (домен), AC-19, AC-28, AC-38
- **Файлы:** `backend/app/domain/auth/registration.py`;
  тесты: `backend/tests/domain/test_019_confirm_registration.py` (новый);
  `specs/019-self-registration-email/plan.md` (примечание к RG-8 и RG-9 по ревью: пространство первым; см. «Попытки»)
- **Зависит от:** R8-T09
- **Описание:** `confirm_registration` в порядке RG-8 с пространством первым (ревью). `commit_durably` вызывается после `register_attempt`
  и в ветках «адрес занят» / «логин занят» после удаления заявки и перед `raise` (RG-6). Новая учётная запись
  создаётся по plan §4.3 (`self_registered=True`, `must_change_password=False`, `created_by=NULL`,
  `workspace_member.role=NULL`). Гонки ловятся savepoint'ом (`db.begin_nested()`, `ON CONFLICT (login) DO NOTHING`,
  `IntegrityError` по `uq_app_user_email`), как в `users/service.create_user`. Событие `user.self_registered`.
  Сессия не создаётся.
  Test-writer: успех и поля учётной записи (AC-13); граница 29:59/30:01 (AC-10); первый токен после второй заявки →
  `RegistrationTokenInvalid` (AC-9); адрес занят → 400 и заявки нет (AC-14); логин занят → `LoginTakenConflict`,
  заявки нет, повтор → 400 (AC-28); шестая попытка по токену и 21-я с IP → `RateLimited` (AC-38); одно событие с
  `actor_id = entity_id`, неудачи событий не пишут (AC-19); `user_session` пуст (AC-16).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_019_confirm_registration.py backend/tests/domain/test_019_request_registration.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 2. Тесты: 99 passed (test_019_confirm_registration, test_019_request_registration, `test_commit_durably_used_only_by_auth_service`); ruff check и format, mypy чисты; task_scope exit 0 (plan.md добавлен в «Файлы»). Исправления ревью: (1) MAJOR: при подтверждении пространство проверяется первым, сразу после политики и до лимитов и токена, как в RG-7 (`confirm_registration`, docstring модуля и функции, RG-8 в plan §2); неверный токен при 0 или 2 пространствах даёт 404 и не пишет попыток. Тесты `…_wrong_token_with_zero_workspaces_…`, `…_wrong_token_with_two_workspaces_…`, `…_valid_token_with_zero_workspaces_works_after_one_is_back` падали на прежнем порядке; (2) граница 30:00 добавлена в AC-10 (ловит `>` → `>=`, проверено мутацией). Открыто, ждёт подтверждения владельца: `client_ip=None` → общая корзина «no-ip» и для confirm, как в T09 (вариант A по умолчанию). Долг (minor, до T22): число коммитов на успешном пути и `FOR UPDATE` тестами не покрыты.

## R8-T11 — Публичный API регистрации
- **Статус:** DONE (ревью: FAIL по тестам AC-7 → исправлено spy-тестами и порядком письма; 2026-11-08)
- **AC:** AC-1 (API), AC-4…AC-16, AC-18, AC-27, AC-28, AC-29, AC-38 (API)
- **Файлы:** `backend/app/api/v1/registration.py` (новый), `backend/app/api/v1/schemas/registration.py` (новый), `backend/app/api/v1/__init__.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` (перегенерация);
  тесты: `backend/tests/api/test_019_registration_api.py` (новый), `backend/tests/api/test_route_guards.py`, `backend/tests/cli/test_openapi.py`
- **Зависит от:** R8-T10, R8-T07
- **Описание:** Схемы `RegistrationRequest`, `RegistrationAccepted` (`detail = ACCEPTED_DETAIL`), `RegistrationConfirm`
  по plan §4.4. Роутер `/auth/registration`: `request_registration` (200; при `MailMessage` —
  `background.add_task(deliver, state.mailer, message)`; IP из `request.client`) и `confirm_registration` (204 без
  тела и cookie). OpenAPI-ответы: 404, 409, 429 через `error_response`, 400/403/422 через `error_responses`.
  `PUBLIC` в `test_route_guards.py` и `public` в `test_openapi.py::test_d33_*` += оба POST, `BODY_ROUTES_400` += оба.
  Перегенерировать API.
  Test-writer: трассировка plan §6 для AC-1, AC-4…AC-16, AC-18, AC-27…AC-29, AC-38 на уровне HTTP
  (`reset_api_env` и `api_env` без SMTP). AC-7: 4 варианта × 20 запусков с разными IP через
  `httpx.ASGITransport(client=…)`, побайтное сравнение тела и заголовков, медианы ≤ 200 мс. RG-5: 10 заявок с
  одного IP с ответом 422 (занятый логин, неверный email) → 11-я корректная заявка 429. RG-9: второе пространство →
  оба POST 404 `feature_disabled`.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_019_registration_api.py backend/tests/api/test_route_guards.py backend/tests/api/test_007_password_reset_api.py` зелёный; «Перегенерация API» выполнена; «Линт бэкенда» чист
- **Попытки:** 2. Попытка 1 — реализация (без записи в журнал). Попытка 2 — исправления ревью R8-T11. Тесты: test_019_registration_api.py 43 passed; набор из задачи (с test_route_guards, test_openapi, test_openapi_roles, test_frontend_api_types) 168 passed; test_007_password_reset_api.py в составе 147 passed; ruff check и format, mypy чисты; task_scope exit 0; `scripts/gen-api.sh` не меняет артефакты. Исправления: (1) MAJOR, AC-7: `test_019_ac7_hash_runs_once_for_taken_and_free_address` считает вызовы `hash_in_thread` (monkeypatch в `app.domain.auth.registration`, где он вызывается): занятый и свободный адрес дают ровно 1 вызов. Мутация «хеш после проверки занятости» — тест падает. `test_019_ac7_mail_leaves_after_response_and_commit_only_for_free`: журнал порядка (`commit` через слушатель `after_commit` класса `Session`, `response` через ASGI-обёртку, `deliver` через подмену в `app.api.v1.registration`); факт: `commit, commit, response, deliver`; для занятого адреса `deliver` не вызывается. Мутация «`await deliver` вместо `background.add_task`» — тест падает. (2) `test_019_smtp_failure_same_answer_and_no_address_in_log`: отказ SMTP → 200, тело и заголовки как у обычного ответа, в логе только `mail delivery failed: OSError`, адреса нет. (3) Границы: `test_019_ac4_email_length_254_accepted_255_invalid` (254 → 200 и письмо; 255 → `email_invalid`); `test_019_ac29_first_name_100_accepted_101_invalid`; `test_019_schema_limit_1024_reaches_domain_1025_is_validation_error` (email, first_name, last_name, login: 1024 → код поля домена, 1025 → `validation_error`). `schemas/registration.py` не менялась. (4) НЕ ВЫПОЛНЕНО, нужно решение владельца: код `registration_token_invalid` в описании 400 у confirm. Описание 400 с кодом (проверено) ломает `test_openapi.py::test_t68_400_declared_exactly_on_routes_with_body` (D-65: у всех маршрутов с телом описание 400 равно «Некорректный JSON в теле запроса (code: bad_request)»). Код уже есть в описании операции (docstring, `description` в openapi.json). Снять можно только ослаблением D-65 в `test_openapi.py`, а этот файл вне списка этой правки. (5) Процесс, фиксация: тесты написаны исполнителем без отдельного test-writer, хотя описание задачи его требует. Отклонение: при выключенной функции и при 0 пространствах (проверено зондом) невалидное тело даёт 422 `validation_error`, а не 404 `feature_disabled`: FastAPI валидирует тело до обработчика. Тот же паттерн, что в 007. Решить на уровне проекта; долг до T22.

## R8-T12 — Очистка истёкших заявок в `gostracker maintenance`
- **Статус:** DONE (ревью: PASS; 2026-11-08)
- **AC:** NFR-9
- **Файлы:** `backend/app/domain/system/maintenance.py`, `backend/app/domain/ops/maintenance.py`, `backend/app/cli/commands/maintenance.py` (текст справки и шага, ревью), `docs/data-model.md` (фраза о команде, ревью), `README.md` (разделы «Регулярное обслуживание» и «Regular maintenance»: команда удаляет также истёкшие заявки на регистрацию);
  тесты: `backend/tests/db/test_019_purge_registration.py` (новый), `backend/tests/cli/test_maintenance.py`
- **Зависит от:** R8-T01
- **Описание:** `purge_expired_registration_requests(sessionmaker, *, now, dry_run=False) -> int` (RG-18):
  `DELETE … WHERE expires_at <= now` (при `dry_run` — `COUNT`). `MaintenanceReport` += `registration_requests_expired:
  int = 0` последним полем, `run_maintenance` его заполняет. В README поменять фразу «удаляет только истёкшие
  сессии» в обоих языках. Команду писать так, как она называется в базе ветки (`gostracker maintenance`),
  переименование в `gtrack` придёт слиянием с `main` (R8-T00). Строку cron не трогать (её проверяет `test_docs_static.py`).
  Test-writer: истёкшие удаляются, действующие остаются, `dry_run` только считает; список ключей отчёта в
  `test_maintenance.py` расширен.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/db/test_019_purge_registration.py backend/tests/cli/test_maintenance.py backend/tests/infra/test_docs_static.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1. Тесты: 262 passed; ruff, mypy, scope чисты. Ревью PASS. Правки по ревью: фразы README (RU/EN) и справка CLI уточнены, data-model.md фраза про команду. Долг (minor, T22): тест сохранности сессий при очистке заявок; имя теста test_t88_readme_maintenance_is_sessions_only_no_trash в test_docs_static.py устарело; сигнатура принимает sessionmaker (соответствует plan §4.3).

## R8-T13 — Экспорт и импорт: имена есть, заявок и попыток нет
- **Статус:** DONE (ревью: PASS; 2026-11-08)
- **AC:** AC-37
- **Файлы:** `backend/app/domain/ops/archive.py`, `backend/app/domain/ops/importer.py`;
  тесты: `backend/tests/cli/test_019_export_names.py` (новый), `backend/tests/cli/test_export_import.py`
- **Зависит от:** R8-T01
- **Описание:** По plan §4.5: `EXCLUDED_TABLES` += `registration_request`, `registration_attempt`, docstring модуля
  дополнить. `importer.AUTO_TABLES` начинается с этих двух таблиц (рядом с таблицами сброса пароля).
  `EXCLUDED_COLUMNS` не менять.
  Test-writer: архив с учётной записью «Анна»/«Петрова-Иванова» и email содержит имена и `self_registered`, не
  содержит `email`, заявок и попыток (даже если строки есть в БД); импорт в пустую БД восстанавливает имена, email
  NULL; цикл export→import→export идентичен.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/cli/test_019_export_names.py backend/tests/cli/test_export_import.py backend/tests/cli/test_demo_data.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1. Тесты: 65 passed; ruff, mypy, scope чисты. Ревью PASS. Изменён индекс в test_007_archive_constants_describe_exclusions: AUTO_TABLES[:2] → [2:4] (сдвиг по plan §4.5, точное равенство сохранено; префикс проверяется в test_019_export_names.py).

## R8-T14 — Бэкенд: сквозные сценарии, утечки, аудит, управление ТА
- **Статус:** DONE (только тесты; ревью — самопроверка исполнителя и повторный прогон оркестратором; 2026-11-08)
- **AC:** AC-12, AC-13 (сброс пароля после регистрации), AC-19, AC-20, AC-22, AC-24, AC-25, AC-26 (ТА), AC-32
- **Файлы:** тесты: `backend/tests/api/test_019_registration_leaks.py` (новый), `backend/tests/api/test_019_ta_manages_self_registered.py` (новый), `backend/tests/unit/test_019_settings.py` (новый)
- **Зависит от:** R8-T11, R8-T04, R8-T07
- **Описание:** Задача только на тесты. Код не меняется. Если тест выявит дефект, вернуть `PLAN_ISSUE` с указанием
  задачи-источника. Сценарии (plan §6): заявка → подтверждение → вход → `/no-role` (403 `no_role` на `/me` и
  `/projects`) → назначение роли ТА → `GET /projects` 200 той же сессией; сброс пароля по email новой учётной
  записи; `caplog` DEBUG без email, имени, фамилии, логина, токена и пароля; ответы API без токена и хешей; журнал
  с одной записью `user.self_registered`; ТА видит запись с именами и `self_registered=true`, блокирует, сбрасывает
  пароль, назначает каждую из трёх ролей; ТА создаёт учётную запись с именами, одноразовым паролем и обязательной
  сменой; `Settings.model_fields` без отдельного выключателя и списков допуска (AC-32).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_019_registration_leaks.py backend/tests/api/test_019_ta_manages_self_registered.py backend/tests/unit/test_019_settings.py backend/tests/arch backend/tests/unit/test_no_telemetry.py` зелёный
- **Попытки:** 1. Тесты: 77 passed (14 новых + arch + no_telemetry); ruff чист; scope exit 0. Дефектов в коде не выявлено. Замечание: SecretsFilter маскирует секреты до caplog — добавлен перехватчик перед фильтром. Не покрыто: AC-20 (nginx, R8-T22), AC-21/AC-23 (фронтенд).

## R8-T15 — Фронтенд: ключи i18n и подписи аудита
- **Статус:** TODO
- **AC:** основа для AC-2, AC-16, AC-21, AC-30, AC-34, AC-35; AC-19 (подпись события в журнале)
- **Файлы:** `frontend/src/shared/i18n/ru.ts`, `frontend/src/features/admin/AuditPage.tsx`;
  тесты: `frontend/tests/shared/i18n.test.ts`, `frontend/tests/features/admin/AuditPage.test.tsx`
- **Зависит от:** R8-T11
- **Описание:** Добавить все ключи plan §4.7. `auth.help_p2_registration` — текст FR-12 из plan §9, Q-1 (принят владельцем). Ключ `auth.help_p2` (005 v0.1) не удалять. В
  `API_CODES` теста i18n добавить `rate_limited`, `registration_token_invalid`, `first_name_invalid`,
  `last_name_invalid`. `ACTION_CODES` += `user.self_registered`, `user.name_changed`, `FIELD_CODES` +=
  `first_name`, `last_name`. Если в словаре есть подписи возможностей, добавить `onboard_accounts`.
- **Готово, когда:** `cd frontend && npx vitest run tests/shared/i18n.test.ts tests/features/admin/AuditPage.test.tsx` зелёный; `cd frontend && npm run lint` чист
- **Попытки:** 0

## R8-T16 — Фронтенд: API регистрации и экран `/register`
- **Статус:** TODO
- **AC:** AC-1 (экран), AC-2, AC-3
- **Файлы:** `frontend/src/features/auth/api.ts`, `frontend/src/features/auth/RegisterPage.tsx` (новый), `frontend/src/app/router.tsx`;
  тесты: `frontend/tests/features/auth/RegisterPage.test.tsx` (новый), `frontend/tests/features/auth/api.test.ts`, `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** R8-T15
- **Описание:** В `api.ts` — `requestRegistration`, `confirmRegistration` (типы только из `components["schemas"]`).
  `RegisterPage` по plan §4.7: статус из `passwordResetStatus` с тем же `queryKey`, что на `LoginPage` (RG-13).
  В `router.tsx` — маршрут `/register` в `GuestOnly` до `*` и исключение `/register` в `onUnauthenticated` (RG-14).
  Test-writer: ровно пять полей и одна кнопка; пустые поля — без запроса; тело запроса; успех → `role="status"`,
  форма скрыта; ошибки по коду (`login_taken`, `email_invalid`, `rate_limited`, `feature_disabled`); `enabled:false`
  → `auth.register_disabled`; через `AppRoutes`: `/me` 200 → стартовый экран, `/me` 401 → остаётся `/register`.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/auth tests/app` зелёный; «Линт фронтенда»: `npm run lint` чист, `npm run typecheck` чист или падает только на `src/features/admin/UsersPage.tsx` (до R8-T20); `source .venv/bin/activate && pytest -q backend/tests/infra/test_frontend_scaffold.py` зелёный
- **Попытки:** 0

## R8-T17 — Фронтенд: экран `/register/confirm`
- **Статус:** TODO
- **AC:** AC-16 (экран), AC-9, AC-10, AC-28 (сообщения)
- **Файлы:** `frontend/src/features/auth/RegisterConfirmPage.tsx` (новый), `frontend/src/app/router.tsx`;
  тесты: `frontend/tests/features/auth/RegisterConfirmPage.test.tsx` (новый), `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** R8-T16
- **Описание:** По plan §4.7 и RG-15: токен из `#token=` читается один раз, фрагмент убирается
  `history.replaceState`, запрос только по кнопке «Подтвердить». Маршрут `/register/confirm` без `GuestOnly`, до `*`.
  Test-writer: после загрузки `location.hash === ""`; без нажатия запросов нет; тело `{token}`; успех →
  `auth.register_confirmed` и ссылка на `/login`, запроса `/auth/login` нет; `registration_token_invalid` и
  `login_taken` → свои тексты и ссылка на `/register`; нет токена → `auth.register_link_invalid`; `enabled:false` →
  `auth.register_disabled`.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/auth` зелёный; `npm run lint` чист; `source .venv/bin/activate && pytest -q backend/tests/infra/test_frontend_scaffold.py` зелёный
- **Попытки:** 0

## R8-T18 — Фронтенд: ссылка «Зарегистрироваться» и справка на `/login`
- **Статус:** TODO
- **AC:** AC-1 (ссылка), AC-21
- **Файлы:** `frontend/src/features/auth/LoginPage.tsx`;
  тесты: `frontend/tests/features/auth/LoginPage.test.tsx`
- **Зависит от:** R8-T16
- **Описание:** При `resetStatus.data?.enabled === true` после ссылки «Забыли пароль?» добавить `<Link to="/register">`
  `auth.register_link`, а вторым `<p>` блока `ui-login-help` показать `auth.help_p2_registration` (plan §4.7, Q-1
  закрыт владельцем: второй абзац о регистрации только при включённой регистрации). На базе `origin/work3` блок
  справки по 005 v0.1 состоит из `help_p1` и `help_p2`: при включённой регистрации второй `p` —
  `auth.help_p2_registration` вместо `auth.help_p2`, при `enabled !== true` разметка прежняя (`help_p1` + `help_p2`).
  Фокус при загрузке остаётся на «Логин». Новых запросов на экране нет. Существующие тесты 005 выполняются при
  `enabled:false`. Если тест сейчас мокает `enabled:true`, test-writer разносит случаи явно, не ослабляя проверки.
  Сведение с 005 v0.2 из `main` (один `p`) — в R8-T00, не здесь.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/auth` зелёный; `npm run lint` чист
- **Попытки:** 0

## R8-T19 — Фронтенд: экран профиля `/profile` и пункт меню
- **Статус:** TODO
- **AC:** AC-34 (экран)
- **Файлы:** `frontend/src/features/auth/ProfilePage.tsx` (новый), `frontend/src/features/auth/api.ts`, `frontend/src/app/router.tsx`;
  тесты: `frontend/tests/features/auth/ProfilePage.test.tsx` (новый), `frontend/tests/app/sidebar.test.tsx`, `frontend/tests/app/navigation.test.tsx`, `frontend/tests/app/start-screen.test.tsx`, `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** R8-T05, R8-T15, R8-T18
- **Описание:** `updateMyName` в `api.ts`. `ProfilePage` по plan §4.7. В `router.tsx`: `RoleScreen` получает
  необязательный `capability` (без него показывает содержимое любой роли, RG-16), маршрут `/profile` и пункт меню
  `nav.profile` у всех ролей. После сохранения обновляется кэш `["auth","me"]`.
  Test-writer: поля заполнены из профиля; сохранение и `role="status"`; 422 `first_name_invalid` → текст ошибки;
  меню ТА, БА и П содержит «Профиль» (существующие списки меню дополняются, порядок прочих пунктов прежний).
- **Готово, когда:** `cd frontend && npx vitest run tests/features/auth tests/app` зелёный; `npm run lint` чист; `source .venv/bin/activate && pytest -q backend/tests/infra/test_frontend_scaffold.py` зелёный
- **Попытки:** 0

## R8-T20 — Фронтенд: имена в `UsersPage`, диалог «Изменить имя»
- **Статус:** TODO
- **AC:** AC-22 (экран), AC-33 (форма), AC-35 (экран)
- **Файлы:** `frontend/src/features/admin/UsersPage.tsx`, `frontend/src/features/admin/api.ts`, `frontend/src/features/admin/NameDialog.tsx` (новый);
  тесты: `frontend/tests/features/admin/UsersPage.test.tsx`, `frontend/tests/features/admin/NameDialog.test.tsx` (новый), `frontend/tests/features/admin/api.test.ts`, `frontend/tests/features/admin/helpers.tsx`, `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** R8-T04, R8-T15
- **Описание:** По plan §4.7: колонки `first_name`, `last_name` (пусто → `admin.users.name_missing`) и `origin`
  (`self_registered`), обязательные «Имя» и «Фамилия» в форме создания (пустые — без запроса), `setUserName` в
  `api.ts`, кнопка «Изменить имя» в строке открывает `NameDialog` (образец — `EmailDialog.tsx`). После этой задачи
  `npm run typecheck` должен быть чист (закрывает plan R-3).
- **Готово, когда:** `cd frontend && npx vitest run tests/features/admin` зелёный; «Линт фронтенда» чист; `source .venv/bin/activate && pytest -q backend/tests/infra/test_frontend_scaffold.py` зелёный
- **Попытки:** 0

## R8-T21 — Фронтенд: раздел БА «Учётные записи без роли»
- **Статус:** TODO
- **AC:** AC-30 (экран), AC-26 (БА)
- **Файлы:** `frontend/src/features/admin/UnassignedAccountsPage.tsx` (новый), `frontend/src/features/admin/api.ts`, `frontend/src/app/router.tsx`;
  тесты: `frontend/tests/features/admin/UnassignedAccountsPage.test.tsx` (новый), `frontend/tests/app/sidebar.test.tsx`, `frontend/tests/app/navigation.test.tsx`, `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** R8-T07, R8-T15, R8-T19, R8-T20
- **Описание:** `listUnassigned`, `assignUserRole` в `api.ts`. Страница по plan §4.7 (таблица, `ConfirmDialog`,
  обновление списка, пустой список, `Pagination`). Маршрут `/unassigned-accounts` в
  `RoleScreen capability="onboard_accounts"`, пункт меню `nav.unassigned` только при `onboard_accounts`.
  Test-writer: у БА пункт меню есть, у ТА и П нет; таблица без email; назначение → `PUT` с `{role:"user"}` и
  повторная загрузка; 403 → `errorMessage("forbidden")`.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/admin tests/app` зелёный; «Линт фронтенда» чист; `source .venv/bin/activate && pytest -q backend/tests/infra/test_frontend_scaffold.py` зелёный
- **Попытки:** 0

## R8-T22 — Интеграция и полная проверка
- **Статус:** TODO
- **AC:** все (AC-1…AC-38, кроме удалённых AC-17 и AC-31); AC-23, AC-24, NFR-8
- **Файлы:** тесты: `frontend/tests/features/auth/019_no_register_link.test.tsx` (новый); код — только исправления, найденные прогоном, в файлах задач R8-T01…R8-T21 (перечислить в отчёте с причиной)
- **Зависит от:** R8-T01…R8-T21
- **Описание:** Test-writer (AC-23): на `/change-password`, `/password-reset`, `/password-reset/confirm` и
  `/no-role` при `enabled:true` нет ссылки «Зарегистрироваться»; существующие тесты этих экранов зелёные без
  правок. Исполнитель: `bash scripts/gen-api.sh` не меняет файлы (идемпотентность); полная проверка; `python scripts/task_scope.py R8-Tnn` для каждой задачи;
  `git diff --stat` по `backend/pyproject.toml`, `frontend/package.json`, `frontend/package-lock.json` пуст (AC-24);
  `git diff` по `frontend/src/features/auth/{ChangePasswordPage,PasswordResetRequestPage,PasswordResetConfirmPage,NoRolePage}.tsx`
  пуст (AC-23). Сверить трассировку plan §6: у каждого AC есть зелёный тест. Ручная проверка из plan §6 (тестовый
  SMTP, логи nginx) — по желанию владельца, только на стенде без реальных пользователей. В отчёте напомнить: до
  решения ИБ по К-4 (ADR-0019) регистрацию на стенде с реальным доступом не включать.
- **Готово, когда:** `bash scripts/check.sh` завершается с кодом 0; `git status --porcelain docs/api frontend/src/shared/api` пуст после `bash scripts/gen-api.sh`
- **Попытки:** 0

## R8-T00 — Проверка слияния с `main` перед выпуском
- **Статус:** TODO
- **AC:** NFR-8 на результате слияния; AC-21, AC-36, AC-37 после слияния (plan §7, R-10, R-12)
- **Файлы:** конфликтные файлы слияния с `main` из plan §7 (перечислить в отчёте); код фичи — только правки,
  нужные для сведения с `main`, в файлах задач R8-T01…R8-T22
- **Зависит от:** R8-T22; влитие 020 (`origin/work3`) в `main`
- **Описание:** Выполняет оркестратор (git-операции) с исполнителем. Номер `T00` — это шаг выпуска, а не первая
  задача. Ветка основана на `origin/work3`, где нет коммитов `main` `96869b9` (PR #7) и `2c8576a`/`3f0232a`
  (GOSTracker → GTrack). Шаги: (1) проверить, что 020 в `main` и голова `main` — `0009` (`alembic heads` на
  `origin/main`). Если 020 там перенумерована, обновить `down_revision` в `0010_self_registration.py` и пины голов,
  иначе вернуть `PLAN_ISSUE`. (2) Во временном `git worktree` сделать rebase или merge `feat/self-registration` на
  `origin/main`, способ выбирает владелец. (3) Конфликты: `LoginPage.tsx`, `ru.ts`, `LoginPage.test.tsx`,
  `i18n.test.ts` — по plan §4.7. Регистрация выключена → один `p` по 005 v0.2 из `main`, ключ `auth.help_p2` удалён,
  как в `main`. Регистрация включена → `help_p1` из v0.2 и `auth.help_p2_registration`. README и CLI-тесты — имя
  `gtrack` из `main` с добавлениями 019 (очистка заявок в `gtrack maintenance`). `archive.py`, `importer.py`,
  `test_export_import.py`, `test_maintenance.py`, `test_openapi.py`, `test_migrations.py`, `test_frontend_scaffold.py`,
  `test_docs_static.py` — объединить обе стороны, assert-ы не ослаблять. (4) Перегенерировать API, затем полная проверка.
  В отчёте перечислить конфликты и как они решены.
- **Готово, когда:** на результате слияния `alembic -c backend/alembic.ini heads` показывает одну голову `0010`;
  `source .venv/bin/activate && bash scripts/gen-api.sh` не меняет файлы; `bash scripts/check.sh` завершается с кодом
  0; `grep -rn "gostracker" backend frontend/src README.md` пуст (кроме мест, которые `main` оставил намеренно)
- **Попытки:** 0

---

## Покрытие AC

| AC | Задачи |
|----|--------|
| AC-1 | R8-T11, R8-T16, R8-T18 |
| AC-2, AC-3 | R8-T16 |
| AC-4, AC-5, AC-6 | R8-T09, R8-T11 |
| AC-7 | R8-T09, R8-T11 |
| AC-8 | R8-T08, R8-T09, R8-T11 |
| AC-9, AC-10 | R8-T10, R8-T11, R8-T17 |
| AC-11 | R8-T09, R8-T11 |
| AC-12 | R8-T11, R8-T14 |
| AC-13 | R8-T10, R8-T11, R8-T14 |
| AC-14 | R8-T10, R8-T11 |
| AC-15 | R8-T09, R8-T11 |
| AC-16 | R8-T10, R8-T11, R8-T17 |
| AC-17 | удалён в v0.4 |
| AC-18 | R8-T08, R8-T09, R8-T11 |
| AC-19 | R8-T10, R8-T14, R8-T15 |
| AC-20 | R8-T14 (+ ручная проверка логов прокси в R8-T22) |
| AC-21 | R8-T18, R8-T00 (сведение с 005 v0.2) |
| AC-22 | R8-T03, R8-T04, R8-T14, R8-T20 |
| AC-23 | R8-T22 |
| AC-24 | R8-T14, R8-T22 |
| AC-25 | R8-T14 |
| AC-26 | R8-T06, R8-T07, R8-T14, R8-T21 |
| AC-27 | R8-T09, R8-T11 |
| AC-28 | R8-T10, R8-T11, R8-T17 |
| AC-29 | R8-T03, R8-T09, R8-T11 |
| AC-30 | R8-T06, R8-T07, R8-T21 |
| AC-31 | удалён в v0.4 |
| AC-32 | R8-T14 |
| AC-33 | R8-T04, R8-T20 |
| AC-34 | R8-T05, R8-T19 |
| AC-35 | R8-T03, R8-T04, R8-T20 |
| AC-36 | R8-T01, R8-T00 (голова после слияния) |
| AC-37 | R8-T13 |
| AC-38 | R8-T08, R8-T10, R8-T11 |
| NFR-9 | R8-T12 |
| NFR-8 | R8-T22, R8-T00 (после слияния с `main`) |

## Таблица статусов
| Задача | Статус |
|---|---|
| R8-T01 | DONE |
| R8-T02 | DONE |
| R8-T03 | DONE |
| R8-T04 | DONE |
| R8-T05 | DONE |
| R8-T06 | DONE |
| R8-T07 | DONE |
| R8-T08 | DONE |
| R8-T09 | DONE |
| R8-T10 | DONE |
| R8-T11 | DONE |
| R8-T12 | DONE |
| R8-T13 | DONE |
| R8-T14 | DONE |
| R8-T15 | TODO |
| R8-T16 | TODO |
| R8-T17 | TODO |
| R8-T18 | TODO |
| R8-T19 | TODO |
| R8-T20 | TODO |
| R8-T21 | TODO |
| R8-T22 | TODO |
| R8-T00 | TODO |
