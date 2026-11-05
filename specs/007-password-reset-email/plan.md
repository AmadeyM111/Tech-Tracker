# Plan: Самостоятельный сброс пароля по email с экрана входа (spec 007)

- **Spec:** ./spec.md (v0.1, статус APPROVED 2026-11-04); ADR-0017 (принято), ADR-0004, ADR-0006, ADR-0010
- **Разведка:** ./context.md
- **Статус:** APPROVED — владелец принял предложенные варианты Q-1, Q-3, Q-5, Q-6, Q-11, Q-12 (2026-11-05); остальные Q-n — по предложению плана
- **Обозначения:** решения плана — `PR-n`, вопросы к spec — `Q-n` (раздел 9), задачи — `R7-Tnn` (tasks.md;
  префикс `R7-` нужен, потому что `T01…` уже заняты в `specs/001-pilot-r1/tasks.md`, а `scripts/task_scope.py`
  требует уникальный ID во всех `specs/*/tasks.md`).

## 1. Подход

Бэкенд получает колонку `app_user.email` (хранится нормализованной: обрезка пробелов и нижний регистр, с
`UNIQUE` и `CHECK`, как `login`, D-39) и две служебные таблицы: `password_reset_token` (SHA-256 токена,
срок, `used_at`) и `password_reset_attempt` (HMAC ключа лимита и время, для FR-9). Логика сброса живёт в
новом доменном модуле `app/domain/auth/password_reset.py` (запрос и подтверждение) и `reset_limits.py`
(лимиты). Публичный роутер `app/api/v1/password_reset.py` только вызывает домен. Письмо уходит после
COMMIT через FastAPI `BackgroundTasks` + `asyncio.to_thread(smtplib)`: ответ не ждёт SMTP (NFR-2), а
открытый токен не хранится нигде, кроме памяти процесса и письма (FR-8). Без `SMTP_HOST` в `app.state`
нет политики сброса: оба POST отвечают 404 `feature_disabled`, а публичный
`GET /auth/password-reset/status` отдаёт `{"enabled": false}`, и фронт скрывает ссылку (AC-2).
Администратор задаёт email при создании и через новый `PUT /admin/users/{id}/email`. Экспорт исключает
колонку `email` и обе новые таблицы явным механизмом в `archive.py`. Фронт: ссылка на `/login`, два
публичных экрана (без `GuestOnly`, `/me` не вызывается) и колонка/диалог email в `UsersPage`.

## 2. Решения

| # | Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---------|---------|--------------------------|--------|
| PR-1 | Регистронезависимая уникальность email | Колонка `email varchar(254) NULL`, значение нормализуется в Python (`strip().lower()`), `UNIQUE (email)` (`uq_app_user_email`) + `CHECK (lower(email COLLATE "C") = email)` (`ck_app_user_email_lower`) | Функциональный `UNIQUE INDEX (lower(email))`; `citext` | Проверенный в проекте приём D-39/D-66 (`login`). `alembic check` в `scripts/check.sh` надёжно сравнивает обычный `UNIQUE`, а для индексов по выражению бывают ложные расхождения. Поиск по `email = :normalized` без `lower()` в каждом запросе. `citext` — расширение БД. Цена: администратор видит адрес в нижнем регистре (Q-8) |
| PR-2 | «Активная» учётная запись | FR-1: уникальность среди **всех** строк `app_user` (мягкого удаления нет, заблокированные тоже держат адрес). FR-7/FR-14: активна = `is_blocked = false` **и** есть строка `workspace_member` (как при входе: `auth/service.py:login`) | Частичный уникальный индекс `WHERE NOT is_blocked` | Удалённых записей нет. Если уникальность учитывает блокировку, разблокировка может дать дубль. Без членства вход и так невозможен (Q-3) |
| PR-3 | Код занятого email | **409 `email_taken`** (новый `EmailTaken(AppError)`), как требует AC-1 | 422 `email_taken` по образцу `login_taken` | AC-1 задаёт статус явно, spec — источник истины. 409 семантически верен (конфликт с существующим ресурсом). Фронт различает ошибки по `code`, статус ему не важен. Расхождение с `login_taken` (422) фиксируется в Q-6, `login_taken` не меняется |
| PR-4 | Имена событий аудита | `user.password_reset_requested`, `user.password_reset_completed`, `user.email_changed` (entity `user`, `audit=True`, `fields` пустые) | Буквально `password_reset_requested` без префикса | Все действия в каталоге имеют вид `<entity>.<action>`. `AuditPage`/`ru.ts` строят подписи из этого вида. Spec называет события логически (так же как `users.email` при таблице `app_user`). Значение задаётся одной константой в `catalog.py`. **Нужно подтверждение владельца (Q-1)** |
| PR-5 | Workspace и актор публичных событий | `workspace_id` — первое членство пользователя (`ORDER BY workspace_member.created_at, workspace_id LIMIT 1`, как в `login`). `completed`: `actor_id = user_id`. `requested`: `actor_id = NULL` (запросивший анонимен) | Событие в каждом пространстве; `actor_id = user_id` для `requested` | В пилоте одно пространство. Пользователь без членства не считается активным (PR-2), поэтому workspace есть всегда. Запрос может прийти от постороннего, приписывать его пользователю нельзя (Q-2) |
| PR-6 | Доставка письма (NFR-2) | FastAPI `BackgroundTasks` в том же процессе: обработчик получает от домена `MailMessage \| None` и при наличии ставит `deliver(mailer, message)`; `deliver` вызывает `asyncio.to_thread(mailer.send, message)` и при любой ошибке пишет в лог только тип исключения | Очередь в БД с отдельным отправителем | `DbSession` (`Depends(get_db, scope="function")`) фиксирует транзакцию до ответа, а фоновые задачи Starlette выполняются после отправки ответа и только при успехе. Значит, письмо уходит после COMMIT, клиент SMTP не ждёт. Очередь в БД потребовала бы хранить открытый токен или текст письма (нарушает FR-8 «в БД только SHA-256») и отдельный процесс. Цена: при падении процесса письмо теряется, пользователь повторяет запрос (риск R-3) |
| PR-7 | Ограничение частоты (FR-9) | Таблица `password_reset_attempt(id, scope 'email'\|'ip', key_hash bytea(32), created_at)`. Ключ — `HMAC-SHA256(secret_key, "<scope>:" + значение)`. В транзакции запроса: удаление строк старше часа → `pg_advisory_xact_lock` по ключам → подсчёт за час → при `email ≥ 3` или `ip ≥ 10` отказ (строки не пишутся), иначе вставка обеих строк | Счётчики в памяти процесса; Redis; slowapi | Новых зависимостей нет (NFR-5). Счётчик в памяти теряется при перезапуске. HMAC вместо открытого email/IP: адреса посторонних и IP не хранятся в открытом виде (NFR-1). Отклонённые запросы не продлевают окно, поэтому злоумышленник не может держать блокировку бесконечно |
| PR-21 | Невалидный адрес в лимитах (решение владельца: учитывается только в лимите IP) | `reset_limits.register_request(db, key, *, email: str | None, ip, now)`. При `email=None` область `email` не проверяется и не пишется, остальная логика без изменений. `password_reset.request_reset` нормализует адрес; при невалидном вызывает `register_request(email=None, ip=…)` и возвращает `None` | Отдельная функция для IP в обход модуля лимитов | Один механизм лимитов, без дублирования счётчика. Открытого адреса нет даже в проверке. Найдено в R7-T08 (PLAN_ISSUE). Уточнение механики, решение владельца (невалидный адрес — только в лимите IP) не меняется; оркестратор принял правку, владелец проверит в ревью |
| PR-8 | IP клиента | `request.client.host`, без чтения `X-Forwarded-For` в коде | Разбор `X-Forwarded-For` в приложении | Поставляемый запуск: `uvicorn --proxy-headers --forwarded-allow-ips='*'` (`backend/docker-entrypoint.sh`), api наружу не опубликован, nginx перезаписывает `X-Forwarded-For $remote_addr` (`deploy/web/default.conf.template`). Uvicorn уже подставляет адрес клиента в `scope["client"]`. Подделанный клиентом заголовок до api не доходит. `client is None` → лимит по IP не применяется, лимит по email действует |
| PR-9 | Признак «функция включена» для фронта | Новый публичный `GET /api/v1/auth/password-reset/status` → `{"enabled": bool}` (всегда 200) | Поле в `/health`; поле в ответе `/me` | `/health` — healthcheck контейнера, его контракт `{"status":"ok"}` лучше не менять. `/me` требует сессию. Новый маршрут добавляется в `PUBLIC` тестов гардов (`test_route_guards.py`) и в `public` у `test_openapi.py::test_d33_*` |
| PR-10 | Источник ссылки в письме | Новая переменная `PUBLIC_BASE_URL` (`http(s)://host[:port]`, без пути и `/` на конце). Обязательна, если задан `SMTP_HOST`, иначе приложение не стартует (Fail Fast) | Строить из заголовков `Host`/`Origin` запроса | Заголовки подделываются (атака «подмена ссылки сброса»). Переменной нет в списке FR-3 (Q-5) |
| PR-11 | Модуль домена | `app/domain/auth/password_reset.py` (`request_reset`, `confirm_reset`), `app/domain/auth/reset_limits.py`, `app/domain/auth/reset_mail.py` (единственный шаблон письма, NFR-3), `app/domain/users/email.py` (`normalize_email`) | Всё в `auth/service.py` | `service.py` уже около 300 строк. `commit_durably` сбросу не нужен: все записи (лимиты, токены, события) фиксируются обычным COMMIT запроса, а ветки ошибок ничего сохранять не должны. AST-ограничение на `commit_durably` не затрагивается |
| PR-12 | SMTP-адаптер | `app/core/mail.py`: `MailMessage`, протокол `Mailer`, `SmtpMailer` (stdlib `smtplib` + `email.message.EmailMessage`, таймаут 10 с, STARTTLS через `ssl.create_default_context()`), `deliver()`. В `lifespan`: `state.mailer = SmtpMailer(settings)` и `state.password_reset_policy = ResetPolicy(...)` только при `SMTP_HOST`, иначе оба `None` | `aiosmtplib` | NFR-5: только stdlib. Синхронный вызов уходит в поток через `asyncio.to_thread`. Неявный TLS (порт 465) не поддерживается: в FR-3 только `SMTP_STARTTLS` |
| PR-13 | Подмена SMTP в тестах | `tests/mail_support.py::RecordingMailer` (список `MailMessage`) ставится в `app.state.mailer` после старта lifespan фикстурой `reset_api_env` (`tests/conftest.py`). Настройки фикстуры: `smtp_host="smtp.invalid"`, `smtp_from="tracker@example.test"`, `public_base_url="https://tracker.example.test"`. Модульные тесты `SmtpMailer` подменяют `smtplib.SMTP` через `monkeypatch` | Локальный SMTP-сервер в тестах | Тесты не ходят в сеть (NFR-6) и не зависят от порядка |
| PR-14 | Экспорт/импорт | В `archive.py`: `EXCLUDED_TABLES` += `password_reset_token`, `password_reset_attempt`; новый `EXCLUDED_COLUMNS = {"app_user": frozenset({"email"})}` и функция `exported_columns(table)`. `export._read_table` выбирает только эти колонки, `importer._decode_table` сверяет строки с ними же. При вставке `email` не передаётся (NULL). `importer.AUTO_TABLES` начинается с `password_reset_token`, `password_reset_attempt` (чистятся вместе с автоданными) | Удалять email из payload после выборки | Явный механизм проверяется тестом. Цикл export→import→export остаётся идентичным. `schema_version` = голова alembic, поэтому архивы 0007 по-прежнему отвергаются, как и раньше (ADR-0010). «Старые архивы» с совпадающей версией появиться не могут |
| PR-15 | Проверка нового пароля | Своя обёртка `_check_new_password` в `password_reset.py`: кодировка → `validate_new_password` → `Unprocessable(code=exc.code)` (как `users/service.py:_check_one_time_password`). Проверки `password_reused` нет | Переиспользовать `auth/service._check_new_password` | Там проверяется совпадение с текущим паролем, а при сбросе текущего нет (context.md). Это третья копия 8 строк. Общий хелпер с переводом двух старых вызовов — вне рамок фичи (долг DRY, отмечен для ревьюера) |
| PR-16 | Эффекты успешного `confirm` | Одной транзакцией: `used_at = now` (условный `UPDATE … WHERE used_at IS NULL AND expires_at > now RETURNING`) → `app_user`: новый хеш, `must_change_password=false`, `password_changed_at=now`, `failed_login_count=0`, `login_locked_until=NULL` (`WHERE NOT is_blocked`) → удаление остальных неиспользованных токенов пользователя → `sessions.delete_all_for_user` → событие `completed` → удаление файла пароля первого ТА после COMMIT (как в `change_own_password`) | Не трогать `must_change_password` и счётчики входа | Владелец почты доказал владение учётной записью. Пароль задан им самим (FR-13), блокировка перебора снимается, как при смене пароля (Q-11) |
| PR-17 | Публичные экраны фронта | Маршруты `/password-reset` и `/password-reset/confirm` до `*`, без `GuestOnly` | Обернуть в `GuestOnly` | `GuestOnly` запрашивает `/me`, 401 вызывает `onUnauthenticated` и уводит на `/login`. Ссылка из письма открывалась бы с потерей токена. Без обёртки экраны не делают запросов с сессией. Вошедший пользователь тоже может сбросить пароль, его сессии будут завершены (FR-13) |
| PR-18 | Токен из фрагмента (FR-10) | Читается один раз в ленивом инициализаторе `useState(() => parseToken(window.location.hash))`. В `useEffect` вызывается `window.history.replaceState(window.history.state, "", pathname + search)` (state роутера сохраняется) | `useLocation().hash` + `navigate(..., {replace:true})` | Вызов `navigate` до чтения в StrictMode может потерять токен. Сохранение `history.state` не ломает индекс BrowserRouter |
| PR-19 | Ответ `request` | 200, `{"detail": "Если для этого адреса есть учётная запись, мы отправили письмо со ссылкой."}` (схема `PasswordResetAccepted`), без cookie. Невалидный по формату email — тот же ответ (только лимит IP), а не 422. 422 только для отсутствующего поля, строки длиннее 254 и лишних полей | 202; 422 на «плохой» email | Единый ответ FR-6. Формат адреса не раскрывает существование учётной записи, но разный ответ на него дал бы лишний сигнал |
| PR-20 | Порядок проверок `confirm` | `feature_disabled` (404) → валидация схемы (422) → токен (400 `reset_token_invalid`: не найден, просрочен, использован, пользователь заблокирован или без членства) → политика пароля (422) → хеширование → условное поглощение токена | Сначала политика пароля | С неверным токеном пароль подбирать бессмысленно, пользователь должен запросить новую ссылку. AC-9: при 422 токен не расходуется (откат и поглощение после проверки) |

