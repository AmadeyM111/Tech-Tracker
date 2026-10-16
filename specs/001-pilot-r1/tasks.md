# Tasks: Пилот GOSTracker R1

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED | SUPERSEDED (заменена MVP-задачей, номер указан) |
SKIPPED (следующая версия). Статусы ведёт оркестратор.

> **MVP-пересборка (архитектор, 2026-10-15).** Решением владельца продукта объём сокращён до
> прототипа таск-трекера (plan §11). Действующий порядок работ — раздел **«MVP-пересборка»** в
> конце файла (T29, T35, T67–T89). Задачи T33–T66 не удалены: каждая помечена SUPERSEDED (с
> номером заменяющей задачи) или SKIPPED (следующая версия); реестр с причинами и отложенными
> AC — раздел **«Отложено (следующая версия)»**. R1.0 (T01–T28) и выполненные T30–T32a не менялись.

Синхронизировано со spec v0.15 (OI-103…OI-118, FR-14c, FR-73, AC-108…AC-122).
Детально расписаны этапы **R1.0 «Фундамент»** (T01–T28, закрыт) и **R1.1 «Проекты и задачи»**
(T29–T66, детализирован 2026-10-15 по plan §10). Этапы R1.2–R1.4 — крупными блоками в конце
файла; они детализируются отдельно, когда закрыт предыдущий этап.

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
- **Статус:** DONE
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
- **Попытки:** 1

## T20 — Образ API
- **Статус:** DONE
- **AC:** FR-48 (api), FR-6 (bootstrap при старте), NFR-4, N-6, D-19, D-21
- **Файлы:** `backend/Dockerfile`, `backend/docker-entrypoint.sh`, `backend/.dockerignore`;
  тесты: `backend/tests/infra/test_api_image_static.py` (`infra_static`), `backend/tests/infra/test_api_image_build.py` (`infra_stack`, `GT_INFRA_STACK=1`)
- **Зависит от:** T10, T19
- **Описание:** По plan §4.12: `python:3.12-slim-bookworm`, исходники в `/app`,
  `pip install --no-cache-dir /app`, `ALEMBIC_CONFIG=/app/alembic.ini`, пользователь uid 10001,
  `/data` принадлежит ему, `VOLUME /data`; entrypoint `umask 077` → `gostracker bootstrap` →
  `exec uvicorn … --proxy-headers --forwarded-allow-ips='*' --no-access-log`; `HEALTHCHECK` на
  `/api/v1/health` средствами Python (без curl).
- **Готово, когда:** `docker build -t gostracker-api:test backend` успешен;
  `pytest -q -m infra_static backend/tests/infra/test_api_image_static.py` и `GT_INFRA_STACK=1 pytest -q -m infra_stack backend/tests/infra/test_api_image_build.py` зелёные (Python 3.12, uid 10001, `gostracker --help`).
- **Заметка ревью T02:** при `depends_on: db: condition: service_healthy` добавить `start_period` к healthcheck db.
- **Заметки ревью T10 (желательные, не блокировали):** (1) `alembic upgrade head` выполнять под тем же advisory lock (параллельный запуск на чистой БД падает на `alembic_version`); (2) при ошибке COMMIT перед удалением файла пароля проверить отдельной сессией, не зафиксировано ли пространство (обрыв после фиксации оставляет ТА с неизвестным паролем); (3) минимальная длина `SECRET_KEY` из env (≥ 32 байт) и сравнение заглушки `strip().lower()` — требование в FR-6/D-20 через plan; (4) удалять остатки `.<name>.*.tmp` под блокировкой; `ensure_private_dir` — `lstat`/`S_ISDIR`, чинить права 0755 → 0700; (5) advisory lock на AUTOCOMMIT-соединении; `_known_secrets` из `settings`; `path_separator = os` в `alembic.ini`; plan §4.7 — stdout только путь, текст в stderr.
- **Попытки:** 2

## T21 — Каркас фронтенда
- **Статус:** DONE
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
- **Попытки:** 1

## T22 — API-клиент, сгенерированные типы, словарь строк, фоновый опрос
- **Статус:** DONE
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
- **Заметки ревью T21:** (1) eslint для `src/**` кроме `src/shared/api/**`: `no-restricted-globals` на `fetch`, `no-restricted-properties` на `window.fetch`/`globalThis.fetch`, `no-restricted-imports` на `axios`; (2) README и `engines` в package.json: Node `^22.12 || ^24 || >=26`; (3) `frontend/.npmrc` с `ignore-scripts=true` (fsevents) и проверка `npm ci`+сборки; (4) `server.strictPort: true` в vite.config.ts; (5) `scripts/check.sh`: понятное сообщение «выполните `cd frontend && npm ci`» при отсутствии `node_modules`; (6) `backend/tests/infra/test_frontend_scaffold.py::test_t21_src_files_only_expected` расширить списком файлов T22; (7) `src/shared/api/schema.d.ts` — генерируемый, в ignores eslint; сгенерировать `npm run gen:api` из `docs/api/openapi.json` и закоммитить (тест на совпадение с генерацией).
- **Заметки ревью T22 (в T23+/T26/T27):** (1) polling.ts: ограничить задержку тика сверху `POLL_INTERVAL_MS` (перевод часов назад замораживает опрос); (2) фоновые тики без retry (серия 5xx даёт пачку из 4 запросов каждые ~22 с); (3) pytest-сверка `PASSWORD_MIN_LENGTH` с `MIN_PASSWORD_LENGTH` и списка кодов бэкенда со словарём (коды R1.1+ не должны молча уходить в `error.unknown`); (4) известный краевой случай: `refetch()` во время летящего фонового тика без данных присоединяется к нему и уходит с заголовком (plan §4.14).
- **Попытки:** 3

## T23 — Экраны входа, смены пароля и «нет роли»
- **Статус:** DONE
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
  **Ревью T23 (попытка 1):** добавлена проверка сессии (`GET /api/v1/me` через `me()` в `features/auth/api.ts`) на `/`: 200 — заглушка главной, 401 → `/login`, 403 `password_change_required` → `/change-password`, 403 `no_role` → `/no-role`; `*` → `/`; после смены пароля переход на `/` и далее по `/me` (новый пользователь без роли попадает на «нет роли», FR-4/FR-66/AC-75); `/login` при действующей сессии → `/`; один общий клиент приложения с колбэками навигации (plan §4.14); логин на клиенте обрезается по краям; повторная одинаковая ошибка снова переносит фокус; тесты на 401 при выходе и очистку кэша.
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` — успешно.
- **Заметки ревью T23 (в T24+):** (1) экраны T24 оборачивать в guard сессии (как `Root`), а не полагаться только на колбэк: после «Назад» с `/login` глобальный `fired` не взведён; (2) `/login` при pending `me` показывает форму (мелькание допустимо; индикатор ломает тест маршрута); (3) на `/no-role` нет ссылки на `/change-password` (добровольная смена только по прямому URL; тесты FR-55 запрещают ссылки на экранах — решить в T24/UX); (4) `client.ts` расширен `getAppClient()`/`setNavigationHandlers()` (правка вне списка T23, аддитивная).
- **Попытки:** 3

## T24 — Экраны администрирования: учётные записи, роли, сессии, журнал
- **Статус:** DONE
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
- **Заметки ревью T24:** (1) правки вне списка T24: `router.tsx` (главная, SessionGate), `shared/ui/{ConfirmDialog,Pagination,TextField,ui.css}`, `eslint.config.js` (запрет `Math.random` в `src/**`), `ru.ts`; (2) главная содержит «Выйти» (FR-60) и ссылку на `/change-password` (FR-56) — решение замечания T23 №3; (3) журнал фильтруется по `entity_type` и `actor_id` (API R1.0 других фильтров не даёт; период/действие — вне спецификации FR-47); (4) для ввода `actor_id` — свободное поле UUID, выбор из списка пользователей — UX на R1.1; (5) опрос на admin-экранах не подключён (FR-29 их не перечисляет).
- **Попытки:** 2

## T25 — Образ web: TLS-прокси nginx и статика
- **Статус:** DONE
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
- **Заметка ревью T20:** nginx перезаписывает `X-Forwarded-Proto` (`proxy_set_header`), не пропуская клиентский.
- **Заметки ревью T25 (перенесены в T26/T28):** см. блок «Перенесено из ревью T25» в T26 и T28.
- **Попытки:** 1

## T26 — Поставляемый docker-compose и инфраструктурные тесты стека
- **Статус:** DONE
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
- **Перенесено из ревью T10/T20 (не терять):** (2) при ошибке COMMIT перед удалением файла пароля проверять отдельной сессией, не зафиксировано ли пространство; (4) удалять остатки `.<name>.*.tmp` под блокировкой, `ensure_private_dir` — `lstat`/`S_ISDIR` и 0755 → 0700; (5) advisory lock на AUTOCOMMIT-соединении, `_known_secrets` из `settings`, `path_separator = os` в `alembic.ini` (предупреждение alembic в логах); `run_bootstrap(locked: bool)` → токен-маркер от `bootstrap_lock`; не логировать `/api/v1/health` в INFO (≈8,6 тыс. строк/сутки от HEALTHCHECK) — правка теста T09; Dockerfile: слой зависимостей до исходников и очистка `/app/build`, `*.egg-info`.
- **Перенесено из ревью T25:** (1) `deploy/web/10-gostracker-tls.sh`: временные файлы через `mktemp` в каталоге генерации (PID одинаков в контейнерах — гонка двух контейнеров на одном томе); перед использованием сгенерированной пары сверять открытые ключи и `-checkend 0`, при несовпадении/просрочке перегенерировать с сообщением в лог (не для сертификата оператора); предупреждение, если оператор положил только один из файлов; не глушить stderr openssl, проверка длины `TLS_SERVER_NAME` (≤ 64); (2) проверять `HTTPS_PORT` — число 1…65535, иначе понятная ошибка; (3) `.gitignore`: `deploy/tls/*` + `!deploy/tls/README.md`; (4) в compose у web: `HTTPS_PORT: ${HTTPS_PORT:-443}`, `TLS_SERVER_NAME: ${TLS_SERVER_NAME:-localhost}`, контекст сборки `.`, `dockerfile: deploy/web/Dockerfile`; api собирать строго с контекстом `./backend` (корневой `.dockerignore` — белый список: только `frontend` и `deploy/web`); одна реплика web на том `tls-generated`; healthcheck api только GET (HEAD `/api/v1/health` → 405); HEALTHCHECK у web; (5) infra_stack: вход и POST при `HTTPS_PORT=8443` с Origin с портом, подставной `X-Forwarded-Proto` ни на что не влияет; (6) тесты: 404 для отсутствующего `/assets/*`, `/api` не отдаёт index, `Cache-Control: no-cache` у index.html, `server_tokens off`, отказ при `TLS_SERVER_NAME` с `;`, `$(...)`; (7) ответы 502/400/405 от nginx на `/api` приходят HTML, не ErrorResponse — клиент T22 переносит (`invalid_response`), принять как известное; 413 с кодом `attachment_too_large` для любого пути.
- **Заметки ревью T26:** перенесены в T27/T28 (блоки «Перенесено из ревью T26»).
- **Попытки:** 1

## T27 — CI
- **Статус:** DONE
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
- **Заметки ревью T19:** вынести `_safe_description`/`wait_for_database`/`BootstrapError` из `bootstrap` в общий модуль CLI; в OpenAPI уточнить 403 у login/logout/password до `origin_mismatch` и объявить 500/default с `ErrorResponse`; `hash-bench` при неверных `ARGON2_*` печатать причину; R1.1 — единый `gostracker maintenance` с `--dry-run` и unit-тест `purge_expired_sessions` на точных границах (8 ч, ±1 мкс, `absolute == now`).
- **Открытый вопрос (оркестратор, T20):** `ruff check backend` обнаружил I001 в `backend/tests/cli/test_bootstrap.py` (:430, :532) и `backend/tests/api/test_deps_gates.py` (:147), существовавшие с T10/T12, хотя `bash scripts/check.sh` на тех задачах был зелёным; воспроизводится и с `--no-cache`, причина молчания прежних запусков не установлена. В CI запускать линтер на чистой выгрузке без кэша (`--no-cache`), версию ruff закрепить в `pyproject.toml`.
- **Перенесено из ревью T26:** (1) CI infra-задание строго в порядке `up` → `pytest -m infra_stack` → `down -v` на свежем проекте (тесты first_run зависят от порядка/состояния), при ошибке — `docker compose logs`; только infra_stack ловит удаление `lock_timeout`; (2) `test_stack_first_run.py`: проверка свежести стека в начале модуля (`pytest.fail("нужен свежий стек: down -v")` вместо 9 каскадных KeyError) и статическая проверка `lock_timeout`/`idle_in_transaction_session_timeout` в `test_compose_static.py`; (3) `lock_timeout=30s` задан на весь сервер: в соединении блокировки bootstrap и в alembic — `SET lock_timeout = 0` (второй bootstrap по plan §4.7 ждёт); ответ на `LockNotAvailableError` сейчас 500 `internal_error` — код ошибки нужен в spec/plan (R1.1); (4) `deploy/web/10-gostracker-tls.sh`: удалять остатки `.tls.*.??????` (с закрытым ключом) под flock; `ensure_secret_key`: чистить `.secret_key.*.tmp`; (5) HEALTHCHECK web пишет `GET /` в access-лог nginx каждые 10 с — отдельный location с `access_log off`; (6) `restart: unless-stopped` — решить через plan (сейчас нет restart policy; иначе описать в T28); (7) `.gitignore`: строки `deploy/tls/*.crt|*.key` лишние (покрыты `deploy/tls/*`); bootstrap печатает путь к файлу пароля дважды.
- **Заметки ревью T27 (R1.1+/T28):** (1) код ошибки для `LockNotAvailableError` (сейчас 500 `internal_error`, нужен пункт в spec/plan); (2) mypy на `backend/tests` (с `--explicit-package-bases` ≈64 ошибки в 15 файлах; без флага не стартует — конфликт имён `conftest`); (3) заметки T19, не сделанные в T27: вынос `_safe_description`/`wait_for_database`/`BootstrapError`, уточнение 403/500 в OpenAPI, причина в `hash-bench`, `gostracker maintenance --dry-run`, unit-тест границ `purge_expired_sessions`; (4) частичный индекс журнала по `actor_id` — по замеру NFR-2 (R1.4); (5) пины `actions/*` (v4/v5/v4) работают на рантайме Node 20 — поднять мажоры при первом прогоне CI; (6) `.gitignore`: лишние строки `deploy/tls/*.crt|*.key` (тест T25 их требует — убрать вместе с тестом); (7) T28 (документация): семантика `restart: unless-stopped` (после `docker stop`/`kill` не поднимается; unhealthy не перезапускается); bootstrap и миграции ждут блокировки бессрочно (`lock_timeout=0`), зависшая блокировка → api не healthy и `up --wait` висит; `/healthz` доступен снаружи (200 «ok»); infra_stack требует свежий стек (`down -v`); требования к Node; Content-Type `/healthz` — косметика.
- **Попытки:** 2

## T28 — Документация R1.0
- **Статус:** DONE
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
- **Перенесено из ревью T20:** документация оператора — `--forwarded-allow-ips='*'` допустим пока порт api не публикуется; при публикации 8000 сузить до адреса прокси; plan D-20 — правило «`SECRET_KEY` короче 32 байт отклоняется, заглушка по `strip().lower()`».
- **Окружение (T22):** `node` в среде разработчика — shim `proto` с единственной Node 18; `engines.node = "^22.12 || ^24 || >=26"` требует ≥ 22.12: запускать с `PATH=/opt/homebrew/bin:$PATH` (Node 26.3) либо `proto install node 24`; README и CI должны требовать/устанавливать подходящий Node.
- **Перенесено из ревью T25:** документация: после смены `TLS_SERVER_NAME`, при битом/просроченном (825 дней, первый — около января 2029) сгенерированном сертификате удалить том `<project>_tls-generated`; при доступе по IP в SAN будет DNS-запись, а не IP; файлы оператора называются `tls.crt`/`tls.key`; access-log nginx пишет query — секреты в URL не передавать.
- **Перенесено из ревью T26:** документация: `SECRET_KEY` в api из `.env` не пробрасывается — ключ в `/data/secrets/secret_key`; `POSTGRES_PASSWORD` подставляется в `DATABASE_URL` без URL-кодирования (`@ : / %` ломают подключение), смена пароля после первой инициализации БД не меняет пароль в БД; `INITIAL_ADMIN_LOGIN` без пробелов по краям; таймауты 30 с / 60 с: админ-действие при занятой блокировке получает 500 через 30 с, стек не обновлять во время бэкапа; без restart policy после перезагрузки хоста нужен `docker compose up -d`; web остаётся healthy при упавшем api (на `/api` HTML 502), health api не проверяет БД; `TLS_SERVER_NAME` пропускает синтаксически неверные имена (`a..b`, `a-`).
- **Заметки T28:** `docs/STATE.md` в T28 не обновлялся: файл правит параллельная сессия (состояние после R1.0 внести после её завершения); `.gitignore` дополнен `.data/` (dev DATA_DIR с секретами).
- **Попытки:** 2

---

## Этап R1.1 «Проекты и задачи» (T29–T66)

Детализирован архитектором 2026-10-15 по spec v0.15 (с правками рабочего дерева: FR-9 — 413,
FR-14c — «владелец-БА в своём проекте, СМ в любом»), plan §4.3–§4.11 и **plan §10** (решения
D-40…D-52, протокол блокировок, API, сервисы, каталог событий, корзина, трассировка, вопросы
Q-1…Q-9), приёмке R1.0 (`reviews/R1.0-acceptance.md`, раздел «R1.1!» и техдолг).

### Общие условия для задач R1.1

- Действуют все «Общие условия для всех задач R1.0» (вверху файла).
- Источник интерфейсов — plan §10 (таблица API §10.3, сигнатуры §10.4); порядок проверок —
  plan §4.5 (401 → 403 раздела → 422 схемы → 404 → 403 объекта → 409 → 422 бизнес-правил);
  блокировки — plan §10.2, в указанном там порядке. Отступление — `PLAN_ISSUE`, не додумывать.
- Предложения архитектора с пометкой «Q-n» (plan §10.8) реализуются как предложено; если
  заказчик или аналитик ответит иначе, правится только место, указанное в §10.8.
- События — только `record_event` с действиями и белыми списками полей plan §10.5 (T30);
  события ленты всегда с `project_id`. Сервисы не вызывают `commit()`; `commit_durably` в R1.1
  не используется.
- Каждая выборка — с `workspace_id = actor.workspace_id`; мягко удалённое (`deleted_at IS NOT NULL`)
  вне корзины — 404 (FR-45a).
- Задачи с API: у роутеров и маршрутов объявлены ответы `error_responses(...)`
  (`app/api/openapi.py`); после изменения маршрутов — `bash scripts/gen-api.sh`, в коммит входят
  `docs/api/openapi.json` и `frontend/src/shared/api/schema.d.ts` (руками не правятся); всегда
  зелёные `pytest -q backend/tests/cli/test_openapi.py backend/tests/infra/test_frontend_api_types.py backend/tests/api/test_route_guards.py`
  (обход маршрутов автоматически проверяет 401 / 403 без роли и с одноразовым паролем у новых
  маршрутов). Задачи с API выполнять последовательно: генерируемые файлы общие.
- Фабрики R1.1 (`make_project`, `make_project_member`, `make_task`, `make_label`, `make_comment`,
  `make_mention`, `make_attachment`) добавляет test-writer в T33 и расширяет в следующих задачах.
- Файлы вложений в тестах — только во временном `DATA_DIR` (`tmp_path`); запись вне него — дефект.
- Новая таблица или столбец — обновить `docs/data-model.md` в той же задаче
  (`test_nfr11_data_model_covers_every_table_and_column`, `infra_static`).
- Фронтенд: строки — только из словаря `frontend/src/shared/i18n/ru.ts`; экраны FR-29 (список
  задач, карточка задачи, лента проекта, счётчик упоминаний) опрашиваются через `usePolledQuery`
  (`shared/api/polling.ts`), прочие — `useQuery`; сетевые вызовы — только через общий клиент
  (`shared/api/client.ts`); новые файлы `frontend/src/**` test-writer вносит в
  `backend/tests/infra/test_frontend_scaffold.py::test_t21_src_files_only_expected`; новая
  зависимость фронтенда в R1.1 одна — `react-markdown ^10` (T62, plan §7.2). «Фронтенд зелёный» =
  `cd frontend && npm run lint && npm run typecheck && npm test && npm run build` и
  `pytest -q -m infra_static backend/tests/infra/test_frontend_scaffold.py`.
- Задачи с `infra_stack`: стек поднимается заново из текущего дерева —
  `HTTP_PORT=18080 HTTPS_PORT=18443 docker compose -p gostracker-infratest up -d --build --wait`,
  затем `GT_INFRA_STACK=1 GT_INFRA_PROJECT=gostracker-infratest HTTP_PORT=18080 HTTPS_PORT=18443 pytest -q -m infra_stack <файлы>`,
  затем `docker compose -p gostracker-infratest down -v` (только тестовый проект).
- Конкурентные сценарии (параллельные запросы через HTTP, ≥ 100 итераций, без 500), где они
  указаны в задаче, — по образцу `tests/api/test_session_row_lock.py` (T16a).

### Подготовка: техдолг приёмки R1.0, блокирующий R1.1

## T29 — Занятая блокировка БД и взаимоблокировка: 503 `service_busy`
- **Статус:** DONE
- **AC:** FR-45 (единый формат ошибок), FR-57 и NFR-9 (в ответе и логе нет SQL и параметров); plan D-40, §10.2; приёмка R1.0 «R1.1!» (код для `LockNotAvailableError`), ревью T26 п.3, T27 п.1. **Q-1** (подтверждение заказчика, Д-8)
- **Файлы:** `backend/app/core/errors.py`; тесты: `backend/tests/api/test_db_busy_errors.py`
- **Зависит от:** —
- **Описание:** Сейчас ожидание блокировки дольше `lock_timeout=30s` (compose, plan §4.12) даёт 500
  `internal_error`. Добавить `class ServiceBusy(AppError)`: 503, код `service_busy`, текст
  «Сервер занят, повторите запрос». Обработчик `sqlalchemy.exc.DBAPIError` в
  `install_error_handlers`: SQLSTATE берётся из `exc.orig` (`sqlstate`, затем `pgcode`) или из
  `exc.orig.__cause__.sqlstate` (asyncpg); `55P03` (`lock_not_available`) и `40P01`
  (`deadlock_detected`) → 503 с заголовком `Retry-After: 5` и телом `ErrorResponse`; лог —
  warning с SQLSTATE, без текста запроса и параметров. Прочие `DBAPIError` — прежний путь 500
  (тот же обработчик, что для `Exception`, тело `internal_error`). Транзакцию откатывает `get_db`,
  как при любом исключении; ошибка на COMMIT в `get_db` обрабатывается так же. В OpenAPI по
  маршрутам 503 не объявляется (как 500). Подсказка test-writer: настоящая ошибка asyncpg
  получается `SET LOCAL lock_timeout = '50ms'` + `SELECT … FOR UPDATE` строки, занятой вторым
  соединением, на тестовом маршруте приложения теста.
- **Готово, когда:** `pytest -q backend/tests/api/test_db_busy_errors.py backend/tests/api/test_errors.py` зелёный, линтер чистый.
- **Заметки ревью T29:** (1) прочие `DBAPIError` теперь обрабатывает `ExceptionMiddleware` (ответ 500 и ERROR прежние; проброса в uvicorn больше нет); (2) `test_t29_transaction_rolled_back_on_busy` не различает наличие rollback (транзакция после 55P03 уже прервана) — регрессионный; (3) перечисление логинов через 503 на входе возможно только при занятой >30 с строке `app_user` (до T29 это был 500; reserve-before-verify не нарушен) — в бэклог; (4) в T88 (документация) исправить «админ-действие при занятой блокировке → 500» на «503 `service_busy`, `Retry-After: 5`»; (5) код `service_busy` во фронтенд-словаре — в T81…T85; (6) порядок-зависимый ERROR `cli/test_openapi.py::…stdout_is_valid_json` (JSON-логи alembic в stdout после `configure_logging`) — предсуществующий, чинится в тестах: импортировать `app.cli.main` до `capfd.readouterr()` (включить в T68 или T32b).
- **Попытки:** 1

## T30 — Каталог событий R1.1, белые списки полей, устойчивое чтение журнала
- **Статус:** DONE
- **AC:** FR-41, BR-2, AC-65 (основа: в журнале только имена полей из белого списка), AC-66 (журнал не меняется); plan D-41, §4.4, §10.5; приёмка «R1.1!» (расширение `EntityType`, белый список `changed_fields`), ревью T18/T19
- **Файлы:** `backend/app/domain/events/catalog.py`, `backend/app/domain/events/writer.py`,
  `backend/app/domain/events/queries.py`; тесты: `backend/tests/unit/test_event_catalog.py`,
  `backend/tests/db/test_event_log.py` (дополнение), `backend/tests/api/test_audit.py` (дополнение)
- **Зависит от:** —
- **Описание:** (1) `EventAction` — все действия R1.1 из plan §10.5; `EventSpec` дополняется
  `fields: frozenset[str] = frozenset()` и `value_fields: frozenset[str] = frozenset()`;
  записи `EVENT_CATALOG` — ровно по таблице §10.5 (`user.*` — без изменений, `in_audit` как в
  R1.0). (2) `record_event` дополнительно отклоняет `ValueError` (строка не пишется): имя в
  `changed_fields` вне `spec.fields` или повторяющееся; `changes` у события с пустым
  `value_fields`; `changes[].field` вне `spec.value_fields`; событие с `feed == "project"` без
  `project_id`. Текст исключения называет действие и имя поля, но не значения. (3)
  `queries._to_records`: строка, чей `entity_type` не входит в `EntityType` (откат кода к
  версии без нового типа), пропускается с `logger.warning` (id события и тип, без значений) —
  страница отдаётся без неё, без 500. `entity_deleted` для не-`user` остаётся `False` до T55.
  CHECK `ck_domain_event_entity_type_valid` добавляет T33 (миграция 0004); тест пропуска строки
  снимает этот CHECK внутри транзакции теста (`ALTER TABLE … DROP CONSTRAINT IF EXISTS`), если он уже есть.
- **Готово, когда:** `pytest -q backend/tests/unit/test_event_catalog.py backend/tests/db/test_event_log.py backend/tests/api/test_audit.py` зелёный, линтер чистый.
- **Заметки ревью T30 (в T36/T41/T55/T58):** (1) `record_event`: `changes=[]` у события с непустым `value_fields` пишется как `[]`, у события с пустым — `ValueError`; вызывающим (T36 `project.updated`, T41 `task.updated`) передавать `None`, когда значений нет, лента T55 должна понимать `[]` и `None`; добавить тест на `changes=[]`; (2) нет требования «поля `changes` ⊆ `changed_fields`» и проверки повторов в `changes` — решить в T41; (3) подписи в `AuditPage.ACTION_CODES` для `project.ownership_transferred|archived|unarchived` — в T58/T64 (иначе показываются сырые коды, AC-98); (4) пустая страница журнала при `has_next=true` после пропуска строки — допустимо.
- **Попытки:** 1

## T31 — Команда обслуживания: каркас, `--dry-run`, границы истечения сессий, регулярный запуск
- **Статус:** DONE
- **AC:** FR-25b (каркас автоочистки), FR-59 (истёкшие сессии удаляются), AC-63 и AC-66 *инфра* (каркас; содержательная часть — T54); plan D-42, §4.13, §10.4 (`run_maintenance`, `MaintenanceReport`); приёмка «R1.1!» (регулярный `maintenance`, `--dry-run`, unit-тест границ), заметки T16a/T19/T27
- **Файлы:** `backend/app/domain/ops/__init__.py`, `backend/app/domain/ops/maintenance.py`,
  `backend/app/domain/system/maintenance.py` (параметр `dry_run`), `backend/app/cli/commands/maintenance.py`,
  `README.md` (раздел «Регулярное обслуживание» / «Regular maintenance»);
  тесты: `backend/tests/db/test_purge_sessions_boundaries.py`, `backend/tests/cli/test_maintenance.py`
  (test-writer переписывает под новый вывод), `backend/tests/infra/test_docs_static.py` (дополнение, `infra_static`)
- **Зависит от:** —
- **Описание:** `run_maintenance(sessionmaker, settings, *, clock, dry_run) -> MaintenanceReport`
  (поля — plan §10.4; в этой задаче заполняется `sessions_expired`, остальные счётчики — 0, их
  заполнит T54). `purge_expired_sessions(..., dry_run: bool = False)`: при `dry_run` — только
  `count(*)` тем же предикатом (`last_activity_at <= now − idle` или `absolute_expires_at <= now`),
  ничего не удаляется. CLI: `gostracker maintenance [--dry-run]`; ожидание БД — как сейчас; stdout
  — строки `ключ=значение` в порядке полей отчёта (`dry_run=0|1`, `sessions_expired=N`,
  `projects_purged=N`, `tasks_purged=N`, `comments_purged=N`, `attachments_purged=N`,
  `files_removed=N`, `orphan_files_removed=N`), ошибки — в stderr без DSN; код 0/1. Границы
  (тест с явным `now`): `last_activity_at = now − 8 ч` — удаляется, `now − 8 ч + 1 мкс` — нет;
  `absolute_expires_at = now` — удаляется, `now + 1 мкс` — нет. README (ru и en): зачем
  запускать (корзина 30 дней и истёкшие сессии без запуска не очищаются, FR-25b), пример
  `crontab` — `17 3 * * * cd /opt/gostracker && docker compose exec -T api gostracker maintenance >> /var/log/gostracker-maintenance.log 2>&1`,
  `--dry-run`, безопасность при работающем API. Сервис compose и запуск из api не добавлять
  (D-42: «фонового планировщика в R1 нет»).
- **Готово, когда:** `pytest -q backend/tests/db/test_purge_sessions_boundaries.py backend/tests/cli/test_maintenance.py` и
  `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёные, линтер чистый.
- **Заметки ревью T31 (в T54/T57):** (1) README: `/opt/gostracker` заменить на «каталог клона», запуск под пользователем с доступом к Docker, при `COMPOSE_PROJECT_NAME`/`-p` указать его в cron-строке; добавить `date -u` перед командой в примере; (2) предикат истечения сессий продублирован в dry-run и удалении — вынести в одно выражение (T54); (3) T54: срок корзины — момент UTC (`deleted_at <= now − 30 дней`, plan §4.10), пакеты короткие, занятые строки пропускаются — сохранить верным в README; снимок `FixedClock` на запуск корректен.
- **Попытки:** 1

## T32 — Мелочи приёмки R1.0: сквозные AC-2/AC-64, сканер строк, `--wait`, имя тестовой БД
- **Статус:** DONE
- **AC:** AC-2, AC-64 (по одному сквозному API-сценарию), AC-98 (автопроверка словаря: латиница и атрибуты), NFR-3 (README); приёмка R1.0, замечания 1–4
- **Файлы:** `README.md` (`docker compose up -d --build --wait` в ru и en перед `exec api cat …`),
  `frontend/src/**` и `frontend/src/shared/i18n/ru.ts` (только перенос строк, найденных новым
  сканером, в словарь); тесты: `backend/tests/db/test_migrations.py` (имя БД — из
  `TEST_DATABASE_URL`, а не литерал `tracker_test`, строки ~381 и ~573),
  `backend/tests/api/test_e2e_accounts.py` (новый: AC-2 — ТА создаёт 12 учётных записей и
  назначает 4 роли, каждый входит, меняет одноразовый пароль, `/me` отдаёт назначенную роль;
  AC-64 — один сценарий ТА: создание, блокировка, разблокировка, сброс пароля, завершение
  сессий, назначение/смена/снятие роли другому, назначение себе → ровно одна запись на действие
  с автором, временем UTC, действием, затронутым пользователем; ни одна запись и ни один ответ
  не содержат паролей), `frontend/tests/shared/i18n.test.ts` (латинские текстовые узлы JSX и
  значения `aria-label`, `placeholder`, `title`, `alt` вне словаря), `backend/tests/infra/test_docs_static.py` (`--wait`)
- **Зависит от:** T31 (README)
- **Описание:** Код приложения не меняется, кроме переноса строк интерфейса в словарь. Если
  сквозные тесты AC-2/AC-64 падают — это дефект R1.0: исправление в соответствующем модуле с
  записью в отчёте; если правка выходит за перечисленные файлы — `BLOCKED` с описанием.
- **Готово, когда:** `pytest -q backend/tests/db/test_migrations.py backend/tests/api/test_e2e_accounts.py` и
  `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёные; фронтенд зелёный; линтер чистый.
- **Заметки ревью T32 (в T58/T32a):** (1) ПЕРЕД T58 перевести `scanLatinUi` (i18n.test.ts) на compiler API `typescript` (уже в devDependencies): сейчас регулярные выражения пропускают текст с `( ) ; = & |`, строки в тернарниках/`&&`, шаблоны с подстановкой, константы и пользовательские пропсы (`message="…"`) и дают ложное срабатывание на `{a > b ? <hr/> : null}`; в `src` таких строк пока нет; (2) AC-64: «назначает роль себе» = смена роли ТА на другую (назначение той же — no-op без события; пользователь без роли ничего не может по FR-66) — уточнить формулировку при ближайшей правке spec; (3) в `test_e2e_accounts.py` для самоназначения проверять `details == {role_from, role_to}`; (4) i18n.test.ts: prettier переформатировал существующие строки (шум в diff) — не повторять.
- **Попытки:** 1

## T32a — Принципы разработки закреплены проверками (scope-guard, allowlist зависимостей, сложность)
- **Статус:** DONE
- **AC:** NFR-10 (проверки качества), `AGENTS.md` «Принципы разработки»; решение владельца 2026-10-15
- **Файлы:** `scripts/task_scope.py`, `backend/app/core/errors.py` и `backend/app/cli/commands/bootstrap.py` (только строки `noqa`), `backend/pyproject.toml` (правила `ruff`: `C901`, `PLR0912`, `PLR0913`, `PLR0915`, `ARG`),
  `AGENTS.md` (только ссылка на команду scope-guard в блоке «Команды», если ещё нет);
  тесты: `backend/tests/arch/test_task_scope.py`, `backend/tests/arch/test_dependencies_allowlist.py`, `backend/tests/arch/test_ruff_complexity_rules.py`
  (каталог `backend/tests/arch/` — новый, с `__init__.py`, если так заведено в `backend/tests`)
- **Зависит от:** —
- **Описание:** (1) `scripts/task_scope.py <T..> [--base <ref>]`: читает поле «Файлы» задачи из
  `specs/*/tasks.md`, раскрывает перечисленные пути и шаблоны (glob), берёт изменённые и неотслеженные
  файлы рабочего дерева относительно `--base` (по умолчанию `HEAD`) и печатает файлы вне списка;
  всегда допустимы `specs/**/tasks.md`, `specs/**/reviews/**` и `docs/api/openapi.json` вместе с
  `frontend/src/shared/api/schema.d.ts` (генерируемые); выход 0 — всё в рамках, 1 — есть вне рамок
  (с понятным списком), 2 — задача не найдена; без внешних зависимостей. Не входит в `check.sh`
  (на рабочем дереве бывают чужие правки); используется ревьюером и оркестратором перед коммитом.
  (2) Тест-allowlist: множества имён зависимостей `backend/pyproject.toml` (`dependencies` и `dev`) и
  `frontend/package.json` (`dependencies`, `devDependencies`) равны константам в тесте; добавление
  зависимости требует правки теста (видно в ревью) и пункта в `plan.md`. (3) `ruff`: включить
  `C901` (mccabe), `PLR0912`, `PLR0913`, `PLR0915`, `ARG` с порогами, при которых текущий код проходит
  без правок (зафиксировать выбранные пороги и максимумы текущего кода в отчёте; порог только
  уменьшается); нарушения в существующем коде — не чинить рефакторингом (вне задачи), а при
  необходимости добавлять точечные `# noqa` с причиной (не более 5 и перечислить в отчёте).
  **Доработка по ревью (попытка 2, архитектор 2026-10-15):** (а) пути из групп `(+ …)` входят в список
  (path-подобные токены: содержат `/` или расширение, без пробелов); прочие скобочные пояснения игнорируются;
  токен, не начинающийся с корневого каталога репозитория (`router.tsx`, `features/x/api.ts`), сопоставляется
  как суффикс пути (`path == token` или `path.endswith('/' + token)`); (б) ошибки git (нет репозитория,
  несуществующий `--base`) — понятное сообщение в stderr и код 2, без traceback; `--base` передаётся
  безопасно (`--end-of-options`/проверка, что не начинается с `-`, и `--` перед путями); (в) флаг `--staged`:
  проверять только индекс (`git diff --cached --name-status -z <base> --`, без неотслеженных) — режим для
  оркестратора перед коммитом; (г) один ID задачи в нескольких `specs/*/tasks.md` → код 2 (неоднозначность);
  (д) `**/__init__.py` допустим всегда — зафиксировано как правило в описании скрипта; семантика `*`/`**`
  описана в docstring; (е) пороги ruff равны текущим максимумам `backend/app` (16/16/10/34; ratchet в тесте
  по ним же: `max-statements` ≤ 34); ARG001 — ровно 5 точечных `# noqa: ARG001  # <причина>` в
  `app/core/errors.py` и `app/cli/commands/bootstrap.py` вместо `per-file-ignores` на файл; `per-file-ignores`
  допустимы только для `tests/**` (тест проверяет явно); файлы `app/core/errors.py` и
  `app/cli/commands/bootstrap.py` включены в «Файлы» T32a (только строки `noqa`).
