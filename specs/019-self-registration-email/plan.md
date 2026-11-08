# Plan: Самостоятельная регистрация по email (spec 019)

- **Spec:** ./spec.md (v0.4, APPROVED 2026-11-08). ADR-0019 (предложено, ждёт решения ИБ по К-4), ADR-0004,
  ADR-0006, ADR-0010, ADR-0013, ADR-0017. Образец решений: `specs/007-password-reset-email/plan.md` (PR-n).
- **Разведка:** context.md нет. Обзор кода сделан архитектором, факты в §3 и §8.
- **Статус:** DRAFT
- **Решения владельца (2026-11-08):** Q-1, Q-2, Q-3, Q-4, Q-6, Q-7 закрыты (§9). Миграция — `0010`
  (RG-21), ветка основана на `origin/work3` (§7, R-12, R8-T00).
- **Обозначения:** решения плана — `RG-n`, вопросы к владельцу — `Q-n` (§9), задачи — `R8-Tnn` (tasks.md).
  Префикс `R8-` нужен потому, что `scripts/task_scope.py` требует уникальный ID во всех `specs/*/tasks.md`.
  `R3…R7` и `M20` уже заняты.
- **Предусловие запуска (не плана):** до принятия ADR-0019 с решением ИБ по К-4 (реальные ПДн, 152-ФЗ)
  регистрацию нельзя включать на стенде с реальным доступом. Включение = настроенный SMTP (FR-1), отдельного
  выключателя нет. Значит, на таком стенде до решения ИБ нельзя задавать `SMTP_HOST` для версии с этой фичей.
  Это ограничит и сброс пароля (007). Реализация и тесты от К-4 не зависят.

## 1. Подход

Регистрация устроена по образцу сброса пароля из 007 и переиспользует его инфраструктуру: `SMTP_*`,
`PUBLIC_BASE_URL`, `core/mail.py`, `BackgroundTasks`, `RecordingMailer`, нормализацию email и модель лимитов на
HMAC. Новая миграция `0010` только добавляет объекты. В `app_user` появляются `first_name`, `last_name`
(NULL у существующих) и `self_registered`. Добавляются таблицы `registration_request` (заявка до
подтверждения: email, логин, имя, фамилия, Argon2-хеш пароля, SHA-256 токена) и `registration_attempt`
(счётчики лимитов). Домен `app/domain/auth/registration.py` принимает заявку и подтверждает её. Заявка всегда
проходит одинаковый путь: лимит, валидация, хеширование, проверка занятости. На свободный адрес выдаётся письмо,
на занятый — ничего, ответ одинаков. Подтверждение создаёт `app_user` и `workspace_member` с `role = NULL`,
затем пишет событие. Попытки учитываются в лимитах и при ошибке, поэтому модулю регистрации разрешён
`commit_durably`. Без SMTP функция выключена так же, как сброс: 404 `feature_disabled`. Фронт узнаёт об этом из
существующего `GET /auth/password-reset/status`. Имя и фамилия правятся через `PUT /me/name` (сам
пользователь) и `PUT /admin/users/{id}/name` (ТА). У БА новая возможность `onboard_accounts` и отдельный раздел
`/unassigned-accounts`: список учётных записей без роли и назначение роли «Пользователь». Экспорт берёт новые
колонки `app_user` автоматически, новые таблицы исключаются.

## 2. Решения

| # | Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---------|---------|--------------------------|--------|
| RG-1 | Хранение заявки до подтверждения (FR-6, FR-8) | Отдельная таблица `registration_request`. `UNIQUE(email)`, новая заявка на тот же адрес — `INSERT … ON CONFLICT (email) DO UPDATE` (токен, логин, имя, фамилия, хеш пароля, сроки заменяются). `token_hash` `UNIQUE`. Строка удаляется при подтверждении и при отказе подтверждения из-за занятого логина или адреса | Строка `app_user` с флагом «не подтверждён»; хранить данные заявки в токене (JWT) | FR-8: до подтверждения учётной записи нет, адрес и логин не заняты. Флаг в `app_user` заставил бы фильтровать его во входе, списках, экспорте и уникальности. Самодостаточный токен не отзывается новой заявкой (FR-6) и тянет хеш пароля в письмо. Upsert по email отзывает предыдущий токен одной командой (AC-9) |
| RG-2 | Признак «самостоятельно зарегистрирована» (FR-13) | Колонка `app_user.self_registered boolean NOT NULL DEFAULT false` (`server_default`, существующие строки получают `false`) | Выводить из `created_by IS NULL` или из события `user.self_registered` в журнале | `created_by IS NULL` есть и у первого ТА из `bootstrap`. Чтение журнала ради списка нарушает SRP и даёт лишний запрос. Явная колонка дешёвая, переносится экспортом и не содержит ПДн |
| RG-3 | Имя и фамилия в БД | `first_name`, `last_name` — `varchar(100) NULL`, CHECK нет. Нормализует сервис: `strip()`, длина 1…100, без непечатаемых символов, иначе 422 `first_name_invalid` / `last_name_invalid` (новые коды `ErrorCode`, раздел `[019]`) | `NOT NULL` с пустой строкой у старых записей; CHECK в БД | NFR-6: у существующих записей поля пустые, не вымышленные. NULL однозначно означает «не заполнено». Единственный писатель — сервис (импорт берёт значения из своего же экспорта), CHECK ради этого — YAGNI. Код ошибки называет поле (FR-3a «с указанием поля»), как уже принято для `login_invalid` и `email_invalid` |
| RG-4 | Лимиты (FR-10) | Таблица `registration_attempt(scope, key_hash, created_at)`, области `request_ip` (10/ч), `confirm_ip` (20/ч), `confirm_token` (5 за окно). Окно у всех — 1 час, оно больше срока токена в 30 минут, поэтому «5 на ссылку» действует всё время жизни ссылки. Ключ — `HMAC-SHA256(secret_key, "<scope>:<value>")`, для токена `value` = hex SHA-256 токена. Отказ — 429 `rate_limited` (`RateLimited`), отклонённая попытка не записывается | Новые `scope` в `password_reset_attempt`; счётчики в памяти; Redis | Чтобы расширить `CHECK scope IN ('email','ip')`, пришлось бы менять ограничение существующей таблицы, а миграция только добавляет. Нет зависимостей, IP и токен в открытом виде не хранятся (FR-10, AC-18, AC-38). Модуль `registration_limits.py` повторяет схему `reset_limits.py`. Это второй экземпляр кода, общий хелпер по AHA появится только на третьем (замечание для ревьюера) |
| RG-5 | Что считается заявкой для лимита IP | Любой запрос `POST …/registration/request`, прошедший схему и включённую функцию, в том числе с ответом 422 (`login_taken`, `email_invalid`, пароль). Отказ 429 не записывается | Считать только принятые заявки (ответ 200) | Если не считать 422, проверку `login_taken` можно перебирать без ограничений (spec §7.4, риск перебора логинов). AC-18 выполняется в обоих вариантах. **Принято владельцем 2026-11-08 (Q-4)**: ответы 422 входят в лимит 10 заявок в час с IP |
| RG-6 | Сохранение попыток при отказе | Сразу после записи попытки в лимиты и перед разбором формы или токена `registration.py` вызывает `commit_durably(db)`. Второй вызов — перед `raise` в ветках «логин или адрес занят при подтверждении», чтобы поглощение заявки сохранилось (AC-28). `domain/auth/registration.py` добавляется в разрешённый список AST-теста `test_commit_durably_used_only_by_auth_service`, docstring `commit_durably` в `core/db.py` дополняется | Возвращать результат вместо исключения и собирать ответ 4xx в роутере; отдельная сессия для счётчиков | `get_db` откатывает транзакцию на любом исключении, без фиксации неудачные подтверждения не учитывались бы (AC-38). Тот же приём уже санкционирован для входа (FR-61). Роутер с ручными ответами ломает единый формат ошибок и слои. Вторая сессия — новая абстракция |
| RG-7 | Порядок проверок заявки (FR-3, FR-4) | `feature_disabled` (404) → схема (422) → лимит IP (429) + `commit_durably` → email (`email_invalid`) → имя → фамилия → логин (`login_invalid`, `login_taken` — 422) → пароль (`password_too_short`/`password_too_common`/`validation_error`) → Argon2-хеш (всегда) → занятость адреса в `app_user` (любой статус) → если свободен: удаление истёкших заявок, upsert заявки, письмо. Ответ 200 с одним и тем же телом | Проверять занятость адреса раньше логина или пароля | Ошибки валидации не зависят от адреса (FR-3, AC-27). Хеширование во всех ветках выравнивает время (AC-7, NFR-3). Письмо уходит после COMMIT, как в 007/PR-6 |
| RG-8 | Порядок подтверждения (FR-8, FR-9) | `feature_disabled` → схема → лимиты `confirm_ip`, `confirm_token` (429) + `commit_durably` → заявка по `token_hash` с `expires_at > now` `FOR UPDATE` (иначе 400 `registration_token_invalid`) → пространство пилота → адрес занят в `app_user` → удалить заявку, `commit_durably`, 400 → логин занят → удалить заявку, `commit_durably`, 409 `login_taken` (`LoginTakenConflict`) → INSERT `app_user` в savepoint (гонка: `uq_app_user_email` → как адрес занят, конфликт логина → как логин занят) → INSERT `workspace_member(role=NULL)` → DELETE заявки → событие → 204 без cookie | Сначала создавать учётную запись, потом проверять | AC-14, AC-28. `FOR UPDATE` не даёт создать две учётные записи двумя одновременными подтверждениями. Сессия не создаётся (AC-16) |
| RG-9 | Пространство новой учётной записи | Единственное пространство (`SELECT id FROM workspace LIMIT 2`). Если пространств не ровно одно, ответ 404 `feature_disabled` на заявку и на подтверждение | Первое пространство по `created_at`; пространство первого ТА | Spec: «единственное пространство пилота». Выбор «первого» при нескольких пространствах молча отдал бы человека в чужой арендатор (мультиарендность, AGENTS.md). Публичный эндпоинт — сознательное исключение из правила «фильтр по пространству актора», как в 007. **Принято владельцем 2026-11-08 (Q-7)** |
| RG-10 | Имена событий (FR-11) | `user.self_registered` (актор = новый пользователь, объект = он же, без `fields`), `user.name_changed` (`fields={"first_name","last_name"}`, в `changed_fields` только реально изменённые, значений нет). Назначение роли — существующий `user.role_assigned` с `details` `role_from`/`role_to` | Буквально `user_self_registered` | Каталог использует вид `<entity>.<action>`, владелец принял это в 007 (Q-1). Spec называет события логически. **Принято владельцем 2026-11-08 (Q-2)**. Сейчас в `catalog.py` таких членов нет (последние — `USER_TOKEN_CREATED`/`USER_TOKEN_REVOKED` из 020). В `test_event_catalog.py` оба значения добавляются в `USER_ACTIONS` (блок `# 019`), `user.name_changed` — ещё и в `EXPECTED` с `fields={first_name,last_name}` |
| RG-11 | Право БА (FR-13a, §3.1) | Новая `Capability.ONBOARD_ACCOUNTS` только у БА. Раздел `/api/v1/unassigned-accounts`: `GET` (страница учётных записей пространства с `role IS NULL`: id, логин, имя, фамилия, `created_at`, без email) и `PUT /{user_id}/role` (`{"role": …}`). Сервис `users/onboarding.py`: `role != "user"` → 403, у цели есть роль → 403, цели нет в пространстве → 404. Блокировки: advisory-ключ пространства (тот же, что у действий ТА) → `FOR NO KEY UPDATE` строк актора и цели `ORDER BY user_id` → актор всё ещё активный БА, иначе 403. Событие `user.role_assigned` с автором-БА | Пустить БА в `PUT /admin/users/{id}/role`; проверять роль БА без возможности; дать `ONBOARD_ACCOUNTS` и ТА | Роутер `/admin/users` закрыт `MANAGE_ACCOUNTS` на уровне роутера, и это гарантирует 403 БА на всё остальное (AC-30). Ослаблять этот гейт опасно. Фронт строит меню по `capabilities`. ТА уже видит список и назначает любую роль через `/admin/users`, второй путь ему не нужен (§3.1 «да» для ТА выполняется существующим разделом). `_lock_for_account_change` требует, чтобы актор был ТА, поэтому для БА нужен свой протокол, сериализованный с действиями ТА через тот же advisory-ключ. **Принято владельцем 2026-11-08 (Q-6)**: раздел и право — как здесь, у ТА `onboard_accounts` нет |
| RG-12 | Учётные записи без роли, но заблокированные, в списке БА | Показываются, роль «Пользователь» назначается (буквальное прочтение FR-13a: «любая учётная запись в состоянии „без роли“») | Скрывать заблокированные | Без входа роль ничего не даёт. Блокировку снимает только ТА, и в журнале видно, кто назначил роль. Меньше кода. **Подтверждает владелец (Q-5)** |
| RG-13 | Признак «функция включена» для фронта (FR-1) | Существующий `GET /auth/password-reset/status`, тот же `queryKey` `["auth","password-reset-status"]`. Отдельного эндпоинта статуса регистрации нет | Новый `GET /auth/registration/status` | По FR-1 и AC-32 регистрация включается ровно тем же условием, что сброс, второй выключатель запрещён. Новый эндпоинт добавил бы экрану входа ещё один запрос (005/FR-4) и дублировал бы одно значение. В бэкенде отдельный объект `state.registration_policy` создаётся по тому же условию |
| RG-14 | Публичные экраны фронта | `/register` обёрнут в `GuestOnly`. `useClientHandlers.onUnauthenticated` не уводит на `/login`, если текущий путь `/register`, так же как для `/login`. `/register/confirm` — без `GuestOnly`, как `/password-reset/confirm` (007/PR-17) | `/register` без `GuestOnly` | AC-3 требует увести вошедшего на стартовый экран, а это делает `GuestOnly`. Без исключения в обработчике 401 от `GET /me` увёл бы гостя с `/register` на `/login`. Ссылка из письма не должна терять токен, поэтому подтверждение работает без проверки сессии |
| RG-15 | Токен на `/register/confirm` | Как 007/PR-18: ленивое чтение `#token=` в `useState`, затем `history.replaceState` без фрагмента. Запрос уходит только по кнопке «Подтвердить» | Автоматическое подтверждение при открытии | FR-8: одно действие «Подтвердить». Почтовые сканеры, открывающие ссылки, не подтверждают регистрацию, к тому же фрагмент на сервер не уходит |
| RG-16 | Экран профиля (FR-3c) | Новый маршрут `/profile` для любой роли: `RoleScreen` получает необязательный `capability`, без него проверяется только сессия. Пункт меню «Профиль» у всех ролей. `GET /me` дополняется `first_name`/`last_name`, новый `PUT /me/name` → `MeResponse` | Отдельная обёртка `ProfileScreen`; поля имени в `/no-role` | Сессия, меню и оболочка переиспользуются. Учётная запись без роли получает 403 `no_role` от `get_active_actor` и уходит на `/no-role`, сам экран не меняется (FR-14) |
| RG-17 | Имя и фамилия при создании ТА (FR-3b) | `CreateUserRequest.first_name`, `last_name` — обязательные `str` (`max_length=1024`), проверка в домене. Порядок `create_user`: `login_invalid` → `login_taken` → `first_name_invalid` → `last_name_invalid` → `email_invalid` → `email_taken` → пароль. `bootstrap` (первый ТА) и демо-данные имена не задают (NULL) | Сделать поля необязательными в API | FR-3b требует обязательности. Первый ТА создаётся командой, не формой, поэтому FR-3b к нему не относится. Изменение ломает обратную совместимость `POST /admin/users`, но клиент в репозитории один, и ADR-0019 эту обязательность фиксирует |
| RG-18 | Срок хранения заявок (NFR-9) | (1) Каждая принятая заявка удаляет заявки с `expires_at <= now`. (2) CLI-команда `maintenance` (на базе `origin/work3` — `gostracker maintenance`, после слияния с `main` — `gtrack maintenance`, R-12) получает шаг `purge_expired_registration_requests` и поле отчёта `registration_requests_expired`. README уже рекомендует ежедневный cron, текст раздела дополняется | Только удаление по ходу запросов; фоновая задача в API | Без трафика (1) ничего не удаляет, а (2) с суточным cron гарантирует «не позднее 24 часов». Фоновых задач в процессе API в проекте нет |
| RG-19 | Шаблон письма (FR-5) | `registration_mail.build_registration_mail(*, to, link, ttl)` — единственный шаблон, тема «Подтверждение регистрации». В теле: ссылка `…/register/confirm#token=…`, «Ссылка действует 30 минут.», «Если вы не регистрировались, ничего не делайте: учётная запись не будет создана.» Логина, имени, фамилии и пароля в письме нет | Обобщить шаблон сброса | Тексты разные. Общая часть — две строки |
| RG-20 | Ответ на заявку | 200 `RegistrationAccepted {detail}`. `detail` — текст FR-4 дословно. Cookie нет | 202 | Как в 007/PR-19. Тело и заголовки одинаковы во всех ветках (AC-7) |
| RG-21 | Номер миграции | Файл `0010_self_registration.py`, `revision="0010"`, `down_revision="0009"` — это `revision` файла `0009_mcp_agent_access.py` (в репозитории ID ревизий короткие: `"0008"`, `"0009"`). Миграция `0009_mcp_agent_access.py` не меняется. Голова в тестах `"0009"` → `"0010"` | `0009_self_registration` с `down_revision="0008"` (две головы); слияние ревизий (`merge`) | **Решение владельца 2026-11-08 (Q-3):** фича 020 (MCP) вливается первой, ветка основана на `origin/work3`, где голова — `0009`. Линейная цепочка `0008 → 0009 → 0010` |

