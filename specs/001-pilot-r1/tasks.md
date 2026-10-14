# Tasks: Пилот GOSTracker R1

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

Синхронизировано со spec v0.15 (OI-103…OI-118, FR-14c, FR-73, AC-108…AC-122).
Детально расписан этап **R1.0 «Фундамент»** (T01–T28). Этапы R1.1–R1.4 — крупными блоками
в конце файла; они детализируются отдельно, когда R1.0 будет закрыт.

## Общие условия для всех задач R1.0

- Источник истины — `spec.md`; интерфейсы, схемы и решения — `plan.md` (разделы указаны в
  каждой задаче). Если задача противоречит spec или plan — `PLAN_ISSUE`, не додумывать.
- Окружение: Python 3.12 (`.venv`, см. T01), команды из корня репозитория после
  `source .venv/bin/activate`.
- Тестовая БД для задач с БД (начиная с T05):
  `docker compose -p gostracker-dev -f docker-compose.yml -f deploy/compose.dev.yml up -d db`
  (публикует `127.0.0.1:5432`); тесты используют `TEST_DATABASE_URL`
  (по умолчанию `postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test`, plan §5).
- Тесты и фикстуры (`backend/tests/**`, `frontend/tests/**`, в т.ч. `conftest.py`,
  `factories.py`) пишет test-writer; исполнитель их не меняет.
- «Линтер чистый» во всех задачах backend = `ruff check backend && ruff format --check backend && mypy --config-file backend/pyproject.toml backend/app` (из корня; без `--config-file` mypy не видит конфиг — ревью T01-1).
- В тестах: фиксированные часы `FixedClock` (plan §4.2) и фиксированный seed; Argon2 с
  дешёвыми параметрами (`time_cost=1, memory_cost_kib=1024, parallelism=1`).
- Сессия БД в API подключается только как `DbSession` (core/db.py, scope="function"); прямой `Depends(get_db)` запрещён (ревью T05-1).
- Каждая выборка из БД фильтруется по `workspace_id` текущего пользователя (AGENTS.md).

---

## T01 — Окружение Python 3.12 и конфигурация инструментов
- **Статус:** DONE
- **AC:** NFR-10 (часть), N-6 / OI-69 (эталон Python 3.12)
- **Файлы:** `backend/pyproject.toml`, `backend/app/__init__.py`, `scripts/check.sh`;
  тесты: `backend/tests/test_toolchain.py`
- **Зависит от:** —
- **Описание:** Пересоздать `.venv` на Python 3.12 (`python3.12 -m venv --clear .venv`;
  на этой машине `python3` — 3.14) и установить `pip install -e "backend[dev]"`. В
  `pyproject.toml`: `[build-system]` setuptools; `[tool.setuptools.packages.find] include = ["app*"]`;
  `package-data` для `app/core/security/data/*`; зависимости `argon2-cffi>=25.1,<26` и
  `tzdata>=2025.2` (plan §7.1); `[project.scripts] gostracker = "app.cli.main:main"`;
  mypy `python_version = "3.12"`, плагин `pydantic.mypy`; pytest `pythonpath = ["."]`,
  маркеры `committed`, `infra_static`, `infra_stack`, `asyncio_default_fixture_loop_scope = "session"`.
  `scripts/check.sh` вызывает инструменты из активного окружения, как сейчас.
- **Готово, когда:** `python --version` → 3.12.x; `pytest -q backend/tests/test_toolchain.py backend/tests/test_health.py`
  зелёный; `bash scripts/check.sh` зелёный.
- **Попытки:** 2

## T02 — Закрыть порт БД в поставке; dev-конфигурация БД
- **Статус:** DONE
- **AC:** AC-105 (статическая часть: порт 5432 не опубликован, нет override-файлов), FR-6a, AC-95 (для `db`)
- **Файлы:** `docker-compose.yml`, `deploy/compose.dev.yml`, `deploy/dev.env.example`, `.env.example`,
  `backend/pyproject.toml` (dev-зависимости `pyyaml`, `types-PyYAML`, plan §7.1);
  тесты: `backend/tests/infra/conftest.py`, `backend/tests/infra/test_compose_static.py`
- **Зависит от:** T01
- **Описание:** По plan D-18, §4.12: убрать `ports` у `db`; переменные `POSTGRES_*` — из
  `.env` с умолчаниями `${POSTGRES_USER:-tracker}` и т.п.; `healthcheck` `pg_isready`;
  якорь `x-logging` (json-file, 10m × 5) на `db`. `deploy/compose.dev.yml` добавляет только
  `services.db.ports: ["127.0.0.1:5432:5432"]`. `deploy/dev.env.example` — по plan §4.12.
  `.env.example` — `POSTGRES_USER/PASSWORD/DB`, без `SECRET_KEY` и `COOKIE_SECURE`.
  Файлы `docker-compose.override.y*ml` и `compose.override.y*ml` не создавать.
- **Готово, когда:** `pytest -q -m infra_static backend/tests/infra/test_compose_static.py` зелёный;
  `docker compose -p gostracker-dev -f docker-compose.yml -f deploy/compose.dev.yml up -d db`
  поднимает БД, `pg_isready -h 127.0.0.1 -p 5432` (или `docker compose … exec db pg_isready`) — ок.
- **Попытки:** 1

## T03 — Настройки и часы
- **Статус:** DONE
- **AC:** AC-68 (расчёт «сегодня» по Europe/Moscow — юнит-часть), NFR-5, FR-46 (UTC), BR-12
- **Файлы:** `backend/app/core/config.py`, `backend/app/core/clock.py`;
  тесты: `backend/tests/unit/test_config.py`, `backend/tests/unit/test_clock.py`
- **Зависит от:** T01
- **Описание:** Реализовать `Settings` и `get_settings()` ровно по plan §4.2 (только
  переменные окружения, `.env` не читается; `cookie_secure` по умолчанию `True`). Реализовать
  `Clock`, `SystemClock`, `FixedClock` (отклоняет naive datetime), `utcnow()` через ContextVar,
  `use_clock()`, `today_msk()`; `MOSCOW_TZ = ZoneInfo("Europe/Moscow")`.
  Пример для теста: `today_msk(2026-10-13T21:30:00Z) == date(2026, 10, 14)`.
- **Готово, когда:** `pytest -q backend/tests/unit/test_config.py backend/tests/unit/test_clock.py` зелёный, линтер чистый.
- **Уточнения к plan §4.2 (оркестратор, по вопросам test-writer):** `FixedClock` на naive datetime
  (в `__init__` и `set`) — `ValueError`; `now()` нормализует aware не-UTC в UTC; `today_msk(naive)` —
  `ValueError`; имена env-переменных = имена полей `Settings`, регистр не важен, без префикса.
- **Попытки:** 1

## T04 — Единый формат ошибок и фабрика приложения
- **Статус:** DONE
- **AC:** FR-45 (формат `{"detail","code"}`), FR-57 (ответ 422 не содержит введённых значений), FR-7 (health публичный), D-32
- **Файлы:** `backend/app/core/errors.py`, `backend/app/main.py`, `backend/app/api/v1/health.py`
  (+ пустые `app/api/__init__.py`, `app/api/v1/__init__.py` со сборкой роутеров);
  тесты: `backend/tests/api/test_errors.py`
- **Зависит от:** T03
- **Описание:** Иерархия `AppError` и `install_error_handlers()` по plan §4.2, включая
  `ErrorCode`, обработку `RequestValidationError` (удалить `input`, `ctx`, `url`), 404/405
  Starlette, 500 `internal_error` без трассировки в теле. `create_app(settings: Settings | None = None,
  *, clock: Clock | None = None) -> FastAPI`; модульный `app = create_app()`; подключения к БД
  при импорте нет. ASGI-middleware (не `BaseHTTPMiddleware`) ставит часы `app.state.clock` через
  `use_clock`. `/docs`, `/redoc`, `/openapi.json` выключены, если `expose_api_docs` ложно.
  `generate_unique_id_function=lambda route: route.name`. `debug=False`.
- **Готово, когда:** `pytest -q backend/tests/api/test_errors.py backend/tests/test_health.py` зелёный, линтер чистый.
- **Заметка ревью T01:** подпакетам `app/api`, `app/core`, `app/domain` нужен `__init__.py`, иначе `packages.find` не включит их в установку (Docker, T20).
- **Заметка ревью T03:** `Settings` сейчас с `extra="ignore"` (опечатки в аргументах проглатываются); при создании `create_app(settings)` рассмотреть `extra="forbid"`; нет теста `today_msk(naive)` → `ValueError` и таймауты без проверки `gt=0` — добавить при ближайшем касании config/clock.
- **Попытки:** 1