## 3. Затрагиваемые модули и файлы

**Бэкенд — схема и модели**
- `backend/migrations/versions/0008_password_reset_email.py` — новый: `app_user.email` + `uq_app_user_email` + `ck_app_user_email_lower`; таблицы `password_reset_token`, `password_reset_attempt`; downgrade удаляет всё это.
- `backend/app/domain/users/models.py` — изменяется: `email` и CHECK.
- `backend/app/domain/auth/models.py` — изменяется: `PasswordResetToken`, `PasswordResetAttempt`.
- `backend/tests/upgrade002_support.py:67`, `backend/tests/db/test_migrations.py` (`"0007"` в строках ~962, 996, 1010, 1060) — голова `0008`.
- `backend/tests/factories.py` — `make_user(..., email: str | None = None)`.

**Бэкенд — ядро**
- `backend/app/core/errors.py` — `FeatureDisabled` (404), `ResetTokenInvalid` (400), `EmailTaken` (409), `ErrorCode.email_invalid` (422).
- `backend/app/core/config.py` — `smtp_*`, `public_base_url`, `password_reset_enabled`, валидаторы.
- `backend/app/core/mail.py` — новый: SMTP-адаптер.
- `backend/app/main.py` — `lifespan`: `state.mailer`, `state.password_reset_policy`.
- `.env.example`, `docker-compose.yml` (`api.environment`), `deploy/dev.env.example` (закомментированный пример) — переменные `SMTP_*`, `PUBLIC_BASE_URL`.

**Бэкенд — домен**
- `backend/app/domain/users/email.py` — новый: `normalize_email`.
- `backend/app/domain/users/service.py` — `email` в `UserAccount`/`_Target`/`list_accounts`/`_load_target`; `create_user(..., email=)`; новый `set_email`.
- `backend/app/domain/events/catalog.py` — три новых действия.
- `backend/app/domain/auth/reset_limits.py` — новый.
- `backend/app/domain/auth/reset_mail.py` — новый: шаблон письма.
- `backend/app/domain/auth/password_reset.py` — новый: `ResetPolicy`, `request_reset`, `confirm_reset`.
- `backend/app/domain/auth/service.py` — `_remove_initial_admin_file_after_commit` переименовать в публичный `remove_initial_admin_file_after_commit` (единственное изменение файла).
- `backend/app/domain/ops/archive.py`, `export.py`, `importer.py` — исключения (PR-14).

**Бэкенд — API**
- `backend/app/api/v1/schemas/admin.py` — `AdminUser.email`, `CreateUserRequest.email`, `SetEmailRequest`.
- `backend/app/api/v1/admin_users.py` — `PUT /{user_id}/email`.
- `backend/app/api/v1/schemas/password_reset.py` — новый.
- `backend/app/api/v1/password_reset.py` — новый роутер `/auth/password-reset`.
- `backend/app/api/v1/__init__.py` — подключение роутера.
- `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` — только перегенерацией `bash scripts/gen-api.sh`.
- Тесты, которые меняются: `backend/tests/api/test_route_guards.py` (`PUBLIC`), `backend/tests/cli/test_openapi.py` (`public` в `test_d33_*`, `BODY_ROUTES_400`), `backend/tests/unit/test_event_catalog.py` (`USER_ACTIONS`), `backend/tests/unit/test_config.py`, `backend/tests/infra/test_compose_static.py`, `backend/tests/cli/test_export_import.py`, `backend/tests/conftest.py` (фикстура `reset_api_env`), `backend/tests/infra/test_frontend_scaffold.py` (белый список `frontend/src`).