## 3. Затрагиваемые модули и файлы

**Бэкенд — схема и модели**
- `backend/migrations/versions/0010_self_registration.py` — новый (§4.1). `0009_mcp_agent_access.py` не меняется.
- `backend/app/domain/users/models.py` — `first_name`, `last_name`, `self_registered`.
- `backend/app/domain/auth/models.py` — `RegistrationRequest`, `RegistrationAttempt`.
- Тесты: `backend/tests/upgrade002_support.py:67` (`HEAD_REVISION` `"0009"` → `"0010"`),
  `backend/tests/db/test_migrations.py` (`"0009"` → `"0010"` в строках ~962, 996, 1010, 1070; разрешённый список
  `commit_durably`, ~593), `backend/tests/db/test_007_schema.py` (`"0009"` → `"0010"` в строках ~127, 377, 394).
  `backend/tests/db/test_m20_t02_mcp_schema.py` не меняется: `downgrade 0008` от головы проходит и через `0010`.
  `backend/tests/factories.py` (`make_user(..., first_name=, last_name=, self_registered=)`).

**Бэкенд — ядро**
- `backend/app/core/errors.py` — `RateLimited` (429), `RegistrationTokenInvalid` (400), `LoginTakenConflict`
  (409, code `login_taken`), `ErrorCode.first_name_invalid`, `ErrorCode.last_name_invalid`.
- `backend/app/core/db.py` — только docstring `commit_durably` (+ `domain/auth/registration.py`).
- `backend/app/main.py` — `state.registration_policy`.
- Настроек и переменных окружения не добавляется (AC-32): `config.py`, `.env.example`, `docker-compose.yml` не
  меняются.

**Бэкенд — домен**
- `backend/app/domain/access/roles.py` — `Capability.ONBOARD_ACCOUNTS` в `_BUSINESS_ADMIN_CAPS`.
- `backend/app/domain/events/catalog.py` — `USER_SELF_REGISTERED`, `USER_NAME_CHANGED`.
- `backend/app/domain/users/names.py` — новый: `normalize_person_name`.
- `backend/app/domain/users/service.py` — поля в `UserAccount`/`_Target`/`_load_target`/`list_accounts`;
  `create_user(first_name=, last_name=)`; новый `set_name`.
- `backend/app/domain/users/profile.py` — новый: `get_own_profile`, `set_own_name`.
- `backend/app/domain/users/onboarding.py` — новый: `list_unassigned`, `assign_user_role`.
- `backend/app/domain/auth/registration_limits.py`, `registration_mail.py`, `registration.py` — новые.
- `backend/app/domain/system/maintenance.py`, `backend/app/domain/ops/maintenance.py` — очистка заявок (RG-18).
- `backend/app/domain/ops/archive.py`, `backend/app/domain/ops/importer.py` — исключение новых таблиц.

**Бэкенд — API**
- `backend/app/api/v1/schemas/admin.py` — поля `AdminUser`, `CreateUserRequest`, новый `SetNameRequest`.
- `backend/app/api/v1/admin_users.py` — создание с именами, `PUT /{user_id}/name`.
- `backend/app/api/v1/schemas/auth.py` — `MeResponse.first_name`, `last_name`.
- `backend/app/api/v1/me.py` — `GET /me` читает имена, `PUT /me/name`.
- `backend/app/api/v1/schemas/accounts.py`, `backend/app/api/v1/unassigned_accounts.py` — новые (RG-11).
- `backend/app/api/v1/schemas/registration.py`, `backend/app/api/v1/registration.py` — новые.
- `backend/app/api/v1/__init__.py` — два роутера.
- `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` — только через
  `source .venv/bin/activate && bash scripts/gen-api.sh`.
- Тесты, которые расширяются: `backend/tests/api/test_route_guards.py` (`PUBLIC`), `backend/tests/cli/test_openapi.py`
  (`public`, `BODY_ROUTES_400`), `backend/tests/cli/test_openapi_roles.py` (список полей с ролью),
  `backend/tests/unit/test_event_catalog.py`, `backend/tests/unit/test_role_matrix.py`,
  `backend/tests/cli/test_export_import.py`, `backend/tests/cli/test_maintenance.py`,
  `backend/tests/infra/test_frontend_scaffold.py`. Вызовы создания учётной записи в тестах получают имена (R8-T04).
- `README.md` — раздел «Регулярное обслуживание» / «Regular maintenance» (RG-18).

**Фронтенд**
- `frontend/src/shared/i18n/ru.ts` — ключи §4.7.
- `frontend/src/features/admin/AuditPage.tsx` — `ACTION_CODES`, `FIELD_CODES`.
- `frontend/src/features/auth/api.ts` — `requestRegistration`, `confirmRegistration`, `updateMyName`.
- `frontend/src/features/auth/RegisterPage.tsx`, `RegisterConfirmPage.tsx`, `ProfilePage.tsx` — новые.
- `frontend/src/features/auth/LoginPage.tsx` — ссылка «Зарегистрироваться», абзац справки (Q-1).
- `frontend/src/app/router.tsx` — маршруты `/register`, `/register/confirm`, `/profile`,
  `/unassigned-accounts`, пункты меню, исключение в `onUnauthenticated`, необязательный `capability` у `RoleScreen`.
- `frontend/src/features/admin/api.ts` — `createUser` с именами, `setUserName`, `listUnassigned`, `assignUserRole`.
- `frontend/src/features/admin/UsersPage.tsx` — колонки «Имя», «Фамилия», отметка самостоятельной регистрации,
  поля имени в форме создания, кнопка «Изменить имя».
- `frontend/src/features/admin/NameDialog.tsx`, `UnassignedAccountsPage.tsx` — новые.

## 4. Интерфейсы

### 4.1 Схема БД (миграция 0010, файл `0010_self_registration.py`, `revision="0010"`, `down_revision="0009"`, литералы без импорта `app.*`)

```text
app_user.first_name        varchar(100) NULL
app_user.last_name         varchar(100) NULL
app_user.self_registered   boolean NOT NULL DEFAULT false        -- server_default=sa.false()

registration_request
  id             uuid PK
  email          varchar(254) NOT NULL
    uq_registration_request_email              UNIQUE (email)
    ck_registration_request_email_lower        CHECK (lower(email COLLATE "C") = email)
  login          varchar(64)  NOT NULL                             -- ключ (normalize_login)
  login_display  varchar(64)  NOT NULL                             -- написание из формы
  first_name     varchar(100) NOT NULL
  last_name      varchar(100) NOT NULL
  password_hash  text NOT NULL                                     -- Argon2id
  token_hash     bytea NOT NULL
    uq_registration_request_token_hash         UNIQUE (token_hash)
    ck_registration_request_token_hash_length  CHECK (octet_length(token_hash) = 32)   -- SHA-256
  created_at     timestamptz NOT NULL
  expires_at     timestamptz NOT NULL
    ix_registration_request_expires_at         (expires_at)

registration_attempt
  id          uuid PK
  scope       text NOT NULL
    ck_registration_attempt_scope_valid        CHECK (scope IN ('request_ip','confirm_ip','confirm_token'))
  key_hash    bytea NOT NULL
    ck_registration_attempt_key_hash_length    CHECK (octet_length(key_hash) = 32)    -- HMAC-SHA256
  created_at  timestamptz NOT NULL
  ix_registration_attempt_scope_key_hash_created_at (scope, key_hash, created_at)
  ix_registration_attempt_created_at (created_at)
```
Downgrade удаляет обе таблицы и три колонки. Модели объявляют те же объекты (`server_default=false()` у
`self_registered`, `default=False` в ORM), `alembic check` должен быть чист. Время пишется через `utcnow()`.
FK у новых таблиц нет: заявка не связана с `app_user`.