- **Готово, когда:** `pytest -q backend/tests/arch` зелёный; `ruff check --no-cache backend` чист;
  `python scripts/task_scope.py T32a` печатает «в рамках задачи» для собственных изменений; `bash scripts/check.sh` зелёный.
- **Заметки ревью T32a:** scope-guard: в режиме по умолчанию на рабочем дереве с чужими правками всегда код 1 — перед коммитом оркестратор делает `git add` файлов задачи и запускает `python scripts/task_scope.py T.. --staged`; голые токены сопоставляются суффиксом; `scripts/` не покрыт ruff/mypy (вне `backend`).
- **Попытки:** 2

### Backend: модель, права, проекты

## T33 — Модели R1.1 и миграция 0004
- **Статус:** SUPERSEDED → T69 (MVP: 0004 без меток, упоминаний, вложений, `pg_trgm`, `project.status`)
- **AC:** AC-108 (уровень БД: пределы длин), FR-13, FR-14, FR-14b, FR-18, FR-18a, FR-18b (уникальность метки без учёта регистра, OI-100), FR-21 (позиция только у задач верхнего уровня), FR-24 (метаданные вложения), FR-71 (упоминание), AC-66 (CHECK журнала не меняет строки); plan §4.3 (R1.1), D-2…D-4, D-22, D-24…D-26, D-41 (CHECK `entity_type`), D-52
- **Файлы:** `backend/app/domain/projects/models.py`, `backend/app/domain/tasks/models.py`,
  `backend/app/domain/labels/models.py`, `backend/app/domain/comments/models.py`,
  `backend/app/domain/attachments/models.py` (+ `__init__.py` пакетов), `backend/app/domain/events/models.py`
  (CHECK), `backend/app/domain/registry.py`, `backend/migrations/versions/0004_projects_tasks.py`,
  `docs/data-model.md` (таблицы R1.1, CHECK журнала, строка миграции 0004);
  тесты: `backend/tests/db/test_r11_models.py`, `backend/tests/db/test_migrations.py` (цикл
  upgrade → downgrade → upgrade с 0004, `alembic check`), `backend/tests/factories.py` (фабрики R1.1)
  (больше 3 файлов: декларации моделей и миграция неразделимы — модели без миграции ломают `alembic check`)
- **Зависит от:** T30
- **Описание:** Таблицы `project`, `project_member`, `task`, `label`, `task_label`, `comment`,
  `mention`, `attachment` ровно по plan §4.3 R1.1 с уточнениями: миксины `UUIDPkMixin`,
  `TimestampMixin`, `WorkspaceMixin` у всех (у `project_member` и `task_label` — составной PK
  вместо `id`); `AuthoredMixin` — `project`, `project_member`, `label`, `comment`, `attachment`,
  у `task` `created_by NOT NULL`; `SoftDeleteMixin` — `project`, `task`, `comment`, `attachment`.
  `ProjectStatus` (`active`, `archived`), `TaskStatus` (`todo`, `in_progress`, `review`, `done`),
  `TaskPriority` (`base`, `high`) — `StrEnum` в моделях, в БД `text` + CHECK (D-3).
  `description` проекта и задачи — `text NOT NULL` (пустая строка по умолчанию задаётся
  приложением). CHECK по `char_length`: название проекта и задачи 1–255 (и `varchar(255)`),
  описание ≤ 10 000, метка 1–50, текст комментария 1–10 000; `attachment.size_bytes >= 0`;
  `task`: `CHECK ((parent_id IS NULL) = (position IS NOT NULL))`. FK: `task.project_id` и
  `task.parent_id` — `CASCADE`, `task_label`, `comment.task_id`, `mention.comment_id`,
  `attachment.task_id`, `project_member.project_id` — `CASCADE`; все FK на `app_user`
  (`owner_id`, `assignee_id`, `user_id`, `created_by`) — `RESTRICT`; все `DEFERRABLE INITIALLY
  IMMEDIATE` (D-26). `mention`: `id`, `workspace_id`, `comment_id`, `user_id`, `is_read`,
  `created_at`, `updated_at`; `UNIQUE(comment_id, user_id)`, индекс `(user_id, is_read)`.
  `label`: уникальный индекс `(workspace_id, lower(name))`. Индексы — plan §4.3 (частичные
  `WHERE deleted_at IS NULL` задаются в моделях через `postgresql_where`, GIN `gin_trgm_ops` по
  `project.name` и `task.title`), чтобы `alembic check` был чистым. Миграция: `CREATE EXTENSION IF
  NOT EXISTS pg_trgm`; `domain_event`: `CHECK ck_domain_event_entity_type_valid` (`entity_type IN`
  все 7 значений `EntityType`), то же `CheckConstraint` — в модели `DomainEvent`; `downgrade`
  удаляет таблицы R1.1 и CHECK журнала (расширение не удаляется).
- **Готово, когда:** `pytest -q backend/tests/db/test_r11_models.py backend/tests/db/test_migrations.py backend/tests/db/test_event_log.py` и
  `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёные, линтер чистый.
- **Попытки:** 0

## T34 — Объектные права и проверка получателей (чистые функции)
- **Статус:** SUPERSEDED → T70 (MVP: «свой проект» = владелец, без архива/вложений/`DEAL_RESPONSIBLE`)
- **AC:** FR-9, FR-10, FR-11, FR-14a, FR-14b, FR-14c (редакция рабочего дерева), FR-15, FR-15a, FR-16, FR-19, FR-19a, FR-19b, FR-20, FR-23, FR-24, FR-25a, FR-25b (право окончательного удаления = право восстановления), FR-68, FR-70, BR-1, BR-11; unit-уровень AC-9, AC-46, AC-47, AC-48, AC-52, AC-54, AC-73, AC-74, AC-99, AC-100, AC-103, AC-109, AC-110, AC-112; plan §4.5 (policy, recipients), D-45, §10.4, §10.6
- **Файлы:** `backend/app/domain/access/policy.py`, `backend/app/domain/access/recipients.py`;
  тесты: `backend/tests/unit/test_policy.py`, `backend/tests/unit/test_recipients.py`
- **Зависит от:** —
- **Описание:** Без БД. `ProjectFacts`, `TaskFacts`, функции plan §4.5 и `can_view_project`
  (D-45). Правила (роль — текущая, `actor.role`; ТА и «без роли» — везде `False`):
  `is_own_project` — БА: участник и (владелец или `actor_has_task`), СМ: участник;
  `can_read_project_content` — `BUSINESS_ACCESS` и участник; `can_view_project` — БА/СМ: да, П:
  участник; `can_edit_task_fully` — П: участник и автор = исполнитель = актор, БА:
  `is_own_project`, СМ: участник; `can_change_task_status` — `can_edit_task_fully` или (участник
  и исполнитель = актор); `can_create_task(a, p, assignee_id)` — участник и (исполнитель = актор
  или `TASK_ASSIGN_OTHERS`), где `assignee_id` уже разрешён сервисом (FR-20: у П «не передан» →
  актор, явный `null` остаётся `None` → `False`; у БА/СМ «не передан» → `None`);
  `can_create_subtask` — `can_edit_task_fully(parent)` или (участник, исполнитель родителя = актор
  и исполнитель подзадачи = актор); `can_change_assignee` — роль БА или СМ и `can_edit_task_fully`;
  `can_delete_task` = `can_edit_task_fully`; `can_delete_comment` — участник и (автор, или БА и
  `is_own_project`, или СМ); `can_edit_comment` — автор; `can_delete_attachment` — участник и
  (автор загрузки или `can_edit_task_fully`); `can_manage_project` и `can_manage_members` — (БА и
  владелец) или СМ (участие не требуется); `can_add_member(a, p, user_id)` —
  `can_manage_members` и не (БА и `user_id` = актор) (FR-15); `can_remove_self` — участник и не
  владелец. `recipients.check_recipient` — порядок plan §4.5; цели: `PROJECT_MEMBER` (роль
  БА/СМ/П), `TASK_ASSIGNEE` (БА/СМ/П + участник), `PROJECT_OWNER` (БА/СМ + участник),
  `DEAL_RESPONSIBLE` (БА/СМ; используется в R1.3); ошибки — `Unprocessable` с кодами
  `user_not_found`, `user_blocked`, `recipient_wrong_role`, `not_project_member`.
- **Готово, когда:** `pytest -q backend/tests/unit/test_policy.py backend/tests/unit/test_recipients.py` зелёный, линтер чистый.
- **Попытки:** 0

## T35 — Справочник пользователей и загрузка получателей; `GET /users`
- **Статус:** DONE
- **MVP-пересборка:** задача входит в MVP без изменений по смыслу; зависимость «T34» читать как
  **T70** (`RecipientFacts` и `recipients` — из T70); цель `DEAL_RESPONSIBLE` не нужна (plan §11.5).
- **AC:** FR-70 (факты получателя), FR-13, AC-21 (справочник — только своё пространство), AC-75 (без роли — 403, через обход маршрутов); plan §10.2 п.3, §10.3 (`GET /users`, общие схемы), §10.4 (`directory`)
- **Файлы:** `backend/app/domain/users/directory.py`, `backend/app/api/v1/users.py`,
  `backend/app/api/v1/schemas/common.py` (`UserRef`, `ProjectRef`) (+ подключение в
  `app/api/v1/__init__.py`, генерация контракта); тесты: `backend/tests/domain/test_directory.py`,
  `backend/tests/api/test_users_directory.py`
- **Зависит от:** T34
- **Описание:** `list_directory`: незаблокированные члены пространства с ролью БА/СМ/П, `q` —
  подстрока логина (`ILIKE` с экранированием `\ % _`, D-24), `ORDER BY login, id`, `paginate`;
  `password_hash` не читается (`load_only`). `load_recipient(db, workspace_id, user_id, *, lock)` →
  `RecipientFacts` (нет членства в пространстве → `in_workspace=False`); `lock=True` — строки
  `app_user` и `workspace_member` `FOR SHARE` (§10.2 п.3). `user_refs` — один запрос на набор id.
  Маршрут `GET /users` — router-level `require_capability(BUSINESS_ACCESS)` (ТА → 403).
- **Готово, когда:** `pytest -q backend/tests/domain/test_directory.py backend/tests/api/test_users_directory.py` и проверки контракта
  (общие условия) зелёные, линтер чистый.
- **Заметки ревью T35 (в T71/T72/T88):** (1) `list_directory` повторяет LIMIT+1/OFFSET из `core/pagination.paginate` (колонки из JOIN, не сущность): при втором потребителе (T71 `GET /projects/{id}/members` — строки `{user, role, is_blocked}`) завести `paginate_rows` с проверкой `ORDER BY` и использовать в обоих местах (AHA — после третьего повторения); (2) тело 422 для `q` содержит технический текст регулярки (`^[^\x00]*$`) — человекочитаемость через общий обработчик валидации, не в T35; (3) `ProjectRef` в `schemas/common.py` — задел для T72; (4) `q` ≤ 64 символов, без NUL; список и роль одним SELECT; Seq Scan по логину допустим (pg_trgm отложен, D-24/D-58).
- **Попытки:** 2

## T36 — Проекты: сервис и выборки
- **Статус:** SUPERSEDED → T71 (MVP: без архива, событий ленты)
- **AC:** AC-51, AC-52, AC-48 (удаление проекта: не владелец — 403, владелец — мягко), AC-55 (список без содержимого), AC-70 (архив и разархив: права; в архиве правка полей — 409, передача владения и удаление — разрешены), AC-71 (список: архивный — только с фильтром), AC-72, AC-108 (проект), AC-110, AC-65 (события владения и архива), FR-14, FR-14a, FR-14b, FR-14c, FR-16 (мягкое удаление с каскадом), FR-17, FR-41; plan D-43, D-45, D-46, D-52, §10.2, §10.3–§10.5
- **Файлы:** `backend/app/domain/projects/service.py`, `backend/app/domain/projects/queries.py`;
  тесты: `backend/tests/domain/test_projects_service.py`
- **Зависит от:** T30, T33, T34, T35
- **Описание:** Сигнатуры — plan §10.4. `load_project_facts` одним запросом (проект, членство
  актора, `actor_has_task` по неудалённым задачам и подзадачам), 404 для несуществующего,
  удалённого (кроме `include_deleted`) и чужого; `lock="update"|"share"` — §10.2. `create_project`:
  `PROJECT_CREATE`, владелец и участник — актор, статус `active`, событий нет (в каталоге нет).
  `update_project`: `can_manage_project` → 409 в архиве → изменение; `project.updated` с
  `changed_fields` только реально изменённых `name`/`description`, без `changes`; ничего не
  изменилось — без события (D-46). `set_archived`: `can_manage_project`; повтор — без события;
  `project.archived`/`unarchived` с `changed_fields=["status"]`. `transfer_ownership`:
  `can_manage_project` → получатель `PROJECT_OWNER` (БА/СМ, участник, активен) → 
  `project.ownership_transferred` с `changes` `owner_id: {id, login}` старый/новый; текущему
  владельцу — без события; в архиве разрешено. `delete_project`: `can_manage_project`, в архиве
  разрешено, каскад D-43 (проект, его задачи и подзадачи, их комментарии и вложения — один
  `deleted_batch_id`, одно `deleted_at`), событий нет. `list_projects`: БА/СМ — все
  неудалённые, П — где участник; `status` (`active` по умолчанию / `archived` / `all`);
  `task_count` — неудалённые задачи верхнего уровня; `ORDER BY lower(name), id`. `get_project` —
  `can_view_project` (403), `permissions` — из policy.
- **Готово, когда:** `pytest -q backend/tests/domain/test_projects_service.py` зелёный, линтер чистый.
- **Попытки:** 0

## T37 — Участники проекта: сервис
- **Статус:** SUPERSEDED → T71 (MVP: объединена с сервисом проектов, без событий ленты)
- **AC:** AC-50 (исключённый теряет доступ, его задачи остаются без исполнителя), AC-53, AC-54, AC-73, AC-74 (участник: ТА, заблокированный, без роли → 422; снятие роли участника не исключает), AC-70 (добавление участника в архиве — 409), FR-15, FR-15a, FR-38 (`member.*`, `task.unassigned_member_removed`); plan D-46, D-47 (**Q-7**), §10.2, §10.5
- **Файлы:** `backend/app/domain/projects/members.py`; тесты: `backend/tests/domain/test_project_members_service.py`
- **Зависит от:** T36
- **Описание:** `add_member`: проект `FOR NO KEY UPDATE` → `can_add_member` (403; БА-владелец
  добавляет себя — 403, FR-15) → 409 в архиве → `load_recipient(lock=True)` + `check_recipient(PROJECT_MEMBER)`
  (422) → уже участник — ничего (D-46) → вставка + `member.added` (`entity_id` = пользователь,
  `project_id`). `remove_member`: блокировка проекта → цель не участник — 404 → право
  (`can_manage_members` или `can_remove_self`, если цель = актор) → 409 в архиве → цель —
  владелец → 422 `owner_cannot_be_removed` («сначала передайте владение») → снять исполнителя у
  всех задач проекта, где цель — исполнитель (включая подзадачи и мягко удалённые, D-47) →
  `task.unassigned_member_removed` на каждую неудалённую (`changed_fields=["assignee_id"]`,
  `changes` `{id, login}` → `null`) → удалить членство → `member.removed`. `list_members` —
  `can_view_project`, `ORDER BY login, id`. Конкурентный сценарий (≥ 100 итераций, без 500 и без
  исполнителя-неучастника): исключение участника параллельно с назначением его исполнителем.
- **Готово, когда:** `pytest -q backend/tests/domain/test_project_members_service.py` зелёный, линтер чистый.
- **Попытки:** 0

## T38 — API проектов и участников
- **Статус:** SUPERSEDED → T72
- **AC:** AC-51, AC-52, AC-53, AC-54, AC-55 (список; задачи чужого проекта — T45), AC-70 (проектная часть), AC-71 (список проектов), AC-72, AC-73, AC-74 (участник, владелец), AC-75 (список проектов без роли — 403), AC-94 (ТА → проект с несуществующим id — 403), AC-108 (проект), AC-110, AC-65 (через API журнала: записи владения и архива с автором, временем, типом, id, действием, именами полей; без названий и значений), AC-21; FR-14…FR-17, FR-45a; plan §4.5, §10.3 (проекты, участники), D-52
- **Файлы:** `backend/app/api/v1/projects.py`, `backend/app/api/v1/schemas/projects.py` (+
  `app/api/v1/__init__.py`, генерация контракта); тесты: `backend/tests/api/test_projects.py`,
  `backend/tests/api/test_project_members.py`, `backend/tests/api/test_project_archive.py`
  (проектная часть), `backend/tests/api/test_not_found_vs_forbidden.py` (новый; ТА → проект),
  `backend/tests/api/test_workspace_isolation.py` и `backend/tests/api/test_audit.py` (дополнения)
- **Зависит от:** T36, T37
- **Описание:** Маршруты проектов и участников plan §10.3; router-level
  `require_capability(BUSINESS_ACCESS)`, у `POST /projects` дополнительно `PROJECT_CREATE` (П →
  403). Схемы: `ProjectCreate {name: str (1–255), description: str (≤ 10 000) = ""}`,
  `ProjectPatch` (оба необязательны), `OwnerChange {user_id}`, `MemberAdd {user_id}`,
  `ProjectListQuery(PageParams) {status}`; название из одних пробелов — 422 (D-52); ответы —
  `ProjectDetail`, `ProjectListItem`, `ProjectMember`. Ответы об ошибках объявлены по таблице §10.3.
- **Готово, когда:** `pytest -q backend/tests/api/test_projects.py backend/tests/api/test_project_members.py backend/tests/api/test_project_archive.py backend/tests/api/test_not_found_vs_forbidden.py backend/tests/api/test_workspace_isolation.py backend/tests/api/test_audit.py`
  и проверки контракта зелёные, линтер чистый.
- **Попытки:** 0

### Backend: задачи и метки

## T39 — Позиции карточек и прогресс
- **Статус:** SUPERSEDED → T73 (MVP: + `move_task` из R1.2; без `place_after`)
- **AC:** FR-28a (новая задача — в конец первой колонки; смена статуса без соседей — в конец целевой; перенумерация шагом 1024), AC-81 и AC-61 (часть «новая задача последняя») — уровень домена, AC-118 (помощник `place_after`), FR-22 и AC-7 (функция прогресса); plan §4.8, D-22, §10.2 п.4, §10.4
- **Файлы:** `backend/app/domain/tasks/positions.py`, `backend/app/domain/tasks/progress.py`;
  тесты: `backend/tests/db/test_positions.py`, `backend/tests/unit/test_progress.py`
- **Зависит от:** T33
- **Описание:** `STEP = 1024`. `lock_columns(db, project_id, *statuses)` — уникальные статусы в
  отсортированном порядке, `pg_advisory_xact_lock(hashtext(:key))` с ключом
  `f"{project_id}:{status}"` (одноключевая форма). `append_position` — `max(position) + STEP` по
  неудалённым задачам верхнего уровня колонки или `STEP`. `renumber_column` — `STEP, 2·STEP, …` по
  `(position, created_at, id)` неудалённых задач верхнего уровня. `place_after(db, project_id,
  status, occupied_position)` — позиция между занимающей задачей и её следующим соседом
  (`(low + high) // 2`), без соседа — `occupied + STEP`, промежуток < 2 — `renumber_column` и
  повторный расчёт; вызывается до снятия `deleted_at` с восстанавливаемой задачи. `move_task` —
  R1.2, в этой задаче не реализуется. `progress(done, total)` — `None` при `total == 0`, иначе
  `done * 100 // total` (AC-7: 1 из 3 → 33).