**Фронтенд**
- `frontend/src/shared/i18n/ru.ts` — ключи (§4.7).
- `frontend/src/features/admin/AuditPage.tsx` — `ACTION_CODES` += три действия.
- `frontend/src/features/auth/api.ts` — `passwordResetStatus`, `requestPasswordReset`, `confirmPasswordReset`.
- `frontend/src/features/auth/LoginPage.tsx` — ссылка «Забыли пароль?».
- `frontend/src/features/auth/PasswordResetRequestPage.tsx` — новый.
- `frontend/src/features/auth/PasswordResetConfirmPage.tsx` — новый.
- `frontend/src/app/router.tsx` — два маршрута.
- `frontend/src/features/admin/api.ts` — `createUser` с `email`, `setUserEmail`.
- `frontend/src/features/admin/UsersPage.tsx` — колонка email, метка «email не указан», поле email при создании, кнопка «Изменить email».
- `frontend/src/features/admin/EmailDialog.tsx` — новый: диалог изменения/очистки email.

## 4. Интерфейсы

### 4.1 Схема БД (миграция 0008, `revision="0008"`, `down_revision="0007"`, литералы без импорта `app.*`)

```text
app_user.email            varchar(254) NULL
  uq_app_user_email        UNIQUE (email)                       -- NULL допускается многократно
  ck_app_user_email_lower  CHECK (lower(email COLLATE "C") = email)

password_reset_token
  id          uuid PK
  user_id     uuid NOT NULL FK app_user.id ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE, index
  token_hash  bytea NOT NULL UNIQUE, CHECK (octet_length(token_hash) = 32)   -- SHA-256
  created_at  timestamptz NOT NULL
  expires_at  timestamptz NOT NULL
  used_at     timestamptz NULL

password_reset_attempt
  id          uuid PK
  scope       text NOT NULL CHECK (scope IN ('email','ip'))
  key_hash    bytea NOT NULL CHECK (octet_length(key_hash) = 32)             -- HMAC-SHA256
  created_at  timestamptz NOT NULL
  ix_password_reset_attempt_scope_key_hash_created_at (scope, key_hash, created_at)
  ix_password_reset_attempt_created_at (created_at)
```
Имена ограничений и индексов следуют naming convention из `backend/app/core/models.py`. Модели объявляют те же
объекты, `alembic check` должен быть чист. Время пишется через `utcnow()` (без `DEFAULT now()`).

### 4.2 Ядро

```python
# app/core/errors.py
class FeatureDisabled(AppError):  status_code = 404; code = "feature_disabled"; default_detail = "Функция отключена"
class ResetTokenInvalid(AppError): status_code = 400; code = "reset_token_invalid"; default_detail = "Ссылка для сброса пароля недействительна"
class EmailTaken(AppError):       status_code = 409; code = "email_taken"; default_detail = "Email уже используется"
class ErrorCode(StrEnum): ...; email_invalid = "email_invalid"   # раздел [007]

# app/core/config.py (Settings)
smtp_host: str | None = None          # ""/пробелы → None; None → функция выключена
smtp_port: int = 587
smtp_user: str | None = None          # ""→None
smtp_password: SecretStr | None = None  # ""→None
smtp_from: str | None = None          # ""→None; обязателен при smtp_host
smtp_starttls: bool = True
public_base_url: str | None = None    # ""→None; обязателен при smtp_host; ^https?://[^/\s]+$ (без пути и "/")
@property
def password_reset_enabled(self) -> bool: return self.smtp_host is not None
# model_validator(mode="after"): smtp_host задан, а smtp_from или public_base_url нет → ValueError (имя поля, без значений)

# app/core/mail.py
@dataclass(frozen=True)
class MailMessage:
    to: str = field(repr=False)
    subject: str
    body: str = field(repr=False)

class Mailer(Protocol):
    def send(self, message: MailMessage) -> None: ...

class SmtpMailer:
    def __init__(self, settings: Settings) -> None: ...   # требует settings.smtp_host и smtp_from
    def send(self, message: MailMessage) -> None: ...     # smtplib.SMTP(host, port, timeout=10); starttls(context=ssl.create_default_context()) при smtp_starttls; login при smtp_user; send_message(EmailMessage)

async def deliver(mailer: Mailer, message: MailMessage) -> None:
    """asyncio.to_thread(mailer.send, message); Exception → logger.warning("…: %s", type(exc).__name__); наружу не выходит."""
```
Логгер `app.mail`. В лог не попадают адрес, тема, тело, ссылка и текст исключения.

### 4.3 Домен