### 4.2 Ядро

```python
# app/core/errors.py
class RateLimited(AppError):              status_code = 429; code = "rate_limited"; default_detail = "Слишком много запросов. Попробуйте позже"
class RegistrationTokenInvalid(AppError): status_code = 400; code = "registration_token_invalid"; default_detail = "Ссылка подтверждения недействительна"
class LoginTakenConflict(AppError):       status_code = 409; code = "login_taken"; default_detail = "Логин уже занят"
class ErrorCode(StrEnum): ...  # [019]
    first_name_invalid = "first_name_invalid"
    last_name_invalid = "last_name_invalid"

# app/domain/access/roles.py
class Capability(StrEnum): ...; ONBOARD_ACCOUNTS = auto()   # «onboard_accounts»: список без роли + роль «Пользователь» (019/FR-13a)
# _BUSINESS_ADMIN_CAPS += ONBOARD_ACCOUNTS; у ТА и П её нет

# app/domain/events/catalog.py
USER_SELF_REGISTERED = "user.self_registered"   # -> _USER_AUDITED
USER_NAME_CHANGED = "user.name_changed"         # -> EventSpec(USER, audit=True, feed=None, deal_history=False,
                                                #              fields=frozenset({"first_name", "last_name"}))

# app/main.py (_lifespan), в ветке settings.password_reset_enabled:
state.registration_policy = RegistrationPolicy(base_url=settings.public_base_url, limit_key=ensure_secret_key(settings))
# иначе: state.registration_policy = None
```

### 4.3 Домен

```python
# app/domain/users/names.py
NAME_MAX_LENGTH: Final = 100
def normalize_person_name(value: str) -> str | None:
    """strip() -> None, если пусто, длиннее 100 или есть непечатаемые символы (not str.isprintable()).
    Написание сохраняется. Значение в исключения и логи не попадает."""

# app/domain/users/service.py
@dataclass(frozen=True) class UserAccount: ...; first_name: str | None; last_name: str | None; self_registered: bool
# те же поля в _Target, _load_target, list_accounts (load_only += три колонки)
async def create_user(db, actor, hasher, *, login: str, one_time_password: SecretStr,
                      first_name: str, last_name: str, email: str | None = None) -> UserAccount
    # порядок — RG-17; self_registered=False
async def set_name(db: AsyncSession, actor: Actor, user_id: UUID, first_name: str, last_name: str, /) -> UserAccount
    # MANAGE_ACCOUNTS (403) -> normalize обоих (422 first_name_invalid | last_name_invalid) -> _lock_for_account_change
    # -> _load_target (404) -> без изменений: без UPDATE и события -> UPDATE (updated_at=utcnow())
    # -> record_event(USER_NAME_CHANGED, changed_fields=[изменённые в порядке first_name, last_name])

# app/domain/users/profile.py
@dataclass(frozen=True) class OwnProfile: first_name: str | None; last_name: str | None
async def get_own_profile(db: AsyncSession, actor: Actor) -> OwnProfile
async def set_own_name(db: AsyncSession, actor: Actor, first_name: str, last_name: str) -> OwnProfile
    # actor.role is None -> NoRole (защита от прямого вызова; гейт уже в get_active_actor)
    # -> normalize (422) -> без изменений: без события -> UPDATE app_user WHERE id = actor.user_id
    # -> record_event(USER_NAME_CHANGED, actor_id=entity_id=actor.user_id, workspace_id=actor.workspace_id)

# app/domain/users/onboarding.py
@dataclass(frozen=True) class UnassignedAccount: id: UUID; login: str; first_name: str | None; last_name: str | None; created_at: datetime
async def list_unassigned(db, actor: Actor, params: PageParams) -> tuple[list[UnassignedAccount], bool]
    # ONBOARD_ACCOUNTS (403); workspace_member.workspace_id = actor.workspace_id AND role IS NULL; ORDER BY login, id; без email
async def assign_user_role(db, actor: Actor, user_id: UUID, role: Role | None, /) -> None
    # ONBOARD_ACCOUNTS (403) -> role != Role.USER -> Forbidden -> _lock_for_onboarding -> цель в пространстве (404)
    # -> у цели есть роль -> Forbidden -> UPDATE workspace_member SET role='user' WHERE … AND role IS NULL
    # -> record_event(USER_ROLE_ASSIGNED, actor_id=actor.user_id, details=UserEventDetails(role_from=None, role_to="user"))
async def _lock_for_onboarding(db, workspace_id: UUID, target_id: UUID, actor_id: UUID) -> None
    # pg_advisory_xact_lock(_ACCOUNT_LOCK_NAMESPACE, hashtext(workspace_id)) — импорт константы из service.py
    # -> SELECT … FROM workspace_member JOIN app_user WHERE workspace_id=… AND user_id IN (actor, target)
    #    ORDER BY user_id FOR NO KEY UPDATE -> актор: role='business_admin' и не заблокирован, иначе Forbidden

# app/domain/auth/registration_limits.py
REQUEST_IP_LIMIT: Final = 10
CONFIRM_IP_LIMIT: Final = 20
CONFIRM_TOKEN_LIMIT: Final = 5
LIMIT_WINDOW: Final = timedelta(hours=1)
Scope = Literal["request_ip", "confirm_ip", "confirm_token"]
def limit_key_hash(key: bytes, scope: Scope, value: str) -> bytes        # HMAC-SHA256(key, f"{scope}:{value}")
async def register_attempt(db: AsyncSession, key: bytes, checks: Sequence[tuple[Scope, str]], *, now: datetime) -> bool
    """1) DELETE attempt WHERE created_at <= now - LIMIT_WINDOW; 2) pg_advisory_xact_lock(ns 0x72656769 «regi», id)
    по номерам ключей по возрастанию; 3) COUNT за окно по каждой области; хоть одна >= лимита -> False, ничего не пишется;
    4) иначе INSERT по строке на область -> True. Пустой checks -> True."""

# app/domain/auth/registration_mail.py
SUBJECT: Final = "Подтверждение регистрации"
def build_registration_mail(*, to: str, link: str, ttl: timedelta) -> MailMessage     # RG-19

# app/domain/auth/registration.py
TOKEN_TTL: Final = timedelta(minutes=30)
ACCEPTED_DETAIL: Final = ("Если адрес можно использовать для регистрации, мы отправили на него письмо с "
                          "подтверждением. Ссылка действует 30 минут.")
@dataclass(frozen=True)
class RegistrationPolicy:
    base_url: str
    limit_key: bytes = field(repr=False)
@dataclass(frozen=True)
class RegistrationForm:
    email: str = field(repr=False); first_name: str = field(repr=False); last_name: str = field(repr=False)
    login: str = field(repr=False); password: SecretStr
def confirm_link(base_url: str, token: str) -> str          # f"{base_url}/register/confirm#token={token}"
async def request_registration(db: AsyncSession, policy: RegistrationPolicy | None, hasher: PasswordHasher, *,
                               form: RegistrationForm, client_ip: str | None, now: datetime) -> MailMessage | None
    """RG-7. Ошибки: FeatureDisabled, RateLimited, Unprocessable(email_invalid | first_name_invalid | last_name_invalid |
    login_invalid | login_taken | password_too_short | password_too_common | validation_error). Адрес занят -> None."""
async def confirm_registration(db: AsyncSession, policy: RegistrationPolicy | None, *, token: SecretStr,
                               client_ip: str | None, now: datetime) -> None
    """RG-8. Ошибки: FeatureDisabled, RateLimited, RegistrationTokenInvalid, LoginTakenConflict.
    INSERT app_user: login=key, login_display, email, first_name, last_name, password_hash из заявки,
    must_change_password=False, is_blocked=False, self_registered=True, failed_login_count=0, password_changed_at=now,
    created_by=NULL. workspace_member: role=NULL, created_by=NULL.
    record_event(USER_SELF_REGISTERED, actor_id=user_id, entity_id=user_id)."""
```
Токен и хеш — `password_reset.new_token()` / `password_reset.token_hash()` (переиспользуются). Проверка пароля —
своя обёртка `_check_password` (кодировка → `validate_new_password` → `Unprocessable(code=exc.code)`). Это
четвёртая копия восьми строк, как в 007/PR-15 (долг DRY для ревьюера). Ограничения ruff — функции дробить на
помощники (`_validate_form`, `_email_taken`, `_upsert_request`, `_load_request_for_update`, `_consume_and_fail`,
`_insert_account`, `_single_workspace_id`).