## T05 — Слой БД, базовые миксины, Alembic и тестовая БД
- **Статус:** DONE
- **AC:** FR-13 (каркас `WorkspaceMixin`), FR-46, D-2…D-4, D-26
- **Файлы:** `backend/app/core/db.py`, `backend/app/core/models.py`, `backend/app/domain/registry.py`,
  `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`,
  `backend/app/main.py` (lifespan: движок и sessionmaker в `app.state`), `backend/pyproject.toml`;
  тесты: `backend/tests/conftest.py` (фикстуры БД по plan §5), `backend/tests/db/test_migrations.py`
- **Зависит от:** T02, T04
- **Описание:** `create_engine()` (`hide_parameters=True`, `pool_pre_ping=True`), `get_db()`
  (одна транзакция на запрос, откат при исключении, без `commit()` в сервисах), `Base` с
  naming convention, миксины по plan §4.2 (все FK `deferrable=True, initially="IMMEDIATE"`;
  метки времени — из `utcnow()`). `domain/registry.py` импортирует все модули моделей (для
  autogenerate). Alembic async, `script_location = %(here)s/migrations`, URL — из `Settings`
  или `-x dburl=…`. Миграций в этой задаче нет.
- **Готово, когда:** `pytest -q backend/tests/db/test_migrations.py` зелёный (upgrade → downgrade → upgrade на
  тестовой БД, `alembic check` без расхождений), линтер чистый.
- **Заметка ревью T01:** решить, нужен ли `asyncio_default_test_loop_scope = "session"` при session-фикстурах движка БД (иначе «attached to a different loop»).
- **Уточнения (оркестратор, по отчёту test-writer):** добавить `greenlet>=3.0,<4` в зависимости
  `backend/pyproject.toml` (plan §7.1) и `asyncio_default_test_loop_scope = "session"` в pytest;
  naming convention: `ix_%(column_0_label)s`, `uq_%(table_name)s_%(column_0_name)s`,
  `ck_%(table_name)s_%(constraint_name)s`, `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`,
  `pk_%(table_name)s`; `WorkspaceMixin`/`AuthoredMixin` через `declared_attr`; `engine.dispose()`
  в lifespan после `yield`; `migrations/versions/.gitkeep`. Файлы задачи дополнены: `backend/pyproject.toml`.
- **Ревью T05-1 (CHANGES_REQUESTED):** `core/db.py` — `DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]`
  как единственная точка подключения (иначе сбой COMMIT после отправки ответа → клиент получает 200; прямой
  `Depends(get_db)` рядом с `scope="function"` даёт две транзакции на запрос); docstring исправить. Новые тесты:
  сбой на COMMIT (`SET CONSTRAINTS ALL DEFERRED` + нарушение FK) → 500 и откат; AST-запрет `Depends(get_db` вне
  `core/db.py`. Прочее: `env.py` — `hide_parameters=True`, `NullPool`; `alembic.ini` — `prepend_sys_path = %(here)s`;
  защита имени `_test` не должна обходиться query-параметром `?database=` (db_support.py).
- **Попытки:** 2

## T06 — Модель идентичности: пространство, пользователь, членство, сессия (миграция 0001)
- **Статус:** DONE
- **AC:** AC-116 (уровень БД: логин уникален и соответствует шаблону), FR-73, FR-66 (не больше одной роли), FR-58 (серверная сессия), FR-13, D-5, D-39
- **Файлы:** `backend/app/domain/workspaces/models.py`, `backend/app/domain/users/models.py`,
  `backend/app/domain/auth/models.py`, `backend/migrations/versions/0001_identity.py`,
  `backend/app/domain/registry.py`; тесты: `backend/tests/db/test_identity_models.py`,
  `backend/tests/factories.py` (`make_workspace`, `make_user(role=…, password=…, blocked=…, must_change_password=…)`)
- **Зависит от:** T05
- **Описание:** Таблицы `workspace`, `app_user`, `workspace_member`, `user_session` ровно по
  plan §4.3 (R1.0): `UNIQUE(login)`, `CHECK login = lower(login)`, `CHECK role IN (…)`,
  `PK(workspace_id, user_id)`, `user_session.id bytea` (HMAC), индексы. Логин: `UNIQUE(login)` и
  `CHECK (login ~ '^[a-z0-9][a-z0-9._-]{2,63}$')` (FR-73, хранится в нижнем регистре). Миграция с `downgrade`.
- **Готово, когда:** `pytest -q backend/tests/db/test_identity_models.py backend/tests/db/test_migrations.py` зелёный, линтер чистый.
- **Попытки:** 1

## T07 — Журнал событий: append-only таблица, каталог, запись (миграция 0002)
- **Статус:** DONE
- **AC:** AC-66 (неизменяемость на уровне БД), FR-41 (основа), FR-35/FR-38 (основа таблицы), FR-57 (`details` без паролей по типу), D-7, D-8
- **Файлы:** `backend/app/domain/events/models.py`, `backend/app/domain/events/catalog.py`,
  `backend/app/domain/events/writer.py`, `backend/migrations/versions/0002_domain_event.py`;
  тесты: `backend/tests/db/test_event_log.py`
- **Зависит от:** T06
- **Описание:** Таблица `domain_event` и индексы по plan §4.3; функция-триггер
  `gt_forbid_event_mutation()` на `BEFORE UPDATE OR DELETE` (строки) и `BEFORE TRUNCATE`
  (оператор) — исключение. `EntityType`, `EventAction`, `EventSpec`, `EVENT_CATALOG` по plan
  §4.4 — в этой задаче только действия `user.*`, структура готова к остальным. `record_event()`
  по сигнатуре plan §4.4: `in_audit` и `entity_type` берутся из каталога; неизвестное действие
  — `ValueError`; `details` допустим только для `entity_type = user`.
- **Готово, когда:** `pytest -q backend/tests/db/test_event_log.py` зелёный (UPDATE/DELETE/TRUNCATE падают,
  событие откатывается вместе с транзакцией), линтер чистый.
- **Попытки:** 1

## T08 — Пароли: политика, Argon2id, список частых паролей
- **Статус:** DONE
- **AC:** AC-27, AC-28, AC-115 (юнит-уровень: совпадение точное, с учётом регистра), AC-3 (формат хеша `$argon2id$`), FR-2, FR-52, FR-53, FR-57
- **Файлы:** `backend/app/core/security/passwords.py`, `backend/app/core/security/common_passwords.py`,
  данные `backend/app/core/security/data/common-passwords-10k.txt`, `backend/app/core/security/data/NOTICE.md`;
  тесты: `backend/tests/unit/test_passwords.py`
- **Зависит от:** T01
- **Описание:** По plan §4.2 и §7.3. Список: скачать
  `https://raw.githubusercontent.com/danielmiessler/SecLists/913b327317496d062bcc7cace524aaad8a693be2/Passwords/Common-Credentials/10k-most-common.txt`,
  оставить первые 10 000 строк, sha256 файла должен быть
  `fa1ea0cf2f673458b58be3a7171d2b7fc6f2e704b4691e69c13a9a8511f5cf31`; `NOTICE.md` — источник,
  коммит, текст MIT. Сравнение — точное совпадение с учётом регистра (FR-53, OI-111): `Unbelievable` не частый. `PasswordHasher` (Argon2id, параметры
  из аргументов), `dummy_verify`, `needs_rehash`, `hash_in_thread`/`verify_in_thread`,
  `validate_new_password` (сообщение без значения пароля), `generate_password`.
- **Готово, когда:** `pytest -q backend/tests/unit/test_passwords.py` зелёный, линтер чистый.
- **Попытки:** 1

## T09 — Логирование без секретов
- **Статус:** DONE
- **AC:** FR-57 (часть AC-35), FR-51 (логи в stdout для драйвера Docker), D-31
- **Файлы:** `backend/app/core/logging.py`, `backend/app/main.py` (подключение);
  тесты: `backend/tests/unit/test_logging.py`
- **Зависит от:** T04
- **Описание:** `configure_logging(level)` — JSON-строки в stdout; фильтр, заменяющий на
  `"***"` значения ключей `(?i)password|secret|token|cookie|authorization` в `extra` и
  dict-аргументах; чистый ASGI access-лог: метод, путь без query, статус, длительность,
  `request.state.user_id` (если есть). Заголовки и тела не логируются. Логгер `uvicorn.access`
  отключён.