- **Готово, когда:** `pytest -q backend/tests/db/test_positions.py backend/tests/unit/test_progress.py` зелёный, линтер чистый.
- **Попытки:** 0

## T40 — Метки: сервис и API
- **Статус:** SKIPPED (следующая версия) — метки отложены (plan §11, SC-7)
- **AC:** AC-69, AC-57 (удаление метки снимает её со всех задач, прочие поля задач не меняются; несуществующая и 11-я метка — T41/T42), FR-18b, OI-100, AC-21; plan §10.3 (метки), §10.4 (`labels`), D-52
- **Файлы:** `backend/app/domain/labels/service.py`, `backend/app/api/v1/labels.py`,
  `backend/app/api/v1/schemas/labels.py` (+ `__init__`, генерация контракта);
  тесты: `backend/tests/domain/test_labels_service.py`, `backend/tests/api/test_labels.py`
- **Зависит от:** T33, T35
- **Описание:** `GET /labels` — `BUSINESS_ACCESS`; создание, переименование, удаление — гейт
  маршрута `LABELS_MANAGE` (П → 403, ТА → 403 гейтом раздела). Уникальность без учёта регистра:
  проверка перед записью и перехват нарушения уникального индекса (гонка) → 422
  `label_name_taken`; переименование метки в то же имя с другим регистром — разрешено.
  Удаление — жёсткое (`task_label` уходит каскадом), `task.updated_at` не меняется, событий нет
  (в каталоге нет). `resolve_labels(db, workspace_id, label_ids)` — повторы убираются; > 10 → 422
  `too_many_labels`; любой отсутствующий в пространстве → 422 `label_not_found`.
- **Готово, когда:** `pytest -q backend/tests/domain/test_labels_service.py backend/tests/api/test_labels.py` и проверки контракта зелёные, линтер чистый.
- **Попытки:** 0

## T41 — Задачи: создание задачи и подзадачи
- **Статус:** SUPERSEDED → T74 (MVP: без меток, архива, событий ленты)
- **AC:** AC-8 (подзадача у подзадачи — 422), AC-9, AC-24 (новая — «К выполнению»), AC-47 (подзадача себе — да, другому — 403), AC-49 (приоритет по умолчанию «Базовый»), AC-56, AC-57 (метки при создании), AC-61 (часть: новая задача — последняя в первой колонке), AC-74 (исполнитель), AC-106, AC-108 (задача), AC-109, FR-18…FR-21, FR-28a; plan §4.5 (FR-20), §4.8, §10.2, §10.4 (`context`, `create_*`), §10.5 (`task.created`)
- **Файлы:** `backend/app/domain/tasks/context.py`, `backend/app/domain/tasks/service.py`;
  тесты: `backend/tests/domain/test_tasks_create.py`
- **Зависит от:** T36, T39, T40
- **Описание:** `load_task_context` (plan §10.4): задача и факты проекта, 404 для
  несуществующей, удалённой (если не `include_deleted`), чужой и задачи удалённого проекта;
  `lock_project="share"` — §10.2 п.2. `TaskCreateData {title, description, assignee, due_date,
  priority, label_ids}`, где `assignee: UUID | None | Unset` (сентинел `UNSET` в `service.py`).
  Разрешение исполнителя (FR-20): «не передан» → П: актор, БА/СМ: `None`; явный `None` — как
  есть. `create_task`: проект (404) → `FOR SHARE` → `can_create_task` (403; П с явным `null` — 403)
  → 409 в архиве → получатель `TASK_ASSIGNEE` при исполнителе (422) → `resolve_labels` (422) →
  вставка (`todo`, приоритет по умолчанию `base`, `lock_columns` + `append_position(todo)`) →
  `task_label` → `task.created` (`project_id`). `create_subtask`: родитель (404) → права
  `can_create_subtask` (403) → 409 → родитель — подзадача → 422 `subtask_depth_exceeded` →
  получатель → метки → вставка (`position = NULL`) → `task.created`.
- **Готово, когда:** `pytest -q backend/tests/domain/test_tasks_create.py` зелёный, линтер чистый.
- **Попытки:** 0

## T42 — Задачи: изменение и удаление
- **Статус:** SUPERSEDED → T75 (MVP: без меток, архива, событий ленты)
- **AC:** AC-7 (родитель закрывается при незакрытых подзадачах), AC-42, AC-43 (кроме «находится фильтром» — R1.2), AC-46, AC-47, AC-48, AC-50 (переназначение после исключения), AC-57 (несуществующая и 11-я метка), AC-81, AC-99 (права удаления, каскад), AC-103 (задачи), AC-70 (изменение и удаление в архиве — 409), FR-19…FR-20, FR-25a, FR-28a, FR-38; plan D-43, D-46, §4.4 (`task.updated`), §10.2, §10.5
- **Файлы:** `backend/app/domain/tasks/service.py` (`update_task`, `delete_task`); тесты: `backend/tests/domain/test_tasks_update_delete.py`
- **Зависит от:** T41
- **Описание:** `update_task(db, actor, task_id, patch)`: контекст (404, `FOR SHARE` проекта) →
  набор реально меняющихся полей (значение отличается от текущего; D-46) → права по полям:
  `status` — `can_change_task_status`, `assignee_id` — `can_change_assignee`, остальные
  (`title`, `description`, `due_date`, `priority`, `label_ids`) — `can_edit_task_fully`; любое
  запрещённое — 403, ничего не меняется → 409 в архиве → новый исполнитель — `TASK_ASSIGNEE` (422;
  `null` допустим для БА/СМ) → `resolve_labels` → смена статуса задачи верхнего уровня:
  `lock_columns(старый, новый)` и `append_position(новый)` (FR-28a, AC-81) → `task.updated` одной
  строкой, если изменилось что-то из `status`, `assignee_id`, `due_date`, `title`, `description`:
  `changed_fields` — эти имена, `changes` — только `status`, `assignee_id` (`{id, login}` или
  `null`), `due_date` (`YYYY-MM-DD` или `null`). `delete_task`: `can_delete_task` (403) → 409 →
  каскад D-43 (задача, её подзадачи, комментарии и вложения задачи и подзадач — один пакет) →
  `task.deleted`. Конкурентный сценарий: параллельные смены статуса в одну колонку (≥ 100) —
  позиции неудалённых задач колонки уникальны, без 500.
- **Готово, когда:** `pytest -q backend/tests/domain/test_tasks_update_delete.py` зелёный, линтер чистый.
- **Попытки:** 0

## T43 — Задачи: карточка и списки (выборки)
- **Статус:** SUPERSEDED → T76 (MVP: + фильтры исполнитель/статус; без меток, вложений, архива)
- **AC:** AC-6 (личный список), AC-7 (прогресс в карточке), AC-11 (не участник → 403), AC-71 (личный список: архивные — по фильтру), AC-80 (подзадачи в списках; число задач проекта — T36), FR-17, FR-22, FR-26, FR-27 (без фильтров — R1.2), FR-47; plan §10.3 (`TaskDetail`, `TaskListItem`), §10.4 (`queries`)
- **Файлы:** `backend/app/domain/tasks/queries.py`; тесты: `backend/tests/domain/test_tasks_queries.py`
- **Зависит от:** T39, T41
- **Описание:** `get_task`: контекст (404) → `can_read_project_content` (403) → метки,
  неудалённые подзадачи (`ORDER BY created_at, id`), `progress` по неудалённым подзадачам,
  неудалённые вложения (метаданные), `UserRef` автора и исполнителей (`user_refs`, один запрос),
  `permissions` из policy; число SQL-запросов не зависит от числа подзадач и вложений.
  `list_project_tasks`: участник (403), неудалённые задачи и подзадачи, `ORDER BY created_at DESC,
  id DESC`, `paginate`. `list_my_tasks`: исполнитель = актор, неудалённые задача и проект, актор —
  участник, фильтр `project_status` (по умолчанию `active`), `ORDER BY due_date ASC NULLS LAST, id`.
- **Готово, когда:** `pytest -q backend/tests/domain/test_tasks_queries.py` зелёный, линтер чистый.
- **Попытки:** 0

## T44 — API карточки задачи и подзадач
- **Статус:** SUPERSEDED → T77 (объединена с T45)
- **AC:** AC-7, AC-8, AC-9, AC-11, AC-24, AC-42, AC-43 (кроме фильтра — R1.2), AC-46, AC-47, AC-48, AC-49, AC-56, AC-57, AC-68 (формат срока: `2026-10-20` сохраняется и возвращается как есть; `2026-10-20T10:00:00Z`, `2026-02-30` → 422), AC-70 (задачи: создание, изменение, удаление в архиве — 409; чтение — 200), AC-74 (исполнитель), AC-81, AC-94 (несуществующая и мягко удалённая задача — 404), AC-103, AC-106, AC-108 (задача), AC-109, AC-21; plan §10.3 (задачи), D-51, D-52
- **Файлы:** `backend/app/api/v1/tasks.py`, `backend/app/api/v1/schemas/tasks.py` (+ `__init__`, генерация контракта);
  тесты: `backend/tests/api/test_tasks.py`, `backend/tests/api/test_subtasks.py`,
  `backend/tests/api/test_task_permissions.py`, `backend/tests/api/test_reassign_blocked.py`,
  `backend/tests/api/test_recipients.py`, дополнения `test_project_archive.py`,
  `test_not_found_vs_forbidden.py`, `test_workspace_isolation.py`
- **Зависит от:** T38, T42, T43
- **Описание:** Маршруты `POST /projects/{id}/tasks`, `GET|PATCH|DELETE /tasks/{id}`,
  `POST /tasks/{id}/subtasks` (plan §10.3). `DueDate` — D-51; названия — D-52; `TaskStatus`,
  `TaskPriority` — перечисления в схеме (значение вне набора → 422); «исполнитель не передан» и
  «передан `null`» различаются по `model_fields_set` и передаются в сервис как `UNSET`/`None`.
  Ответ — `TaskDetail` из `get_task`.
- **Готово, когда:** `pytest -q backend/tests/api/test_tasks.py backend/tests/api/test_subtasks.py backend/tests/api/test_task_permissions.py backend/tests/api/test_reassign_blocked.py backend/tests/api/test_recipients.py backend/tests/api/test_project_archive.py backend/tests/api/test_not_found_vs_forbidden.py backend/tests/api/test_workspace_isolation.py`
  и проверки контракта зелёные, линтер чистый.
- **Попытки:** 0

## T45 — API списков задач: задачи проекта и личный список
- **Статус:** SUPERSEDED → T77 (объединена с T44)
- **AC:** AC-6, AC-55 (БА запрашивает задачи проекта, где не участвует, — 403), AC-71 (личный список без фильтра — без задач архивного проекта, с фильтром — с ними), AC-75 (`/me/tasks` без роли — 403), AC-80 (подзадача в списке проекта и в личном списке исполнителя), AC-18 (удалённые задачи не в списках), AC-21; FR-26, FR-27 (без фильтров), FR-47; plan §10.3
- **Файлы:** `backend/app/api/v1/tasks.py` (маршруты `GET /projects/{id}/tasks`, `GET /me/tasks`),
  `backend/app/api/v1/schemas/tasks.py` (`TaskListItem`, параметры запроса) (+ генерация контракта);
  тесты: `backend/tests/api/test_personal_tasks.py`, `backend/tests/api/test_project_task_list.py`
- **Зависит от:** T44
- **Описание:** Тонкие маршруты над `list_project_tasks` и `list_my_tasks` (T43), `Page[TaskListItem]`,
  `project_status` — `active` по умолчанию.
- **Готово, когда:** `pytest -q backend/tests/api/test_personal_tasks.py backend/tests/api/test_project_task_list.py` и проверки контракта зелёные, линтер чистый.
- **Попытки:** 0

### Backend: комментарии и упоминания

## T46 — Комментарии: очистка HTML и разбор упоминаний (чистые функции)
- **Статус:** SUPERSEDED → T79 (`strip_html`); разбор упоминаний — SKIPPED (следующая версия)
- **AC:** AC-58 (HTML вырезается — unit), AC-116 (`@Ivan.Petrov` распознаётся как `ivan.petrov` — unit), FR-23, FR-71, FR-73; plan D-28, D-39, D-48 (**Q-4**)
- **Файлы:** `backend/app/domain/comments/sanitize.py`, `backend/app/domain/comments/mentions.py`
  (только `MENTION_RE` и `extract_mention_candidates`); тесты: `backend/tests/unit/test_sanitize.py`,
  `backend/tests/unit/test_mention_parse.py`
- **Зависит от:** —
- **Описание:** `strip_html(text)` на `html.parser.HTMLParser` с `convert_charrefs=False`: теги
  (открывающие, закрывающие, самозакрывающиеся), комментарии, декларации и инструкции удаляются;
  содержимое `script`/`style` (включая незакрытые) удаляется; ссылки на сущности (`&lt;`, `&#60;`)
  и прочий текст сохраняются как есть (markdown-цитаты `>` и `a < b` не портятся).
  `extract_mention_candidates(text) -> list[tuple[str, ...]]` — по D-48: на каждое упоминание
  кортеж «токен в нижнем регистре, затем его укорочения без хвостовых `.`/`_`/`-` (длина ≥ 3)»,
  порядок появления, повторы убраны; `e-mail@example.com` упоминанием не считается.
- **Готово, когда:** `pytest -q backend/tests/unit/test_sanitize.py backend/tests/unit/test_mention_parse.py` зелёный, линтер чистый.
- **Попытки:** 0

## T47 — Комментарии и упоминания: сервис
- **Статус:** SUPERSEDED → T79 (комментарии); упоминания — SKIPPED (следующая версия)
- **AC:** AC-58 (HTML не сохраняется; чужой комментарий П править/удалять — 403; время правки и «изменён»; удалённый — заглушка с автором и временем; БА удаляет чужой в своём проекте), AC-102, AC-103 (комментарии), AC-116 (упоминание), AC-70 (комментарий в архиве — 409), FR-23, FR-38 (`comment.*`), FR-71; plan D-48, §4.3 (видимость упоминаний), §10.2, §10.4, §10.5
- **Файлы:** `backend/app/domain/comments/service.py`, `backend/app/domain/comments/mentions.py`
  (`sync_mentions`, `list_mentions`, `unread_count`, `mark_read`); тесты:
  `backend/tests/domain/test_comments_service.py`, `backend/tests/domain/test_mentions_service.py`
- **Зависит от:** T30, T41, T46
- **Описание:** `create_comment`: контекст задачи (404, `FOR SHARE` проекта) → участник (403) → 409
  → `strip_html`; пусто или одни пробелы после очистки → 422 `validation_error` → вставка →
  `sync_mentions` (участники проекта, чей логин совпал с первым подходящим вариантом кандидата;
  `ON CONFLICT DO NOTHING`) → `comment.created` (`project_id`). `edit_comment`: неудалённый
  комментарий (404) → участник и автор (403) → 409 → очистка → `body`, `edited_at = now` →
  `sync_mentions` (только новые; убранные правкой не снимаются — D-48, Q-4). `delete_comment`:
  `can_delete_comment` (403) → 409 → мягкое удаление (свой `deleted_batch_id`) → `comment.deleted`.
  `list_comments`: участник (403), все комментарии задачи включая удалённые (`body = None`),
  `ORDER BY created_at, id`. Упоминание видно, пока комментарий, задача и проект не удалены и
  получатель — участник проекта; `list_mentions` (`unread_only`), `unread_count`, `mark_read`
  (не своё или невидимое — 404; повтор — без ошибки). Восстановление комментария возвращает
  упоминания без изменения таблицы `mention` (T52).
- **Готово, когда:** `pytest -q backend/tests/domain/test_comments_service.py backend/tests/domain/test_mentions_service.py` зелёный, линтер чистый.
- **Попытки:** 0

## T48 — API комментариев и упоминаний
- **Статус:** SUPERSEDED → T80 (комментарии); упоминания — SKIPPED (следующая версия)
- **AC:** AC-58, AC-102, AC-103 (комментарии), AC-116 (упоминание), AC-70 (комментарий в архиве — 409), AC-75 (`/mentions` без роли — 403, обход маршрутов), AC-21; FR-23, FR-29 (счётчик для опроса), FR-71; plan §10.3
- **Файлы:** `backend/app/api/v1/comments.py`, `backend/app/api/v1/mentions.py`,
  `backend/app/api/v1/schemas/comments.py` (+ `__init__`, генерация контракта);
  тесты: `backend/tests/api/test_comments.py`, `backend/tests/api/test_mentions.py`,
  `backend/tests/api/test_workspace_isolation.py` (дополнение)
- **Зависит от:** T44, T47
- **Описание:** Маршруты plan §10.3: `GET|POST /tasks/{id}/comments`, `PATCH|DELETE /comments/{id}`,
  `GET /mentions`, `GET /mentions/unread-count`, `POST /mentions/{id}/read`. Тело — `{body: str}`,
  1–10 000 символов до очистки (иначе 422).
- **Готово, когда:** `pytest -q backend/tests/api/test_comments.py backend/tests/api/test_mentions.py backend/tests/api/test_workspace_isolation.py` и проверки контракта зелёные, линтер чистый.
- **Попытки:** 0

### Backend: вложения

## T49 — Определение типа вложения
- **Статус:** SKIPPED (следующая версия) — вложения отложены (SC-5)
- **AC:** AC-59 (`.exe`, переименованный в `.pdf`; zip с исполняемым файлом), AC-117 (вложенность до уровня 3 — проверяется; уровень 4, зашифрованный и повреждённый элемент — отказ), FR-24, C-7; plan D-27, §4.11
- **Файлы:** `backend/app/domain/attachments/filetype.py`; тесты: `backend/tests/unit/test_filetype.py`
  (образцы собираются в тесте из байтов и `zipfile`; бинарных файлов в репозитории нет)
- **Зависит от:** —
- **Описание:** Ровно по plan §4.11: `DetectedType`, `RejectedFile(reason)`, `EXTENSION_KINDS`,
  `detect(path, original_name)`. Расширение — по последней точке, без учёта регистра; файл без
  расширения или с расширением вне `EXTENSION_KINDS` → `not_allowed`. Загружаемый архив — уровень
  1, проверяются уровни 1–3; ZIP на уровне 4, зашифрованный (`flag_bits & 0x1`) или повреждённый
  элемент, превышение бюджета распаковки 100 МБ → `unverifiable_archive`.
- **Готово, когда:** `pytest -q backend/tests/unit/test_filetype.py` зелёный, линтер чистый.
- **Попытки:** 0