```python
# app/domain/system/maintenance.py
async def purge_expired_registration_requests(sessionmaker, *, now: datetime, dry_run: bool = False) -> int
    # DELETE registration_request WHERE expires_at <= now (dry_run: COUNT); одна транзакция
# app/domain/ops/maintenance.py: MaintenanceReport += registration_requests_expired: int = 0 (последнее поле)
```

### 4.4 API

| Метод и путь | Доступ | Тело | Ответ | Ошибки (`{"detail","code"}`) |
|---|---|---|---|---|
| `POST /api/v1/auth/registration/request` | публичный (+`check_origin`) | `RegistrationRequest {email, first_name, last_name, login: str ≤1024; password: Password}` (`extra=forbid`, `_require_encodable` у пароля) | 200 `RegistrationAccepted {detail}` | 400 `bad_request`, 403 `origin_mismatch`, 404 `feature_disabled`, 422 коды RG-7 и `validation_error` схемы, 429 `rate_limited` |
| `POST /api/v1/auth/registration/confirm` | публичный (+`check_origin`) | `RegistrationConfirm {token: SecretStr ≤128}` (`extra=forbid`) | 204 без cookie | 400 `bad_request` / `registration_token_invalid`, 403, 404 `feature_disabled`, 409 `login_taken`, 422, 429 `rate_limited` |
| `GET /api/v1/me` (изм.) | `get_active_actor` | — | `MeResponse` + `first_name: str \| null`, `last_name: str \| null` | как было |
| `PUT /api/v1/me/name` | `get_active_actor` (любая роль) | `SetNameRequest {first_name: str, last_name: str}` (`extra=forbid`; длину 1…100 проверяет домен, RG-3, поэтому 101+ даёт `first_name_invalid`, а не `validation_error`) | 200 `MeResponse` | 400, 401, 403 `no_role` / `password_change_required`, 422 `first_name_invalid` / `last_name_invalid` |
| `POST /api/v1/admin/users` (изм.) | как было | `CreateUserRequest` + обязательные `first_name`, `last_name` | 201 `AdminUser` | + 422 `first_name_invalid` / `last_name_invalid` |
| `PUT /api/v1/admin/users/{user_id}/name` | `MANAGE_ACCOUNTS` | `SetNameRequest` | 200 `AdminUser` | 400, 401, 403, 404, 422 |
| `GET /api/v1/admin/users*`, `PUT …/role`, `PUT …/email` (изм.) | как было | — | `AdminUser` + `first_name`, `last_name`, `self_registered: bool` (10 полей) | — |
| `GET /api/v1/unassigned-accounts` | `ONBOARD_ACCOUNTS` (БА) | query `page`, `page_size` | 200 `Page[UnassignedAccountOut {id, login, first_name, last_name, created_at}]` | 401, 403, 422 |
| `PUT /api/v1/unassigned-accounts/{user_id}/role` | `ONBOARD_ACCOUNTS` (БА) | `SetRoleRequest {role}` (переиспользуется из `schemas/admin.py`) | 204 | 400, 401, 403 (роль не «user», у цели есть роль, актор потерял роль), 404, 422 |

- Роутеры: `registration.py` — `APIRouter(prefix="/auth/registration", tags=["auth"])`, operationId (имена функций):
  `request_registration`, `confirm_registration`. Обработчик заявки собирает `RegistrationForm`, вызывает домен один
  раз и при `MailMessage` делает `background.add_task(deliver, state.mailer, message)`. IP берётся из
  `request.client.host` (007/PR-8). `unassigned_accounts.py` — `APIRouter(prefix="/unassigned-accounts",
  tags=["accounts"], dependencies=[Depends(require_capability(Capability.ONBOARD_ACCOUNTS))])`, operationId
  `list_unassigned_accounts`, `assign_user_role`. `admin_users.py` — `set_user_name`; `me.py` — `set_own_name`.
- `GET /me` получает `DbSession` и вызывает `profile.get_own_profile`, `Actor` не меняется.
- OpenAPI: 429 и 409 — `error_response(429|409, "<описание с code>")`, 400 — `error_responses(400)` (точный
  `BAD_JSON_DESCRIPTION`). `BODY_ROUTES_400` += `POST …/registration/request`, `POST …/registration/confirm`,
  `PUT /api/v1/me/name`, `PUT /api/v1/admin/users/{user_id}/name`, `PUT /api/v1/unassigned-accounts/{user_id}/role`.
  `PUBLIC` (route guards) и `public` (`test_d33_*`) += два публичных POST.
- `AdminUser` docstring: «ровно десять полей». В `UnassignedAccountOut` email нет (NFR-1, FR-13a).

### 4.5 Экспорт и импорт
- `archive.EXCLUDED_TABLES` += `registration_request`, `registration_attempt`. `EXCLUDED_COLUMNS` не меняется:
  `first_name`, `last_name`, `self_registered` выгружаются, `email` — нет (NFR-7).
- `importer.AUTO_TABLES` получает обе таблицы в начале, рядом с таблицами сброса пароля.
- `schema_version` = голова `0010`, архивы `0009` (и старше) отвергаются, как и раньше (ADR-0010).

### 4.6 Тестовая инфраструктура
- Фикстура `reset_api_env` (`backend/tests/conftest.py`) включает SMTP, поэтому `registration_policy` тоже создаётся.
  Письма — `env.app.state.mailer.sent`. Новой фикстуры не нужно.
- В тестах регистрации в БД ровно одно пространство (RG-9). Тест «два пространства → 404» создаёт второе явно.
- IP клиента: `httpx.ASGITransport(app=…, client=(ip, port))` или сдвиг `fixed_clock.advance(timedelta(minutes=61))`.
- Время: `fixed_clock` (`advance`, `set`), токен — граница `expires_at > now`.

### 4.7 Фронтенд

```ts
// features/auth/api.ts
export type RegistrationRequest = components["schemas"]["RegistrationRequest"];
export async function requestRegistration(body: RegistrationRequest): Promise<void>;   // POST …/registration/request
export async function confirmRegistration(token: string): Promise<void>;               // POST …/registration/confirm
export async function updateMyName(body: SetNameRequest): Promise<MeResponse>;          // PUT /me/name
// features/admin/api.ts
export async function createUser(body: CreateUserRequest): Promise<AdminUser>;          // + first_name, last_name
export async function setUserName(id: string, body: SetNameRequest): Promise<AdminUser>;
export async function listUnassigned(p: PageParams): Promise<Page<UnassignedAccountOut>>;
export async function assignUserRole(id: string): Promise<void>;                         // body {role: "user"}
```
- `LoginPage` (Q-1 закрыт владельцем 2026-11-08): при `resetStatus.data?.enabled === true` после ссылки «Забыли
  пароль?» идёт `<Link to="/register">Зарегистрироваться</Link>`, а вторым `<p>` блока справки показывается
  `auth.help_p2_registration` (текст FR-12, §9 Q-1). Второй абзац о регистрации есть только при включённой
  регистрации. При `enabled !== true` блок справки не меняется относительно базы ветки. На `origin/work3` действует
  005 v0.1: блок из двух `p` (`auth.help_p1`, `auth.help_p2`), и при включённой регистрации `auth.help_p2_registration`
  заменяет `auth.help_p2`. В `main` действует 005 v0.2 (один `p`, ключа `auth.help_p2` нет). После слияния (R8-T00)
  при выключенной регистрации — один `p` по 005 v0.2, при включённой — `help_p1` из v0.2 и `help_p2_registration`.
- `RegisterPage` (`/register`, `GuestOnly`): `h1` «Регистрация», поля `TextField` «Email» (`type="email"`,
  `autoComplete="email"`), «Имя» (`given-name`), «Фамилия» (`family-name`), «Логин» (`username`), «Пароль»
  (`new-password`, `reveal`, подсказка `PASSWORD_MIN_LENGTH`), кнопка «Зарегистрироваться». Других полей нет.
  Пустые поля отклоняются на клиенте без запроса (`validation_error`). Успех: `role="status"` с текстом
  `auth.register_sent`, форма скрыта. Ошибки — `errorMessage(code)`, `feature_disabled` →
  `auth.register_disabled`. Если `password-reset-status` вернул `enabled: false`, вместо формы
  `auth.register_disabled`. Ссылка «Вернуться ко входу».