- **Готово, когда:** `pytest -q backend/tests/unit/test_logging.py` зелёный, линтер чистый.
- **Заметка ревью T04:** фильтр секретов должен применяться и к `exc_info` и тексту исключения (RuntimeError("password=…") сейчас попадает в лог как есть); трассировка 500 дублируется логгерами `app.errors` и `uvicorn.error` — подавить дубль.
- **Заметка ревью T08:** не логировать `exc.args`/`repr` у `UnicodeError` (при суррогате в пароле `args[1]` содержит пароль) и не выводить `f_locals` в трассировках (show_locals).
- **Попытки:** 3

## T10 — Первый запуск: секретный ключ, пространство, первый ТА; каркас CLI
- **Статус:** DONE
- **AC:** AC-23 (in-process: ровно один ТА, файл пароля 0600, пароля нет в логах и stdout, ключ стабилен и не `change-me`, повтор не создаёт второго ТА и не меняет файл), AC-114 (часть: после первого запуска в `domain_event` нет строк), FR-6, FR-41 (OI-110), D-9, D-19, D-20, D-29
- **Файлы:** `backend/app/core/secrets.py`, `backend/app/domain/system/bootstrap.py`,
  `backend/app/cli/main.py`, `backend/app/cli/commands/bootstrap.py`;
  тесты: `backend/tests/cli/test_bootstrap.py` (`@pytest.mark.committed`)
- **Зависит от:** T06, T08, T09
- **Описание:** По plan §4.2 (`write_private_file`, `ensure_secret_key`) и §4.7
  (`run_bootstrap`, `remove_initial_admin_file_if_for`). CLI на `argparse`: `main(argv) -> int`,
  подкоманда `bootstrap` (ожидание БД ≤ 60 с, `ensure_secret_key`, `alembic upgrade head`
  через `ALEMBIC_CONFIG`, `run_bootstrap`). Первый запуск под `pg_advisory_lock`; событий аудита
  не пишет (D-9). В stdout — только путь к файлу.
- **Готово, когда:** `pytest -q backend/tests/cli/test_bootstrap.py` зелёный, линтер чистый.
- **Заметка ревью T03:** пустой `SECRET_KEY=""` считать отсутствием ключа (в `ensure_secret_key` или приведением `""` → `None` в Settings).
- **Попытки:** 1

## T11 — Домен аутентификации: провайдер, защита от перебора, сессии
- **Статус:** DONE
- **AC:** AC-30, AC-37, AC-20 (вход заблокированного), AC-32, AC-33 (уровень сервиса), FR-3, FR-56, FR-59, FR-61, D-10, D-13
- **Файлы:** `backend/app/domain/auth/provider.py`, `backend/app/domain/auth/sessions.py`,
  `backend/app/domain/auth/service.py`; тесты: `backend/tests/domain/test_auth_service.py`
- **Зависит от:** T07, T10
- **Описание:** Ровно по plan §4.6: `AuthProvider` (Protocol), `LocalPasswordProvider` с
  логикой блокировки 5 попыток / 15 минут и выравниванием времени; `SessionStore` (HMAC
  токена, idle 8 ч — истекла при `>=`, абсолютный срок 7 суток, `background=True` не трогает
  `last_activity_at`, удаление истёкших); `login()`, `logout()`, `change_own_password()`
  (коды 422 `invalid_current_password`, `password_reused`, `password_too_short`,
  `password_too_common`; удаление остальных сессий; удаление файла пароля первого ТА).
  `InvalidCredentials` одинаков для всех причин отказа. Логин при входе приводится к нижнему
  регистру (FR-73); логин, не подходящий под шаблон, — обычный `InvalidCredentials`.
- **Готово, когда:** `pytest -q backend/tests/domain/test_auth_service.py` зелёный, линтер чистый.
- **Заметка ревью T06:** добавить `CHECK (octet_length(id) = 32)` на `user_session.id` (новой миграцией 000x) и тест; рассмотреть `server_default="0"` для `app_user.failed_login_count`.
- **Уточнения (оркестратор, по отчёту test-writer):** (1) PLAN_ISSUE решён: в `core/db.py` добавить
  `commit_durably(session)`; `login` вызывает его на ветках отказа ДО `raise InvalidCredentials`
  (счётчик и `login_locked_until` переживают откат запроса); `get_db` должен оставаться корректным
  после такого commit (тесты T05 — 38 — зелёные); AST-тест «нет `.commit()` вне core/db.py и cli» остаётся.
  (2) Ошибка удаления файла пароля первого ТА после смены пароля не выходит наружу (пароль сменён, warning без
  секретов). (3) Суррогат в новом пароле → `Unprocessable(code=ErrorCode.validation_error)` (новых кодов не вводить).
  (4) События для login/logout/change_own_password не пишутся (0 строк `domain_event`).
  (5) Без строки `workspace_member` → `InvalidCredentials`; роль NULL → вход разрешён.
  (6) Миграция `0003` — CHECK `octet_length(id) = 32` на `user_session.id`, downgrade снимает constraint.
- **Попытки:** 2

## T12 — Модуль прав: роли, возможности, гейты запроса
- **Статус:** DONE
- **AC:** FR-8, FR-9, FR-10, FR-45a (403 по разделу до 404), FR-55 (гейт), FR-66 (гейт), FR-67, BR-1 (системные строки), D-16
- **Файлы:** `backend/app/domain/access/roles.py`, `backend/app/api/deps.py`,
  `backend/app/main.py` (lifespan: `PasswordHasher`, `SessionStore`, `LocalPasswordProvider`
  в `app.state`; app-level зависимость `check_origin`);
  тесты: `backend/tests/unit/test_role_matrix.py`, `backend/tests/api/test_deps_gates.py`
- **Зависит от:** T11
- **Описание:** `Role`, `Capability`, `ROLE_CAPABILITIES`, `ACCOUNT_ADMIN_ROLES`, `Actor` ровно
  по plan §4.5. `deps.py`: `get_actor` (cookie → `SessionStore.resolve` с флагом фона по
  plan D-14; роль и флаги пользователя читаются из БД на каждый запрос; заблокирован или нет
  членства → 401; ставит `request.state.user_id`), `get_active_actor` (403
  `password_change_required`, затем 403 `no_role`), `require_capability(*caps)` (403
  `forbidden`), `check_origin` (D-16, 403 `origin_mismatch`). Порядок проверок — plan §4.5.
- **Готово, когда:** `pytest -q backend/tests/unit/test_role_matrix.py backend/tests/api/test_deps_gates.py` зелёный, линтер чистый.
- **Заметка ревью T05:** зависимость с `yield` поверх `DbSession` должна объявляться со `scope="function"` (иначе `DependencyScopeError`); AST-тест «нет get_db вне core/db.py» усилить — запретить любое упоминание имени (Name/Attribute/alias, Security).
- **Заметки ревью T11:** `SessionStore` — ключ только из `ensure_secret_key`; истёкшие сессии остаются после отката при 401 — очищать в `gostracker maintenance` (T19) или при входе пользователя.
- **Уточнения (оркестратор, по отчёту test-writer):** `check_origin` проверяет только `Origin` (D-16; `Referer` не проверяется);
  `app.state.session_store`, `app.state.password_hasher`, `app.state.auth_provider`; значения `Capability` — имя члена в нижнем регистре
  (`manage_accounts`); короткий `SECRET_KEY` (< 32 байт) роняет запуск; lifespan не обращается к БД.
- **Попытки:** 1

## T13 — API входа, выхода и профиля; поведение сессии
- **Статус:** DONE
- **AC:** AC-4, AC-20 (код и тело при входе заблокированного), AC-30, AC-32, AC-33, AC-34, AC-36, AC-37, AC-79, AC-116 (вход с логином в верхнем регистре), FR-7, FR-60, FR-73
- **Файлы:** `backend/app/api/v1/auth.py`, `backend/app/api/v1/me.py`, `backend/app/api/v1/schemas/auth.py`
  (+ подключение в `app/api/v1/__init__.py`);
  тесты: `backend/tests/api/test_auth_login.py`, `backend/tests/api/test_login_lockout.py`,
  `backend/tests/api/test_sessions.py`, `backend/tests/api/test_route_guards.py` (часть FR-7),
  дополнения `backend/tests/conftest.py` (приложение, клиент, вход)