## T50 — Вложения: хранилище и сервис
- **Статус:** SKIPPED (следующая версия) — вложения отложены (SC-5)
- **AC:** AC-16 (10 485 760 байт — сохранён, больше — 413, файл не сохранён), AC-59 (21-й — 422; `../../etc/passwd` — имя сохранено как есть, вне каталога вложений ничего не создано; не участник — 403), AC-100, AC-117 (через сервис), AC-70 (загрузка и удаление в архиве — 409, скачивание — разрешено), FR-24, FR-38 (`attachment.*`); plan §4.11, D-49, §10.2, §10.4
- **Файлы:** `backend/app/domain/attachments/storage.py`, `backend/app/domain/attachments/service.py`;
  тесты: `backend/tests/domain/test_attachments_service.py`, `backend/tests/unit/test_attachment_storage.py`
- **Зависит от:** T41, T49
- **Описание:** `AttachmentStorage(settings.attachments_dir)`: каталоги `tmp/` и
  `<workspace_id>/<key[:2]>/` создаются с правами 0700, файлы — 0600; исходное имя в путь не
  попадает. `receive` читает `UploadFile` кусками по 64 КиБ во `tmp/<uuid>`, считает размер и
  sha256; размер > `attachment_max_bytes` → временный файл удаляется, `PayloadTooLarge` (413).
  `upload`: контекст задачи (404, `FOR SHARE`) → участник (403) → 409 → неудалённых вложений
  задачи ≥ `attachments_per_task` → 422 `too_many_attachments` → `receive` (413) → `detect`
  (`RejectedFile` → 422 `attachment_type_not_allowed`) → `promote` (rename) → строка
  `attachment` (`original_name` как передано, пустое или длиннее 255 → 422) → хук `after_rollback`
  удаляет итоговый файл (D-49) → `attachment.created`. `open_content`: неудалённые вложение,
  задача, проект (404) → участник (403; в архиве — разрешено) → путь, тип, исходное имя.
  `delete_attachment`: `can_delete_attachment` (403) → 409 → мягкое удаление → `attachment.deleted`.
  `orphans(...)` — для T54.
- **Готово, когда:** `pytest -q backend/tests/domain/test_attachments_service.py backend/tests/unit/test_attachment_storage.py` зелёный, линтер чистый.
- **Попытки:** 0

## T51 — API вложений, зависимость `python-multipart`, 413 через прокси
- **Статус:** SKIPPED (следующая версия) — вложения отложены (SC-5)
- **AC:** AC-16, AC-59, AC-100, AC-117, AC-70 (вложения: загрузка — 409, скачивание — 200), AC-21; FR-9 (413), FR-24, FR-45; plan §4.11, §7.1 (`python-multipart>=0.0.20,<0.1`), §10.3
- **Файлы:** `backend/app/api/v1/attachments.py`, `backend/app/api/v1/schemas/attachments.py`,
  `backend/pyproject.toml` (+ `__init__`, генерация контракта); тесты: `backend/tests/api/test_attachments.py`,
  `backend/tests/infra/test_stack_attachments.py` (`infra_stack`: через HTTPS-вход файл ровно
  10 485 760 байт — 201, 11 МБ — 413 JSON `attachment_too_large`; скачивание —
  `Content-Disposition: attachment; filename*=UTF-8''…` и `X-Content-Type-Options: nosniff`)
- **Зависит от:** T44, T50
- **Описание:** `POST /tasks/{id}/attachments` (multipart, поле `file`), `GET /attachments/{id}/content`
  (`FileResponse`, имя — `filename*=UTF-8''` + `urllib.parse.quote(name, safe="")`),
  `DELETE /attachments/{id}`. Зависимость добавить в `[project].dependencies`, затем
  `pip install -e "backend[dev]"`; образ api пересобирается при `--build`.
- **Готово, когда:** `pytest -q backend/tests/api/test_attachments.py` и проверки контракта зелёные; `infra_stack`
  (общие условия) для `backend/tests/infra/test_stack_attachments.py` зелёный; линтер чистый.
- **Попытки:** 0

### Backend: корзина, обслуживание, лента, поиск

## T52 — Корзина: сервис, восстановление, окончательное удаление
- **Статус:** SKIPPED (следующая версия) — корзина отложена (SC-4)
- **AC:** AC-18 (удалённое — в корзине, запись с `deleted_at`), AC-62, AC-99, AC-112, AC-118, AC-66 (окончательное удаление не меняет журнал), FR-16 (восстановление проекта), FR-25, FR-25a, FR-25b (кнопка), FR-71 (восстановление комментария возвращает упоминания); plan §4.10, §10.6, D-25, D-43, D-49, D-50 (**Q-2**)
- **Файлы:** `backend/app/domain/trash/service.py`, `backend/app/domain/trash/purge.py`;
  тесты: `backend/tests/domain/test_trash_service.py`
- **Зависит от:** T36, T39, T42, T47, T50
- **Описание:** По plan §10.6. `list_trash`: `UNION ALL` по типам с SQL-предикатами прав,
  эквивалентными `policy` (тест: для каждой роли множество строк корзины = множество объектов,
  для которых `restore` разрешён); ТА и роли без `BUSINESS_ACCESS` — пустой результат без
  обращения к бизнес-таблицам; фильтры `project_id` (D-44, **Q-3**) и `type`; `ORDER BY
  deleted_at DESC, id`. `restore`: удалённый объект пространства (404) → право (403) → 409 по
  D-50 → 422 (`project_deleted`, `parent_task_deleted`) → снятие `deleted_at`/`deleted_batch_id` со
  строк пакета; задача верхнего уровня на занятой позиции — `place_after` (AC-118);
  `task.restored` — только для задачи-корня. `purge.purge(...)`: собирает `(workspace_id,
  storage_key)` всех вложений, которые уйдут (включая вложения задач удаляемых проектов),
  затем `DELETE` (каскады FK); `domain_event` не трогает. `purge_one`: право (403) → 409 по D-50 →
  `purge` → удаление файлов хуком `after_commit` (D-49).
- **Готово, когда:** `pytest -q backend/tests/domain/test_trash_service.py` зелёный, линтер чистый.
- **Попытки:** 0

## T53 — API корзины
- **Статус:** SKIPPED (следующая версия) — корзина отложена (SC-4)
- **AC:** AC-18 (задача и проект не возвращаются в списках и счётчиках; поиск — T56; доска — R1.2), AC-62, AC-99 (корзина П — только своё; корзина ТА — пуста), AC-112, AC-118, AC-66 (кнопка: в журнале не меньше N записей, прежние не изменены), AC-21; FR-25a, FR-25b; plan §4.5 (исключение п.4 для `GET /trash`), §10.3 (корзина), D-44
- **Файлы:** `backend/app/api/v1/trash.py`, `backend/app/api/v1/schemas/trash.py` (+ `__init__`,
  генерация контракта); тесты: `backend/tests/api/test_trash.py`, `backend/tests/api/test_soft_delete.py`
- **Зависит от:** T45, T48, T51, T52
- **Описание:** `GET /trash` — только `get_active_actor` (ТА — 200 с пустой страницей);
  `POST /trash/{type}/{id}/restore` и `DELETE /trash/{type}/{id}` — `require_capability(BUSINESS_ACCESS)`
  на маршруте (ТА — 403 на любой id). `type` — `TrashType` (иное значение — 422).
- **Готово, когда:** `pytest -q backend/tests/api/test_trash.py backend/tests/api/test_soft_delete.py` и проверки контракта зелёные, линтер чистый.
- **Попытки:** 0

## T54 — Обслуживание: автоочистка корзины и файлы-сироты
- **Статус:** SKIPPED (следующая версия) — корзина и вложения отложены (SC-4, SC-5)
- **AC:** AC-63 *инфра*, AC-66 (команда обслуживания) *инфра*, FR-25b, FR-24 (файлы удаляются при окончательном удалении); plan §4.10 п.1 и п.3, D-42, D-49, §10.6
- **Файлы:** `backend/app/domain/ops/maintenance.py`; тесты: `backend/tests/cli/test_maintenance.py`
  (`@pytest.mark.committed`: AC-63 — задача с вложением, проект, комментарий и вложение в
  корзине 31 день удалены вместе с файлами, объекты 29 дней не тронуты; AC-66; `--dry-run` ничего
  не меняет и печатает те же счётчики), `backend/tests/infra/test_stack_maintenance.py`
  (`infra_stack`: `docker compose exec -T api gostracker maintenance --dry-run` — код 0, строки `ключ=число`)
- **Зависит от:** T31, T52
- **Описание:** Шаг «корзина»: по каждому пространству — идентификаторы проектов, задач,
  комментариев, вложений с `deleted_at <= now − trash_retention`, пачками ≤ 500 на транзакцию →
  `trash.purge.purge` → COMMIT → удаление файлов пачки; счётчики отчёта. Шаг «сироты»: файлы под
  `attachments/<workspace_id>/` без строки `attachment` с тем же `storage_key` и файлы `tmp/`
  старше 1 часа (по `mtime` файловой системы) — удаляются. `--dry-run` — только подсчёт. Снятие
  связи со сделкой (plan §4.10 п.1) и CRM-шаг — R1.3. Повторный запуск идемпотентен.
- **Готово, когда:** `pytest -q backend/tests/cli/test_maintenance.py` зелёный; `infra_stack` для
  `backend/tests/infra/test_stack_maintenance.py` зелёный; линтер чистый.
- **Попытки:** 0

## T55 — Лента проекта и признак «объект удалён»
- **Статус:** SKIPPED (следующая версия) — лента отложена (SC-8)
- **AC:** AC-90 (проект: создание задачи, смена статуса, исполнителя и срока, комментарий без текста, вложение, участник, владение, архив — по событию; правка названия — без старого и нового значения; не участник — 403; CRM-событий нет), FR-38, FR-25b (окончательно удалённый объект — «объект удалён» в ленте и журнале, без названия и значений), AC-65 (`entity_deleted`), AC-21; plan §4.4 (представления), §10.3 (`ActivityItem`), **Q-5**
- **Файлы:** `backend/app/domain/activity/service.py`, `backend/app/domain/events/queries.py`
  (`entity_deleted` для project/task/comment/attachment — один запрос на тип для страницы),
  `backend/app/api/v1/projects.py` (маршрут `GET /projects/{id}/activity`),
  `backend/app/api/v1/schemas/activity.py` (+ генерация контракта); тесты:
  `backend/tests/api/test_activity.py`, `backend/tests/api/test_audit.py` (дополнение)
- **Зависит от:** T38, T44, T48, T51, T52
- **Описание:** `project_feed`: неудалённый проект (404) → участник (403) → события
  `workspace_id`, `project_id`, `ORDER BY id DESC`, `paginate`; для страницы одним запросом на тип
  — существует ли объект и его текущее название (`entity.title` по §10.3); нет строки → `deleted =
  true`, `title = null`, `changes = null`. Журнал аудита: `entity_deleted` для R1.1-типов — нет
  строки объекта (мягко удалённый — не «удалён»).
- **Готово, когда:** `pytest -q backend/tests/api/test_activity.py backend/tests/api/test_audit.py` и проверки контракта зелёные, линтер чистый.
- **Попытки:** 0

## T56 — Поиск по задачам и проектам
- **Статус:** SKIPPED (следующая версия) — поиск отложен (SC-9)
- **AC:** AC-92 (задачи и проекты; «КП»/«кп»; 1 символ — 422; ≤ 20 задач из 25; П: только доступное, архивный проект входит, удалённая задача и задача чужого проекта — нет; клиенты и сделки — R1.3), AC-18 (удалённое не в поиске), AC-21; FR-39; plan §4.9, D-24
- **Файлы:** `backend/app/domain/search/service.py`, `backend/app/api/v1/search.py`,
  `backend/app/api/v1/schemas/search.py` (+ `__init__`, генерация контракта); тесты: `backend/tests/api/test_search.py`
- **Зависит от:** T38, T42
- **Описание:** `q.strip()` короче 2 символов → 422 `search_query_too_short` (в сервисе — ради кода),
  длиннее 255 → 422 `validation_error` (схема); экранирование `\ % _`, `ILIKE … ESCAPE '\'`;
  задачи — неудалённые в неудалённых проектах, где актор участник (архивные входят); проекты —
  БА/СМ: все неудалённые, П: где участник; `ORDER BY similarity(…, q) DESC, id`, `LIMIT 20`. Ключей
  CRM в ответе нет (R1.3).
- **Готово, когда:** `pytest -q backend/tests/api/test_search.py` и проверки контракта зелёные, линтер чистый.
- **Попытки:** 0

## T57 — Документация R1.1
- **Статус:** SUPERSEDED → T88
- **AC:** NFR-11 (модель данных, описание API), NFR-3; plan §3 (`docs/data-model.md` [1]), D-42, D-49
- **Файлы:** `docs/data-model.md` (каталог событий R1.1 с белыми списками, корзина и пакеты
  удаления, хранение файлов вложений), `README.md` (ru и en: состояние R1.1; вложения — 10 МБ,
  20 файлов, типы, хранение в томе `appdata`, бэкап вместе с томом; обслуживание и корзина 30 дней)