```python
# app/domain/users/email.py
MAX_EMAIL_LENGTH: Final = 254
def normalize_email(value: str) -> str | None:
    """strip() → lower(); None, если пусто, длиннее 254, не ровно один '@', пустая локальная часть или домен,
    есть пробельные или непечатаемые символы (str.isprintable). Для админки: None от непустого ввода → 422 email_invalid."""

# app/domain/users/service.py
@dataclass(frozen=True) class UserAccount: ...; email: str | None     # то же поле в _Target
async def create_user(db, actor, hasher, *, login: str, one_time_password: SecretStr, email: str | None = None) -> UserAccount
    # порядок: login_invalid → login_taken → email_invalid (422) → email_taken (409) → политика пароля
async def set_email(db: AsyncSession, actor: Actor, user_id: UUID, email: str | None, /) -> UserAccount
    # MANAGE_ACCOUNTS (403) → нормализация ("" и None → None; плохой → 422 email_invalid) → _lock_for_account_change
    # → _load_target (404) → то же значение: без изменений и без события → занят другим → 409 → UPDATE
    # → событие user.email_changed (без fields/details)
# Гонка за один адрес: UPDATE/INSERT в db.begin_nested(); IntegrityError по uq_app_user_email → EmailTaken.

# app/domain/events/catalog.py
USER_EMAIL_CHANGED = "user.email_changed"
USER_PASSWORD_RESET_REQUESTED = "user.password_reset_requested"
USER_PASSWORD_RESET_COMPLETED = "user.password_reset_completed"   # все три → _USER_AUDITED

# app/domain/auth/reset_limits.py
EMAIL_LIMIT: Final = 3
IP_LIMIT: Final = 10
LIMIT_WINDOW: Final = timedelta(hours=1)
def limit_key_hash(key: bytes, scope: Literal["email", "ip"], value: str) -> bytes   # HMAC-SHA256(key, f"{scope}:{value}")
async def register_request(db: AsyncSession, key: bytes, *, email: str, ip: str | None, now: datetime) -> bool
    """1) DELETE attempt WHERE created_at <= now - LIMIT_WINDOW; 2) pg_advisory_xact_lock(ns, hashtext(hex(hash)))
    по каждому ключу в фиксированном порядке (email, ip); 3) COUNT за окно; email ≥ 3 или ip ≥ 10 → False, ничего не пишется;
    4) иначе INSERT обеих строк (ip — если не None) → True. email — нормализованный или strip().lower() сырого ввода."""

# app/domain/auth/reset_mail.py
SUBJECT: Final = "Сброс пароля"
def build_reset_mail(*, to: str, link: str, ttl: timedelta) -> MailMessage
    """Тело (рус.): ссылка, «Ссылка действует 30 минут и сработает один раз.», «Если это были не вы, ничего не делайте:
    пароль останется прежним.». Логина, пароля и хеша нет. Единственный шаблон письма (NFR-3)."""

# app/domain/auth/password_reset.py
TOKEN_TTL: Final = timedelta(minutes=30)
TOKEN_BYTES: Final = 32
@dataclass(frozen=True)
class ResetPolicy:
    base_url: str
    limit_key: bytes = field(repr=False)        # = ensure_secret_key(settings)

def new_token() -> tuple[str, bytes]             # (secrets.token_urlsafe(32), sha256(token).digest())
def token_hash(token: str) -> bytes | None        # None для не-ASCII
def reset_link(base_url: str, token: str) -> str  # f"{base_url}/password-reset/confirm#token={token}"

async def request_reset(db: AsyncSession, policy: ResetPolicy | None, *, email: str, client_ip: str | None,
                        now: datetime) -> MailMessage | None:
    """policy None → FeatureDisabled. register_request (лимиты) → normalize_email → активный пользователь по email
    (не заблокирован, есть членство; workspace по PR-5) → DELETE его неиспользованных токенов → INSERT нового
    (expires_at = now + TOKEN_TTL) → record_event(REQUESTED, actor_id=None, entity_id=user_id, workspace_id=…)
    → build_reset_mail. Любая ветка «нет письма» → None. Исключений, кроме FeatureDisabled, нет."""

async def confirm_reset(db: AsyncSession, policy: ResetPolicy | None, hasher: PasswordHasher, sessions: SessionStore,
                        settings: Settings, *, token: SecretStr, new_password: SecretStr, now: datetime) -> None:
    """Порядок — PR-20, эффекты — PR-16. Ошибки: FeatureDisabled, ResetTokenInvalid, Unprocessable(password_too_short |
    password_too_common | validation_error). Значения токена и пароля в исключения и логи не попадают."""
```
Ограничения ruff (`C901`/`PLR0912`/`PLR0913`/`PLR0915`): функции дробить на приватные помощники
(`_find_active_user`, `_issue_token`, `_load_valid_token`, `_consume_token`, `_apply_new_password`).

### 4.4 API

| Метод и путь | Доступ | Тело | Ответ | Ошибки (`{"detail","code"}`) |
|---|---|---|---|---|
| `GET /api/v1/auth/password-reset/status` | публичный | — | 200 `PasswordResetStatus {enabled: bool}` | — |
| `POST /api/v1/auth/password-reset/request` | публичный (+`check_origin`) | `PasswordResetRequest {email: str, 1..254}` (`extra=forbid`) | 200 `PasswordResetAccepted {detail: str}` | 400 `bad_request`, 403 `origin_mismatch`, 404 `feature_disabled`, 422 валидация |
| `POST /api/v1/auth/password-reset/confirm` | публичный (+`check_origin`) | `PasswordResetConfirm {token: SecretStr ≤128, new_password: Password}` (`extra=forbid`, `_require_encodable`) | 204 | 400 `bad_request` / `reset_token_invalid`, 403 `origin_mismatch`, 404 `feature_disabled`, 422 `password_too_short` / `password_too_common` / `validation_error` |
| `PUT /api/v1/admin/users/{user_id}/email` | `MANAGE_ACCOUNTS` | `SetEmailRequest {email: str \| null, ≤254}` (`extra=forbid`) | 200 `AdminUser` | 400, 401, 403, 404, 409 `email_taken`, 422 `email_invalid` |
| `POST /api/v1/admin/users` (изм.) | как было | `CreateUserRequest` + `email: str \| null = null` | 201 `AdminUser` | + 409 `email_taken`, 422 `email_invalid` |
| `GET /admin/users`, `GET /admin/users/{id}`, `PUT …/role` (изм.) | как было | — | `AdminUser` + `email: str \| null` | — |

- Роутер `app/api/v1/password_reset.py`: `APIRouter(prefix="/auth/password-reset", tags=["auth"])`. Имена функций
  (operationId, D-32): `password_reset_status`, `request_password_reset`, `confirm_password_reset`. Обработчик
  `request_password_reset(body, request, db: DbSession, background: BackgroundTasks)` вызывает домен один раз и
  при `MailMessage` делает `background.add_task(deliver, request.app.state.mailer, message)`.
- Ответ 400 в OpenAPI объявляется через `error_responses(400)` со стандартным описанием (`test_t68_*` требует
  точный текст `BAD_JSON_DESCRIPTION`). Код `reset_token_invalid` описывается в docstring обработчика.
  404 и 409 — `error_response(404|409, "<описание с code>")`.
- `test_openapi.py::BODY_ROUTES_400` += `("POST", "/api/v1/auth/password-reset/request")`,
  `("POST", "/api/v1/auth/password-reset/confirm")`, `("PUT", "/api/v1/admin/users/{user_id}/email")`.
  `public` в `test_d33_*` и `PUBLIC` в `test_route_guards.py` += три публичных маршрута.
- `AdminUser` docstring: «ровно семь полей». `email` отдаётся только в ответах `/admin/users*` (FR-1).

### 4.5 Состояние приложения (`main.py:_lifespan`)
```python
if settings.password_reset_enabled:
    state.mailer = SmtpMailer(settings)
    state.password_reset_policy = ResetPolicy(base_url=settings.public_base_url, limit_key=ensure_secret_key(settings))
else:
    state.mailer = None
    state.password_reset_policy = None
```

### 4.6 Тестовая инфраструктура
```python
# backend/tests/mail_support.py
class RecordingMailer:
    sent: list[MailMessage]
    def send(self, message: MailMessage) -> None: self.sent.append(message)

# backend/tests/conftest.py
RESET_SETTINGS = {"smtp_host": "smtp.invalid", "smtp_from": "tracker@example.test",
                  "public_base_url": "https://tracker.example.test"}
@pytest_asyncio.fixture
async def reset_api_env(settings, fixed_clock, db_sessionmaker) -> AsyncIterator[ApiEnv]:
    """create_app(settings.model_copy(update=RESET_SETTINGS)); после старта lifespan app.state.mailer = RecordingMailer().
    Доступ к письмам: env.app.state.mailer.sent."""
```
Лимиты в тестах обходятся `fixed_clock.advance(timedelta(minutes=61))` или `httpx.ASGITransport(app=…, client=(ip, port))`.