- `RegisterConfirmPage` (`/register/confirm`, RG-15): нет токена → `auth.register_link_invalid` и ссылка на
  `/register`. Иначе кнопка «Подтвердить». Успех → `auth.register_confirmed` («Адрес подтверждён. Теперь можно
  войти») и ссылка «Войти» на `/login`, запроса `/auth/login` нет. `registration_token_invalid` → текст ошибки и
  ссылка на `/register`; `login_taken` → `auth.register_login_taken` и ссылка на `/register`; `rate_limited` →
  `error.rate_limited`.
- `ProfilePage` (`/profile`): `h1` «Профиль», логин только для чтения, поля «Имя» и «Фамилия» с текущими
  значениями из `MeResponse`, кнопка «Сохранить». Успех → `role="status"` `profile.saved` и
  `queryClient.setQueryData(["auth","me"], response)`.
- `UsersPage`: колонки `data-field="first_name"`, `data-field="last_name"` (пусто → `admin.users.name_missing`),
  `data-field="origin"` (`self_registered` → `admin.users.self_registered`, иначе пусто). В форме создания
  обязательные «Имя» и «Фамилия». Кнопка «Изменить имя» открывает `NameDialog` (два поля, ошибки
  `first_name_invalid`/`last_name_invalid` показываются в диалоге).
- `UnassignedAccountsPage` (`/unassigned-accounts`, `RoleScreen capability="onboard_accounts"`): `h1`
  «Учётные записи без роли», таблица «Логин», «Имя», «Фамилия», кнопка «Назначить роль «Пользователь»» →
  `ConfirmDialog` → `assignUserRole` → обновление списка. Пустой список → `accounts.unassigned_empty`. Пункт меню
  при `onboard_accounts`.
- Меню (`MenuItems`): «Профиль» (`/profile`) у всех ролей, «Без роли» (`/unassigned-accounts`) при
  `onboard_accounts`.