- **Зависит от:** T54, T55, T56
- **Готово, когда:** `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёный; ревьюер подтверждает
  соответствие plan §10 и существующие ссылки.
- **Попытки:** 0

### Фронтенд R1.1

## T58 — Фронтенд R1.1: навигация, маршруты, коды ошибок, выбор пользователя
- **Статус:** SUPERSEDED → T81
- **AC:** NFR-6, NFR-7 (видимый фокус, клавиатура), FR-45 (сообщения по кодам R1.1, включая `service_busy`), FR-10 (интерфейс скрывает недоступное по `/me.capabilities`; сервер проверяет сам); plan §4.14, §10.3; заметка T22 п.3 (коды R1.1 не уходят в `error.unknown`)
- **Файлы:** `frontend/src/app/router.tsx` (маршруты `/projects`, `/projects/:projectId`,
  `/tasks/:taskId`, `/my-tasks`, `/mentions`, `/trash`, `/search`, `/labels` под `SessionGate`;
  страницы-заглушки заменяют следующие задачи; меню по capabilities), `frontend/src/shared/i18n/ru.ts`,
  `frontend/src/shared/ui/UserPicker.tsx`, `frontend/src/features/users/api.ts`;
  тесты: `frontend/tests/app/navigation.test.tsx`, `frontend/tests/shared/UserPicker.test.tsx`,
  `frontend/tests/shared/i18n.test.ts` (все коды `ErrorCode` R1.1 и `service_busy` есть в словаре),
  `backend/tests/infra/test_frontend_scaffold.py` (список файлов `src`)
- **Зависит от:** T29, T35, T38
- **Описание:** `UserPicker` — поиск по `GET /users?q=` (клавиатура: стрелки, Enter, Esc;
  `aria-*` для списка), опционально ограничивает выбор переданным набором id (участники проекта).
  ТА видит в меню только администрирование; БА/СМ/П — проекты, мои задачи, упоминания, корзину,
  поиск; метки — при `labels_manage`.
- **Готово, когда:** фронтенд зелёный (общие условия).
- **Попытки:** 0

## T59 — Экраны проектов: список, создание, карточка, участники, архив, владение, удаление
- **Статус:** SUPERSEDED → T82 (без архива)
- **AC:** UF-3 (проект и участники), FR-14…FR-17 (интерфейс), FR-15a (подтверждение самоисключения), AC-51…AC-55, AC-70…AC-73, AC-110 (поведение интерфейса по ответам API); NFR-6, NFR-7
- **Файлы:** `frontend/src/features/projects/api.ts`, `frontend/src/features/projects/ProjectsPage.tsx`,
  `frontend/src/features/projects/ProjectPage.tsx` (+ маршруты в `router.tsx`);
  тесты: `frontend/tests/features/projects/ProjectsPage.test.tsx`, `frontend/tests/features/projects/ProjectPage.test.tsx`
- **Зависит от:** T58
- **Описание:** Список с фильтром статуса (активные / архивные / все) и пагинацией; создание (при
  `project_create`); карточка: правка названия и описания (`permissions.manage`), архив/разархив,
  передача владения (`UserPicker` по участникам), удаление с `ConfirmDialog`, участники
  (добавление через `UserPicker`, исключение, самоисключение с подтверждением); вкладки «Задачи»
  (T60) и «Лента» (T65) — места под них. Ошибки — по `code` (409 `project_archived`, 422 из каталога).
- **Готово, когда:** фронтенд зелёный.
- **Попытки:** 0

## T60 — Списки задач и создание задачи
- **Статус:** SUPERSEDED → T83 (без меток)
- **AC:** UF-3, UF-6 (список), FR-20 (П: поле исполнителя не отправляется — задача себе; «без исполнителя» — только БА/СМ), FR-26, FR-27 (без фильтров — R1.2), FR-29 (опрос списков), AC-6, AC-56, AC-109 (интерфейс); NFR-5 (срок — календарная дата без пересчёта пояса, ADR-0007), NFR-6, NFR-7
- **Файлы:** `frontend/src/features/tasks/api.ts`, `frontend/src/features/tasks/TaskList.tsx`
  (вкладка «Задачи» карточки проекта и страница `/my-tasks` с переключателем «задачи архивных
  проектов»), `frontend/src/features/tasks/CreateTaskForm.tsx`;
  тесты: `frontend/tests/features/tasks/TaskList.test.tsx`, `frontend/tests/features/tasks/CreateTaskForm.test.tsx`
- **Зависит от:** T45, T59
- **Описание:** Списки — `usePolledQuery`. Форма: название, описание, срок (`input type=date`,
  отправляется `YYYY-MM-DD`), приоритет, исполнитель (`UserPicker` по участникам проекта; для П
  поля нет), метки (выбор из `GET /labels`).
- **Готово, когда:** фронтенд зелёный.
- **Попытки:** 0

## T61 — Карточка задачи: поля, статус, исполнитель, метки, подзадачи, удаление
- **Статус:** SUPERSEDED → T84 (без меток)
- **AC:** UF-4, UF-6, FR-18…FR-22 (интерфейс; предупреждение при закрытии родителя с незакрытыми подзадачами, FR-22), FR-29 (опрос карточки), AC-7, AC-46, AC-47 (элементы по `permissions`); NFR-6, NFR-7
- **Файлы:** `frontend/src/features/tasks/TaskPage.tsx`, `frontend/src/features/tasks/SubtaskList.tsx`,
  `frontend/src/features/labels/LabelPicker.tsx` (+ функции в `features/tasks/api.ts`, `features/labels/api.ts`);
  тесты: `frontend/tests/features/tasks/TaskPage.test.tsx`, `frontend/tests/features/tasks/SubtaskList.test.tsx`
- **Зависит от:** T40, T44, T60
- **Описание:** Карточка — `usePolledQuery` (ввод пользователя при обновлении не теряется:
  форма правки — локальное состояние до сохранения). Подзадачи с прогрессом (`null` — «нет
  подзадач»), создание подзадачи; смена статуса; удаление с подтверждением; места под
  комментарии (T62) и вложения (T63).
- **Готово, когда:** фронтенд зелёный.
- **Попытки:** 0

## T62 — Комментарии и упоминания
- **Статус:** SUPERSEDED → T85 (комментарии простым текстом, без `react-markdown`); упоминания — SKIPPED (следующая версия)
- **AC:** UF-6 (комментарий), FR-23, FR-71, FR-29 (опрос счётчика упоминаний), AC-58, AC-102 (интерфейс: «изменён», «комментарий удалён»), D-28 (markdown без HTML); NFR-6, NFR-7
- **Файлы:** `frontend/src/features/comments/Comments.tsx` (+ `features/comments/api.ts`),
  `frontend/src/features/mentions/MentionsPage.tsx`, `frontend/src/features/mentions/MentionCounter.tsx`
  (+ `features/mentions/api.ts`), `frontend/package.json`, `frontend/package-lock.json` (`react-markdown ^10`, plan §7.2);
  тесты: `frontend/tests/features/comments/Comments.test.tsx`, `frontend/tests/features/mentions/MentionsPage.test.tsx`,
  `backend/tests/infra/test_frontend_scaffold.py` (зависимость и список файлов)
- **Зависит от:** T48, T61
- **Описание:** Текст — `react-markdown` с `skipHtml` (сырой HTML не исполняется и не
  отображается); правка и удаление — по `permissions`; удалённый — заглушка с автором и
  временем. `MentionCounter` в меню — `usePolledQuery(GET /mentions/unread-count)`; страница
  упоминаний — список, отметка «прочитано», переход к задаче.
- **Готово, когда:** `cd frontend && npm ci` успешен; фронтенд зелёный.
- **Попытки:** 0

## T63 — Вложения в карточке задачи
- **Статус:** SKIPPED (следующая версия) — вложения отложены (SC-5)
- **AC:** UF-6 (вложение), FR-24 (интерфейс: подсказка типов и 10 МБ; сообщения 413/422 по кодам), AC-16, AC-59, AC-100 (интерфейс); NFR-6, NFR-7
- **Файлы:** `frontend/src/features/attachments/Attachments.tsx`, `frontend/src/features/attachments/api.ts`,
  `frontend/src/shared/api/client.ts` (для `FormData` не ставить `Content-Type: application/json`);
  тесты: `frontend/tests/features/attachments/Attachments.test.tsx`, `frontend/tests/shared/client.test.ts` (дополнение)
- **Зависит от:** T51, T61
- **Описание:** Загрузка — через общий клиент (`openapi-fetch`, `bodySerializer` → `FormData`),
  без прямого `fetch`; скачивание — ссылка на `/api/v1/attachments/{id}/content`; удаление — по
  `permissions.delete`; исходное имя показывается как текст (без интерпретации пути).
- **Готово, когда:** фронтенд зелёный.
- **Попытки:** 0

## T64 — Корзина и управление метками
- **Статус:** SKIPPED (следующая версия) — корзина и метки отложены (SC-4, SC-7)
- **AC:** FR-25a, FR-25b (восстановление и окончательное удаление с подтверждением), FR-18b (экран меток для БА/СМ), AC-62, AC-69, AC-99, AC-112 (интерфейс); NFR-6, NFR-7
- **Файлы:** `frontend/src/features/trash/TrashPage.tsx` (+ `features/trash/api.ts`; фильтр по проекту — D-44),
  `frontend/src/features/labels/LabelsPage.tsx` (+ `features/labels/api.ts`);
  тесты: `frontend/tests/features/trash/TrashPage.test.tsx`, `frontend/tests/features/labels/LabelsPage.test.tsx`
- **Зависит от:** T40, T53, T58
- **Описание:** Корзина: тип, название, проект, дата удаления, срок окончательного удаления;
  `container_deleted` — восстановление недоступно с пояснением; ТА — пустой список. Метки:
  список, создание, переименование, удаление с подтверждением.
- **Готово, когда:** фронтенд зелёный.
- **Попытки:** 0

## T65 — Поиск и лента проекта
- **Статус:** SKIPPED (следующая версия) — поиск и лента отложены (SC-8, SC-9)
- **AC:** UF-9, UF-10, FR-38, FR-39, FR-29 (опрос ленты проекта), AC-90, AC-92 (интерфейс: «не короче 2 символов», «объект удалён»); NFR-5 (время — Europe/Moscow), NFR-6, NFR-7
- **Файлы:** `frontend/src/features/search/SearchPage.tsx` (+ `features/search/api.ts`),
  `frontend/src/features/projects/ActivityFeed.tsx` (вкладка «Лента» карточки проекта, `usePolledQuery`);
  тесты: `frontend/tests/features/search/SearchPage.test.tsx`, `frontend/tests/features/projects/ActivityFeed.test.tsx`
- **Зависит от:** T55, T56, T59
- **Готово, когда:** фронтенд зелёный.
- **Попытки:** 0

## T66 — Приёмка R1.1
- **Статус:** SUPERSEDED → T89 (приёмка MVP)
- **AC:** все AC plan §10.7; NFR-10
- **Файлы:** правок кода нет; вердикт ревьюера оркестратор сохраняет в
  `specs/001-pilot-r1/reviews/R1.1-acceptance.md`; дефекты оформляются задачами `T66a…`
- **Зависит от:** T29–T65
- **Описание:** Сверить трассировку plan §10.7 (каждый AC R1.1 — тест существует и зелёный;
  части других этапов помечены); `bash scripts/check.sh`; свежий стек `up -d --build --wait` и
  `infra_stack` целиком; на стеке — `gostracker maintenance --dry-run`; `alembic downgrade 0003` →
  `upgrade head` на тестовой БД; ручной прогон UF-3, UF-4, UF-6, UF-9, UF-10 в Chromium с
  клавиатуры (предварительная AC-97); статус вопросов Q-1…Q-9 и Д-1…Д-8.
- **Готово, когда:** `bash scripts/check.sh` и `infra_stack` зелёные; ревьюер подтверждает трассировку.
- **Попытки:** 0

### Порядок R1.1 и критический путь

> **SUPERSEDED (MVP-пересборка, 2026-10-15):** действующий порядок — «MVP-пересборка» → «Порядок
> MVP и критический путь» в конце файла. Таблица ниже сохранена для возврата отложенного.

| Задача | Название | Зависит от |
|---|---|---|
| T29 | 503 `service_busy` | — |
| T30 | Каталог событий R1.1 | — |
| T31 | Каркас обслуживания | — |
| T32 | Мелочи приёмки R1.0 | T31 |
| T33 | Модели и миграция 0004 | T30 |
| T34 | Политика прав и получатели | — |
| T35 | Справочник пользователей, `GET /users` | T34 |
| T36 | Проекты: сервис | T30, T33, T34, T35 |
| T37 | Участники: сервис | T36 |
| T38 | API проектов и участников | T36, T37 |
| T39 | Позиции и прогресс | T33 |
| T40 | Метки | T33, T35 |
| T41 | Создание задач | T36, T39, T40 |
| T42 | Изменение и удаление задач | T41 |
| T43 | Выборки задач | T39, T41 |
| T44 | API карточки задачи | T38, T42, T43 |
| T45 | API списков задач | T44 |
| T46 | Очистка HTML, разбор упоминаний | — |
| T47 | Комментарии и упоминания: сервис | T30, T41, T46 |
| T48 | API комментариев и упоминаний | T44, T47 |
| T49 | Тип вложения | — |
| T50 | Вложения: хранилище и сервис | T41, T49 |
| T51 | API вложений | T44, T50 |
| T52 | Корзина: сервис | T36, T39, T42, T47, T50 |
| T53 | API корзины | T45, T48, T51, T52 |
| T54 | Обслуживание: корзина и сироты | T31, T52 |
| T55 | Лента проекта, «объект удалён» | T38, T44, T48, T51, T52 |
| T56 | Поиск | T38, T42 |
| T57 | Документация R1.1 | T54, T55, T56 |
| T58 | Фронтенд: навигация, коды, UserPicker | T29, T35, T38 |
| T59 | Фронтенд: проекты | T58 |
| T60 | Фронтенд: списки задач | T45, T59 |
| T61 | Фронтенд: карточка задачи | T40, T44, T60 |
| T62 | Фронтенд: комментарии и упоминания | T48, T61 |
| T63 | Фронтенд: вложения | T51, T61 |
| T64 | Фронтенд: корзина и метки | T40, T53, T58 |
| T65 | Фронтенд: поиск и лента | T55, T56, T59 |
| T66 | Приёмка R1.1 | T29–T65 |

Критический путь (11 задач): T30 → T33 → T36 → T41 → T42 → T44 → T45 → T60 → T61 → T62 (или T63)
→ T66; ветви той же длины: T33 → T39/T40 → T41 и T36 → T37 → T38 → T44 (или → T58 → T59 → T60). Чистые
задачи T29, T31, T34, T46, T49 не имеют зависимостей и выполняются в начале. Рекомендуемый
порядок выполнения — по номерам (номера уже согласованы с зависимостями).

### Риски R1.1

- **R11-1. Объём** (38 задач) и открытый вопрос 18 `open-questions.md` (сокращение объёма R1):
  ответ «сократить» отменяет часть T46–T54 и T62–T64 (plan §10.8, Q-8). Ответ лучше получить до T46.
- **R11-2. Корзина с правами в SQL** (T52): расхождение предикатов `UNION ALL` с `policy` даёт
  утечку или «невосстановимые» строки. Митигация: тест равенства множеств по всем ролям.
- **R11-3. Блокировки и взаимоблокировки** (§10.2): `FOR SHARE` проекта на каждую запись
  содержимого, advisory-блокировки колонок. Митигация: единый порядок, конкурентные тесты в T37 и
  T42, 503 вместо 500 (T29).
- **R11-4. Согласованность файлов и БД** (T50–T54): сбой между rename и COMMIT. Митигация —
  `after_rollback`/`after_commit` (D-49) и уборка сирот обслуживанием.
- **R11-5. Собственный фильтр HTML** (D-28): основная защита от XSS — `react-markdown` без
  HTML (T62); тесты T46 с векторами `<script>`, `<img onerror>`, незакрытыми тегами.
- **R11-6. Генерируемый контракт**: почти каждая API-задача перегенерирует `openapi.json` и
  `schema.d.ts` — параллельное выполнение API-задач даст конфликты; выполнять последовательно.
- **R11-7. Сторожевые infra_static-тесты** (`test_docs_static` — все таблицы в `data-model.md`;
  `test_frontend_scaffold` — список файлов `src`): забытое обновление валит `scripts/check.sh`.
  Учтено в файлах T33, T58–T65.
- **R11-8. pg_trgm и запросы из 2 символов** не используют индекс (ревью артефактов) — замер в
  R1.4 (NFR-2); на объёме R1.1 не проявится.
- **R11-9. Нерешённые вопросы заказчику** (Д-1…Д-7, Q-1…Q-9): реализация идёт по предложениям,
  каждое локализовано (plan §10.8); риск — переделка точечных мест.

### Вопросы к заказчику и аналитику (R1.1)

Полный список с предложениями и местом правки — plan §10.8. Ни один не блокирует старт R1.1.

- **PLAN_ISSUE Q-1 → заказчик (Д-8):** код ответа при занятой блокировке БД — предложено 503 `service_busy` + `Retry-After` (T29).
- **SPEC_ISSUE Q-2 → аналитик:** архивный проект и корзина: можно ли восстанавливать и окончательно удалять проект и его объекты (T52).
- **SPEC_ISSUE Q-3 → аналитик + архитектор (вопрос 14):** «корзина проекта» = фильтр `project_id` корзины пространства (T52, T53, T64).
- **SPEC_ISSUE Q-4 → аналитик:** снимается ли уведомление, если правка убрала `@логин` (T47).
- **SPEC_ISSUE Q-5 → аналитик:** можно ли показывать в ленте текущее название объекта при событии правки названия (T55).
- **SPEC_ISSUE Q-6 → заказчик (вопрос 13):** «свой проект» БА через собственную задачу — реализуется по spec (T34).
- **SPEC_ISSUE Q-7 → аналитик:** снимать ли исполнителя у мягко удалённых задач исключённого участника (T37).
- **SPEC_ISSUE Q-8 → заказчик (вопрос 18):** сокращение объёма R1.
- **Д-7 → заказчик:** битый JSON без сессии → 422 раньше 401 — наследуется новыми эндпоинтами.
- **Из приёмки R1.0 («R1.1!»):** утвердить итоговую формулировку правок spec параллельной сессии
  (FR-9: 413; FR-14c: владелец-БА — в своём проекте, СМ — в любом) — plan §4.5 `can_manage_project`
  ей уже соответствует; ответы по Д-1…Д-6 (`decisions-for-customer.md`) R1.1 не блокируют.

---

## Этапы R1.2–R1.4 (крупные блоки, детализируются позже)

> **SUPERSEDED (MVP-пересборка, 2026-10-15):** B1.2-A и B1.2-C вошли в MVP (T73, T78, T86);
> B1.4-A — T87; B1.4-F — T88; B1.4-E — частично (ручной чек-лист, T88/T89). Остальное (B1.2-B
> фильтры по сроку, R1.3 целиком, B1.4-B/C/D, Playwright) — «Отложено (следующая версия)».

Модули и интерфейсы — plan §3, §4.3–§4.15; трассировка — plan §6.

Прежние блоки R1.1 разложены на задачи выше: B1.1-A → T34–T38; B1.1-B → T39–T45;
B1.1-C → T46–T48; B1.1-D → T49–T51; B1.1-E → T31, T52–T54; B1.1-F → T55, T56; B1.1-G → T58–T65.

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

---

## MVP-пересборка (архитектор, 2026-10-15)

Решение владельца продукта: максимально ускорить прототип таск-трекера для показа заказчику, CRM —
в следующую версию, MVP без оверинжиниринга. Архитектура, решения D-53…D-65, API, права, модель,
трассировка и SPEC_CHANGES — **plan §11** (имеет приоритет над plan §1–§10 при расхождении).
Решения владельца по вопросам plan §10.8: Q-1 — 503 `service_busy` (T29); Q-6 — «свой проект» БА
= владелец (D-54); Q-9/Д-7 — невалидный JSON → 400 `bad_request` (T68); Q-7 — дефолт; Q-8 — этот
раздел; Q-2…Q-5 — закрыты переносом функций.

Итого до демо: **25 задач** (T29, T35, T67–T89), из них 1 — синхронизация spec (T67, не код)
и 1 — приёмка (T89).

### Общие условия для задач MVP

- Действуют «Общие условия для всех задач R1.0» и «Общие условия для задач R1.1» выше, **кроме**:
  нет 409 `project_archived` (архива нет, D-57), нет меток, упоминаний, вложений, корзины, ленты,
  поиска; в общих условиях R1.1 фабрики `make_label`, `make_mention`, `make_attachment` не нужны;
  новая зависимость фронтенда в MVP одна группа — `@dnd-kit/*` (T86), `react-markdown` не добавлять.
- Источник интерфейсов — plan **§11.4** (API и схемы), **§11.5** (права), **§11.6** (модель);
  порядок проверок — plan §4.5 без п.8, п.5 — по D-65; блокировки — plan §10.2 п.1–п.4.
- События: пишутся только события аудита — `user.*` и `project.ownership_transferred` (D-55).
  События ленты (`project.updated`, `member.*`, `task.*`, `comment.*`) **не пишутся**.
- Удаление — мягкое с каскадом и общим `deleted_batch_id` (D-56); восстановления нет; удалённое — 404.
- Экраны с опросом (`usePolledQuery`): доска, список задач проекта, «мои задачи», карточка задачи
  и её комментарии; прочие — `useQuery`.
- Задачи с API выполняются последовательно (общий генерируемый контракт): T68 → T72 → T77 → T78 → T80.
- Если формулировка spec расходится с plan §11 и T67 ещё не DONE — `PLAN_ISSUE`, не додумывать.

### Синхронизация и техдолг

## T67 — Синхронизация spec и ADR с объёмом MVP (аналитик / spec-writer)
- **Статус:** DONE
- **AC:** C-6 (изменение принятых решений — через ADR); plan §11.9 SC-1…SC-21
- **Файлы:** `specs/001-pilot-r1/spec.md`, `docs/adr/0012-mvp-task-tracker-first.md` (новый),
  `docs/glossary.md` («Свой проект»), `docs/open-questions.md` (вопросы 13, 14, 18 — решения)
- **Зависит от:** —
- **Описание:** Не код; выполняет аналитик/spec-writer, не исполнитель. ADR-0012: MVP-прототип
  таск-трекера, CRM и прочее из plan §11.1 — в следующую версию (меняет объём ADR-0002), «свой
  проект» = владелец (заменяет ADR-0009 п.2 и З-8), невалидный JSON → 400 (Д-7). Spec v0.16:
  применить SC-1…SC-21 plan §11.9; номера FR/AC не удалять, отложенное помечать «отложено
  (следующая версия), ADR-0012»; переформулировать AC-48, AC-72, AC-76, AC-77, AC-114 и частичные AC
  по §11.9. Утверждение — владелец продукта.
- **Готово, когда:** spec v0.16 и ADR-0012 утверждены владельцем; ревьюер подтверждает, что каждый
  пункт SC-1…SC-21 отражён; `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёный.
- **Заметки T67:** spec v0.16 (DRAFT, на утверждении владельцем) и ADR-0012 внесены spec-writer; открыты OI-125 (ТЗ §6 п.7 — изоляция CRM), OI-126 (ТЗ §6 п.10 — производительность), OI-127 (своя задача БА в чужом проекте — блокирует T70); `docs/glossary.md`, `docs/open-questions.md`, пометка о замене п.2 в ADR-0009 — за параллельной сессией; трассировку plan §11.7 дополнить AC-123 (T68) и AC-124 (T29).
- **Попытки:** 1

## T68 — Невалидный JSON в теле: 400 `bad_request` (решение владельца по Д-7)
- **Статус:** DONE
- **AC:** FR-7 и FR-45 в редакции SC-21, FR-57 (тело не возвращается), plan D-65; Д-7 закрыт
- **Файлы:** `backend/app/core/errors.py`, `backend/app/api/openapi.py`, `backend/app/api/v1/auth.py`,
  `backend/app/api/v1/admin_users.py` (только объявление 400 у маршрутов с телом),
  `specs/001-pilot-r1/decisions-for-customer.md` (строка Д-7: «РЕШЕНО владельцем 2026-10-15: 400»)
  (+ генерация контракта); тесты (только ассерты о битом JSON и объявлениях 400):
  `backend/tests/api/test_route_guards.py`, `backend/tests/api/test_auth_login.py`,
  `backend/tests/api/test_errors.py`, `backend/tests/cli/test_openapi.py`
  (больше 3 файлов кода: объявления 400 у существующих маршрутов неотделимы от смены поведения)
- **Зависит от:** — (решение владельца уже зафиксировано в plan D-65; SC-21 вносит T67)
- **Описание:** В `_validation_error_handler`: если список ошибок не пуст и у **всех** `type ==
  "json_invalid"` — ответ 400 `{"detail": "Некорректный JSON в теле запроса", "code": "bad_request"}`
  (код — из `_HTTP_STATUS_MAP[400]`), без `loc`/`msg`/фрагментов тела; иначе — прежний 422
  `validation_error`. Своё `APIRoute` и middleware не делать. Поведение (проверяется тестами):
  битый JSON без cookie, с действующей сессией и с одноразовым паролем — 400 (FastAPI разбирает
  тело до зависимостей; это принято владельцем); валидный JSON с неверными полями без cookie —
  401, с сессией без роли / с одноразовым паролем — 403 гейта, у активного пользователя — 422
  (как сейчас); `Content-Type` не JSON — как сейчас; невалидный JSON размером ~1 МиБ — 400, ответ не
  содержит фрагментов тела; паролей в ответе и логе нет (FR-57). Размер тела ограничивает nginx
  (`client_max_body_size 12m`), приложение тело дополнительно не читает. OpenAPI: в `_DESCRIPTIONS`
  — `400: "Некорректный JSON в теле запроса (code: bad_request)"`, правило в docstring «400 — есть
  тело запроса»; у маршрутов с телом (`POST /auth/login`, `POST /auth/password`, `POST /admin/users`,
  `POST /admin/users/{id}/reset-password`, `PUT /admin/users/{id}/role`) — `error_responses(400, …)`.
  Словарь фронтенда уже содержит `error.bad_request` — не трогать. Тесты R1.0, ждущие 422 на битый
  JSON (`test_plan_4_5_p5_broken_json_without_cookie_is_422_before_401`,
  `test_fr57_malformed_json_is_422_without_echo`), test-writer меняет на 400; прочие 422-ассерты
  (неверные поля, одиночный суррогат, если его тип не `json_invalid`) не ослабляются.
- **Готово, когда:** `pytest -q backend/tests/api/test_route_guards.py backend/tests/api/test_auth_login.py backend/tests/api/test_errors.py backend/tests/api/test_password_change.py backend/tests/api/test_admin_users.py backend/tests/cli/test_openapi.py backend/tests/infra/test_frontend_api_types.py`
  зелёный, линтер чистый.
- **Заметки ревью T68 (в T88/T67):** (1) юнит-тест `RequestValidationError([])` → 422 (мутация «убрать `errors and`» выживает); (2) `test_t68_non_json_content_type_is_still_422` допускает 415|422 — закрепить 422; (3) в `BODY_ROUTES` теста поле называется `password`, в схемах `one_time_password` — поправить имена; (4) невалидный UTF-8 и глубокая вложенность дают 400 `bad_request` с текстом «Некорректный запрос» (FastAPI `HTTPException`), обычный битый JSON — «Некорректный JSON в теле запроса»: код один, решить в spec/T88, унифицировать ли; (5) формулировка Д-7: 400 раньше проверки Origin (битый JSON с чужим Origin → 400, не 403 `origin_mismatch`).
- **Попытки:** 1

(T29 — 503 `service_busy` — выполняется как описано выше, без изменений; T35 — тоже, с зависимостью от T70.)

### Backend MVP: модель, права, проекты

## T69 — Модели MVP и миграция 0004
- **Статус:** DONE
- **AC:** AC-108 (уровень БД), FR-13, FR-14, FR-18, FR-18a, FR-21 (позиция только у задач верхнего уровня), FR-23 (длина комментария), AC-66 (CHECK журнала не меняет строки); plan §11.6, D-2…D-4, D-22, D-25, D-26, D-41, D-52, D-56…D-58
- **Файлы:** `backend/app/domain/projects/models.py`, `backend/app/domain/tasks/models.py`,
  `backend/app/domain/comments/models.py` (+ `__init__.py` пакетов), `backend/app/domain/events/models.py`
  (CHECK), `backend/app/domain/registry.py`, `backend/migrations/versions/0004_projects_tasks.py`,
  `docs/data-model.md` (таблицы MVP, CHECK журнала, строка миграции 0004);
  тесты: `backend/tests/db/test_r11_models.py`, `backend/tests/db/test_migrations.py` (цикл
  upgrade → downgrade → upgrade с 0004, `alembic check`), `backend/tests/factories.py` (`make_project`,
  `make_project_member`, `make_task`, `make_comment`)
  (больше 3 файлов: модели и миграция неразделимы — модели без миграции ломают `alembic check`)
- **Зависит от:** T67
- **Описание:** Ровно 4 таблицы plan §11.6: `project`, `project_member`, `task`, `comment`, и
  `CHECK ck_domain_event_entity_type_valid` (7 значений `EntityType`; тот же `CheckConstraint` — в
  модели `DomainEvent`). **Не создавать:** `pg_trgm`, GIN-индексы, `label`, `task_label`, `mention`,
  `attachment`, столбец `project.status`. Миксины: `UUIDPkMixin`, `TimestampMixin`, `WorkspaceMixin`
  у всех (у `project_member` — составной PK вместо `id`); `AuthoredMixin` — `project`,
  `project_member`, `comment`; у `task` `created_by NOT NULL`; `SoftDeleteMixin` — `project`, `task`,
  `comment`. `TaskStatus` (`todo`, `in_progress`, `review`, `done`), `TaskPriority` (`base`, `high`) —
  `StrEnum` в `tasks/models.py`, в БД `text` + CHECK. FK, CHECK и частичные индексы — §11.6 (через
  `postgresql_where`, чтобы `alembic check` был чистым). `downgrade` удаляет 4 таблицы и CHECK журнала.
- **Готово, когда:** `pytest -q backend/tests/db/test_r11_models.py backend/tests/db/test_migrations.py backend/tests/db/test_event_log.py` и
  `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёные, линтер чистый.
- **Заметки ревью T69 (в T71–T77/T88):** (1) решение архитектора: целостность workspace и иерархии в MVP обеспечивает СЕРВИС, не БД (KISS) — БД допускает задачу workspace B в проекте workspace A, участника/комментарий с чужим `workspace_id`, подзадачу с родителем из другого проекта, второй уровень вложенности и `parent_id = id`; обязательны тесты на каждый инвариант в T71 (участник/проект), T74 (создание задачи/подзадачи → 422), T75 (перенос/правка), T79/T80 (комментарий ↔ workspace задачи); при росте — составные FK и `CHECK (parent_id <> id)` отдельной миграцией (бэклог); (2) формулировка D-58/T69 про `alembic check` неверна: он не сравнивает текст CHECK и предикаты частичных индексов — защита только каталожные тесты по `pg_indexes`/`pg_constraint`; не полагаться на `alembic check` при следующих миграциях; (3) FK `workspace_id` у новых таблиц NO ACTION, у R1.0 RESTRICT (`WorkspaceMixin` без `ondelete`) — унифицировать в D-26/следующей миграции; (4) CHECK статуса/приоритета строить из `TaskStatus`/`TaskPriority`; (5) тесты `test_t69_app_user_is_not_deletable_while_referenced` (проверять 23001 на пользователе без `workspace_member`) и `assert_too_long` (требовать 22001) ужесточить; (6) падение 0004 при «чужом» `entity_type` в журнале (удалить строку нельзя — append-only): описать в runbook T88; при росте журнала — `NOT VALID` + `VALIDATE`.
- **Попытки:** 1

## T70 — Объектные права MVP и проверка получателей (чистые функции)
- **Статус:** DONE
- **AC:** FR-9, FR-10, FR-11, FR-14a, FR-14c, FR-15, FR-15a, FR-16, FR-19 (в редакции SC-2: «свой проект» БА = владелец), FR-19a, FR-19b, FR-20, FR-23, FR-68, FR-70, BR-1, BR-11; unit-уровень AC-9, AC-46, AC-47, AC-48 (SC-2), AC-52, AC-54, AC-73, AC-74, AC-99 (права удаления), AC-103, AC-109, AC-110; plan §11.5, D-45, D-54
- **Файлы:** `backend/app/domain/access/policy.py`, `backend/app/domain/access/recipients.py`;
  тесты: `backend/tests/unit/test_policy.py`, `backend/tests/unit/test_recipients.py`
- **Зависит от:** T67
- **Описание:** Без БД. `ProjectFacts {project_id, owner_id, actor_is_member}`, `TaskFacts
  {created_by, assignee_id, parent_id}` и функции **ровно по plan §11.5** (роль — текущая
  `actor.role`; ТА и «без роли» — везде `False`). Ключевое отличие от прежнего T34: `is_own_project`
  для БА — только `owner_id == actor` (решение владельца, Q-6): БА, создавший себе задачу в чужом
  проекте, чужие задачи не правит, исполнителя не меняет, чужие комментарии не удаляет;
  `can_create_subtask` = `can_create_task(a, p, assignee_id) and (can_edit_task_fully(parent) or
  parent.assignee_id == actor)`. `recipients.py`: `RecipientFacts {user_id, in_workspace, is_blocked,
  role}`, `RecipientPurpose` = `PROJECT_MEMBER`, `TASK_ASSIGNEE`, `PROJECT_OWNER` (без
  `DEAL_RESPONSIBLE`), `check_recipient(target, purpose, *, project_member_ids)` — порядок и коды
  plan §4.5 (`user_not_found`, `user_blocked`, `recipient_wrong_role`, `not_project_member`, все —
  `Unprocessable`). Тесты — таблицей «роль × факты → ожидание», включая случай «БА-участник, не
  владелец, автор своей задачи в проекте → чужую задачу править нельзя».
- **Готово, когда:** `pytest -q backend/tests/unit/test_policy.py backend/tests/unit/test_recipients.py` зелёный, линтер чистый.
- **Решение владельца (OI-127, 2026-10-15, подтверждено; spec v0.16.1):** принят вариант (а): БА — участник проекта может править/удалять СВОЮ задачу в любом проекте, где он участник; «своя» = автор И исполнитель — он (`created_by == assignee_id == actor`, как в FR-19/AC-48); исполнителя меняет только владелец-БА (FR-19a: `TASK_ASSIGN_OTHERS and is_own_project`), СМ — участник; чужие задачи — только владелец-БА (СМ — где участвует). (Уточнено по ревью T70, попытка 1.) Правило изолировано в одной чистой функции (`can_edit_task_fully`/`can_delete_task`); при выборе варианта (б) — правка функции и тестов T70, остальные задачи не затрагиваются.
- **Заметки ревью T70 (в T71/T72/T74/T75/T80):** (1) вызывающие обязаны передавать `project_member_ids` для `TASK_ASSIGNEE`/`PROJECT_OWNER` — иначе `ValueError`; (2) инвариант «владелец проекта всегда участник» проверять в `load_project_facts` (T71): для БА-владельца policy участие не проверяет; (3) решение OI-127 подтверждено владельцем (вариант а), spec v0.16.1; (4) формулы `can_change_assignee` в plan §4.5 и старом T34 — SUPERSEDED, действует §11.5; (5) имена тестов трассировки переименованы (`test_d45_fr17_*`, `test_fr17_ac55_*`, `test_br1_*`, `test_ac53_fr15a_*`).
- **Попытки:** 2

## T71 — Проекты и участники: сервис и выборки
- **Статус:** DONE
- **AC:** AC-50, AC-51, AC-52, AC-53, AC-54, AC-55 (список без содержимого), AC-72 (без «архивного»), AC-73, AC-74 (участник, владелец), AC-108 (проект), AC-110 (без 409), AC-48 (удаление проекта: не владелец — 403, владелец — мягко), AC-65 (событие передачи владения), FR-14, FR-14a, FR-14c, FR-15, FR-15a, FR-16 (мягкое удаление, каскад), FR-17 (без статуса), FR-41; plan §11.4, §11.5, D-45, D-46, D-47, D-52, D-55, D-56, §10.2
- **Файлы:** `backend/app/domain/projects/service.py`, `backend/app/domain/projects/queries.py`,
  `backend/app/domain/projects/members.py`; тесты: `backend/tests/domain/test_projects_service.py`,
  `backend/tests/domain/test_project_members_service.py`, `backend/tests/projects_support.py` (общие фикстуры тестов)
- **Зависит от:** T35, T69, T70
- **Описание:** Сигнатуры — plan §10.4 (`queries`, `service`, `members`) без `set_archived` и
  без фильтра статуса. `load_project_facts(db, actor, project_id, *, lock: Literal["update", "share"]
  | None = None) -> ProjectFacts` — один запрос; 404 для несуществующего, мягко удалённого и
  чужого; `lock` — plan §10.2 п.1/п.2. `create_project`: `PROJECT_CREATE` (403), владелец и участник —
  актор, событий нет. `update_project`: `can_manage_project` (403) → изменение; событий нет; без
  изменений — ничего (D-46). `transfer_ownership`: проект `FOR NO KEY UPDATE` → `can_manage_project`
  → `load_recipient(lock=True)` + `check_recipient(PROJECT_OWNER)` (422) → тот же владелец — ничего
  → `owner_id` + `record_event(PROJECT_OWNERSHIP_TRANSFERRED, project_id=…, changed_fields=["owner_id"],
  changes=[{"field": "owner_id", "old": {"id", "login"}, "new": {"id", "login"}}])` (аудит).
  `delete_project`: `can_manage_project` → одно `deleted_at`/`deleted_batch_id` у проекта, всех его
  неудалённых задач и подзадач и их неудалённых комментариев (D-56); событий нет. `list_projects`:
  БА/СМ — все неудалённые, П — где участник; `task_count` — неудалённые задачи верхнего уровня;
  `ORDER BY lower(name), id`; `paginate`. `get_project`: `can_view_project` (403) → `ProjectView` с
  `permissions` из policy. `add_member`: проект `FOR NO KEY UPDATE` → `can_add_member` (403; БА добавляет
  себя — 403) → получатель `PROJECT_MEMBER` (422) → уже участник — ничего → вставка. `remove_member`:
  блокировка проекта → цель не участник — 404 → `can_manage_members` или (цель = актор и
  `can_remove_self`) (403) → цель — владелец → 422 `owner_cannot_be_removed` («сначала передайте
  владение») → `assignee_id = NULL` у всех задач проекта, где цель — исполнитель (включая подзадачи
  и мягко удалённые, Q-7) → удалить членство; событий нет. `list_members` — `can_view_project`,
  `ORDER BY login, id`. Событий ленты не писать (D-55).
- **Готово, когда:** `pytest -q backend/tests/domain/test_projects_service.py backend/tests/domain/test_project_members_service.py` зелёный, линтер чистый.
- **Заметки ревью T71 (в T72/T74/T87/T88):** (1) решение архитектора: в `remove_member` порядок «цель не участник → 404» раньше прав раскрывает Пользователю-неучастнику состав проекта (D-45) — в T72 поставить `can_view_project` → 403 ПЕРВЫМ для неучастника, затем 404 «цель не участник»; (2) добавить тесты: самоисключение ТА/участником без роли → 403 (мутант `can_remove_self` выживает), передача владения в проекте, где у владельца нет строки участника; (3) демо-данные (T87) вставляют проекты мимо сервиса — обязательно добавлять владельцу строку `project_member`; `list_members` не показывает владельца без строки участника; (4) `list_projects`: `populate_existing=True` в production не нужен, а `select(Project)` тянет описания до 10 000 символов — выбирать колонки; (5) коды `owner_cannot_be_removed`, `not_project_member`, `recipient_wrong_role`, `user_blocked`, `user_not_found` добавить в словарь фронтенда (T81); (6) `load_project_facts(lock=…)` делает ДВА запроса (SELECT … FOR … затем факты) — обосновано снимком READ COMMITTED; формулировку «один запрос» в plan §10.4 и в описании T71 исправить; (7) D-46 vs порядок проверок: повторное добавление уже участника, которого заблокировали, → 422 (получатель проверяется первым) — подтверждено как есть; (8) AC-65/FR-41: в `domain_event.changes` лежат `{id, login}` владельцев (`value_fields={owner_id}`); выдача журнала поля `changes` не содержит — spec-writer уточнить формулировку «в выдаче журнала».
- **Попытки:** 1

## T72 — API проектов и участников
- **Статус:** DONE
- **AC:** AC-21, AC-51…AC-55, AC-72, AC-73, AC-74 (участник, владелец), AC-75 (список проектов без роли — 403), AC-76 (в редакции SC-14: после смены роли БА → П `POST /projects` — 403, после возврата — 201), AC-94 (ТА → проект с несуществующим id — 403), AC-108 (проект), AC-110 (без 409), AC-65 (через API журнала: запись передачи владения с автором, временем, типом, id, действием, `changed_fields`; без названий и значений); FR-14…FR-17, FR-45a; plan §11.4 (проекты, участники), D-52, D-65
- **Файлы:** `backend/app/api/v1/projects.py`, `backend/app/api/v1/schemas/projects.py` (+
  `app/api/v1/__init__.py`, генерация контракта); тесты: `backend/tests/api/test_projects.py`,
  `backend/tests/api/test_project_members.py`, `backend/tests/api/test_not_found_vs_forbidden.py`
  (новый), `backend/tests/api/test_role_change_effect.py` (новый), дополнения
  `backend/tests/api/test_workspace_isolation.py`, `backend/tests/api/test_audit.py`
- **Зависит от:** T68, T71
- **Описание:** Маршруты проектов и участников plan §11.4; router-level
  `require_capability(BUSINESS_ACCESS)`, у `POST /projects` ещё `PROJECT_CREATE` (П → 403). Схемы:
  `ProjectCreate {name: str (1–255), description: str (≤ 10 000) = ""}`, `ProjectPatch` (оба
  необязательны), `OwnerChange {user_id}`, `MemberAdd {user_id}`; название из одних пробелов — 422
  (D-52); ответы `ProjectDetail`, `ProjectListItem`, `ProjectMember` (§11.4, без `status`). Ответы об
  ошибках — `error_responses(...)` по таблице §11.4, у маршрутов с телом — и 400 (D-65).
- **Готово, когда:** `pytest -q backend/tests/api/test_projects.py backend/tests/api/test_project_members.py backend/tests/api/test_not_found_vs_forbidden.py backend/tests/api/test_role_change_effect.py backend/tests/api/test_workspace_isolation.py backend/tests/api/test_audit.py`
  и проверки контракта (общие условия R1.1) зелёные, линтер чистый.
- **Заметки ревью T72 (в T73+/T81/T88):** (1) правка `members.py::remove_member` вне списка T72 — `can_view_project` → 403 первым, затем «цель не участник» → 404 (решение архитектора по T71 п.1); (2) `ProjectPatch.name/description` — без `None` в типе, `Field(default_factory=str)` и `model_fields_set` (явный null → 422, в контракте нет null); приём описан в docstring; (3) `extra="forbid"` на всех схемах тел (контракт `additionalProperties: false`); (4) `list_projects` по-прежнему `select(Project)` с `populate_existing` — `paginate` принимает только сущность; при втором потребителе колонок выделить `paginate_rows` (заметки T35/T71); (5) AC-50/AC-55 части про задачи и доску — T74/T77 (тест `test_d45_user_non_member_gets_403_on_tasks_and_board_when_routes_exist` включится в T77); (6) 503 не объявлен в OpenAPI (решение T29); (7) в `entity_deleted` журнала у мягко удалённого проекта `false` — вне R1 (FR-25b отложено).
- **Попытки:** 2

### Backend MVP: задачи и доска

## T73 — Позиции карточек, перемещение по соседям, прогресс
- **Статус:** DONE
- **AC:** FR-28a (новая — в конец первой колонки; смена статуса без соседей — в конец целевой; перемещение по соседям; перенумерация шагом 1024), AC-61 (домен: 1000 последовательных перемещений в одной колонке — порядок ожидаемый, позиции уникальны), AC-81 (домен), FR-22 и AC-7 (функция прогресса); plan §4.8 (без `place_after`), D-22, §10.2 п.4
- **Файлы:** `backend/app/domain/tasks/positions.py`, `backend/app/domain/tasks/progress.py`;
  тесты: `backend/tests/db/test_positions.py`, `backend/tests/unit/test_progress.py`
- **Зависит от:** T69
- **Описание:** `STEP = 1024`. `lock_columns(db, project_id, *statuses)` — уникальные статусы в
  отсортированном порядке, `pg_advisory_xact_lock(hashtext(:key))`, ключ `f"{project_id}:{status}"`.
  `append_position(db, project_id, status)` — `max(position) + STEP` по неудалённым задачам верхнего
  уровня колонки или `STEP`. `renumber_column` — `STEP, 2·STEP, …` по `(position, created_at, id)`.
  `move_task(db, task, *, status, before_task_id, after_task_id) -> None` — сам вызывает
  `lock_columns(project, старый, новый)`; соседи — неудалённые задачи верхнего уровня того же проекта
  в целевой колонке, не сама задача, иначе 422 `invalid_neighbors`; оба `None` — конец колонки
  (`append_position`); алгоритм и семантика `after`/`before` — plan §4.8; промежуток < 2 —
  `renumber_column` и повторный расчёт; меняет `task.status` и `task.position`. `progress(done,
  total)` — `None` при `total == 0`, иначе `done * 100 // total`.
- **Готово, когда:** `pytest -q backend/tests/db/test_positions.py backend/tests/unit/test_progress.py` зелёный, линтер чистый.
- **Заметки ревью T73 (в T77/T32b):** (1) `ServiceBusy`, брошенный из домена (исчерпание попыток `move_task`), проходит через `_app_error_handler` БЕЗ `Retry-After: 5` (D-40 требует) — добавить заголовок в обработчике AppError (errors.py, вне T73) — в T77; (2) тест на расхождение статуса под блокировкой строки (`_read_state(lock=False)` → locked, `lock=True` → другой): убьёт выжившие мутанты «игнорировать возвращённый статус» и «обычное чтение вместо блокирующего»; (3) `conftest.py::_reset_schema`: `SET lock_timeout` перед `DROP SCHEMA` — чужая открытая транзакция на `tracker_test` вешает прогон бесконечно (причина зависания исполнителя); в отчётах указывать БД прогона — T32b; (4) контракт `move_task` для T77: вызывающий проверяет доступ/существование до вызова, `move_task` сам перечитывает и блокирует, права не проверяет; ошибки: 404 (удалена), 422 `invalid_neighbors`/подзадача, 503 `service_busy` (исчерпание, 40P01, 55P03); (5) `renumber_column` не меняет `updated_at`; порядок колонки — `COLUMN_ORDER = (position, created_at, id)` — использовать в выдаче доски; (6) SQL-агрегация прогресса подзадач одним запросом — в T76/T77.
- **Попытки:** 3

## T74 — Задачи: создание задачи и подзадачи
- **Статус:** DONE
- **AC:** AC-8, AC-9, AC-24, AC-47 (подзадача себе — да, другому — 403), AC-49, AC-56, AC-61 (новая — последняя в первой колонке), AC-74 (исполнитель), AC-106 (не участник — 403), AC-108 (задача), AC-109, FR-18…FR-21, FR-28a; plan §11.4, §11.5 (`can_create_task`, `can_create_subtask`), §4.5 (FR-20), §10.2, §10.4 (`context`)
- **Файлы:** `backend/app/domain/tasks/context.py`, `backend/app/domain/tasks/service.py`
  (`create_task`, `create_subtask`); тесты: `backend/tests/domain/test_tasks_create.py`
- **Зависит от:** T71, T73
- **Описание:** `load_task_context(db, actor, task_id, *, lock_project: Literal["share"] | None = None)
  -> TaskContext` (plan §10.4): задача и `ProjectFacts`; 404 для несуществующей, мягко удалённой,
  чужой и задачи удалённого проекта. `TaskCreateData {title, description, assignee, due_date,
  priority}`, `assignee: UUID | None | Unset` (сентинел `UNSET` в `service.py`); «не передан» → П:
  актор, БА/СМ: `None`. `create_task`: проект (404) → `FOR SHARE` → `can_create_task` (403; П с явным
  `null` — 403) → получатель `TASK_ASSIGNEE` (422) → вставка (`todo`, приоритет по умолчанию `base`,
  `lock_columns` + `append_position(todo)`). `create_subtask`: родитель (404, `FOR SHARE` проекта) →
  `can_create_subtask` (403) → родитель — подзадача → 422 `subtask_depth_exceeded` → получатель →
  вставка (`position = NULL`, `status = todo`). Событий не писать (D-55). Возвращают `UUID`.
- **Готово, когда:** `pytest -q backend/tests/domain/test_tasks_create.py` зелёный, линтер чистый.
- **Заметки ревью T74 (в T75/T77/plan):** (1) тест перечитывания в `load_task_context` под FOR SHARE: другая сессия под FOR NO KEY UPDATE проекта меняет `assignee_id` родителя и фиксирует; `create_subtask` бывшего исполнителя → 403 (мутант «убрать перечитывание» выживает) — добавить в T75; (2) тип `assignee`/`project_id` в сервисе не проверяется (assignee=5 → 500): через API приведёт pydantic в T77 (или `isinstance(UUID)` → 422); (3) T75: `delete_task` блокирует строку задачи FOR NO KEY UPDATE, `create_subtask` перечитывает родителя под FOR SHARE строки — иначе параллельная подзадача останется неудалённой под удалённым родителем (каскад D-56 её не увидит); (4) T77: ограничения title/description/due_date/priority — в pydantic-схеме `TaskCreate` (порядок 422 схемы → 404 → 403); (5) plan §10.4: параметр `include_deleted` у `load_task_context` — SUPERSEDED (корзина отложена); (6) FR-19b/BR-11: зафиксировать, что БА-участник не владелец не создаёт подзадачу к чужой задаче и к задаче, созданной им другому/без исполнителя (формула plan §11.5, 403); (7) D-52: названия из невидимых символов (U+200B) принимаются — уточнить при необходимости; (8) `Subtask depth` код `subtask_depth_exceeded` — в словаре фронтенда есть (T81).
- **Попытки:** 2

## T75 — Задачи: изменение, удаление, перемещение
- **Статус:** DONE
- **AC:** AC-7 (родитель закрывается при незакрытых подзадачах), AC-42, AC-43 (задачи), AC-46, AC-47, AC-48 (SC-2), AC-50 (переназначение после исключения), AC-81, AC-99 (права удаления; каскад на подзадачи и комментарии), AC-103 (задачи), FR-19…FR-20, FR-19b (перенос исполнителем), FR-28a; plan §11.4, §11.5, D-46, D-56, §10.2
- **Файлы:** `backend/app/domain/tasks/service.py` (`update_task`, `delete_task`, `move`);
  тесты: `backend/tests/domain/test_tasks_update_delete.py`, `backend/tests/domain/test_tasks_move.py`
- **Зависит от:** T74
- **Описание:** `update_task(db, actor, task_id, patch: TaskPatch)`: контекст (404, `FOR SHARE`) →
  реально меняющиеся поля (D-46) → права по полям: `status` — `can_change_task_status`,
  `assignee_id` — `can_change_assignee`, `title`/`description`/`due_date`/`priority` —
  `can_edit_task_fully`; любое запрещённое — 403, ничего не меняется → новый исполнитель —
  `TASK_ASSIGNEE` (422; `null` допустим для БА/СМ) → смена статуса задачи верхнего уровня —
  `move_task(…, before=None, after=None)` (конец целевой колонки), у подзадачи — только `status`.
  `delete_task`: `can_delete_task` (403) → одно `deleted_at`/`deleted_batch_id` у задачи, её неудалённых
  подзадач и неудалённых комментариев задачи и подзадач (D-56). `move(db, actor, task_id, *, status,
  before_task_id, after_task_id)`: контекст (404, `FOR SHARE`) → подзадача → 422 `validation_error`
  («подзадачи не размещаются на доске») → `can_change_task_status` (403) → `positions.move_task`
  (422 `invalid_neighbors`). Событий не писать (D-55).
- **Готово, когда:** `pytest -q backend/tests/domain/test_tasks_update_delete.py backend/tests/domain/test_tasks_move.py` зелёный, линтер чистый.
- **Заметки ревью T75 (в T76/T77/backlog):** (1) решение архитектора: участие в проекте (`can_read_project_content`) проверяется ВСЕГДА, до D-46; права по полям — только для меняющихся (уточнить plan §11.4); (2) `update_task`: после блокировки строки задачи пересчитываются `changed`, факты и права (иначе результат не совпадает ни с одним последовательным порядком); порядок блокировок: получатель → advisory колонок → строка (§10.2 п.3–5); (3) `lock_task_columns` вынесена в positions.py; (4) каскад delete_task берёт только неудалённые подзадачи (D-56); (5) правки вне списка T75: positions.py (константа `SUBTASK_NOT_ON_BOARD`, `lock_task_columns`), `create_subtask` (T74: FOR SHARE строки родителя после получателя; повторная проверка прав), `backend/tests/tasks_support.py`; (6) РИСК backlog: в смешанной нагрузке (80 параллельных операций) 2 из 12 прогонов дали 40P01 (цикл только из advisory-блокировок: повтор в `lock_task_columns` добирает колонки вне порядка) → 503 по D-40; улучшение: при повторе брать недостающие колонки через `pg_try_advisory_xact_lock` и при неудаче сразу отвечать 503; (7) тип `assignee_id`/`project_id` не проверяется сервисом (UUID приведёт схема T77); (8) `populate_existing` в `_lock_task` — эквивалентный мутант.
- **Попытки:** 3

## T76 — Задачи: карточка и списки (выборки)
- **Статус:** DONE
- **AC:** AC-6, AC-7 (прогресс в карточке), AC-11, AC-22 (частично: фильтры исполнитель и статус, пагинация), AC-43 («находится фильтром по исполнителю»), AC-80 (подзадачи в списках), AC-18 (удалённое не в списках), FR-17, FR-22, FR-26, FR-27 (в редакции SC-10), FR-47; plan §11.4 (`TaskDetail`, `TaskListItem`), D-62
- **Файлы:** `backend/app/domain/tasks/queries.py`; тесты: `backend/tests/domain/test_tasks_queries.py`
- **Зависит от:** T73, T74
- **Описание:** `get_task(db, actor, task_id) -> TaskView`: контекст (404) → `can_read_project_content`
  (403) → неудалённые подзадачи (`ORDER BY created_at, id`), `progress` по ним, `UserRef` автора и
  исполнителей одним запросом (`user_refs`), `permissions` из policy; число SQL-запросов не зависит от
  числа подзадач. `list_project_tasks(db, actor, project_id, params, *, assignee_id: UUID | None,
  status: TaskStatus | None)`: участник (403), неудалённые задачи и подзадачи, фильтры через «И»,
  `ORDER BY created_at DESC, id DESC`, `paginate`. `list_my_tasks(db, actor, params)`: исполнитель =
  актор, неудалённые задача и проект, актор — участник, `ORDER BY due_date ASC NULLS LAST, id`.
- **Готово, когда:** `pytest -q backend/tests/domain/test_tasks_queries.py` зелёный, линтер чистый.
- **Заметки ревью T76 (в T77/T78):** (1) `permissions.create_subtask` = «операция пройдёт»: для подзадачи False (plan §11.4 записать); (2) `list_my_tasks`: ТА/без роли → строго 403 (в домене); (3) карточка и TaskFacts для permissions — из одного чтения строки (NotFound при исчезновении); (4) списки: `defer(Task.description)`; `get_task` 5 запросов при любом числе подзадач; списки page_size=100 — 3–4 запроса; (5) нарушение инварианта (id не найден в user_refs) → `RuntimeError("UserRef missing …")` — в R1 недостижимо; (6) EXPLAIN на 50 000 задач: индексы `ix_task_project_id_created_at`, `ix_task_workspace_id_assignee_id_due_date` используются; (7) тесты гонок «исчезновение строки между чтениями» и «снятие исполнителя между чтениями» — перенести в test_tasks_queries.py (образцы `/tmp/t76rev/test_rev.py` — может быть удалён); (8) `list_my_tasks` join с project без `Project.workspace_id` (прикрыт `Task.workspace_id`); (9) plan §10.4 сигнатуры list_project_tasks/list_my_tasks заменены §11.4 — пометить SUPERSEDED.
- **Попытки:** 2

- **Заметки ревью T77 (в T78/T88):** APPROVE с 1-й попытки (524 целевых теста, 15 мутаций: 13 убиты). (1) выжила M13: нет теста, что `Retry-After` отсутствует у 403/404/422 — добавить assert в тест T78; (2) выжила M11: нет теста на порядок «не-участник + NUL в description → 422 схемы, не 403»; (3) правка `domain/tasks/context.py` вне списка T77 (404 «Задача не найдена» для задачи удалённого проекта, AC-94); (4) `GET/DELETE /tasks/{id}` объявляют 422 (невалидный UUID) сверх таблицы plan §11.4 — учесть в plan; (5) название из одних пробелов проверяет домен (`_validate`), схема — длины и NUL.

## T77 — API задач: карточка, подзадачи, списки
- **Статус:** DONE
- **AC:** AC-6, AC-7, AC-8, AC-9, AC-11, AC-18 (частично), AC-21, AC-22 (частично), AC-24, AC-42, AC-43 (задачи), AC-46, AC-47, AC-48 (SC-2), AC-49, AC-55 (задачи чужого проекта — 403), AC-56, AC-68 (формат срока), AC-74 (исполнитель), AC-75 (`/me/tasks` без роли — 403), AC-77 (в редакции SC-14), AC-80 (списки), AC-81, AC-94 (несуществующая и мягко удалённая задача — 404), AC-99 (частично), AC-103 (задачи), AC-106 (частично), AC-108 (задача), AC-109; plan §11.4, D-51, D-52, D-65
- **Файлы:** `backend/app/api/v1/tasks.py`, `backend/app/api/v1/schemas/tasks.py` (+ `__init__`,
  генерация контракта); тесты: `backend/tests/api/test_tasks.py`, `backend/tests/api/test_subtasks.py`,
  `backend/tests/api/test_task_permissions.py`, `backend/tests/api/test_reassign_blocked.py`,
  `backend/tests/api/test_task_recipients.py`, `backend/tests/api/test_personal_tasks.py`,
  `backend/tests/api/test_project_task_list.py`, `backend/tests/api/test_soft_delete.py`, дополнения
  `test_not_found_vs_forbidden.py`, `test_workspace_isolation.py`, `test_role_change_effect.py`
- **Зависит от:** T72, T75, T76
- **Описание:** Маршруты `POST|GET /projects/{id}/tasks` (`?assignee_id&status&page&page_size`),
  `GET /me/tasks`, `GET|PATCH|DELETE /tasks/{id}`, `POST /tasks/{id}/subtasks` (plan §11.4). `DueDate` —
  D-51; названия — D-52; `TaskStatus`, `TaskPriority` — перечисления в схеме (вне набора → 422);
  «исполнитель не передан» и «передан `null`» различаются по `model_fields_set` → `UNSET`/`None`.
  Ответ карточки — `TaskDetail` из `get_task`. Маршрута `move` здесь нет (T78).
- **Готово, когда:** все перечисленные тест-файлы `pytest -q backend/tests/api/test_tasks.py backend/tests/api/test_subtasks.py backend/tests/api/test_task_permissions.py backend/tests/api/test_reassign_blocked.py backend/tests/api/test_task_recipients.py backend/tests/api/test_personal_tasks.py backend/tests/api/test_project_task_list.py backend/tests/api/test_soft_delete.py backend/tests/api/test_not_found_vs_forbidden.py backend/tests/api/test_workspace_isolation.py backend/tests/api/test_role_change_effect.py`
  и проверки контракта зелёные, линтер чистый.
- **Попытки:** 1

- **Заметки ревью T78 (в T79/T80/T88):** APPROVE с 1-й попытки (431 тест, 15 мутаций: 13 убиты, M7 эквивалентна). (1) порядок проверок `tasks.service.move` изменён на 404 → 403 → 422 домена (plan §4.5), описание T75 про «подзадача → 422 раньше 403» УСТАРЕЛО; правки вне списка: `domain/tasks/service.py`, `tests/domain/test_tasks_move.py`, `tests/api/test_projects.py`, `tests/cli/test_openapi.py`; (2) `after_task_id` имеет приоритет, если соседи не смежны или в обратном порядке (plan §4.8) — зафиксировано тестом; (3) нет теста на `extra="forbid"` у `TaskMove` (M15) и на число SQL-запросов доски (7, не зависит от числа карточек) — добавить при случае; (4) имя проекта читается вторым запросом (trivial).

## T78 — Доска: выборка и API переноса
- **Статус:** DONE
- **AC:** AC-25, AC-61 (через API: второй пользователь после перемещения видит тот же порядок), AC-80 (доска: одна карточка при 2 подзадачах, `subtask_count`, `progress`), AC-18 (удалённое не на доске), AC-21, FR-19b (исполнитель переносит свою чужую задачу), FR-28, FR-28a, FR-47 (исключение — SC-15); plan §11.4 (`Board`, `move`), D-61
- **Файлы:** `backend/app/domain/boards/service.py` (+ `__init__.py`), `backend/app/api/v1/boards.py`,
  `backend/app/api/v1/schemas/boards.py` (+ `app/api/v1/__init__.py`, генерация контракта);
  тесты: `backend/tests/api/test_board.py`, `backend/tests/api/test_board_move.py`
- **Зависит от:** T75, T77
- **Описание:** `get_board(db, actor, project_id) -> BoardView`: неудалённый проект (404) → участник
  (403) → 4 колонки в порядке FR-18a (пустые тоже), карточки — неудалённые задачи верхнего уровня
  `ORDER BY position, created_at, id`; `subtask_count` и `progress` — по неудалённым подзадачам одним
  агрегирующим запросом на доску. Маршруты `GET /projects/{id}/board` → `Board`, `POST
  /tasks/{id}/move` `{status, before_task_id?, after_task_id?}` → 204 (сервис `tasks.service.move`,
  T75). Конкурентный сценарий (образец `tests/api/test_session_row_lock.py`): ≥ 100 параллельных
  перемещений и смен статуса в одной колонке через HTTP — без 500 (допустим 503 `service_busy`),
  позиции неудалённых задач колонки уникальны.
- **Готово, когда:** `pytest -q backend/tests/api/test_board.py backend/tests/api/test_board_move.py` и проверки контракта зелёные, линтер чистый.
- **Попытки:** 1

### Backend MVP: комментарии

- **Заметки ревью T79 (в T80/T88/backlog):** 2 итерации (CHANGES_REQUESTED → APPROVE по дельте). Исправлено по ревью: (1) запасной путь `strip_html` после 16 проходов собирал тег — теперь вырезается серия `<+`; (2) терялся `&` в конце текста (sentinel `\n`); (3) гонка `create_comment` ↔ `delete_task` — `_lock_task_rows` (FOR SHARE: родитель → задача, `deleted_at IS NULL`). Остаток: (а) **ВЗАИМОБЛОКИРОВКА в `tasks/service.py::delete_task` (T75)**: комментарии обновляются раньше задач, при параллельном `delete_task(parent)` и `delete_task(sub)` с комментариями у подзадачи — 40P01 (≈56/30 раундов в стрессе) → 500 вместо 503; фикс: сначала `UPDATE task` (или `FOR NO KEY UPDATE ORDER BY id` на семье), потом `UPDATE comment`; выполнить до T89 вместе с T80; (б) нет теста на позицию sentinel (мутант M5): `strip_html("line1\n<br>line2") == "line1\nline2"`, `strip_html("x\n&amp;y") == "x\n&amp;y"`; (в) `a<b` без пробелов в конце/середине ввода вырезается как тег (поведение HTMLParser) — записать как известное; (г) `create_comment` держит FOR SHARE на родителе и задаче до конца транзакции — T80: короткие транзакции; (д) тест длины >10 000 на уровне сервиса есть; NUL строго 422.

## T79 — Комментарии: очистка HTML и сервис
- **Статус:** DONE
- **AC:** AC-58, AC-103 (комментарии: СМ-участник удаляет чужой, СМ-не участник — 403), FR-23 (без упоминаний; SC-11); plan D-28, D-60, §11.5 (`can_edit_comment`, `can_delete_comment`), §10.2 п.2
- **Файлы:** `backend/app/domain/comments/sanitize.py`, `backend/app/domain/comments/service.py`;
  тесты: `backend/tests/unit/test_sanitize.py`, `backend/tests/domain/test_comments_service.py`
- **Зависит от:** T74
- **Описание:** `strip_html(text)` — как в T46 (`html.parser.HTMLParser`, `convert_charrefs=False`:
  теги, комментарии, декларации, инструкции удаляются; содержимое `script`/`style`, включая
  незакрытые, удаляется; сущности и прочий текст — как есть, `>` и `a < b` не портятся).
  `create_comment(db, actor, task_id, body)`: контекст задачи (404, `FOR SHARE`) → участник (403) →
  `strip_html`; пусто или одни пробелы после очистки → 422 `validation_error` → вставка.
  `edit_comment`: неудалённый комментарий неудалённой задачи (404) → участник и автор (403) →
  очистка → `body`, `edited_at = now`. `delete_comment`: `can_delete_comment` (403) → мягкое удаление
  (свой `deleted_batch_id`). `list_comments`: участник (403), все комментарии задачи, включая
  удалённые (`body = None`, `is_deleted = True`, автор и время сохраняются), `ORDER BY created_at,
  id`, `paginate`; `permissions {edit, delete}`. Событий и упоминаний нет.
- **Готово, когда:** `pytest -q backend/tests/unit/test_sanitize.py backend/tests/domain/test_comments_service.py` зелёный, линтер чистый.
- **Попытки:** 1

## T80 — API комментариев
- **Статус:** DONE
- **AC:** AC-58, AC-103 (комментарии), AC-21; FR-23; plan §11.4 (комментарии), D-65
- **Файлы:** `backend/app/api/v1/comments.py`, `backend/app/api/v1/schemas/comments.py` (+ `__init__`,
  генерация контракта); тесты: `backend/tests/api/test_comments.py`, дополнение
  `backend/tests/api/test_workspace_isolation.py`
- **Зависит от:** T78, T79
- **Описание:** `GET|POST /tasks/{id}/comments`, `PATCH|DELETE /comments/{id}`. Тело `{body: str}`,
  1–10 000 символов до очистки (иначе 422). Ответ `Comment` (§11.4).
- **Готово, когда:** `pytest -q backend/tests/api/test_comments.py backend/tests/api/test_workspace_isolation.py` и проверки контракта зелёные, линтер чистый.
- **Попытки:** 1

- **Заметки ревью T80 (в T85/T88/backlog):** APPROVE с 1-й попытки (589 тестов, 15 мутаций: 12 убиты, 2 эквивалентны, 1 пробел). Вне списка файлов (обосновано): `domain/tasks/service.py::delete_task` — порядок блокировок «задача → живые подзадачи ORDER BY id → UPDATE task → UPDATE comment» (взаимоблокировка из ревью T79 закрыта; стресс 840 раундов: 0 deadlock, 0 сирот) и `tests/domain/test_delete_task_deadlock.py`. Желательное: (1) в тест пагинации добавить `assert p3["page"] == 3` (мутант M8); (2) кейс `"д"*10_001` на несуществующую задачу (422 раньше 404; M13); (3) API-цепочка AC-103: СМ-не участник DELETE → 403 → добавил себя → 204; (4) тест delete_task против create_comment/edit/move; (5) пустое тело → 422 `missing` (не 400) — действующий контракт T68, Д-7 касается только json_invalid.

### Фронтенд MVP

## T81 — Фронтенд MVP: навигация, маршруты, коды ошибок, выбор пользователя
- **Статус:** DONE
- **AC:** NFR-6, NFR-7 (видимый фокус, клавиатура), FR-45 (сообщения по кодам MVP: `service_busy`, `owner_cannot_be_removed`, `subtask_depth_exceeded`, `invalid_neighbors`, коды получателей), FR-10 (меню по `/me.capabilities`; сервер проверяет сам); plan §4.14, §11.4; заметка ревью T32 п.1 (сканер строк на compiler API — до экранов)
- **Файлы:** `frontend/src/app/router.tsx` (маршруты `/projects`, `/projects/:projectId`,
  `/tasks/:taskId`, `/my-tasks` под `SessionGate`, страницы-заглушки заменяют T82–T84; меню:
  «Проекты» и «Мои задачи» при `business_access`, администрирование — как в R1.0),
  `frontend/src/shared/i18n/ru.ts`, `frontend/src/shared/ui/UserPicker.tsx`, `frontend/src/features/users/api.ts`;
  тесты: `frontend/tests/app/navigation.test.tsx`, `frontend/tests/shared/UserPicker.test.tsx`,
  `frontend/tests/shared/i18n.test.ts` (коды MVP в словаре; `scanLatinUi` на compiler API `typescript`),
  `backend/tests/infra/test_frontend_scaffold.py` (список файлов `src`)
- **Зависит от:** T29, T35, T72
- **Описание:** `UserPicker` — поиск по `GET /users?q=` (стрелки, Enter, Esc; `aria-*`), опционально
  ограничивает выбор переданным набором id (участники проекта). Пунктов меню для CRM, меток,
  корзины, поиска, упоминаний нет.
- **Готово, когда:** фронтенд зелёный (общие условия R1.1).
- **Заметки ревью T81:** кандидатов для `allowedIds` брать из GET /projects/{id}/members (не /users); UserPicker: live region, maxLength 64, Escape — сделано в T82; сканер `scanLatinUi` на compiler API; известные лазейки: вызовы/объектные литералы/массивы, `value`/`defaultValue` в TECHNICAL_ATTRS.
- **Попытки:** 1

## T82 — Экраны проектов: список, создание, карточка, участники, владение, удаление
- **Статус:** DONE
- **AC:** UF-3 (проект и участники), FR-14…FR-17 (интерфейс, без статуса), FR-15a (подтверждение самоисключения), AC-51…AC-55, AC-72, AC-73, AC-110 (поведение по ответам API); NFR-6, NFR-7
- **Файлы:** `frontend/src/features/projects/api.ts`, `frontend/src/features/projects/ProjectsPage.tsx`,
  `frontend/src/features/projects/ProjectPage.tsx` (+ маршруты в `router.tsx`);
  тесты: `frontend/tests/features/projects/ProjectsPage.test.tsx`, `frontend/tests/features/projects/ProjectPage.test.tsx`
- **Зависит от:** T81
- **Описание:** Список с пагинацией (название, владелец, число задач); создание (при
  `project_create`); карточка: правка названия и описания (`permissions.manage`), передача владения
  (`UserPicker` по участникам), удаление с `ConfirmDialog`, участники (добавление через `UserPicker`,
  исключение, самоисключение с подтверждением). Вкладки «Доска» (по умолчанию, T86), «Задачи» (T83),
  «Участники» — места под T83/T86. Ошибки — по `code`.
- **Готово, когда:** фронтенд зелёный.
- **Заметки ревью T82 (в T83/T84/T86):** ключи задач и доски держать под префиксом `["projects", id, …]`; `listAllMembers` вынести и переиспользовать (`["projects", id, "members"]`) для `allowedIds` исполнителя; опрос карточки не ведётся — `usePolledQuery` в списках/доске (FR-29); фокус на h1 при входе на экран — паттерн; UserPicker `busy`/`quietError`; общий `Pagination` при busy не теряет фокус, но на граничной странице нажатая кнопка становится disabled и фокус уходит в BODY (перевести на соседнюю кнопку); правка T82 вне списка: ru.ts, UserPicker.tsx, ui.css, Pagination.tsx; `.ui-pre` — перенос длинных слов сделан.
- **Попытки:** 2

## T83 — Списки задач и создание задачи
- **Статус:** DONE
- **AC:** UF-3, UF-6 (список и фильтр), FR-20 (П: поле исполнителя не отправляется; «без исполнителя» — только БА/СМ), FR-26, FR-27 (фильтры исполнитель и статус, SC-10), FR-29 (опрос списков), AC-6, AC-56, AC-109 (интерфейс); NFR-5 (срок — календарная дата без пересчёта пояса), NFR-6, NFR-7
- **Файлы:** `frontend/src/features/tasks/api.ts`, `frontend/src/features/tasks/TaskList.tsx`
  (вкладка «Задачи» проекта с фильтрами исполнителя и статуса; страница `/my-tasks`),
  `frontend/src/features/tasks/CreateTaskForm.tsx`;
  тесты: `frontend/tests/features/tasks/TaskList.test.tsx`, `frontend/tests/features/tasks/CreateTaskForm.test.tsx`
- **Зависит от:** T77, T82
- **Описание:** Списки — `usePolledQuery`. Форма: название, описание, срок (`input type=date`,
  отправляется `YYYY-MM-DD`), приоритет, исполнитель (`UserPicker` по участникам; для П поля нет).
  Меток нет.
- **Готово, когда:** фронтенд зелёный.
- **Попытки:** 1

## T84 — Карточка задачи: поля, статус, исполнитель, подзадачи, удаление
- **Статус:** DONE
- **AC:** UF-4, UF-6, FR-18…FR-22 (интерфейс; предупреждение при закрытии родителя с незакрытыми подзадачами), FR-29 (опрос карточки), AC-7, AC-46, AC-47 (элементы по `permissions`); NFR-6, NFR-7
- **Файлы:** `frontend/src/features/tasks/TaskPage.tsx`, `frontend/src/features/tasks/SubtaskList.tsx`
  (+ функции в `features/tasks/api.ts`);
  тесты: `frontend/tests/features/tasks/TaskPage.test.tsx`, `frontend/tests/features/tasks/SubtaskList.test.tsx`
- **Зависит от:** T83
- **Описание:** Карточка — `usePolledQuery`; форма правки — локальное состояние до сохранения (опрос
  не затирает ввод). Подзадачи с прогрессом (`null` — «нет подзадач»), создание подзадачи, смена
  статуса, удаление с подтверждением; место под комментарии (T85).
- **Готово, когда:** фронтенд зелёный.
- **Попытки:** 1

## T85 — Комментарии в карточке задачи
- **Статус:** DONE
- **AC:** UF-6 (комментарий), FR-23 (SC-11: простой текст), FR-29 (опрос), AC-58 (интерфейс: «изменён», «комментарий удалён»); NFR-6, NFR-7
- **Файлы:** `frontend/src/features/comments/Comments.tsx`, `frontend/src/features/comments/api.ts`
  (+ подключение в `TaskPage.tsx`); тесты: `frontend/tests/features/comments/Comments.test.tsx`
- **Зависит от:** T80, T84
- **Описание:** Список — `usePolledQuery`, пагинация; текст — обычный текстовый узел React со стилем
  `white-space: pre-wrap` (без `dangerouslySetInnerHTML`, без `react-markdown`); правка и удаление — по
  `permissions`; удалённый — заглушка с автором и временем; время — Europe/Moscow (NFR-5).
- **Готово, когда:** фронтенд зелёный.
- **Попытки:** 1

## T86 — Канбан-доска: перетаскивание и клавиатурная замена
- **Статус:** DONE
- **AC:** UF-5, FR-28, FR-28a (клиент передаёт соседей), FR-29 (опрос доски), FR-19b (перенос по ответу 403 откатывается с сообщением), AC-5 *ручной* (подготовка), AC-97 (клавиатура доски) *ручной*, NFR-7; plan D-61, §11.10
- **Файлы:** `frontend/src/features/boards/BoardView.tsx`, `frontend/src/features/boards/api.ts`,
  `frontend/src/features/boards/dnd.ts` (чистая функция соседей после сброса),
  `frontend/package.json`, `frontend/package-lock.json` (`@dnd-kit/core ^6.3`, `@dnd-kit/sortable ^10`,
  `@dnd-kit/utilities ^3.2`) (+ подключение во вкладку «Доска» `ProjectPage.tsx`);
  тесты: `frontend/tests/features/boards/BoardView.test.tsx`, `frontend/tests/features/boards/dnd.test.ts`,
  `backend/tests/infra/test_frontend_scaffold.py` (список файлов), `backend/tests/arch/test_dependencies_allowlist.py` (три пакета)
- **Зависит от:** T78, T82
- **Описание:** Доска — `usePolledQuery(GET /projects/{id}/board)`; 4 колонки, карточка: название,
  приоритет, срок, исполнитель, прогресс подзадач. `DndContext` с `PointerSensor` и `KeyboardSensor`
  (`sortableKeyboardCoordinates`) — перемещение между колонками и внутри колонки с клавиатуры;
  `dnd.ts::neighborsAfterDrop(columnTaskIds, movedId, targetIndex) -> {after_task_id, before_task_id}`
  (верхний и нижний сосед в целевой колонке без самой карточки). После `POST /tasks/{id}/move` —
  инвалидация доски; ошибка (403, 422, 503) — сообщение по коду и возврат к данным сервера.
  Сетевые вызовы — только через общий клиент.
- **Готово, когда:** `cd frontend && npm ci` успешен; фронтенд зелёный; `pytest -q backend/tests/arch` зелёный.
- **Попытки:** 1

- **Заметки ревью T83–T86 (в T88/backlog):** все APPROVE после 1–3 итераций (фронтенд 670 тестов; check.sh на слитом дереве зелёный). T83: каст `TaskCreate` в api.ts оставлен (контракт не шлёт пустое description); `error.not_project_member` не предлагает «добавьте участника» (FR-20/OI-18) — вернуться при приёмке; `formatDate` дублируется (TaskList/TaskPage/Comments) — вынести в shared/format при третьем потребителе (уже есть 3). T84: гонка двух быстрых выборов исполнителя (второй молча отбрасывается, поле показывает логин второго) и 404 при опросе после удаления другим пользователем — в бэклог; статус и исполнитель отправляются сразу при выборе (шаг клавиатуры стрелками по select в Windows шлёт PATCH на каждый шаг). T85: после создания комментария на странице 1 при `has_next` новый (ORDER BY created_at) попадает на последнюю страницу и не виден — перейти на последнюю страницу/показать подтверждение; фокус после удаления на h2, лучше на заглушку; при удалении комментария во время правки форма исчезает без сообщения; `trim()` текста против FR-23 «хранится как введён» (отступы markdown) — решение владельца; нет тестов на фокус h2 и двойной submit правки. T86: ручная проверка мышью AC-5/AC-97 обязательна (чек-лист в отчёте ревью, войдёт в T88): сброс между карточками/на заголовок/в пустую колонку, высокая карточка, Enter на ссылке, перенос за текст ссылки не уводит на /tasks/<id> (pointer-events), опрос во время переноса (frozen), медленная сеть (moving), клавиатура Space/стрелки/Tab/Escape, скринридер; зависимости @dnd-kit/{core 6.3.1,sortable 10.0.0,utilities 3.2.2} + транзитивные @dnd-kit/accessibility 3.1.1 и tslib 2.8.1 (0BSD) — занести в реестр лицензий.

### Демо, документация, приёмка

## T87 — Команда демо-данных
- **Статус:** DONE
- **AC:** AC-41 *инфра*, AC-104 *инфра*, FR-49 (в редакции SC-13), FR-64, FR-57, BR-9, FR-41 (создание учётных записей и назначение ролей — в журнале, автор «система»); plan §11.8, D-63, D-6, §4.13
- **Файлы:** `backend/app/domain/ops/demo.py`, `backend/app/cli/commands/demo_data.py`,
  `backend/app/cli/main.py` (регистрация); тесты: `backend/tests/cli/test_demo_data.py`
  (`@pytest.mark.committed`)
- **Зависит от:** T69, T73
- **Описание:** Строго по plan §11.8. `load_demo_data(sessionmaker, settings, *, clock, seed) ->
  DemoReport`: одна транзакция; отказ (код 2, данные не меняются) при существующих проектах/задачах
  или пользователях сверх первого ТА; пароли — `generate_password()`, хеш — `PasswordHasher` из
  настроек, `must_change_password = true`; файл `secrets/demo-passwords.txt` — `write_private_file`
  (0600) после успешного создания строк, при ошибке фиксации удаляется (как файл первого ТА, plan
  §4.7); stdout — только путь к файлу и счётчики, паролей в stdout/stderr/логах нет. Тесты: 13
  учётных записей; 12 разных паролей ≥ 12 символов; права файла 0600; вход демо-пользователя требует
  смены пароля; 2 проекта, 30 задач (6 подзадач), каждый исполнитель — участник проекта и не ТА,
  позиции в колонке уникальны, у подзадач `position IS NULL`; журнал содержит `user.created` и
  `user.role_assigned` с автором «система»; повторный запуск — код 2, данные не изменены.
- **Готово, когда:** `pytest -q backend/tests/cli/test_demo_data.py` зелёный, линтер чистый.
- **Заметки ревью T87 (в T88):** (1) README: восстановление при потере файла паролей — `POST /api/v1/admin/users/{id}/reset-password` от имени первого ТА для каждого демо-пользователя либо переустановка с удалением тома; (2) смысл предупреждения при `ENV=production`: перед реальной работой учётные записи `demo.*` удалить/заблокировать; (3) файл паролей пишется ДО фиксации с проверкой отдельной сессией (как у первого ТА, plan §4.7); при убийстве процесса между записью и фиксацией в файле пароли несуществующих пользователей — безопасно (0600); (4) метки времени идут от `clock.now()` вперёд на секунды (до ~+66 с) — при желании считать назад; (5) ветка `ProgrammingError` ловит любую ProgrammingError (не только отсутствие таблицы); (6) формат файла паролей — TAB (plan §11.8).
- **Попытки:** 2

## T88 — Документация MVP и чек-лист демо
- **Статус:** DONE
- **AC:** NFR-3, NFR-11, AC-1 (подготовка), D-64; заметки ревью T31 п.1 (README: каталог клона, `-p`, `date -u`)
- **Файлы:** `README.md` (ru и en: состав MVP-демо и что отложено; загрузка демо-данных
  `docker compose exec api gostracker demo-data` и чтение паролей; сценарий демо; обслуживание — только
  истёкшие сессии, корзины в MVP нет), `docs/data-model.md` (раздел MVP: мягкое удаление без корзины,
  `deleted_batch_id`, какие события пишутся), `docs/acceptance/mvp-demo.md` (новый чек-лист: AC-1,
  AC-5, AC-97 в объёме MVP, AC-98, сценарий UF-2…UF-6, проверка опроса ≤ 15 с вместо AC-107);
  тесты: `backend/tests/infra/test_docs_static.py` (дополнение, `infra_static`)
- **Зависит от:** T86, T87
- **Готово, когда:** `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёный; ревьюер подтверждает
  соответствие plan §11 и рабочие ссылки.
- **Попытки:** 1
- **Заметки ревью T88 (в T89/backlog):** CHANGES_REQUESTED → правки (прогресс 66 %, «at least every 15 s», HTML вырезается, формулировка 503, шаг D-54 в демо, ENV=production в stderr, FR-27a в «Отложено», AC-107 ручной) — приняты без повторного ревью (текстовые). Вне списка: два T31-теста без требования «корзина 30 дней» (ADR-0012 п.3), whitelist `test_frontend_scaffold` (+features/comments), T89a: `AuditPage` показывает `project.ownership_transferred` текстом и поле `owner_id` → «Владелец проекта». Бэклог: «кто → кому» в журнале передачи владения (нужна правка `events/queries.py`/`schemas/audit.py`/openapi); текст предупреждения CLI demo-data «удалите их» против README «заблокируйте» (удаления УЗ нет).

## T89 — Приёмка MVP
- **Статус:** DONE (автоматическая и API-часть; ручной чек-лист в Chromium — за владельцем)
- **AC:** все AC plan §11.7; NFR-10
- **Файлы:** правок кода нет; вердикт ревьюера оркестратор сохраняет в
  `specs/001-pilot-r1/reviews/MVP-acceptance.md`; дефекты — задачами `T89a…`
- **Зависит от:** T29, T35, T67–T88
- **Описание:** Сверить трассировку plan §11.7 (каждый AC — тест существует и зелёный; частичные
  AC — отложенная часть в реестре); `bash scripts/check.sh`; свежий стек `up -d --build --wait` и
  `infra_stack` целиком; на стеке — `gostracker demo-data`, вход демо-пользователем, смена пароля;
  `gostracker maintenance --dry-run`; `alembic downgrade 0003` → `upgrade head` на тестовой БД; ручной
  прогон `docs/acceptance/mvp-demo.md` в Chromium (в т.ч. с клавиатуры и двумя пользователями на
  доске).
- **Готово, когда:** `bash scripts/check.sh` и `infra_stack` зелёные; чек-лист пройден; ревьюер подтверждает трассировку.
- **Попытки:** 1
- **Вердикт:** `specs/001-pilot-r1/reviews/MVP-acceptance.md` — ПРИНЯТО С ЗАМЕЧАНИЯМИ. Дефекты: T89b (503 при плотных переносах, positions.py `lock_task_columns`), T89c (таблица §11.7), T89d (текст предупреждения demo-data), T89e (Cache-Control no-store) — после показа.

## T90 — Оформление интерфейса по макету docs/ui/task-plane.png
- **Статус:** DONE (по тестам; визуальная проверка владельцем)
- **AC:** NFR-7 (контраст AA, видимый фокус), AC-98 (строки без изменений); спец-требований к внешнему виду нет — решение владельца 2026-10-16
- **Файлы:** `frontend/src/shared/ui/ui.css` (токены, тёмная тема), `frontend/src/app/router.tsx` (классы `ui-shell`, `ui-sidebar`), `BoardView.tsx`, `UserPicker.tsx` (inline-стили → классы); тест `frontend/tests/shared/theme.test.ts` (токены, контраст, без жёстких цветов и внешних ресурсов)
- **Заметки:** боковая панель на Home и бизнес-экранах; админ-экраны без панели; «Сменить пароль»/«Выйти» только на Home; результат смотрели только по тестам — требуется взгляд человека (sticky-панель, узкий экран <720px, геометрия dnd-kit, близость к макету). Ограничения: без внешних шрифтов/CDN/изображений.
- **Попытки:** 1


### Порядок MVP и критический путь

| Задача | Название | Зависит от |
|---|---|---|
| T29 | 503 `service_busy` | — |
| T67 | Синхронизация spec, ADR-0012 (аналитик) | — |
| T68 | Невалидный JSON → 400 | — |
| T69 | Модели и миграция 0004 (MVP) | T67 |
| T70 | Права MVP и получатели | T67 |
| T35 | Справочник пользователей, `GET /users` | T70 |
| T71 | Проекты и участники: сервис | T35, T69, T70 |
| T72 | API проектов и участников | T68, T71 |
| T73 | Позиции, перемещение, прогресс | T69 |
| T74 | Создание задач и подзадач | T71, T73 |
| T75 | Изменение, удаление, перемещение задач | T74 |
| T76 | Выборки задач | T73, T74 |
| T77 | API задач | T72, T75, T76 |
| T78 | Доска: выборка и API переноса | T75, T77 |
| T79 | Комментарии: сервис | T74 |
| T80 | API комментариев | T78, T79 |
| T81 | Фронтенд: навигация, коды, UserPicker | T29, T35, T72 |
| T82 | Фронтенд: проекты | T81 |
| T83 | Фронтенд: списки и создание задач | T77, T82 |
| T84 | Фронтенд: карточка задачи | T83 |
| T85 | Фронтенд: комментарии | T80, T84 |
| T86 | Фронтенд: доска | T78, T82 |
| T87 | Демо-данные | T69, T73 |
| T88 | Документация и чек-лист | T86, T87 |
| T89 | Приёмка MVP | все выше |

Рекомендуемый порядок выполнения одним исполнителем — по строкам таблицы. Критический путь
(12 задач): **T67 → T70 → T35 → T71 → T74 → T75 → T77 → T78 → T80 → T85 → T88 → T89**; ветвь той же
длины: T77 → T83 → T84 → T85. Без зависимостей и в начале: T29, T67, T68; параллельно с T70/T35 —
T69 → T73.

### Риски MVP

См. plan §11.11: R-M1 (T67 на критическом пути), R-M2 (цена возврата отложенного), R-M3 (сужение прав
БА меняет сценарий демо), R-M4 (доска без пагинации), R-M5 (приёмка ТЗ §6 не полная), R-M6
(последовательные API-задачи), R-M7 (D-65 меняет поведение R1.0). Дополнительно: T68 и T86 правят
тесты/зависимости, проверяемые сторожевыми тестами (allowlist, контракт) — test-writer обновляет их в
той же задаче.

### Вопросы к владельцу продукта (MVP)

Только то, что нельзя закрыть дефолтом; до ответа работа идёт по дефолту.
- **Q-M1 (D-54):** «права на проект задаются вручную» = только передача владения (один владелец) и
  роль СМ? Или нужен признак «со-управляющий проекта» у участника (несколько БА с правами
  владельца)? Дефолт: один владелец + СМ; признак — аддитивный столбец `project_member` позже.
- **Q-M2 (ADR-0012):** подтвердить заказчику, что показ MVP — промежуточный этап, а не приёмка R1:
  пункты ТЗ §6 п.8, п.9 (CRM), п.11 (экспорт/импорт), п.12 (бэкап) в него не входят. Дефолт: да.
- **Q-M3:** будет ли заказчик вести в прототипе реальную работу неделями (тогда нужна резервная
  копия FR-50, +1 задача из B1.4-C)? Дефолт: нет, прототип только для показа.

### Spec v0.17: отображаемый логин (FR-73a, D-66, архитектор, 2026-10-16)

Изменение принятого требования R1.0 по решению владельца продукта (OI-128): логин хранится и
показывается в написании при создании (`Ivanov.Petr`), вход, уникальность, поиск и сортировка —
без учёта регистра. Решения: **plan D-66** (§11.2) и **plan §11.12** (схема, миграция 0005,
интерфейсы, тест-план). Ответы владельца, переданные оркестратором 2026-10-16: OI-129 — а)
(порядок по нормализованному логину, как до v0.17), OI-130 — а) (первый ТА — в написании из
`INITIAL_ADMIN_LOGIN`). Занятый логин — 422 `login_taken` (не 409). Итого 7 задач (T93–T99).

**Общие условия для T93–T99:**
- Действуют «Общие условия для задач MVP» выше. Источник интерфейсов — plan §11.12; при
  расхождении spec v0.17 с plan §11.12 (кроме пометок [ВОПРОС ВЛАДЕЛЬЦУ] у OI-129/OI-130 — они
  решены, SC-22/SC-23) — `PLAN_ISSUE`, не додумывать.
- `AppUser.login` — **ключ** (строчные): только вход, проверка «занят», `ON CONFLICT`, поиск
  `ILIKE`, `ORDER BY`. Всё, что отдаёт логин наружу, читает `AppUser.login_display`.
- Имена полей API и контракт не меняются: `docs/api/openapi.json` и
  `frontend/src/shared/api/schema.d.ts` не перегенерируются и не правятся. Если тест контракта
  краснеет — это ошибка реализации, а не повод перегенерировать.
- Не трогать файлы параллельной работы над доской (T91/T92): `frontend/src/features/boards/*`,
  `frontend/src/features/projects/ProjectPage.tsx`, `frontend/src/shared/i18n/ru.ts`,
  `frontend/src/shared/ui/ui.css`, `frontend/tests/features/boards/*` — кроме T98 после фиксации
  этой работы. `backend/tests/infra/test_stack_first_run.py` не трогать (изменён другой сессией).
- Логины в тестах — синтетические (BR-9); примеры AC (`Ivanov.Petr`, `Sidorova.Anna`, `Mixed.Admin`,
  `Kuznetsov.Oleg`, `QA-Team_1`) допустимы.

## T91 — Доска: создание задачи из колонки, оптимистичный перенос, фильтр по исполнителю
- **Статус:** DONE (ревью APPROVE + T91-R)
- **AC:** решение владельца 2026-10-16; FR-18a, FR-19b, FR-20, FR-28/28a, FR-29, NFR-7, AC-98; контракт — шапка `frontend/tests/features/boards/helpers.tsx`
- **Файлы:** `frontend/src/features/boards/{BoardView.tsx,dnd.ts,api.ts}`, `ProjectPage.tsx`, `ru.ts`, `ui.css`; тесты `frontend/tests/features/boards/{BoardCreate,BoardOptimistic,BoardFilter}.test.tsx`, `dnd.full.test.ts`
- **Заметки:** создание — POST create (в todo) + move для не-todo колонок (backend не менялся); фильтр клиентский, соседи для move по ПОЛНОМУ порядку колонки; бэклог: задача, созданная под фильтром исполнителя, может быть не видна; `createTask` дублирует `tasks/api.ts`.
- **Попытки:** 2

## T92 — Стиль ссылки «На главную»
- **Статус:** DONE
- **Файлы:** `frontend/src/app/router.tsx` (`ui-home-link`), `ui.css`; тесты `theme.test.ts`, `tests/app/home-link.test.tsx`
- **Попытки:** 1

## T93 — Столбец `login_display`: модель и миграция 0005
- **Статус:** DONE
- **AC:** FR-73a (хранение написания; существующие записи получают `login_display = login`), AC-128 (уровень БД), AC-131 (заполнение при обновлении); plan D-66, §11.12.2–§11.12.4
- **Файлы:** `backend/app/domain/users/models.py`, `backend/migrations/versions/0005_login_display.py` (новый),
  `docs/data-model.md` (строка `login_display` в `app_user`, CHECK, строка `0005` в таблице миграций,
  вступление «миграции 0001–0005»); тесты: `backend/tests/db/test_identity_models.py`,
  `backend/tests/db/test_migrations.py`, `backend/tests/factories.py`
- **Зависит от:** —
- **Описание:** Строго по plan §11.12.2–§11.12.4. Модель: `login_display: Mapped[str] =
  mapped_column(String(64), nullable=False, default=_login_display_default)`, где
  `_login_display_default(context: DefaultExecutionContext) -> str` возвращает
  `context.get_current_parameters()["login"]`; `CheckConstraint('lower(login_display COLLATE "C") =
  login', name="login_display_lower")` → имя `ck_app_user_login_display_lower`; докстринг модели и
  комментарии у обоих столбцов: `login` — ключ, не показывать; `login_display` — показ (D-66).
  Миграция 0005 (`revision = "0005"`, `down_revision = "0004"`): `add_column` (NULL) → `UPDATE
  app_user SET login_display = login` → `alter_column(nullable=False)` → `create_check_constraint`;
  `downgrade` — `drop_constraint` и `drop_column`. Код приложения (сервисы, bootstrap, демо) **не
  менять**: Python-default заполняет `login_display = login`, поведение остаётся прежним до T94.
  Фабрика `make_user(login=X)`: в столбец `login` — `X.lower()`, в `login_display` — `X`;
  `UserRow.login` — `X` (так тесты T94–T97 создают учётную запись `Ivanov.Petr` одной строкой).
  `user_values` в `test_identity_models.py` не обязана передавать `login_display` (default).
  Тесты (`test_d66_*`): вставка `login='ivanov.petr', login_display='Ivanov.Petr'` принята;
  `login_display='Ivanov.Pet'` или `'Ivanov.Petr2'` при `login='ivanov.petr'` → `23514`;
  `login_display` со знаком Кельвина (`'Kivan'`) при `login='kivan'` → `23514`; кириллица в
  показе → `23514`; без `login_display` → равен `login`; два пользователя с показами `Ivanov.Petr` и
  `ivanov.petr` → `23505` по `uq_app_user_login`; `UPDATE login_display` в другое написание той же
  длины, но не совпадающее с ключом → `23514`. `test_t93_*`: файл и цепочка 0004 → 0005, голова одна;
  `downgrade 0004` при пользователях → столбца и CHECK нет, строки целы; `upgrade head` →
  `login_display = login` у всех строк, CHECK на месте; `alembic check` чист. Существующие тесты
  (`test_ac116_*` уровня БД, `test_t69_*`) остаются зелёными без ослабления.
- **Готово, когда:** `pytest -q backend/tests/db/test_identity_models.py backend/tests/db/test_migrations.py`
  и `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёные; `alembic -c backend/alembic.ini check`
  чист; `pytest -q backend/tests` зелёный целиком (поведение API не изменилось); линтер и mypy чистые.

## T94 — Учётные записи и справочник: создание с написанием, показ `login_display`
- **Статус:** DONE
- **AC:** AC-125, AC-128, AC-130, OI-129 а) (учётные записи, `GET /users`), AC-116 (тесты приводятся к FR-73a); FR-4, FR-73, FR-73a; plan §11.12.4, §11.12.5
- **Файлы:** `backend/app/domain/users/service.py`, `backend/app/domain/users/directory.py`; тесты:
  `backend/tests/domain/test_user_admin_service.py`, `backend/tests/api/test_admin_users.py`,
  `backend/tests/api/test_users_directory.py`
- **Зависит от:** T93
- **Описание:** По таблице plan §11.12.4 (строки `users/service.py`, `users/directory.py`).
  `create_user`: порядок проверок прежний (`login_invalid` → `login_taken` по ключу → политика
  пароля); вставка `login=normalized, login_display=login`; ответ `UserAccount(login=login)`.
  `_load_target`, `list_accounts`, `list_directory`, `user_refs` читают `AppUser.login_display`;
  `ORDER BY AppUser.login, AppUser.id` и `AppUser.login.ilike(...)` не менять. Докстринг
  `create_user` — «сохраняется написание при вводе, проверки по нормализованному виду». Тесты — по
  строкам AC-125, AC-128, AC-130, OI-129 и AC-116 таблицы plan §11.12.8, в том числе параллельное
  создание `Ivanov.Petr`/`ivanov.petr` (`@pytest.mark.committed`, одно пространство и два разных:
  ровно один успех, второй — `login_taken`, одна строка с ключом `ivanov.petr`, одно событие
  `user.created`). Старые тесты, ждавшие строчного логина в ответе, привести к FR-73a:
  `test_admin_users.py::test_ac116_login_with_capitals_is_normalized_to_lower_case` (ждать
  `Ivan.Petrov`; переименовать по смыслу), `test_user_admin_service.py::test_ac116_login_is_lowercased_on_create`
  (`created.login == "Ivan.Petrov"`; ключ `ivan.petrov` в БД; вход `IVAN.PETROV` проходит),
  `::test_ac116_boundary_valid_logins_are_accepted` (`created.login == good`). Остальные ассерты
  AC-116 (вход в любом регистре, 422 на регистровый дубль и невалидные логины) не ослаблять.
  Поиск по коду: других тестов, ждущих строчного логина в ответе для логина, созданного с
  заглавными, быть не должно — если найдутся вне файлов задачи, перечислить в отчёте.
- **Готово, когда:** `pytest -q backend/tests/domain/test_user_admin_service.py backend/tests/api/test_admin_users.py backend/tests/api/test_users_directory.py backend/tests/domain/test_directory.py backend/tests/cli/test_openapi.py backend/tests/infra/test_frontend_api_types.py`
  зелёный; `git diff --exit-code docs/api/openapi.json frontend/src/shared/api/schema.d.ts` — без
  изменений; линтер и mypy чистые.

## T95 — Вход и профиль: логин в написании при создании
- **Статус:** DONE
- **AC:** AC-126, AC-127; FR-1, FR-61, FR-73a; plan §11.12.4
- **Файлы:** `backend/app/api/deps.py`, `backend/app/domain/auth/service.py`; тесты:
  `backend/tests/api/test_auth_login.py`, `backend/tests/api/test_login_lockout.py`
- **Зависит от:** T93 (можно параллельно с T94: файлы не пересекаются)
- **Описание:** `get_actor` и `service.login` выбирают `AppUser.login_display` (в `Actor.login` и
  `LoginResult.login`); `normalize_login`, `LocalPasswordProvider`, `reserve_attempt` и
  `change_own_password` не менять. Докстринг `service.login`: «логин нормализуется для поиска
  учётной записи; в результате — отображаемый логин (FR-73a)». Тесты — строки AC-126 и AC-127 plan
  §11.12.8 (учётная запись `make_user(login="Ivanov.Petr", role="business_admin")`; сдвиг часов —
  как в существующих тестах блокировки). Существующие `test_ac116_*` с логином, созданным строчными,
  остаются без изменений.
- **Готово, когда:** `pytest -q backend/tests/api/test_auth_login.py backend/tests/api/test_login_lockout.py backend/tests/domain/test_auth_service.py backend/tests/api/test_password_change.py backend/tests/api/test_deps_gates.py`
  зелёный; линтер и mypy чистые.

## T96 — Проекты, участники, журнал: логин в написании при создании
- **Статус:** DONE
- **AC:** AC-129, OI-129 а) (участники проекта); FR-14, FR-14a, FR-15, FR-20, FR-23, FR-41, FR-73a; plan §11.12.4
- **Файлы:** `backend/app/domain/projects/queries.py`, `backend/app/domain/projects/members.py`,
  `backend/app/domain/events/queries.py`; тесты: `backend/tests/api/test_login_display.py` (новый)
- **Зависит от:** T94
- **Описание:** `project_view` — `AppUser.login_display.label("owner_login")`; `list_members` —
  `load_only(AppUser.id, AppUser.login_display, AppUser.is_blocked)` и
  `UserRef(login=u.login_display)`, `ORDER BY AppUser.login, AppUser.id` не менять; `_to_records` —
  `select(AppUser.id, AppUser.login_display)`. Задачи, доска, комментарии, список проектов и «мои
  задачи» берут логин из `user_refs` (исправлено в T94) — здесь только проверяются. Тест
  `test_ac129_*` — сценарий AC-129 целиком через API: `Mixed.Admin` (СМ, фабрика) создаёт через
  `POST /admin/users` учётные записи `Ivanov.Petr`, `Kuznetsov.Oleg`, `Sidorova.Anna` и назначает
  роли через API (нужны записи журнала с автором `Mixed.Admin`); постоянный пароль — сменой
  одноразового через `POST /auth/password` либо служебным `UPDATE` в тесте (на выбор
  test-writer); далее проект, участники, задача с исполнителем `Sidorova.Anna`, комментарий,
  проверки списков и карточек из AC-129, «мои задачи» `Sidorova.Anna`, передача владения
  `Kuznetsov.Oleg`, журнал от имени `Mixed.Admin` (авторы записей), карточка проекта (владелец).
  `test_oi129_members_*` — участники `anna`, `Boris`, `ivan`, `Kirill` → порядок `anna, Boris, ivan, Kirill`.
- **Готово, когда:** `pytest -q backend/tests/api/test_login_display.py backend/tests/api/test_projects.py backend/tests/api/test_project_members.py backend/tests/api/test_audit.py backend/tests/domain/test_projects_service.py backend/tests/domain/test_project_members_service.py`
  зелёный; линтер и mypy чистые.

## T97 — Первый ТА в написании из настройки; обновление существующей установки
- **Статус:** DONE
- **AC:** OI-130 а), FR-6, AC-131; FR-49, FR-64, FR-73a; plan §11.12.3, §11.12.4
- **Файлы:** `backend/app/domain/system/bootstrap.py`; тесты: `backend/tests/cli/test_bootstrap.py`,
  `backend/tests/db/test_login_display_upgrade.py` (новый, `@pytest.mark.committed`)
- **Зависит от:** T94, T95, T96
- **Описание:** `_initial_login(settings) -> tuple[str, str]` — `(ключ, написание из настройки)`;
  `ValueError` для логина вне шаблона — как было (текст без значения). `AppUser(login=ключ,
  login_display=написание, …)`; файл пароля — `login=<написание>\npassword=…`.
  `remove_initial_admin_file_if_for` сравнивает без учёта регистра (`owner.lower() ==
  login.strip().lower()`), докстринг — почему (plan §11.12.4). `ops/demo.py` и CLI не менять (демо-
  логины строчные, `login_display` — default). Тесты: строки OI-130 и AC-131 plan §11.12.8. AC-131:
  на head — `run_bootstrap`, `create_user("ivan.petrov")` от имени первого ТА (доменная функция с
  `Actor` ТА), `load_demo_data(seed=1)`; снимок; `run_alembic(url, "downgrade", "0004")` и
  `"upgrade", "head"` (как `test_t69_*` в `db/test_migrations.py`); после миграций
  `await db_engine.dispose()` перед запросами приложения (кэш подготовленных выражений asyncpg);
  проверки через API (`committed_api_env` или своё приложение поверх `committed`): вход прежними
  паролями (`initial-admin-password.txt`, `demo-passwords.txt`, одноразовый `ivan.petrov`) — `login`
  в ответе прежний; список учётных записей и журнал — прежние логины и число записей; создание
  `Demo.BA1` → 422 `login_taken`. Существующие тесты bootstrap (логин по умолчанию `admin`) не
  менять.
- **Готово, когда:** `pytest -q backend/tests/cli/test_bootstrap.py backend/tests/cli/test_bootstrap_hardening.py backend/tests/cli/test_demo_data.py backend/tests/db/test_login_display_upgrade.py backend/tests/api/test_password_change.py`
  зелёный; линтер и mypy чистые.

## T98 — Фронтенд: порядок исполнителей на доске без учёта регистра, тексты о логине
- **Статус:** DONE
- **AC:** OI-129 а) (фильтр исполнителей доски), AC-132 (подготовка); FR-73a; plan §11.12.6
- **Файлы:** `frontend/src/features/boards/BoardView.tsx`, `frontend/src/features/admin/UsersPage.tsx`
  (только комментарий у строки показа созданного логина), `frontend/src/shared/i18n/ru.ts`
  (только `admin.users.login_hint`); тесты: `frontend/tests/features/boards/BoardFilter.test.tsx`
- **Зависит от:** фиксация параллельной работы над доской T91/T92 (вне этого файла задач: она
  добавила фильтр исполнителей в `BoardView.tsx`, ключи `boards.filter_*` в `ru.ts` и
  `BoardFilter.test.tsx`). От backend-задач не зависит: контракт не меняется.
- **Описание:** В `BoardView.tsx` список исполнителей фильтра сортировать по
  `login.toLowerCase()`, при равенстве — по `id` (сейчас `a.login < b.login` ставит `Boris` раньше
  `anna`). `UsersPage.tsx`: комментарий «The server-side (normalized) login» → «The login as the
  server stored it (FR-73a), not the typed one»; поведение не менять. `ru.ts`
  `admin.users.login_hint`: «От 3 до 64 символов: латинские буквы, цифры, точка, подчёркивание и
  дефис; первый символ — буква или цифра. Логин показывается так, как введён; при входе регистр
  не учитывается». Тест: доска с исполнителями `Boris`, `anna`, `Kirill`, `ivan` → варианты фильтра
  после «Все исполнители» и «Без исполнителя» в порядке `anna, Boris, ivan, Kirill`; карточки
  показывают логины как пришли. `ProjectPage.tsx` (фильтр владельца уже без учёта регистра),
  `UserPicker`, `AuditPage` — не менять.
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` зелёный.

## T99 — Документация: отображаемый логин, обновление, ручная проверка AC-132
- **Статус:** DONE
- **AC:** AC-132 *ручной* (пункт чек-листа), NFR-11, FR-73a; plan §11.12, R-M10
- **Файлы:** `README.md` (ru и en), `docs/acceptance/mvp-demo.md`; тесты:
  `backend/tests/infra/test_docs_static.py` (дополнение, `infra_static`)
- **Зависит от:** T97, T98
- **Описание:** README (ru и en): логин показывается в написании при создании, вход без учёта
  регистра, логин, отличающийся только регистром, занят; `INITIAL_ADMIN_LOGIN` показывается как
  задан, в файле пароля — то же написание; обновление с предыдущей версии MVP — без действий
  оператора (миграция 0005 при старте), логины прежние; откат версии ниже 0005 теряет написание
  (R-M10). Чек-лист `mvp-demo.md`: новый пункт AC-132 (учётные записи `Ivanov.Petr` — БА,
  владелец проекта, и `Sidorova.Anna` — участник, исполнитель с комментарием; перечень экранов из
  AC-132; ожидание — нигде не строчными). Тесты `test_t99_*`: README ru/en упоминают регистр
  логина (ru «регистр», en «case»), чек-лист содержит `AC-132`.
- **Готово, когда:** `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёный;
  `bash scripts/check.sh` зелёный (финальная проверка v0.17); ревьюер подтверждает трассировку plan
  §11.12.8.

### Порядок v0.17 и критический путь

| Задача | Название | Зависит от |
|---|---|---|
| T93 | `login_display`: модель, миграция 0005 | — |
| T94 | Учётные записи и справочник | T93 |
| T95 | Вход и профиль | T93 |
| T96 | Проекты, участники, журнал | T94 |
| T97 | Первый ТА; обновление установки (AC-131) | T94, T95, T96 |
| T98 | Фронтенд: порядок на доске, тексты | фиксация T91/T92 |
| T99 | Документация, AC-132 | T97, T98 |

Критический путь (5 задач): **T93 → T94 → T96 → T97 → T99**. T95 — параллельно с T94; T98 — как
только зафиксирована работа T91/T92, независимо от backend. Риски — plan §11.11 R-M8…R-M11.

---

## Отложено (следующая версия)

Реестр для возврата (MVP-пересборка, архитектор, 2026-10-15). Возврат — отдельной детализацией по
plan §1–§10 с учётом plan §11.2 (D-53…D-65) и §11.11 R-M2. Номера задач и блоков не переиспользуются.

| Исходное | Что | Причина | Что остаётся в MVP | Отложенные FR / AC | Как вернуть |
|---|---|---|---|---|---|
| R1.3 целиком: B1.3-A…G, миграция 0005, plan §4.3 R1.3, §4.15, D-23 | CRM: клиенты, контакты, сделки, воронка, история и лента сделки, связь сделка ↔ проект, CRM в корзине, `restore-crm`, поиск по CRM, фронтенд CRM | решение владельца: CRM — после одобрения таск-трекера | задел R1.0 без изменений (D-53): capabilities `crm_*`, `pipeline_manage`, `EntityType.STAGE/DEAL`, `domain_event.deal_id`, коды ошибок [3] | FR-30…FR-37, FR-25c, CRM-части FR-5, FR-16, FR-25/25b, FR-34/FR-6, FR-38, FR-39, FR-41, FR-49, FR-68, FR-70, FR-72; AC-10, 13, 14, 15, 67, 82–89, 91, 101, 119, 120, 122; CRM-части AC-18, 42, 43, 65, 74, 94 | детализировать B1.3-A…G; миграция 0005; `deal_link` в `ProjectDetail` |
| T40, T64 (метки) | метки, экран меток | не нужны для демо | — | FR-18b, AC-57, AC-69, «метки» в FR-18/AC-47 | таблицы `label`, `task_label` новой миграцией; `label_ids` в схемах задач |
| T46 (упоминания), T47, T48, T62 (упоминания) | `@упоминания`, уведомления, счётчик | не нужны для демо | комментарии без упоминаний (T79, T80, T85) | FR-71, AC-102, AC-116 (упоминание) | таблица `mention`; D-48, Q-4 — дефолт «не снимать» |
| T49, T50, T51, T63 | вложения, `python-multipart`, 413 через прокси | не нужны для демо | nginx уже ограничивает тело 12 МБ (R1.0) | FR-24, C-7, AC-16, 59, 100, 117 | таблица `attachment`; D-27, D-49 |
| T52, T53, T54, T64 (корзина) | корзина, восстановление, окончательное удаление, автоочистка корзины и файлов | не нужны для демо | мягкое удаление с `deleted_batch_id` (D-56); `maintenance` — только сессии | FR-25a, FR-25b, AC-62, 63, 99 (восстановление), 112, 118, AC-18 («в корзине»), AC-66 (окончательное удаление) | `trash` по plan §10.6, `place_after`; Q-2/Q-3 — дефолты |
| T36/T38/T59 (архив) | архив проекта, 409 `project_archived` | не нужен для прав (D-57) | — | FR-14b, BR-13, AC-70, AC-71, 409-части AC-106, AC-110, AC-65 (архив) | `ADD COLUMN status … DEFAULT 'active'`; шаг 409 во всех изменяющих сервисах |
| T55, T65 (лента) | лента активности проекта, «объект удалён» | не нужна для демо | события аудита пишутся (D-55) | FR-38, AC-90, UF-9 | писать события ленты во всех сервисах (каталог T30 готов); Q-5 — дефолт |
| T56, T65 (поиск) | поиск по названиям, `pg_trgm` | не нужен для демо | — | FR-39, AC-92, UF-10 | расширение и GIN-индексы новой миграцией |
| B1.2-B (часть) | фильтры по сроку, общий список `GET /tasks` | часовые пояса FR-27a — отдельная работа | фильтры исполнитель и статус в списке проекта (D-62) | FR-27a, AC-60, AC-68 (фильтры), AC-111 | `tasks/queries` |
| B1.4-B | экспорт/импорт JSON | прототип | — | FR-40, AC-17, AC-93, UF-11 | plan §4.10 (экспорт/импорт) |
| B1.4-C | резервная копия и восстановление | прототип (Q-M3) | — | FR-50, AC-12, UF-12 | сервис `ops`, D-35 |
| B1.4-D | генератор нагрузки, замер NFR-2, калибровка Argon2 | прототип | индексы plan §11.6; команда `hash-bench` (R1.0) | FR-72, NFR-2, AC-19, AC-38 (замер), AC-96 | plan §5.1, D-36, D-37 |
| B1.4-E (часть) | Playwright e2e | прототип | ручная проверка опроса в чек-листе (T88) | AC-107 | `@playwright/test`, plan §7.2 |