### 4.7 Фронтенд

```ts
// features/auth/api.ts
export type PasswordResetStatus = components["schemas"]["PasswordResetStatus"];
export async function passwordResetStatus(): Promise<PasswordResetStatus>;           // GET …/status
export async function requestPasswordReset(email: string): Promise<void>;            // POST …/request
export async function confirmPasswordReset(token: string, newPassword: string): Promise<void>; // POST …/confirm
// features/admin/api.ts
export async function createUser(body: CreateUserRequest): Promise<AdminUser>;       // body.email?: string | null
export async function setUserEmail(userId: string, email: string | null): Promise<AdminUser>; // PUT …/email
```
- `LoginPage`: `useQuery({queryKey: ["auth","password-reset-status"], queryFn: passwordResetStatus, retry: false,
  refetchOnWindowFocus: false})`. Ссылка `<Link to="/password-reset">` под кнопкой «Войти», до блока справки
  `ui-login-help`, только при `data?.enabled === true`. Блок справки не меняется (FR-17).
- `PasswordResetRequestPage` (`/password-reset`): `h1`, одно поле `TextField` «Email» (`type="email"`,
  `autoComplete="email"`), кнопка «Отправить ссылку». Успех: `role="status"` с текстом `auth.reset_request_sent`,
  форма скрыта. Ошибка: `errorMessage(code)` через `ErrorAlert`. Ссылка «Вернуться ко входу» → `/login`.
- `PasswordResetConfirmPage` (`/password-reset/confirm`): PR-18. Токена нет → сообщение
  `auth.reset_link_invalid` + ссылка на `/password-reset`. Поля «Новый пароль» и «Повторите пароль»
  (`reveal`, `PASSWORD_MIN_LENGTH`), кнопка «Сохранить пароль». Несовпадение → `auth.password_mismatch`
  без запроса. Успех → `auth.reset_done` + ссылка «Войти» на `/login` (без автоматического входа).
  `reset_token_invalid` → текст ошибки + ссылка на `/password-reset`.
- `UsersPage`: колонка `data-field="email"`: адрес или метка `admin.users.email_missing` («email не указан»).
  Поле «Email (необязательно)» в форме создания. Кнопка «Изменить email» в строке открывает `EmailDialog`
  (поле с текущим значением; пустое значение очищает адрес; ошибки `email_taken`/`email_invalid` показываются
  в диалоге).
- Ключи `ru.ts` (значения — кириллица, `error.*` попарно различны):
  `auth.forgot_password` «Забыли пароль?», `auth.reset_request_title` «Сброс пароля»,
  `auth.reset_email_label` «Email», `auth.reset_request_submit` «Отправить ссылку»,
  `auth.reset_request_sent` «Если для этого адреса есть учётная запись, мы отправили письмо со ссылкой.»,
  `auth.reset_back_to_login` «Вернуться ко входу», `auth.reset_confirm_title` «Новый пароль»,
  `auth.reset_new_password_label` «Новый пароль», `auth.reset_repeat_password_label` «Повторите пароль»,
  `auth.reset_confirm_submit` «Сохранить пароль», `auth.reset_done` «Пароль изменён. Войдите с новым паролем.»,
  `auth.reset_login_link` «Войти», `auth.reset_link_invalid` «Ссылка недействительна. Запросите новую.»,
  `auth.reset_request_again` «Запросить новую ссылку»;
  `error.feature_disabled` «Сброс пароля по email не настроен. Обратитесь к администратору.»,
  `error.reset_token_invalid` «Ссылка для сброса пароля недействительна или устарела.»,
  `error.email_taken` «Этот email уже указан у другой учётной записи.»,
  `error.email_invalid` «Некорректный email.»;
  `admin.users.email_column` «Email», `admin.users.email_missing` «email не указан»,
  `admin.users.email_label` «Email (необязательно)», `admin.users.edit_email` «Изменить email»,
  `admin.users.edit_email_aria` «Изменить email пользователя {login}», `admin.users.email_dialog_title`
  «Email пользователя {login}», `admin.users.email_dialog_hint` «Оставьте поле пустым, чтобы удалить email.»,
  `admin.users.email_save` «Сохранить», `admin.users.email_cancel` «Отмена»;
  `admin.audit.action.user.email_changed` «Email изменён», `admin.audit.action.user.password_reset_requested`
  «Запрошен сброс пароля по email», `admin.audit.action.user.password_reset_completed` «Пароль сброшен по email».
  Исполнитель может уточнить формулировку, но не набор ключей. `{login}` — по правилам `t(key, params)`.

## 5. Данные и эксперименты (для ML)
Не применимо: ML-кода нет. Тестовые email только синтетические (`*@example.test`).

## 6. Тестовая стратегия и трассировка

Бэкенд — pytest (API через `reset_api_env`/`api_env`, домен через `db`, миграции через `committed`), фронт —
vitest. Новые тесты именуются `test_007_acN_*` (бэкенд) и `007_acN_*` (vitest). SMTP всегда подменён (PR-13).