- **Зависит от:** T12
- **Описание:** `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/me` по
  таблице plan §4.6: cookie `gt_session` с `HttpOnly`, `SameSite=Lax`, `Secure` (если
  `cookie_secure`), `Path=/`, `Max-Age=604800`; пароль в схеме — `SecretStr`; логин
  нормализуется в нижний регистр; `/me` отдаёт отсортированный список capabilities.
- **Готово, когда:** `pytest -q backend/tests/api/test_auth_login.py backend/tests/api/test_login_lockout.py backend/tests/api/test_sessions.py backend/tests/api/test_route_guards.py`
  зелёный, линтер чистый.
- **Заметка ревью T11:** роут входа не должен писать в сессию БД до `service.login` (иначе `checkpoint`/`commit_durably` зафиксирует эти записи досрочно).
- **Заметки ревью T12:** (a) тест порядка проверок для битого JSON (422 раньше 401, plan §4.5 п.5) или свой `APIRoute`; (b) `check_origin`: сверять схему Origin с `request.url.scheme` (X-Forwarded-Proto при `--proxy-headers`), строго разбирать Origin (без userinfo/path); (c) имя cookie с префиксом `__Host-` — только при `cookie_secure` (в dev по http префикс недопустим); (d) `require_capability()` без аргументов — `assert caps`.
- **Уточнения (оркестратор, по отчёту test-writer):** `/me` — только для активного актора (403 `no_role` / `password_change_required`
  по plan §4.6; фронтенд строит экраны по коду ошибки); тело входа — ровно `{"user": {id, login, role, must_change_password}}`;
  logout → 204 (повтор 204 или 401, не 5xx); повторный вход создаёт новую сессию, старый токен действует до logout/истечения;
  имя cookie — `settings.cookie_name` (префикс `__Host-` по умолчанию не вводится; T28 — рекомендация оператору);
  `deps.check_origin` ужесточается в рамках T13 (схема Origin против `request.url.scheme`; без userinfo/path/query/fragment; `null`/мусор → 403);
  файлы задачи дополнены: `backend/app/api/deps.py`.
- **Попытки:** 1

## T14 — Смена своего пароля, одноразовый пароль, пользователь без роли
- **Статус:** DONE
- **AC:** AC-29, AC-31, AC-35, AC-27, AC-28 и AC-115 (через API), AC-75 (вход, смена пароля, выход; 403 на прочее), AC-113 (часть: при одноразовом пароле выход выполняется и старая сессия получает 401, прочие запросы отклоняются), AC-23 (файл пароля удаляется после смены), FR-55, FR-56, FR-66
- **Файлы:** `backend/app/api/v1/auth.py` (`POST /api/v1/auth/password`), `backend/app/api/v1/schemas/auth.py`;
  тесты: `backend/tests/api/test_password_change.py`, `backend/tests/api/test_password_leaks.py`,
  `backend/tests/api/test_route_guards.py` (обход маршрутов: 403 при одноразовом пароле и без роли)
- **Зависит от:** T13
- **Описание:** Эндпоинт `{current_password, new_password}` → 204 через
  `change_own_password` (T11). `logout` и `auth/password` доступны при одноразовом пароле и без
  роли; всё остальное — 403 (plan §4.5, п.2–3). Сценарий AC-35: неудачный вход, успешный вход,
  смена пароля, ошибка сервера при входе (тест подменяет провайдер) — паролей нет ни в логах,
  ни в телах ответов, ни в 422.
- **Готово, когда:** `pytest -q backend/tests/api/test_password_change.py backend/tests/api/test_password_leaks.py backend/tests/api/test_route_guards.py`
  зелёный, линтер чистый.
- **Заметка ревью T08:** пароль с одиночным суррогатом проходит `SecretStr` и `validate_new_password`, но `hash`/`verify` падают с `UnicodeEncodeError` (500) — отклонять на уровне схемы (422) или ловить; тест порядка «короткий и частый → password_too_short».
- **Заметки ревью T11:** (5) перебор `current` в `change_own_password` не ограничен — после N подряд `invalid_current_password` завершать сессию (открытый вопрос к spec, FR-61 говорит только о входе); (6) удалять файл пароля первого ТА ПОСЛЕ успешного COMMIT (хук `after_commit` или в роутере) + тест сбоя COMMIT (тест T11 `test_fr6_change_removes_initial_admin_file_for_this_login` потребует правки через test-writer).
- **Заметки ревью T13:** `Max-Age` cookie брать из `settings.session_absolute_timeout` (а не константа 604800); `max_length` у полей пароля/логина в схемах (пароль на 20 МБ доходит до проверки; предел ≈ 1024); `assert caps` в `require_capability`; явная проверка вместо `assert actor.role is not None` в `me.py`; отклонять запрос с повторным заголовком `Origin`.
- **Уточнения (оркестратор; решение вне spec — вынести заказчику):** (1) неверный `current_password` в `change_own_password` считается теми
  же счётчиком и порогом, что вход (FR-61: 5 подряд → блокировка входа на 15 минут, `login_locked_until`); на пороге текущая сессия
  завершается (следующий запрос 401); успешная смена сбрасывает счётчик; ответ на неверный `current` — 422 `invalid_current_password`
  (на пороге — тот же ответ, сессия удаляется); (2) файл пароля первого ТА удаляется ПОСЛЕ успешного COMMIT (после ответа сервиса;
  сбой удаления не меняет результат); сбой COMMIT оставляет файл на месте; тест T11
  `test_fr6_change_removes_initial_admin_file_for_this_login` правится test-writer под новый порядок; (3) `max_length` ≈ 1024 у полей
  пароля/логина в схемах (422); пароль с суррогатом → 422 (не 500); (4) `Max-Age` cookie логина — из `settings.session_absolute_timeout`.
- **Попытки:** 1

## T15 — Постраничный вывод
- **Статус:** DONE
- **AC:** FR-47 (каркас), AC-22 (формат: 50 элементов и `has_next`), D-34
- **Файлы:** `backend/app/core/pagination.py`; тесты: `backend/tests/db/test_pagination.py`
- **Зависит от:** T05
- **Описание:** `PageParams`, `Page[T]`, `paginate()` по plan §4.2: `page ≥ 1`,
  `1 ≤ page_size ≤ 100`, по умолчанию 50; `LIMIT page_size + 1 OFFSET …`; без COUNT.
- **Готово, когда:** `pytest -q backend/tests/db/test_pagination.py` зелёный, линтер чистый.
- **Попытки:** 2

## T16 — Сервис учётных записей и ролей
- **Статус:** DONE
- **AC:** AC-78, AC-121 (уровень сервиса: создание без роли — одно событие, назначение роли — второе), AC-113 и AC-116 (уровень сервиса), FR-4, FR-5 (блокировка завершает сессии), FR-5a, FR-12, FR-55, FR-62, FR-65, FR-66, FR-69, FR-73; события `user.*` (основа AC-64)
- **Файлы:** `backend/app/domain/users/service.py`; тесты: `backend/tests/domain/test_user_admin_service.py`
- **Зависит от:** T07, T12, T15
- **Описание:** Функции ровно по plan §4.6 «Сервис учётных записей»: `create_user` (без роли,
  `must_change_password=True`; логин → нижний регистр → шаблон FR-73, иначе 422 `login_invalid`;
  занят — 422 `login_taken`; одноразовый пароль — политика FR-52/FR-53, иначе 422), `block_user`,
  `unblock_user`, `reset_password`, `revoke_sessions`, `set_role` (та же роль — без события),
  `ensure_account_admin_remains` (`FOR UPDATE`, 422 `last_account_admin`). Каждое действие —
  ровно одно событие `record_event` в той же транзакции; одноразовые пароли нигде не
  сохраняются, кроме хеша. Все выборки — в пространстве актора (404 для чужого).