- Ключи `ru.ts` (значения — кириллица, `error.*` попарно различны; формулировки исполнитель может уточнить, набор
  ключей — нет): `auth.register_link` «Зарегистрироваться», `auth.register_title` «Регистрация»,
  `auth.register_email_label` «Email», `auth.register_first_name_label` «Имя», `auth.register_last_name_label`
  «Фамилия», `auth.register_login_label` «Логин», `auth.register_password_label` «Пароль»,
  `auth.register_submit` «Зарегистрироваться», `auth.register_sent` (текст FR-4 дословно),
  `auth.register_disabled` «Регистрация недоступна. Обратитесь к администратору.», `auth.register_back_to_login`
  «Вернуться ко входу», `auth.register_confirm_title` «Подтверждение регистрации», `auth.register_confirm_submit`
  «Подтвердить», `auth.register_confirmed` «Адрес подтверждён. Теперь можно войти», `auth.register_login_link` «Войти»,
  `auth.register_link_invalid` «Ссылка недействительна. Зарегистрируйтесь заново.», `auth.register_login_taken`
  «Этот логин уже занят. Зарегистрируйтесь заново с другим логином.», `auth.register_again` «Зарегистрироваться
  заново», `auth.help_p2_registration` (Q-1); `profile.title` «Профиль», `profile.login_label` «Логин»,
  `profile.first_name_label` «Имя», `profile.last_name_label` «Фамилия», `profile.save` «Сохранить», `profile.saved`
  «Сохранено»; `nav.profile` «Профиль», `nav.unassigned` «Без роли»; `accounts.unassigned_title` «Учётные записи без
  роли», `accounts.assign_user` «Назначить роль «Пользователь»», `accounts.assign_title`, `accounts.assign_message`
  «Назначить {login} роль «Пользователь»?», `accounts.unassigned_empty` «Учётных записей без роли нет»;
  `admin.users.first_name_column` «Имя», `admin.users.last_name_column` «Фамилия», `admin.users.origin_column`
  «Источник», `admin.users.self_registered` «Самостоятельная регистрация», `admin.users.name_missing` «не указано»,
  `admin.users.first_name_label` «Имя», `admin.users.last_name_label` «Фамилия», `admin.users.edit_name` «Изменить
  имя», `admin.users.edit_name_aria` «Изменить имя пользователя {login}», `admin.users.name_dialog_title` «Имя
  пользователя {login}», `admin.users.name_save` «Сохранить», `admin.users.name_cancel` «Отмена»;
  `error.rate_limited` «Слишком много попыток. Попробуйте позже.», `error.registration_token_invalid` «Ссылка
  подтверждения недействительна или устарела.», `error.first_name_invalid` «Укажите имя (до 100 символов).»,
  `error.last_name_invalid` «Укажите фамилию (до 100 символов).»; `admin.audit.action.user.self_registered`
  «Самостоятельная регистрация», `admin.audit.action.user.name_changed` «Имя изменено»,
  `admin.audit.field.first_name` «Имя», `admin.audit.field.last_name` «Фамилия»;
  `admin.capability.onboard_accounts` — если в словаре есть подписи возможностей (проверить grep'ом).

## 5. Данные и эксперименты (для ML)
Не применимо: ML-кода нет. Тестовые адреса и имена синтетические (`*@example.test`, «Анна Петрова-Иванова» из AC).

## 6. Тестовая стратегия и трассировка

Бэкенд — pytest (API через `reset_api_env`/`api_env`, домен через `db`, миграции через `committed`), фронт —
vitest. Новые тесты называются `test_019_acN_*` (бэкенд) и `019_acN_*` (vitest). SMTP всегда подменён.

| AC | Где реализуется | Тест (уровень) |
|----|-----------------|----------------|
| AC-1 | `state.registration_policy`, `FeatureDisabled`, `LoginPage`, `RegisterPage` | `backend/tests/api/test_019_registration_api.py::test_019_ac1_*` (`api_env` без SMTP: оба POST → 404 `feature_disabled`, писем нет); `frontend/tests/features/auth/LoginPage.test.tsx` (`enabled:false` → ссылки нет), `RegisterPage.test.tsx` (`enabled:false` → `auth.register_disabled`, формы нет) |
| AC-2 | `RegisterPage` | `frontend/tests/features/auth/RegisterPage.test.tsx::019_ac2_*` (ровно пять полей с метками, одна кнопка) |
| AC-3 | `router.tsx` (`GuestOnly`, исключение `onUnauthenticated`) | `RegisterPage.test.tsx::019_ac3_*` (через `AppRoutes`: `/me` 200 → переход на `startPath`; `/me` 401 → форма остаётся на `/register`) |
| AC-4 | `request_registration` (`normalize_email`) | API: пустой, 255 символов, без `@` → 422 `email_invalid`, писем 0 |
| AC-5 | `normalize_email`, `_email_taken` | API: ` New@Example.RU ` → письмо на `new@example.ru`; при учётной записи `new@example.ru` — писем 0 |
| AC-6 | отсутствие фильтров домена | API: три домена → три письма |
| AC-7 | RG-7 (единый путь, хеш всегда) | API `test_019_ac7_*`: 4 варианта × 20 запусков, разные IP или `advance(61 мин)`. Статус, тело и заголовки побайтно равны, \|медиана_i − медиана_j\| ≤ 200 мс |
| AC-8 | `_upsert_request`, `build_registration_mail` | API: одно письмо, ссылка `https://tracker.example.test/register/confirm#token=`, «30 минут», «Если вы не регистрировались, ничего не делайте»; в теле нет пароля, логина, имени и фамилии; в `registration_request` лежат `token_hash == sha256(token)` и Argon2-хеш (`$argon2id$`), открытого пароля и токена нет. Юнит `backend/tests/unit/test_019_registration_mail.py` |
| AC-9 | upsert по email (RG-1) | API: две заявки → первый токен 400 `registration_token_invalid`, второй 204 |
| AC-10 | `expires_at > now` | API: `advance(30 мин 1 с)` → 400, учётной записи нет; `advance(29 мин 59 с)` → 204 |
| AC-11 | `_email_taken` (любой статус) | API: адрес активной и заблокированной учётной записи → писем 0, `app_user` не прибавилось, ответ равен AC-7 |
| AC-12 | RG-1 | API: после заявки `GET /admin/users` (ТА) без новой записи; вход логином и паролем → 401 `invalid_credentials` |
| AC-13 | `confirm_registration` | API: 204; одна строка `app_user` с email, `login_display` как введён, «Анна», «Петрова-Иванова», `self_registered=true`, `must_change_password=false`; `workspace_member.role IS NULL`; `project_member` пуст; затем `POST /auth/password-reset/request` → письмо |
| AC-14 | RG-8 (адрес занят) | API: заявка → `PUT /admin/users/{id}/email` другой записи → confirm 400, записи нет |
| AC-15 | `_check_password` | API: 11 символов → 422 `password_too_short`; из списка → 422 `password_too_common`; 12 символов → 200 |
| AC-16 | удаление заявки; нет `Set-Cookie` | API: повтор → 400; в ответе 204 нет `Set-Cookie`, `user_session` пуст. Vitest `RegisterConfirmPage.test.tsx`: успех → `auth.register_confirmed`, ссылка на `/login`, запроса `/auth/login` нет |
| AC-17 | удалён в v0.4 | — |
| AC-18 | `registration_limits`, RG-5 | Домен `backend/tests/domain/test_019_registration_limits.py` (10 → True, 11-я False, отклонённые не пишутся, `advance(61 мин)` → True, другой IP не затронут); API: 10 разных адресов → 11-я 429; 9 → 10-я 200; 10 на один адрес → все 200, 11-я 429; 429 одинаков для адреса с учётной записью и без; в `registration_attempt.key_hash` нет байтов IP, все длиной 32 |
| AC-19 | `record_event(USER_SELF_REGISTERED)` | `backend/tests/api/test_019_registration_leaks.py`: одна запись `user.self_registered`, `actor_id = entity_id = id`, `changed_fields = []`, `details` NULL; после заявки без подтверждения и после неудачных подтверждений новых событий нет |
| AC-20 | NFR-1 | `test_019_registration_leaks.py`: сценарий заявка → подтверждение → вход под `caplog` DEBUG; в `caplog.text` нет email, имени, фамилии, логина, токена и пароля. Логи прокси (nginx) — только ручная проверка в R8-T22: тело запросов nginx не пишет, фрагмент URL на сервер не уходит |
| AC-21 | `LoginPage` | `LoginPage.test.tsx::019_ac21_*`: `enabled:true` → после «Войти» и «Забыли пароль?» ссылка `href="/register"`, фокус на «Логин», в блоке справки два `p`, второй — `auth.help_p2_registration`; `enabled:false` → блок как в 005 базы ветки (на `work3` — v0.1, `help_p1` + `help_p2`; после слияния с `main` — v0.2, один `p`), текста о регистрации нет |
| AC-22 | `AdminUser`, `UsersPage`, существующие действия | API `test_019_ta_manages_self_registered.py`: в `GET /admin/users` есть `first_name`, `last_name`, `self_registered=true`; block, reset-password, `PUT …/role` с каждой из трёх ролей (по одной учётной записи на роль) работают; создание ТА с именами даёт `must_change_password=true`. Vitest `UsersPage.test.tsx`: колонки и отметка |
| AC-23 | без изменений экранов | `frontend/tests/features/auth/019_no_register_link.test.tsx`: на `/change-password`, `/password-reset`, `/password-reset/confirm`, `/no-role` нет ссылки «Зарегистрироваться»; существующие тесты этих экранов зелёные без правок |
| AC-24 | NFR-2 | `backend/tests/arch/test_dependencies_allowlist.py` не меняется и проходит (списки зависимостей равны разрешённым, капчи нет); `backend/tests/unit/test_no_telemetry.py` проходит; SMTP подменён во всех тестах. В R8-T22 — `git diff` по `pyproject.toml`/`package.json` пуст |
| AC-25 | существующий гейт `no_role`, `LoginPage` | API: вход новой учётной записью → 200, `user.role = null`, `must_change_password = false`; `GET /me` и `GET /projects` → 403 `no_role`. Vitest — существующий тест перехода на `/no-role` при `role = null` |
| AC-26 | `set_role` (ТА), `assign_user_role` (БА) | API: ТА назначил «user» → `GET /projects` 200 той же сессией; то же от БА через `PUT /unassigned-accounts/{id}/role` → 200, в `/audit` `user.role_assigned` с `actor_id` = БА |
| AC-27 | RG-7 (логин раньше занятости адреса) | API: занятый логин со свободным и с занятым адресом → оба 422 `login_taken`, тела равны, писем 0; `Ab_c` при `ab_c` → `login_taken` |
| AC-28 | RG-8 (логин занят) | API: заявка `newuser` → ТА создал `newuser` → confirm 409 `login_taken`, учётной записи по заявке нет, строки заявки нет; повтор → 400 |
| AC-29 | `normalize_person_name` | Юнит `backend/tests/unit/test_019_names.py`; API: пустое имя → 422 `first_name_invalid`, фамилия из пробелов → `last_name_invalid`, 101 символ → 422; ` Анна ` + 100 символов → 200, в заявке «Анна» |
| AC-30 | `onboarding.py`, `unassigned_accounts.py`, гейт `/admin/users` | Домен `backend/tests/domain/test_019_onboarding.py`; API `backend/tests/api/test_019_onboarding_api.py`: список БА содержит обе записи без роли (своя и созданная ТА) с логином и именами и без ключа `email`, записей с ролью нет; «user» → 204; «business_admin»/«tech_admin» → 403, роль прежняя; смена или снятие у записи с ролью (в том числе только что назначенной) → 403 через оба пути (`/unassigned-accounts/…/role` и `/admin/users/…/role`); block, reset-password, `POST /admin/users`, `PUT /admin/users/{id}/name`, `GET /admin/audit` → 403; П: список и назначение → 403 |
| AC-31 | удалён в v0.4 | — |
| AC-32 | нет новых настроек | `backend/tests/unit/test_019_settings.py`: в `Settings.model_fields` нет имён с `regist`, `allow`, `domain`, `pilot`; `password_reset_enabled` — единственный флаг функции |
| AC-33 | `create_user` (RG-17), `CreateUserRequest` | Домен `backend/tests/domain/test_019_user_names.py`; API: пустое, из пробелов, 101 символ → 422 с кодом поля, записи нет; с именами → 201, имена в ответе, `must_change_password=true` |
| AC-34 | `profile.py`, `PUT /me/name`, `ProfilePage` | API `backend/tests/api/test_019_profile_api.py`: П и БА меняют свои имена → 200, `GET /me` их отдаёт, событие `user.name_changed` с `changed_fields` и без значений; пустое имя → 422; `PUT /admin/users/{other}/name` от П/БА → 403; без роли → 403 `no_role`. Vitest `ProfilePage.test.tsx` |
| AC-35 | `set_name`, `NameDialog`, `UsersPage` | API: ТА задаёт имена записи с NULL → 200, видны в `GET /admin/users`, событие с `actor_id` = ТА, `changes` NULL. Vitest `NameDialog.test.tsx`, `UsersPage.test.tsx` |
| AC-36 | миграция 0010 | `backend/tests/db/test_019_schema.py`: upgrade 0009→0010 на БД с пользователями → имена NULL, `self_registered=false`, остальные колонки байт в байт прежние, вход и роли работают; downgrade → upgrade; ограничения таблиц заявок и попыток; `alembic check` чист |
| AC-37 | `archive.py`, `importer.py` | `backend/tests/cli/test_019_export_names.py` + `test_export_import.py`: в архиве `first_name`/`last_name`, нет `email`, `registration_request`, `registration_attempt`; импорт в пустую БД восстанавливает имена, `email IS NULL`; цикл export→import→export идентичен |
| AC-38 | `registration_limits`, RG-6 | API: 5 подтверждений одним токеном (несуществующим или использованным) → 6-е 429, записи нет; 20 подтверждений с одного IP с разными токенами → 21-е 429; в `registration_attempt` нет IP и токена в открытом виде (ни в байтах `key_hash`, ни hex) |
| FR-3c / FR-11 (журнал имени) | `set_name`, `set_own_name` | см. AC-34, AC-35 |
| NFR-9 | RG-18 | Домен `backend/tests/db/test_019_purge_registration.py` (истёкшие удаляются, действующие нет, `dry_run` только считает); `backend/tests/cli/test_maintenance.py` (новый ключ отчёта) |
| NFR-8 | всё | `bash scripts/check.sh` (R8-T22; повторно на результате слияния с `main` — R8-T00) |

Ручная проверка (R8-T22, вне CI, на стенде без реальных пользователей): заявка с MailHog или другим тестовым
SMTP, открыть ссылку, подтвердить, войти, увидеть `/no-role`; затем БА назначает «Пользователь». Логи nginx не
содержат email, токена и пароля (AC-20).

## 7. Ветка и зависимости

**Ветка.** Реализация идёт в `feat/self-registration`, основанной на `origin/work3` (фича 020 MCP, голова
`401a63e`). Причина: миграция `0009_mcp_agent_access` есть только там, а миграция регистрации `0010` ставится
после неё (RG-21). В `main` её нет.

**Расхождение с `main`.** `origin/work3` ответвлён от `main` на `557d14c` и не содержит последних коммитов `main`:
слияние PR #7 (`96869b9`) и переименование продукта GOSTracker → GTrack (`2c8576a`, `3f0232a`, ~89 файлов). Что
это значит для фичи:
- CLI на `work3` — `gostracker` (`backend/pyproject.toml`, README), в `main` — `gtrack`. Задачи пишут команду
  так, как она называется в базе ветки (R8-T12), переименование приходит слиянием.
- В `main` изменены файлы, которые трогает и эта фича: `frontend/src/features/auth/LoginPage.tsx`,
  `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/auth/LoginPage.test.tsx`,
  `frontend/tests/shared/i18n.test.ts`, `backend/app/domain/ops/archive.py`, `backend/app/domain/ops/importer.py`,
  `backend/tests/cli/test_export_import.py`, `backend/tests/cli/test_maintenance.py`, `backend/tests/cli/test_openapi.py`,
  `backend/tests/db/test_migrations.py`, `backend/tests/infra/test_frontend_scaffold.py`,
  `backend/tests/infra/test_docs_static.py`, `README.md`, `specs/005-login-help/spec.md` (v0.2: один абзац справки).
  При слиянии ожидаются конфликты, прежде всего в справке `/login` (§4.7, Q-1).
- Перед выпуском нужен rebase или merge с `main` и полный прогон: задача R8-T00, риск R-12.

**Зависимости.** Новых пакетов нет. Python: `hmac`, `hashlib`, `secrets` (stdlib), `smtplib` уже используется через `core/mail.py`.
npm: нет. `test_dependencies_allowlist.py` не меняется (NFR-6, AC-24).

## 8. Риски
- **R-1. К-4 (ПДн, 152-ФЗ).** Код готов раньше решения ИБ. Включение = SMTP, выключателя нет, поэтому на стенде
  с реальным доступом до ADR-0019 нельзя задавать `SMTP_HOST`, и сброс пароля там тоже не работает. Если ИБ
  потребует согласие на обработку ПДн в форме, это новое поле и новая версия spec: затронет R8-T09, T11, T16.
- **R-2. Ломающее изменение `POST /admin/users` (RG-17).** Около 20 тестовых файлов создают учётные записи без
  имён (`admin_support.py`, `test_admin_users.py`, `test_password_change.py`, `test_user_admin_service.py`
  и др.). R8-T03 и R8-T04 перечисляют их явно, правка — только добавление аргументов, assert-ы не меняются.
- **R-3. Красный `npm run typecheck` между задачами.** Перегенерация `schema.d.ts` (R8-T02, T04, T05, T07,
  T11) делает обязательными новые поля (`CreateUserRequest.first_name`, `AdminUser.*`, `MeResponse.*`).
  `UsersPage.tsx` и типизированные моки (`frontend/tests/features/admin/helpers.tsx`,
  `frontend/tests/app/startPath.test.ts`) перестают компилироваться до R8-T19/T20. Моки правятся в той задаче, где
  меняется тип (они перечислены в файлах). `UsersPage.tsx` чинится только в R8-T20, поэтому критерии «Готово»
  бэкенд-задач фронтенд не включают. Полная проверка — R8-T22.
- **R-4. `alembic check`.** `server_default` у `self_registered` и имена ограничений должны совпасть с
  моделью. R8-T01 завершается только при чистом `alembic check`.
- **R-5. Время ответа (AC-7).** Ветки различаются одним upsert и удалением истёкших заявок. Медианы на 20
  запусках, на перегруженной машине тест может мигать, как в 007/R-1.
- **R-6. `commit_durably` в новом модуле (RG-6).** После фиксации advisory-блокировки лимитов снимаются,
  дальнейшие записи идут в новой транзакции запроса. Ничего, что нельзя фиксировать, до вызова быть не должно.
  Ревьюер проверяет, что `commit_durably` стоит только в двух описанных местах.
- **R-7. Меню.** Пункт «Профиль» у всех ролей меняет состав меню. Тесты `frontend/tests/app/sidebar.test.tsx`,
  `navigation.test.tsx`, `start-screen.test.tsx` расширяются (R8-T19, T21), а не ослабляются.
- **R-8. Перебор логинов** через `login_taken` ограничен лимитом IP (RG-5), с многих IP он возможен (spec §7.4).
- **R-9. Репутация почтового домена** (spec §7.4): без капчи и лимита по адресу один ящик можно засыпать письмами с
  разных IP. Код это не закрывает, решение принято владельцем.
- **R-10. Номер миграции** — снят: владелец решил, что 020 вливается первой, регистрация — `0010` (RG-21, Q-3).
  Остаток риска: если 020 в `main` изменит или перенумерует `0009`, `down_revision` придётся обновить в R8-T00.
- **R-11. Лимиты в dev** без `--proxy-headers`: все запросы с `127.0.0.1` (007/R-4).
- **R-12. Ветка без последних коммитов `main`** (§7). База — `origin/work3`. В нём нет слияния PR #7 и
  переименования GOSTracker → GTrack. Перед выпуском нужен rebase/merge с `main` с конфликтами в `LoginPage`,
  `ru.ts`, тестах экрана входа, README и CLI-тестах. После слияния возможны красные тесты, которые зелены на обеих
  ветках по отдельности (имя CLI в README и `test_docs_static.py`, абзац справки, пины голов миграций). Меры: задача
  R8-T00 после R8-T22, проверка во временном `git worktree`, решение конфликтов по §4.7 и §7, полный
  `bash scripts/check.sh` на результате слияния. Фичу нельзя выпускать раньше, чем 020 попадёт в `main`.

## 9. Вопросы к владельцу и проблемы spec

Решения владельца от 2026-11-08 окончательные. Открытым остаётся только К-4.

- **Q-1 (FR-12, AC-21) — закрыт.** Второй абзац справки на `/login` показывается только при включённой регистрации.
  Текст `auth.help_p2_registration` — по FR-12: «Учётную запись выдаёт технический администратор, или её можно
  создать самостоятельно через «Зарегистрироваться». Роль после регистрации назначает технический или
  бизнес-администратор.» При выключенной регистрации справка как в 005 базы ветки (§4.7, R8-T18, R8-T00).
- **Q-2 (FR-11) — закрыт.** События `user.self_registered` и `user.name_changed`, не `user_self_registered` (RG-10).
- **Q-3 — закрыт.** 020 (MCP) вливается первой. Миграция регистрации — `0010_self_registration`, `down_revision`
  = ревизия `0009_mcp_agent_access` (`"0009"`). `0009` не трогается (RG-21, §7).
- **Q-4 (FR-10) — закрыт.** Ответы 422 входят в лимит 10 заявок в час с IP (RG-5).
- **Q-5 (FR-13a).** Заблокированные учётные записи без роли видны БА, и он может назначить им «Пользователь» (RG-12).
  Владелец утвердил раздел и право БА «как в плане», отдельно этот пункт не обсуждался. Реализуется как в RG-12.
- **Q-6 (§3.1) — закрыт.** У ТА нет `onboard_accounts`, ему хватает `/admin/users` (RG-11).
- **Q-7 (FR-9) — закрыт.** Если пространств не ровно одно, регистрация отвечает 404 `feature_disabled` (RG-9).
- **К-4** — решение ИБ по ПДн, предусловие запуска (шапка плана, R-1). Открыто.


> Примечание (R8-T06, ревью): `FOR NO KEY UPDATE` в этом плане реализуется как `with_for_update(key_share=True)` в SQLAlchemy (так же, как в `users/service.py`).