| AC | Где реализуется | Тест (уровень) |
|----|-----------------|----------------|
| AC-1 | `users/email.py`, `users/service.py` (`create_user`, `set_email`), `EmailTaken`, `admin_users.py`, `UsersPage` | `backend/tests/domain/test_007_user_email.py` (домен: регистр, 409, пустой email, гонка), `backend/tests/api/test_007_admin_email.py` (API 409 `email_taken`, `null`/пусто допустимы, 422 `email_invalid`, 403 для не-ТА, 404 чужой id, событие `user.email_changed` без значений); `frontend/tests/features/admin/UsersPage.test.tsx` (поле при создании, ошибка `email_taken`) |
| AC-2 | `Settings.password_reset_enabled`, `lifespan`, `FeatureDisabled`, `status`, `LoginPage` | `backend/tests/api/test_007_password_reset_api.py::test_007_ac2_*` (`api_env` без SMTP: оба POST → 404 `feature_disabled`, `status.enabled=false`, писем нет); `frontend/tests/features/auth/LoginPage.test.tsx` (`enabled:false` → ссылки нет) |
| AC-3 | `LoginPage`, `PasswordResetRequestPage`, `router.tsx` | `LoginPage.test.tsx` (`enabled:true` → ссылка с `href="/password-reset"` после кнопки «Войти», до блока справки), `frontend/tests/features/auth/PasswordResetRequestPage.test.tsx` (ровно одно поле «Email», кнопка «Отправить ссылку», отправка, текст успеха) |
| AC-4 | `request_reset` (один путь без ветвлений по ответу), `PasswordResetAccepted` | `test_007_password_reset_api.py::test_007_ac4_*`: три варианта (активный email, неизвестный email, пользователь без email — запрос по адресу, которого ни у кого нет, и проверка, что у пользователя email NULL) × 20 запусков, `fixed_clock.advance(61 мин)` перед каждым. Статус, тело и заголовки побайтно равны, |медиана_i − медиана_j| ≤ 200 мс |
| AC-5 | `password_reset.request_reset`, `reset_mail.build_reset_mail`, `deliver` | API: ровно одно письмо в `RecordingMailer`, ссылка `https://tracker.example.test/password-reset/confirm#token=`, срок «30 минут», «если это были не вы», в теле нет логина, хеша и пароля; в `password_reset_token.token_hash` лежит `sha256(token)` и нет самого токена. Юнит `backend/tests/unit/test_007_reset_mail.py` (шаблон), `backend/tests/unit/test_007_mail.py` (`SmtpMailer` с подменённым `smtplib.SMTP`: STARTTLS, login, from/to; `deliver` глотает исключение и логирует только тип) |
| AC-6 | `_issue_token` (удаление прежних неиспользованных) | API: два запроса (между ними сдвиг часов меньше часа, в пределах лимита 3). `confirm` первым токеном → 400 `reset_token_invalid`, вторым → 204 |
| AC-7 | `_load_valid_token` (`expires_at > now`) | API: `fixed_clock.advance(30 мин + 1 с)` → 400 `reset_token_invalid`; хеш пароля не изменился. Граница: ровно 30 мин → недействителен (`expires_at > now` строго) |
| AC-8 | `confirm_reset` (PR-16), `PasswordResetConfirmPage` | API: 204; повторно → 400; `session_ids(user)` пусты (две заранее открытые сессии); `must_change_password` false (в том числе у пользователя, у которого был true); вход новым паролем 200. Vitest: успех → `auth.reset_done` и ссылка на `/login`, автоматического входа нет (нет запроса `/auth/login`) |
| AC-9 | `_check_new_password` до поглощения (PR-20) | API: 11 символов → 422 `password_too_short`; пароль из списка частых → 422 `password_too_common`; затем тот же токен с хорошим паролем → 204 |
| AC-10 | `reset_limits.register_request` | Домен `backend/tests/domain/test_007_reset_limits.py`: 3 → True, 4-й → False, через 61 мин → True; IP: 10 разных email с одного IP → 11-й False; другой IP не затронут; отклонённые не записываются. API: 4 запроса → 4 одинаковых ответа, писем 3 |
| AC-11 | `_find_active_user`, `_load_valid_token`/`_apply_new_password` (`NOT is_blocked`) | API: выдать токен, заблокировать (`block_user` через админ-API) → `confirm` 400; `request` для заблокированного → ответ как FR-6, писем 0. Плюс: пользователь без членства → писем 0 |
| AC-12 | `record_event` (`completed`, `requested`), отсутствие значений в логах | `backend/tests/api/test_007_password_reset_leaks.py` (образец — `test_password_leaks.py`): полный сценарий (request → confirm → login) под `caplog` уровня DEBUG. В `caplog.text` и в ответах API нет токена, пароля и email. В `domain_event` есть `user.password_reset_requested` (`actor_id NULL`) и `user.password_reset_completed` (`actor_id = user_id`), `changed_fields = []`, `details`/`changes` NULL; `GET /audit` показывает их без значений |
| AC-13 | `PasswordResetConfirmPage` (PR-18) | `frontend/tests/features/auth/PasswordResetConfirmPage.test.tsx`: старт на `/password-reset/confirm#token=abc` → `location.hash === ""`; оба поля видны; несовпадение → `auth.password_mismatch`, `fetch` не вызывался; отправка уходит с `token: "abc"` |
| AC-14 | `AdminUser.email`, `UsersPage` | `UsersPage.test.tsx`: запись с `email: null` → метка «email не указан»; с адресом → адрес; кнопка сброса через администратора работает как раньше (существующие тесты зелёные). Бэкенд: `backend/tests/api/test_admin_users.py` проходит без изменений assert-ов |
| AC-15 | Без изменений `ChangePasswordPage`, `NoRolePage`, блока справки | `frontend/tests/features/auth/ChangePasswordPage.test.tsx` и новый `frontend/tests/features/auth/007_no_reset_link.test.tsx`: на `/change-password` и `/no-role` нет ссылки «Забыли пароль?»; существующие тесты блока справки 005 зелёные без правок |
| FR-2 (журнал смены email) | `set_email` | `test_007_admin_email.py`: `user.email_changed` в `/audit`, без значения адреса |
| FR-3 (конфиг) | `Settings`, compose | `backend/tests/unit/test_config.py` (умолчания, `""→None`, Fail Fast без `SMTP_FROM`/`PUBLIC_BASE_URL`, маска `smtp_password` в `repr`), `backend/tests/infra/test_compose_static.py` (`SMTP_*`, `PUBLIC_BASE_URL` из `.env` с умолчаниями, пароль только ссылкой `${…}`) |
| NFR-4 | миграция 0008 | `backend/tests/db/test_007_schema.py`: upgrade/downgrade 0007↔0008, колонки и ограничения, CHECK нижнего регистра, CASCADE токенов; `alembic check` чист |
| §7 / ADR-0017 (email не экспортируется) | PR-14 | `backend/tests/cli/test_export_import.py` + `test_007_*`: в архиве нет ключа `email` в `app_user` и нет таблиц токенов/попыток; после импорта `email IS NULL`; цикл export→import→export идентичен; архив с ключом `email` отвергается (`ImportRefused`) |
| NFR-6 | всё | `bash scripts/check.sh` (R7-T21) |

Ручная проверка (вне CI, R7-T21, по желанию владельца): поднять стенд с реальным SMTP-ретранслятором (например,
MailHog в отдельной сети, не в поставляемом compose), запросить сброс и открыть ссылку из письма.