- **Готово, когда:** `pytest -q backend/tests/domain/test_user_admin_service.py` зелёный, линтер чистый.
- **Заметка ревью T11:** единый шаблон логина (сейчас `provider.LOGIN_RE` и `bootstrap._LOGIN_RE`), правило «только ASCII перед lower()» одинаково при создании и при входе.
- **Заметка ревью T14:** добавить тесты на ветки «блокировка входа уже стоит → 422 без засчитывания» и «сброс серии при верном `current` и отказе по политике»; обновить docstring `commit_durably` («только на ветках отказа» устарел: вызывается и до verify) и комментарий в `core/logging.py` про дубль `uvicorn.error`.
- **Заметка ревью T15:** `paginate(db, stmt: Select[R], params)` — всегда `order_by(..., Entity.id)` (тай-брейкер); типизированный вызов обязан проходить mypy strict; без ORDER BY — `ValueError`; добавить тест на этот `ValueError`; рассмотреть верхнюю границу `sqlalchemy<2.2` в `pyproject.toml`.
- **Уточнения (оркестратор, по отчёту test-writer):** (1) повторная блокировка и разблокировка активного — без ошибки и без события;
  (2) разблокировка сбрасывает `failed_login_count` и `login_locked_until` (FR-5a: «вход проходит»), блокировка их не трогает;
  (3) `create_user`/`set_role` возвращают frozen dataclass `UserAccount(id, login, role, is_blocked, must_change_password, created_at)`
  (типа `UserRow` в приложении нет); (4) проверка прав — ДО загрузки цели (БА к чужому пользователю → 403, чужое пространство
  для ТА/СМ → 404); (5) `ensure_account_admin_remains`: блокировка строк админов `FOR NO KEY UPDATE ORDER BY user_id` + `pg_advisory_xact_lock` по пространству ДО изменения (plan §4.6)
  (иначе deadlock при взаимной смене ролей); (6) единый шаблон логина: `provider.LOGIN_RE`/`normalize_login` — единственное место,
  `bootstrap` использует их же (знак Кельвина отклоняется и у первого ТА); (7) в исходнике сервиса нет подстрок `projects`/`tasks` (BR-2).
- **Попытки:** 3

## T16a — get_actor: не держать блокировку строки сессии до конца запроса (дефект на стыке T12/T16)
- **Статус:** DONE
- **AC:** FR-5, FR-62, FR-67 (корректность без deadlock при действиях над сессией работающего пользователя), AC-79 (фон), AC-32/AC-33 (границы), D-14
- **Файлы:** `backend/app/api/deps.py` (`get_actor`), `backend/app/domain/auth/sessions.py` (при необходимости),
  `backend/app/core/db.py`; тесты: `backend/tests/api/test_session_row_lock.py`, правки `backend/tests/api/test_deps_gates.py` и AST-теста
  `commit_durably` (T11) только через test-writer
- **Зависит от:** T12, T16
- **Описание:** Найдено исполнителем T16 (попытка 3), воспроизведено 3 из 3: `get_actor` → `SessionStore.resolve` делает
  `UPDATE user_session SET last_activity_at` в транзакции запроса и держит эту строку до его конца. Администратор C блокирует /
  сбрасывает пароль / завершает сессии администратора A, пока у A идёт своё действие: A держит свою строку сессии и ждёт
  advisory-блокировку, C держит её и ждёт сессию A → deadlock, 500. Тот же механизм возможен для `change_own_password` цели Y при
  параллельном block/reset/revoke над Y. Решение (проверить альтернативы): зафиксировать обновление активности сразу после `resolve`
  (`commit_durably` в `get_actor`; побочно закрывает заметку T12 «4xx откатывает `last_activity_at`» и «истёкшая сессия остаётся
  после отката при 401»), либо брать строку сессии без удержания до конца запроса. Расширить разрешённый список для `commit_durably`
  (AST-тест T11/T05) осознанно: `deps.py`.
- **Готово, когда:** новые API-тесты (параллельные админ-действия над работающим админом через HTTP, 100+ итераций) зелёные без 500;
  тесты T12/T13/T14 не ослаблены (границы AC-32/AC-33/AC-79 прежние); `pytest -q backend/tests`, `bash scripts/check.sh` зелёные.
- **Попытки:** 1

## T17 — API системных настроек: учётные записи и роли
- **Статус:** DONE
- **AC:** AC-2, AC-3, AC-20 (сессия заблокированного получает 401), AC-26, AC-39, AC-44, AC-45, AC-75 (назначение и снятие роли), AC-78, AC-113 (создание и сброс: пароль в запросе, в ответе его нет, 422 для 11 символов и частого), AC-116 (создание: `ivan.petrov`, `Ivan.Petrov` занят, `ab`, `.ivan`, `ivan petrov`, `иван`, 65 символов → 422), AC-121 (после создания роли нет), AC-21 (пользователи другого пространства — 404), FR-4, FR-42, FR-45a (БА/П на `/admin/*` с любым id — 403), FR-55, FR-65, FR-67, FR-73
- **Файлы:** `backend/app/api/v1/admin_users.py`, `backend/app/api/v1/schemas/admin.py`;
  тесты: `backend/tests/api/test_admin_users.py`, `backend/tests/api/test_admin_roles.py`,
  `backend/tests/api/test_workspace_isolation.py`
- **Зависит от:** T16a (+ T16, T15, T12)
- **Описание:** Эндпоинты `/api/v1/admin/users*` по таблице plan §4.6 (гейт раздела —
  router-level `require_capability(MANAGE_ACCOUNTS)`, `PUT …/role` — `ASSIGN_ROLES`).
  Одноразовый пароль приходит в запросе (`SecretStr`), в ответах паролей нет (D-15).
- **Готово, когда:** `pytest -q backend/tests/api/test_admin_users.py backend/tests/api/test_admin_roles.py backend/tests/api/test_workspace_isolation.py`
  зелёный, линтер чистый.
- **Заметка ревью T15:** `paginate(db, stmt: Select[R], params)` — всегда `order_by(..., Entity.id)` (тай-брейкер); типизированный вызов обязан проходить mypy strict; без ORDER BY — `ValueError`; добавить тест на этот `ValueError`; рассмотреть верхнюю границу `sqlalchemy<2.2` в `pyproject.toml`.
- **Заметка ревью T16:** порядок проверок в `create_user`: `login_invalid` → `login_taken` → политика пароля; сериализация действий над одним пользователем — `FOR NO KEY UPDATE` (иначе deadlock с вставками, ссылающимися на `app_user` по FK).
- **Заметка ревью T16a:** окно устаревшего актора — в `_lock_for_account_change` проверять, что актор входит в заблокированное множество активных админов (иначе 401/403); в `change_own_password` добавить `is_blocked = false` в условие UPDATE; реальные админ-эндпоинты добавить в дедлок-сценарии T16a (тот же стресс на HTTP).
- **Попытки:** 1

## T18 — API журнала аудита
- **Статус:** DONE
- **AC:** AC-64, AC-65 (часть: БА и П получают 403; успешный и неудачный вход записей не создают), AC-66 (через API запись не меняется и не удаляется — 405), AC-114 *инфра* (после первого запуска журнал пуст, после создания учётной записи — ровно одна запись), AC-121 (две записи: создание и назначение роли), AC-21 (журнал другого пространства не виден)
- **Файлы:** `backend/app/domain/events/queries.py`, `backend/app/api/v1/audit.py`,
  `backend/app/api/v1/schemas/audit.py`; тесты: `backend/tests/api/test_audit.py`,
  `backend/tests/cli/test_bootstrap_audit.py` (`@pytest.mark.committed`: `run_bootstrap` → API журнала)
- **Зависит от:** T17
- **Описание:** `GET /api/v1/admin/audit` (фильтры `entity_type`, `actor_id`, пагинация) и
  `GET /api/v1/admin/audit/{id}` по plan §4.4 и §4.6: схема `AuditEntry` без поля `changes`;
  `details` только для `entity_type = user`; `actor.kind = system` при `actor_id IS NULL`;
  `entity_deleted` — существует ли объект. Гейт `VIEW_AUDIT`. Сортировка `id DESC`.
- **Готово, когда:** `pytest -q backend/tests/api/test_audit.py backend/tests/cli/test_bootstrap_audit.py` зелёный, линтер чистый.
- **Заметка ревью T07:** триггер журнала даёт `restrict_violation` (класс 23) — глобальный обработчик не должен превращать его в 409 с текстом SQL.
- **Заметка ревью T15:** `paginate(db, stmt: Select[R], params)` — всегда `order_by(..., Entity.id)` (тай-брейкер); типизированный вызов обязан проходить mypy strict; без ORDER BY — `ValueError`; добавить тест на этот `ValueError`; рассмотреть верхнюю границу `sqlalchemy<2.2` в `pyproject.toml`.
- **Заметки ревью T17:** тест `ValueError` у `paginate` без ORDER BY (T15) и рассмотреть `sqlalchemy<2.2`; `list_accounts`-подобные выборки — не тянуть лишние колонки (`password_hash`).
- **Попытки:** 2

## T19 — Служебные команды: OpenAPI и замер хеширования; отсутствие телеметрии
- **Статус:** IN_PROGRESS
- **AC:** FR-43 (все маршруты под `/api/v1`), FR-44, AC-38 (инструмент замера), NFR-4, D-32, D-33
- **Файлы:** `backend/app/cli/commands/openapi.py`, `backend/app/cli/commands/hash_bench.py`,
  `scripts/gen-api.sh`, `docs/api/openapi.json` (генерируется); тесты: `backend/tests/cli/test_openapi.py`,
  `backend/tests/unit/test_no_telemetry.py`
- **Зависит от:** T18
- **Описание:** `gostracker openapi [--out PATH]` — `app.openapi()` без подключения к БД,
  JSON с `sort_keys=True`, `indent=2`, `ensure_ascii=False`, завершающий `\n`.
  `gostracker hash-bench [--iterations N]` — p50/p95 времени `PasswordHasher.hash` с текущими
  параметрами `Settings`, пароль генерируется и не печатается. `scripts/gen-api.sh` — генерирует
  `docs/api/openapi.json`; фронтенд-часть добавляется в T22 (если `frontend/package.json` нет — пропуск).
  Тест «нет телеметрии»: пакет `opentelemetry.sdk` не установлен, приложение не обращается к сети при старте.
- **Готово, когда:** `pytest -q backend/tests/cli/test_openapi.py backend/tests/unit/test_no_telemetry.py` зелёный
  (включая проверку, что `docs/api/openapi.json` совпадает с генерацией), линтер чистый.
- **Заметка ревью T16a:** `gostracker maintenance` удаляет истёкшие сессии (фоновый GET с истёкшей сессией не фиксирует удаление при 401).
- **Заметки ревью T17:** (1) битый JSON даёт 422 `json_invalid` раньше 401/403 на всех эндпоинтах — сквозное решение (обработчик ошибок/middleware) либо принять; (2) OpenAPI: описать ответы 401/403/404 и реальное тело ошибки `{detail, code}` (D-33, генерация типов).
- **Заметки ревью T18:** OpenAPI — описать 401/403/404 для /admin/audit* (D-33); `list_accounts` читает `password_hash` (`users/service.py`) — сузить проекцией (`load_only`); при появлении deal/stage-событий — белый список имён `changed_fields` по действию; пропуск (с логированием) строк журнала с неизвестным `entity_type`, вместо 500 всей страницы.
- **Заметка ревью T18:** строка журнала с неизвестным `entity_type` (откат кода после R1.1+) даёт 500 всей страницы аудита — CHECK-ограничение на `entity_type` в миграции либо отдача «неизвестный тип» без `details`; решить при первой задаче, расширяющей `EntityType`.
- **Попытки:** 0

## T20 — Образ API
- **Статус:** TODO
- **AC:** FR-48 (api), FR-6 (bootstrap при старте), NFR-4, N-6, D-19, D-21
- **Файлы:** `backend/Dockerfile`, `backend/docker-entrypoint.sh`, `backend/.dockerignore`;
  тесты: `backend/tests/infra/test_api_image.py` (`infra_static`)
- **Зависит от:** T10, T19
- **Описание:** По plan §4.12: `python:3.12-slim-bookworm`, исходники в `/app`,
  `pip install --no-cache-dir /app`, `ALEMBIC_CONFIG=/app/alembic.ini`, пользователь uid 10001,
  `/data` принадлежит ему, `VOLUME /data`; entrypoint `umask 077` → `gostracker bootstrap` →
  `exec uvicorn … --proxy-headers --forwarded-allow-ips='*' --no-access-log`; `HEALTHCHECK` на
  `/api/v1/health` средствами Python (без curl).
- **Готово, когда:** `docker build -t gostracker-api:test backend` успешен;
  `pytest -q -m infra_static backend/tests/infra/test_api_image.py` зелёный (Python 3.12, uid 10001, `gostracker --help`).
- **Заметка ревью T02:** при `depends_on: db: condition: service_healthy` добавить `start_period` к healthcheck db.
- **Заметки ревью T10 (желательные, не блокировали):** (1) `alembic upgrade head` выполнять под тем же advisory lock (параллельный запуск на чистой БД падает на `alembic_version`); (2) при ошибке COMMIT перед удалением файла пароля проверить отдельной сессией, не зафиксировано ли пространство (обрыв после фиксации оставляет ТА с неизвестным паролем); (3) минимальная длина `SECRET_KEY` из env (≥ 32 байт) и сравнение заглушки `strip().lower()` — требование в FR-6/D-20 через plan; (4) удалять остатки `.<name>.*.tmp` под блокировкой; `ensure_private_dir` — `lstat`/`S_ISDIR`, чинить права 0755 → 0700; (5) advisory lock на AUTOCOMMIT-соединении; `_known_secrets` из `settings`; `path_separator = os` в `alembic.ini`; plan §4.7 — stdout только путь, текст в stderr.
- **Попытки:** 0

## T21 — Каркас фронтенда
- **Статус:** TODO
- **AC:** NFR-10 (линтер, типы, тесты фронтенда), C-1, NFR-8
- **Файлы:** `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`,
  `frontend/vite.config.ts`, `frontend/eslint.config.js`, `frontend/index.html`,
  `frontend/src/main.tsx`, `frontend/src/app/App.tsx`, `frontend/src/app/providers.tsx`,
  `frontend/README.md`; тесты: `frontend/tests/setup.ts`, `frontend/tests/app/App.test.tsx`
  (каркас неизбежно затрагивает больше 3 файлов — это конфигурация, не логика)
- **Зависит от:** T01
- **Описание:** Vite + React 18.3 + TypeScript `~5.9` strict (`any` запрещён правилом
  eslint), TanStack Query v5, react-router-dom v7; зависимости и версии — строго plan §7.2.
  Скрипты npm: `dev` (прокси `/api` → `http://localhost:8000`), `build`, `lint`,
  `typecheck` (`tsc --noEmit`), `test` (`vitest run`, `include: ["tests/**/*.test.{ts,tsx}"]`,
  jsdom), `gen:api` (`openapi-typescript ../docs/api/openapi.json -o src/shared/api/schema.d.ts`).
- **Готово, когда:** `cd frontend && npm ci && npm run lint && npm run typecheck && npm test && npm run build` — всё успешно.
- **Попытки:** 0

## T22 — API-клиент, сгенерированные типы, словарь строк, фоновый опрос
- **Статус:** TODO
- **AC:** FR-29 и FR-59 (заголовок `X-GT-Background: 1` только на повторных загрузках опроса), FR-44 (типы из OpenAPI), NFR-6, AC-98 (автопроверка: строк интерфейса вне словаря нет)
- **Файлы:** `frontend/src/shared/api/client.ts`, `frontend/src/shared/api/polling.ts`,
  `frontend/src/shared/i18n/ru.ts`, `frontend/src/shared/i18n/index.ts`,
  `frontend/src/shared/api/schema.d.ts` (генерируется), `scripts/gen-api.sh` (фронтенд-часть);
  тесты: `frontend/tests/shared/client.test.ts`, `frontend/tests/shared/polling.test.ts`,
  `frontend/tests/shared/i18n.test.ts`
- **Зависит от:** T19, T21
- **Описание:** По plan §4.14: `openapi-fetch` клиент с middleware ошибок (`ApiError {status, code, detail}`)
  и обработкой 401 / 403 `password_change_required` / 403 `no_role` через колбэки навигации;
  `usePolledQuery` (интервал 15 000 мс; заголовок фона — если у запроса уже есть данные);
  словарь `ru` и `t()`; тест i18n ищет кириллицу в `src/**/*.tsx` вне `src/shared/i18n/`.
- **Готово, когда:** `bash scripts/gen-api.sh && git diff --exit-code frontend/src/shared/api/schema.d.ts docs/api/openapi.json`;
  `cd frontend && npm run lint && npm run typecheck && npm test` — успешно.
- **Заметка ревью T13:** dev-прокси Vite — `changeOrigin: false` (иначе `Host` не совпадёт с `Origin: http://localhost:5173`).
- **Попытки:** 0