## 7. Зависимости
Новых пакетов нет. Python: `smtplib`, `ssl`, `email.message`, `hmac`, `hashlib`, `secrets` — стандартная библиотека
(`test_dependencies_allowlist.py` не меняется). npm: нет.

## 8. Риски
- **R-1. Время ответа (AC-4).** Ветка «пользователь найден» делает 2–3 лишних запроса (DELETE, INSERT токена,
  INSERT события), это единицы миллисекунд. SMTP вынесен в фон. Допуск 200 мс на медиане с запасом. Тест
  выполняется на тестовой БД и может «мигать» на перегруженной машине: сравниваются медианы, не отдельные значения.
- **R-2. `alembic check`.** Модели должны в точности совпадать с 0008 (имена ограничений, `COLLATE "C"`
  в CHECK, индексы). Задача R7-T01 завершается только при чистом `alembic check`.
- **R-3. Потеря письма.** Фоновая задача в процессе: при перезапуске api в момент отправки письмо теряется,
  ошибка SMTP видна в логе только по типу. Пользователь повторяет запрос (лимит 3/час). Принято в PR-6.
- **R-4. Лимиты в dev.** Без `--proxy-headers` (локальный `uvicorn --reload` за vite-proxy) все запросы приходят
  с `127.0.0.1`, и лимит 10/час общий. На поставляемую конфигурацию не влияет.
- **R-5. Существующие тесты, которые придётся обновить:** голова миграций (`"0007"`), `PUBLIC`/`public`/
  `BODY_ROUTES_400`, `USER_ACTIONS` каталога, белый список `frontend/src`, `test_config` (умолчания), `LoginPage.test.tsx`
  (новый GET статуса: моки `fetch` должны его обслуживать). Assert-ы не ослабляются, только расширяются.
- **R-6. Разное поведение `lower()` в Python и PostgreSQL** для не-ASCII. CHECK с `COLLATE "C"` проверяет только
  ASCII. Python-нормализация — единственная точка записи (админ-API), импорт и демо email не заполняют.
- **R-7. Перехват ссылки** (ADR-0017): 30 минут, одноразовость, отзыв сессий. `PUBLIC_BASE_URL` по https
  в поставляемой конфигурации — ответственность оператора (документируется в `.env.example`).
- **R-8. Обновление ADR-0004 и `docs/STATE.md`** вне рамок этих задач: ADR-0017 уже заменяет ограничение.
  Если оркестратор решит править ADR-0004, нужно прогнать `backend/tests/infra/test_docs_static.py`.

## 9. Вопросы к spec (показать владельцу)

Ни один вопрос не блокирует старт: в скобках вариант, по которому написан план. Если владелец ответит иначе,
меняются отмеченные задачи.

- **Q-1 (FR-15, AC-12). Имена событий.** В spec `password_reset_completed`/`password_reset_requested`, в каталоге
  все действия вида `user.*`. *Предложение:* `user.password_reset_requested`, `user.password_reset_completed`
  (PR-4). Если нужно буквально как в spec — меняются константы в R7-T05 и строки в R7-T15.
- **Q-2 (FR-15). Актор события `requested`.** Spec задаёт актора только для `completed`. *Предложение:*
  `actor_id = NULL` (в журнале «система»), потому что запросить может кто угодно.
- **Q-3 (FR-1, FR-7). «Активная (не удалённая)».** У `app_user` нет мягкого удаления. *Предложение:*
  уникальность email среди всех записей, включая заблокированные. «Активна» для письма и сброса =
  не заблокирована и состоит в пространстве (PR-2).
- **Q-4 (FR-15). Пространство события.** `domain_event.workspace_id` обязателен, а сессии нет. *Предложение:*
  первое членство пользователя, как при входе (PR-5).
- **Q-5 (FR-3, FR-4). Базовый адрес ссылки.** Списка `SMTP_*` недостаточно, чтобы построить ссылку.
  *Предложение:* новая переменная `PUBLIC_BASE_URL`, обязательна при `SMTP_HOST`, иначе api не стартует (PR-10).
- **Q-6 (AC-1). 409 против 422.** Делаем 409 `email_taken`, как в AC-1, хотя `login_taken` отдаёт 422.
  Подтвердить, что расхождение допустимо (`login_taken` не меняем).
- **Q-7 (FR-9). Что считается «запросом».** *Предложение:* считаются все принятые запросы на адрес, независимо
  от того, есть ли учётная запись. Отклонённые по лимиту не считаются (окно не продлевается).
  Невалидный по формату адрес учитывается только в лимите IP.
- **Q-8 (FR-1). Регистр в хранении.** Email хранится в нижнем регистре (PR-1), администратор видит `a@x.ru`
  вместо `A@x.ru`. Если важно сохранять написание — нужна пара «ключ + показ», как у логина (+1 колонка).
- **Q-9 (§7, ADR-0010). Экспорт без AC.** Исключение `email` из экспорта утверждено, но в разделе 5 нет AC.
  План добавляет тесты (PR-14). Архивы старой схемы (0007) отвергаются по версии схемы, как и раньше: ADR-0010
  требует совпадения версии. Подтвердить, что миграция архивов не требуется.
- **Q-10 (FR-2). Событие смены email и имя.** В spec имя не задано. *Предложение:* `user.email_changed` без
  `fields`. При создании учётной записи с email пишется только `user.created`.
- **Q-11 (FR-13). Сопутствующие эффекты.** *Предложение:* при успехе `must_change_password = false` (даже если
  администратор выдал одноразовый пароль), счётчик неудачных входов и блокировка входа сбрасываются, файл
  пароля первого ТА удаляется — как при смене пароля (PR-16).
- **Q-12 (FR-5, FR-10). Вошедший пользователь на экранах сброса.** *Предложение:* экраны доступны и с сессией
  (PR-17). После успеха все сессии, включая текущую, завершаются.
- **Q-13 (FR-3). Публичный эндпоинт статуса.** Для AC-2 добавляется `GET /auth/password-reset/status`
  (PR-9). Ломающих изменений API нет, ADR не нужен.
- **Q-14 (нейминг).** Spec пишет `users.email` и `password_reset_tokens`, в БД будут `app_user.email` и
  `password_reset_token` (правило единственного числа), плюс служебная таблица `password_reset_attempt` для FR-9.