## T23 — Экраны входа, смены пароля и «нет роли»
- **Статус:** TODO
- **AC:** UF-2 (вход), FR-55 (при одноразовом пароле доступны смена пароля и выход) и FR-66 (поведение интерфейса), NFR-7 (видимый фокус, клавиатура)
- **Файлы:** `frontend/src/features/auth/api.ts`, `frontend/src/features/auth/LoginPage.tsx`,
  `frontend/src/features/auth/ChangePasswordPage.tsx` (+ `frontend/src/app/router.tsx`,
  небольшие компоненты `frontend/src/shared/ui/*` при необходимости);
  тесты: `frontend/tests/features/auth/LoginPage.test.tsx`, `frontend/tests/features/auth/ChangePasswordPage.test.tsx`
- **Зависит от:** T22
- **Описание:** Вход (`/login`), принудительная и добровольная смена пароля
  (`/change-password`, текущий и новый пароль, подсказка «не короче 12 символов»), экран
  «роль не назначена» с кнопкой выхода, выход. Ошибки по `code` из ответа. Все строки — из
  словаря. Моки — `vi.fn()` для `fetch`, без новых зависимостей.
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` — успешно.
- **Попытки:** 0

## T24 — Экраны администрирования: учётные записи, роли, сессии, журнал
- **Статус:** TODO
- **AC:** UF-2, FR-42 (интерфейс системных настроек), FR-55 и FR-65 (OI-108: одноразовый пароль генерирует клиент и показывает администратору), FR-73 (подсказка формата логина), FR-4 (создание без роли, роль — отдельным действием)
- **Файлы:** `frontend/src/features/admin/api.ts`, `frontend/src/features/admin/UsersPage.tsx`,
  `frontend/src/features/admin/AuditPage.tsx` (+ маршруты в `frontend/src/app/router.tsx`);
  тесты: `frontend/tests/features/admin/UsersPage.test.tsx`, `frontend/tests/features/admin/AuditPage.test.tsx`
- **Зависит от:** T18, T23
- **Описание:** Список пользователей (пагинация), создание (логин + одноразовый пароль,
  сгенерированный `crypto.getRandomValues`, показывается администратору один раз в
  интерфейсе), блокировка/разблокировка, сброс пароля, завершение сессий, назначение/смена/снятие
  роли; журнал аудита с фильтрами. Экраны видны только при соответствующих capabilities из
  `/me` (сервер проверяет сам).
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` — успешно.
- **Попытки:** 0

## T25 — Образ web: TLS-прокси nginx и статика
- **Статус:** TODO
- **AC:** FR-63 (конфигурация; проверка в стеке — T26), AC-40 (проверка образа отдельно), NFR-4, D-17
- **Файлы:** `deploy/web/Dockerfile`, `deploy/web/default.conf.template`, `deploy/web/10-gostracker-tls.sh`,
  `deploy/tls/README.md`, `.gitignore` (`deploy/tls/*.crt`, `deploy/tls/*.key`, `backups/`, `frontend/dist`);
  тесты: `backend/tests/infra/test_web_image.py` (`infra_static`)
- **Зависит от:** T24
- **Описание:** Ровно по plan §4.12: сборка фронтенда на `node:22-alpine`, nginx stable-alpine +
  `openssl`; выбор сертификата оператора / уже сгенерированного / генерация самоподписанного
  (не перегенерируется при перезапуске); 80 → 308 на `https://$host:${HTTPS_PORT}`;
  `ssl_protocols TLSv1.2 TLSv1.3`; `client_max_body_size 12m` и JSON для 413;
  ленивое разрешение `api` через `resolver 127.0.0.11`; заголовки безопасности.
- **Готово, когда:** `docker build -f deploy/web/Dockerfile -t gostracker-web:test .` успешен;
  `pytest -q -m infra_static backend/tests/infra/test_web_image.py` зелёный (самоподписанный
  сертификат создан и стабилен, TLS 1.2 принимается, TLS 1.1 отклоняется, `nginx -T` содержит
  `ssl_protocols TLSv1.2 TLSv1.3`, http → 308).
- **Заметка ревью T12:** `proxy_set_header Host $http_host` (не `$host`), иначе при нестандартном порте HTTPS ложный 403 `origin_mismatch`; `X-Forwarded-Proto` передавать.
- **Заметка ревью T13:** uvicorn за nginx — `--proxy-headers --forwarded-allow-ips`; без этого `check_origin` даёт 403 на каждый POST по https; `client_max_body_size` (вложения 10 МБ, прочее — небольшой предел).
- **Попытки:** 0

## T26 — Поставляемый docker-compose и инфраструктурные тесты стека
- **Статус:** TODO
- **AC:** AC-23 (в стеке), AC-40, AC-95, AC-105, FR-6a, FR-48, FR-51, FR-58, FR-63, NFR-3 (часть), NFR-9
- **Файлы:** `docker-compose.yml`, `.env.example`; тесты: `backend/tests/infra/test_compose_static.py`
  (расширение), `backend/tests/infra/test_stack_first_run.py`, `backend/tests/infra/test_stack_tls.py` (`infra_stack`)
- **Зависит от:** T20, T25
- **Описание:** Поставляемая конфигурация по plan §4.12: сервисы `db`, `api`, `web`
  (сервис `ops` — R1.4), якорь логирования на каждом сервисе, тома `pgdata`, `appdata`,
  `tls-generated`; порты публикует только `web` (`HTTP_PORT`, `HTTPS_PORT` из `.env`);
  у `api` `COOKIE_SECURE: "true"` литералом; healthcheck и `depends_on: condition: service_healthy`.
  `.env.example` — plan §4.12. Инфраструктурные тесты стека поднимают отдельный проект,
  чтобы не трогать стек пользователя.
- **Готово, когда:** `pytest -q -m infra_static backend/tests/infra/test_compose_static.py` зелёный;
  `HTTP_PORT=18080 HTTPS_PORT=18443 docker compose -p gostracker-infratest up -d --build --wait`,
  затем `GT_INFRA_STACK=1 GT_INFRA_PROJECT=gostracker-infratest HTTP_PORT=18080 HTTPS_PORT=18443 pytest -q -m infra_stack backend/tests/infra`
  зелёный, затем `docker compose -p gostracker-infratest down -v` (удаляются только тома тестового проекта).
- **Заметка ревью T12:** infra_stack-тест входа и POST при `HTTPS_PORT=8443` (Origin с портом) — без ложного `origin_mismatch`.
- **Заметка ревью T16:** документация оператора — `INITIAL_ADMIN_LOGIN` читается без `.strip()`: значение с пробелами/переводом строки по краям даёт ошибку запуска (без значения в тексте).
- **Заметка ревью T16:** `idle_in_transaction_session_timeout` на уровне БД и `lock_timeout` для админ-действий (зависшая транзакция админа блокирует остальные админ-действия пространства).
- **Попытки:** 0

## T27 — CI
- **Статус:** TODO
- **AC:** NFR-10, N-6
- **Файлы:** `.github/workflows/ci.yml`, `scripts/check.sh`
- **Зависит от:** T22, T26
- **Описание:** Задания: `backend` (Python 3.12, сервис postgres:16, `pip install -e "backend[dev]"`,
  ruff check/format, mypy, `alembic upgrade head` + `alembic check` на тестовой БД, pytest без
  `infra_stack`); `frontend` (Node 22, `npm ci`, lint, typecheck, test, build); `contract`
  (`scripts/gen-api.sh` + `git diff --exit-code`); `infra` (после `backend` и `frontend`:
  стек с отдельным проектом и портами 18080/18443, `pytest -m infra_stack`, `docker compose logs`
  при ошибке, `down -v`). `scripts/check.sh` добавляет `alembic check` и фронтенд-проверки.
  Секретов в workflow нет; `git push` агенты не выполняют.
- **Готово, когда:** `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"` без ошибок;
  `bash scripts/check.sh` зелёный локально; первый прогон CI на ветке зелёный (проверяет человек после push).
- **Заметка ревью T16a:** AST-тест `commit_durably` — требовать равенство `{auth/service.py, api/deps.py}`; тест числа COMMIT на запрос — `== 2`; mypy на `backend/tests` (≈13 ошибок типов в conftest и др.) — решить, проверять ли тесты.
- **Заметка ревью T17:** `test_admin_roles.py::note_b` — ужесточить до `== 401` для параллельно заблокированного в смене пароля.
- **Наблюдение (оркестратор, T18):** фильтр журнала по `actor_id` без совпадений уходит в `Seq Scan` (1,6 мс на 30 000 строк); при росте журнала (R1.1+, десятки тысяч событий на проект) рассмотреть частичный индекс `(workspace_id, actor_id, id DESC) WHERE in_audit`; замер объёма — в нагрузочном прогоне NFR-2 (R1.4).
- **Попытки:** 0

## T28 — Документация R1.0
- **Статус:** TODO
- **AC:** NFR-11 (часть), NFR-3 (инструкция), FR-63 (самоподписанный сертификат в README), OI-70 (dev-команды)
- **Файлы:** `README.md` (ru + en), `docs/data-model.md`, `AGENTS.md` (только блок «Команды»), `docs/STATE.md`
- **Зависит от:** T26
- **Описание:** README: `git clone` → `cp .env.example .env` → `docker compose up`, где взять
  пароль первого ТА (`docker compose exec api cat /data/secrets/initial-admin-password.txt`),
  предупреждение браузера о самоподписанном сертификате и подключение своего (`deploy/tls/`),
  смена портов; разделы на русском и английском. `docs/data-model.md` — таблицы R1.0 из
  plan §4.3. В `AGENTS.md` заменить комментарий о dev-БД конкретной командой из plan D-18 и
  добавить `TEST_DATABASE_URL`; правила не менять. `docs/STATE.md` — состояние после R1.0.
- **Готово, когда:** ревьюер подтверждает соответствие plan; в README есть обе языковые части и
  команды из plan D-18/§4.12; ссылки на файлы существуют.
- **Заметка ревью T02:** вписать в AGENTS.md и README команду dev-конфигурации (`-f deploy/compose.dev.yml`) и способ загрузки `deploy/dev.env.example` (`set -a; . …; set +a`).
- **Заметка ревью T07:** `downgrade 0002` молча удаляет непустой журнал — описать в документации оператора (или добавить отказ при непустой таблице); в бэклог — отдельная роль БД без SUPERUSER и `REVOKE UPDATE, DELETE, TRUNCATE` (plan D-8).
- **Заметка ревью T08:** в документации оператора — лимит параллельных хешей (m=128 МиБ, пул `min(32, cpu+4)` → ~900 МиБ пик на стенде C-2).
- **Заметка ревью T09:** в README/документации оператора — запускать API через `uvicorn app.main:app` (или CLI), не программным `uvicorn.run(app)` (dictConfig вернёт обработчики без фильтра секретов); правило «не печатать секреты в `__repr__`/`__str__`» — в docstring модуля логирования.
- **Попытки:** 0

---

## Этапы R1.1–R1.4 (крупные блоки, детализируются позже)

Модули и интерфейсы — plan §3, §4.3–§4.14; трассировка — plan §6.

### R1.1 «Проекты и задачи» (миграция 0004; 0003 занята в T11)
- **B1.1-A Справочник пользователей, проекты, участники, владение, архив.** `domain/projects`,
  `domain/access/{policy,recipients}`, `api/v1/{users,projects}`; события `project.*`, `member.*`.
  AC-51, AC-52, AC-53, AC-54, AC-55, AC-70 (кроме перемещения на доске), AC-71 (кроме сделки),
  AC-72, AC-73, AC-74 (проект, задача), AC-75 (проекты, свои задачи), AC-65 (владение, архив),
  AC-94 (ТА → проект 403), AC-21, AC-108 (проект), AC-110 (FR-14c).
- **B1.1-B Задачи, подзадачи, прогресс, метки, личный список, позиции (добавление, конец колонки).**
  `domain/tasks`, `domain/labels`, `api/v1/{tasks,labels}`. AC-6, AC-7, AC-8, AC-9, AC-11, AC-24,
  AC-42 и AC-43 (задачи), AC-46, AC-47, AC-48, AC-49, AC-50, AC-56, AC-57, AC-68 (формат срока),
  AC-69, AC-80 (списки, счётчик), AC-81, AC-94 (задачи 404), AC-103, AC-106, AC-108 (задача), AC-109 (FR-20).
- **B1.1-C Комментарии и упоминания.** `domain/comments`, `api/v1/{comments,mentions}`.
  AC-58, AC-102, AC-103 (комментарии), AC-116 (упоминание `@Ivan.Petrov`, FR-73).
- **B1.1-D Вложения.** `domain/attachments`, `api/v1/attachments`, зависимость `python-multipart`.
  AC-16, AC-59, AC-100, AC-117 (вложенные и зашифрованные архивы).
- **B1.1-E Мягкое удаление, корзина, восстановление, команда обслуживания.** `domain/trash`,
  `domain/ops/maintenance`, `cli maintenance`. AC-18 (задача, проект), AC-62, AC-63, AC-66 (обслуживание),
  AC-99, AC-112 (право окончательного удаления), AC-118 (восстановление на занятую позицию).
- **B1.1-F Лента проекта и поиск по задачам и проектам.** `domain/activity`, `domain/search`.
  AC-90 (проект), AC-92 (задачи, проекты).
- **B1.1-G Фронтенд:** проекты, список и карточка задачи, комментарии, вложения, счётчик упоминаний,
  корзина, поиск; опрос на экранах FR-29 (список задач, карточка, лента, счётчик).

### R1.2 «Доска»
- **B1.2-A Доска и перемещение по соседям.** `domain/boards`, `domain/tasks/positions.move_task`,
  `api/v1/boards`, `POST /tasks/{id}/move`. AC-25, AC-61, AC-70 (перемещение в архиве — 409), AC-80 (доска).
- **B1.2-B Фильтры списка задач.** `domain/tasks/queries`. AC-22, AC-60, AC-68 (фильтры), AC-111 («ближайшие 7 дней», «Готово»).
- **B1.2-C Фронтенд доски:** перетаскивание (`@dnd-kit`) с клавиатурной заменой, опрос доски.
  AC-5 *ручной*, AC-97 (доска) *ручной*.

### R1.3 «CRM» (миграция 0005)
- **B1.3-A Воронка и стадии; стадии по умолчанию при первом запуске.** `domain/crm/pipeline`,
  `domain/system/bootstrap`. AC-85, AC-65 (стадии).
- **B1.3-B Клиенты и контакты.** `domain/crm/{accounts,contacts}`. AC-82, AC-83, AC-89.
- **B1.3-C Сделки, история, лента сделки, аудит.** `domain/crm/{deals,history}`. AC-10, AC-13,
  AC-14, AC-42 и AC-43 (сделки), AC-65 (полностью), AC-67, AC-74 (ответственный), AC-76, AC-77,
  AC-84, AC-86, AC-90 (сделка), AC-94 (П → сделка 403), AC-120 (удаление и восстановление через API).
- **B1.3-D Связь сделки с проектом (plan §4.15).** `api/v1/crm/project_links`, поле `deal_link` проекта.
  AC-15, AC-71 (связь), AC-87, AC-88, AC-91, AC-119, AC-122.
- **B1.3-E CRM в корзине, обслуживание, восстановление командой.** `domain/ops/{maintenance,restore_crm}`.
  AC-18 (сделка), AC-101, AC-120 (восстановление командой — автор «система»), AC-122 (снятие связи после 30 дней).
- **B1.3-F Поиск по клиентам и сделкам.** AC-92 (CRM-часть).
- **B1.3-G Фронтенд CRM:** клиенты, контакты, сделки, воронка (список + сводка), карточка
  сделки, история и лента; опрос на карточке сделки, списке сделок и ленте сделки.

### R1.4 «Приёмка»
- **B1.4-A Демо-данные.** `domain/ops/demo`, `cli demo-data`. AC-41, AC-104; подготовка AC-1.
- **B1.4-B Экспорт и импорт.** `domain/ops/{export,importer}`. AC-17, AC-93.
- **B1.4-C Резервная копия и восстановление.** `scripts/backup.sh`, `scripts/restore.sh`,
  `deploy/ops/run.sh`, сервис `ops`. AC-12 *ручной* (+ инфраструктурный smoke), AC-95 (сервис ops).
- **B1.4-D Генератор нагрузки, замер NFR-2, калибровка Argon2.** `domain/ops/loadgen`,
  `tools/nfr2_bench.py`. AC-96, AC-19 *замер*, AC-38 *замер*.
- **B1.4-E E2E и ручные проверки.** Playwright (`frontend/e2e`), `docs/acceptance/r1-manual.md`.
  AC-107 *e2e*, AC-1, AC-5, AC-12, AC-97, AC-98 *ручной*.
- **B1.4-F Документация.** README (финал), `docs/data-model.md` (полностью), `docs/api/openapi.json`. NFR-11.
