# Plan: ИИ-агент как участник трекера — ключи доступа, операции агента, инструменты MCP, метка «ИИ»

- **Spec:** ./spec.md v0.4 (утверждена владельцем 2026-10-30, открытых вопросов нет; Q-1…Q-13
  закрыты)
- **Статус:** DRAFT. Редакция 2026-10-30 под spec v0.4: З-1 и RK-1 закрыты решением владельца
  (FR-42: события задач и комментариев для всех авторов); добавлены PD-22…PD-24 (приоритет в
  `task.updated`, событие при переносе по доске, `comment.deleted` только при прямом удалении),
  трассировка AC-49…AC-53, перечень правок существующих тестов по AC-47 (§6.2). Остальные
  решения v0.2 не менялись.
- **Основа:** код ветки `feat/r1.0-foundation` на `f7f19cf` (006 реализована, голова миграций
  `0007`). База сравнения API для AC-47 — `docs/api/openapi.json` на `f7f19cf`.
- **Нумерация:** решения плана — `PD-1…`, замечания к spec — `З-1…`, риски — `RK-1…`, задачи —
  `R7-T01…`. Ссылки без префикса ведут на 007 (`AC-12` = 007/AC-12), на другие спецификации — с
  префиксом (`001/FR-57`, `006/FR-23`). Новые тесты: бэкенд — `test_007_acN_*` (или
  `test_007_frN_*`, если AC нет), фронтенд — `007_acN_*` / `007_frN_*`.
- **Окружение (проверено):** Python 3.12.13 в `.venv`; FastAPI 0.143.0, Starlette 1.8.0,
  Pydantic 2.14.1, SQLAlchemy 2.1.4, httpx 0.28.1. `APIRoute.matches` кладёт маршрут в
  `scope["route"]` (fastapi/routing.py). Сервер в поставке — один процесс uvicorn
  (`backend/docker-entrypoint.sh`, без `--workers`), перед ним nginx с самоподписанным
  сертификатом и переадресацией 80 → 443.

## 1. Подход

1. **Агент — обычная учётная запись с признаком `is_agent`.** ТА создаёт её отдельным
   маршрутом `POST /api/v1/admin/agents` (логин + роль П/БА/без роли, без пароля). Пароля нет по
   смыслу: в `password_hash` лежит Argon2-хеш выброшенного случайного значения, вход явно
   отклоняется тем же `invalid_credentials`. Права — роль 002 без изменений.
2. **Ключ** — `gtk_` + base64url(32 случайных байта). В БД — только SHA-256 секрета (таблица
   `api_key`), без префикса и любой части секрета. Передаётся в `Authorization: Bearer <ключ>`.
   ТА выпускает, видит и отзывает ключи через `/api/v1/admin/agents/{user_id}/api-keys*`;
   выпуск, отзыв и создание агента — записи журнала аудита.
3. **Операции агента — существующие маршруты** (`/me`, `/projects`, `/me/tasks`,
   `/projects/{id}/tasks`, `/tasks/{id}`, `/tasks/{id}/subtasks`, `/tasks/{id}/comments`). По
   ключу разрешены ровно эти 10 маршрутов (перечень `AGENT_OPERATIONS` по имени маршрута);
   любой другой маршрут с ключом получает 403 `forbidden` от app-level зависимости до
   обработчика. Форматы ответов и ошибок те же (FR-28). Субъект запроса по ключу — `Actor` с
   `api_key_id`. Гейты 001/002 и сервисы не меняются, кроме двух мест: список проектов по ключу —
   только по членству (FR-19), права удаления и правки комментариев по ключу — `false` (FR-17).
4. **Лимит 120/мин и «последнее использование»** — одним атомарным `UPDATE api_key … RETURNING`
   в аутентификации с немедленной фиксацией (`commit_durably`, как у сессий). Счётчик живёт в БД:
   верно при любом числе процессов.
5. **События** получают столбец `api_key_id`. Запись событий задач и комментариев по FR-42 —
   для людей и агентов одинаково, в сервисах: `task.created` (`create_task`, `create_subtask`),
   `task.updated` (`update_task`; `move` — только при смене колонки), `comment.created`
   (`create_comment`), `comment.deleted` (`delete_comment`, только прямое удаление). Приоритет —
   обычное поле `task.updated` со значениями до/после. Каскадные удаления, правка комментария,
   удаление задачи, перенос внутри колонки, снятие исполнителя при исключении участника — без
   событий (PD-9, PD-22…PD-24).
6. **MCP** — свой минимальный сервер на стандартной библиотеке Python в одном модуле
   `backend/app/agent_mcp.py` (JSON-RPC 2.0 построчно по stdio + `urllib`). 11 инструментов, по
   одному на операцию FR-18…FR-27. Новых зависимостей нет.
7. **Интерфейс** — метка «ИИ» через общий `UserName`, строка «Автор» в карточке, в
   «Учётных записях» — создание агента, ключи с однократным показом секрета, отзыв. Новых файлов
   в `frontend/src` нет.

ML-кода, датасетов, обучения и GPU нет (NFR-5).

## 2. Решения

| ID | Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---|---|---|---|
| PD-1 | Формат и хранение ключа (FR-6, NFR-3, AC-39, AC-41) | Секрет `gtk_` + `base64.urlsafe_b64encode(secrets.token_bytes(32))` без `=` (43 символа, всего 47; 256 бит). Формат — `fullmatch` `gtk_[A-Za-z0-9_-]{43}`. В БД — `api_key.secret_digest = sha256(секрет).digest()` (bytea 32, UNIQUE). Префикса, «последних символов» и любой части секрета нет ни в БД, ни в перечне. Ключ опознаётся по `api_key.id` (UUID) и названию | (а) хранить префикс для опознания; (б) HMAC с `SECRET_KEY`, как у сессий; (в) Argon2; (г) id ключа внутри секрета | (а) и (г) кладут в БД подстроку секрета длиной ≥ 8 — нарушение AC-39 и FR-7 («ни любой его части»). (б) смена `SECRET_KEY` молча отозвала бы все ключи; при 256 битах случайности перебор прообраза невозможен и без секрета сервера. (в) сотни мс на каждый запрос — нарушение NFR-2; медленный хеш нужен только для низкоэнтропийных паролей. Константа `gtk_` (4 символа) — не секрет и в подстроки ≥ 8 без случайной части не входит |
| PD-2 | Заголовок авторизации (FR-12, FR-13) | `Authorization: Bearer <ключ>`. Наличие **любого** заголовка `Authorization` = запрос по ключу: cookie не читается. Значение не вида `Bearer <непробельные>` (другая схема, пусто, два заголовка `Authorization`) — ключ «не по формату» → 401. Путь и параметры адреса не читаются: ключ в `?key=` не аутентифицирует (запрос без заголовка идёт по cookie, без cookie — 401) | (а) свой `X-API-Key`; (б) игнорировать не-Bearer схемы и падать на cookie | (а) нестандартно; `Authorization` уже маскируется логгером (`_SECRET_WORDS`). (б) неоднозначность «чем аутентифицирован запрос». Поставляемый nginx Basic-аутентификацию не использует (ADR-0015 фиксирует: прокси с Basic перед API не поддерживается) |
| PD-3 | Объём доступа по ключу (FR-17, AC-33) | `AGENT_OPERATIONS` — `frozenset` имён маршрутов: `me`, `list_projects`, `list_my_tasks`, `list_project_tasks`, `get_task`, `create_task`, `create_subtask`, `update_task`, `list_comments`, `create_comment`. App-level зависимость `require_agent_scope` (без БД, после `check_origin`): есть `Authorization` и `request.scope["route"].name ∉ AGENT_OPERATIONS` → 403 `forbidden`. Для маршрутов из перечня ключ проверяет `get_actor` (401/429). Дополнительно в `policy.py`: `can_delete_task`, `can_edit_comment`, `can_delete_comment` для `actor.api_key_id is not None` → `False` | (а) отдельные маршруты `/api/v1/agent/*`; (б) проверка перечня внутри `get_actor` | (а) дублирует 10 обработчиков и схем, FR-28 требует формат обычного API. (б) маршруты без `get_actor` (`/auth/login`, `/health`) приняли бы ключ. Правило в `policy.py` — вторая линия защиты и правдивые `permissions` в карточке (З-6). Порядок для маршрута вне перечня с недействительным ключом — 403, а не 401 (З-4) |
| PD-4 | Учётная запись агента (FR-1, FR-2, AC-1, AC-2) | Столбец `app_user.is_agent boolean NOT NULL DEFAULT false`. Создание — `POST /api/v1/admin/agents` `{login, role}` (`role`: `user`/`business_admin`/`null`; `tech_admin` → 422 `agent_role_not_allowed`). `password_hash` = Argon2 от `secrets.token_urlsafe(32)`, значение сразу выбрасывается; `must_change_password=false`. Одно событие аудита `user.agent_created`, `details.role_to`. Вход: `login()` отклоняет `is_agent` тем же `InvalidCredentials`. Сброс пароля агенту — 422 `agent_password_not_allowed`. Смена роли агента на ТА — 422 `agent_role_not_allowed`, без события. Признак не меняется: маршрута смены нет | (а) `password_hash` NULL; (б) расширить `POST /admin/users` полями `is_agent`, `role` | (а) NULL ломает `reserve_attempt`/`verify` и требует правок всех путей входа; хеш случайного значения даёт ту же стоимость проверки, что у людей (время ответа не выдаёт агента). (б) `one_time_password` в существующей схеме обязателен, роль назначается отдельным действием с отдельной записью журнала — AC-1 требует одну запись (З-2) |
| PD-5 | Лимит частоты (FR-33, AC-40) и последнее использование (FR-16) | Фиксированное окно 60 с на ключ в столбцах `api_key.rate_window_start`, `rate_count`. Один `UPDATE api_key SET … WHERE secret_digest=:d AND revoked_at IS NULL AND expires_at > :now RETURNING …`: окно сбрасывается, если `rate_window_start IS NULL OR rate_window_start <= now - 60s`; `rate_count = LEAST(rate_count+1, 121)`; `last_used_at = now`, только если запрос в пределах лимита. Сразу после — `commit_durably` (счётчик и время переживают 4xx/429). `rate_count > 120` → 429 `too_many_requests`, `Retry-After = ceil(window_start + 60s − now)`, не меньше 1. Часы — `utcnow()` (в тестах `FixedClock`) | (а) словарь в памяти процесса; (б) Redis; (в) скользящее окно по журналу запросов | (а) при нескольких процессах uvicorn или репликах лимит умножается, сбрасывается при перезапуске; поставка — один процесс, но оператор может добавить `--workers`. (б) новый сервис и зависимость. (в) больше записей без выгоды. Запись на каждый запрос — тот же приём, что `last_activity_at` у сессий (`get_actor` → `commit_durably`), стоимость измеряется AC-48 |
| PD-6 | API ключей для ТА (FR-5…FR-10, FR-40) | Роутер `api/v1/admin_agents.py`, префикс `/admin/agents`, гейт `require_capability(MANAGE_ACCOUNTS)`: `GET /{user_id}/api-keys` (`Page[ApiKeyInfo]`, `created_at DESC, id DESC`), `POST /{user_id}/api-keys` `{name, expires_in_days=90}` → 201 `IssuedApiKeyResponse {key, secret}` с заголовком `Cache-Control: no-store`, `POST /{user_id}/api-keys/{key_id}/revoke` → 204. Срок: `expires_in_days` целое 1…365 (отрицательное = «в прошлом», 0 = «нулевой», 366 = «больше максимума» → 422 `validation_error`). Состояние ключа вычисляется: `revoked` (есть `revoked_at`), иначе `expired` (`expires_at <= now`), иначе `active`. Лимит 5 действующих → 422 `api_key_limit_reached`. Не агент → 422 `not_an_agent`; заблокирован → 422 `user_blocked`. Перечень у не агента — пустая страница | (а) абсолютная дата окончания; (б) `DELETE` ключа для отзыва | (а) возможна, но «сутки» — единица spec и проще в интерфейсе (З-9). (б) ключ не удаляется — история и `domain_event.api_key_id` ссылаются на него |
| PD-7 | Блокировка (FR-4, AC-4) | `block_user` в той же транзакции: `UPDATE api_key SET revoked_at=now, revoked_by=actor WHERE user_id=target AND revoked_at IS NULL AND expires_at > now`. Отдельных записей журнала нет (одна `user.blocked`). Разблокировка ключи не трогает | Проверять блокировку только в аутентификации | FR-4: ключи должны остаться отозванными после разблокировки (AC-4) |
| PD-8 | Протокол блокировок действий с ключами | Выпуск и отзыв — после `users.service.lock_for_account_change` (публичная обёртка над `_lock_for_account_change`, тот же advisory-lock пространства): подсчёт пяти действующих ключей и вставка не гонятся | Свой `SELECT … FOR UPDATE` строки агента | Единый протокол действий с учётными записями (deadlock-разбор T16/T16a в 001); монопатч `_lock_for_account_change` в `test_admin_roles.py` продолжает действовать, т.к. обёртка вызывает его по имени модуля |
| PD-9 | События и идентификатор ключа (FR-30, FR-42, AC-35, AC-49) | `domain_event.api_key_id uuid NULL` (FK `api_key.id` RESTRICT, ключи не удаляются). `record_event(..., api_key_id: UUID | None = None)`. Сервисы передают `actor.api_key_id` (у людей `None`). Пишутся для всех авторов (FR-42): `task.created` (`create_task`, `create_subtask`), `task.updated` (`update_task` — при изменении хотя бы одного поля из `fields` каталога, `changes` — по `value_fields`; `move` — PD-23), `comment.created` (`create_comment`), `comment.deleted` (`delete_comment`, PD-24). Аудит: `user.agent_created`, `user.api_key_issued`, `user.api_key_revoked` (`entity_type=user`, `entity_id` = агент, `details.api_key_id`, `details.api_key_name`) | ContextVar с ключом запроса | Явная передача видна в типах; ContextVar в зависимости FastAPI под `httpx.ASGITransport` живёт в задаче теста и «протекает» между запросами |
| PD-10 | Признак «агент» в API (FR-31, AC-36, NFR-1) | Обязательное `is_agent: bool` в ответах: `UserRef` (автор, исполнитель, автор комментария, участник, владелец, доска), `DirectoryUser`, `AdminUser`, `MeResponse`. Доменные `UserRef`/`DirectoryUser`/`UserAccount` получают поле без значения по умолчанию (mypy находит все места создания). `AuditActor` не меняется | Необязательное поле с умолчанием | Признак всегда известен; FastAPI всё равно делает поля ответа с умолчанием обязательными в выходной схеме. `AuditActor` не входит в перечень FR-31 (журнал — раздел ТА) |
| PD-11 | Маскирование секрета (FR-32, AC-38) | (1) Секрет хешируется до любого обращения к БД — в SQL и тексты `DBAPIError` попадает только дайджест. (2) `redact_text` в `core/logging.py` дополнительно заменяет `gtk_[A-Za-z0-9_-]{8,}` на `***` в любом тексте (сообщения, трассировки, путь в access-логе). (3) `IssuedApiKey.secret` — `field(repr=False)`. (4) Ошибки аутентификации не содержат значения заголовка. (5) nginx: свой `log_format` без строки запроса (`$request_method $uri`), чтобы ключ в `?…` не попал в access-лог web | Только существующий фильтр по именам ключей | Фильтр маскирует `authorization=…`, но не голое значение (например, в пути); шаблон ключа узнаваем по префиксу |
| PD-12 | Реализация MCP (FR-35, D-7, NFR-6) | Свой минимальный сервер в одном модуле `backend/app/agent_mcp.py`, **только стандартная библиотека** (проверяется AST-тестом). JSON-RPC 2.0, одно сообщение — одна строка UTF-8 в stdin/stdout; методы `initialize`, `ping`, `tools/list`, `tools/call`; уведомления (`notifications/*`) без ответа; массивы (batch) → `-32600`. Версии протокола: `2025-06-18`, `2025-03-26`, `2024-11-05` (ответ — запрошенная, если поддержана, иначе `2025-06-18`). HTTP — `urllib.request`. Запуск: `python3 -I <репозиторий>/backend/app/agent_mcp.py` (установка пакета не нужна) или консольная команда `gostracker-mcp` (`[project.scripts]`) | (а) официальный пакет `mcp` (MIT); (б) сервер на Node; (в) точка MCP в сервере трекера | (а) ~10 транзитивных пакетов (anyio, httpx-sse, starlette, sse-starlette, uvicorn, pydantic-settings, jsonschema, python-multipart…), правка allowlist и проверка лицензий; на машине агента пришлось бы ставить весь бэкенд. Нужные 4 метода — ~300 строк. (б) второй рантайм. (в) вне рамок (Q-9) |
| PD-13 | Набор инструментов (FR-35, AC-42) | **Ровно 11**, по одному на действие: FR-18 `whoami`, FR-19 `list_projects`, FR-20 `list_my_tasks`, FR-21 `list_project_tasks`, FR-22 `get_task`, FR-23 `create_task`, FR-24 `create_subtask`, FR-25 `set_task_status`, FR-26 `update_task`, FR-27 `list_comments` и `add_comment`. FR-25 и FR-26 — разные инструменты над одним `PATCH /tasks/{id}` (`set_task_status` шлёт только `status`; у `update_task` параметра `status` нет). Таблица — §4.9 | (а) 10 (один `update_task` со статусом); (б) 10 (комментарии одним инструментом с режимом) | FR-27 называет две операции (чтение и добавление); AC-42 требует описания смены статуса с `done` как закрытием — отдельный инструмент делает это однозначным. Число 11 закрепляется тестом (З-3) |
| PD-14 | Проверка аргументов инструментов (FR-37, AC-44) | Локально: аргументы — объект; неизвестные имена → ошибка `invalid_arguments`; параметры пути (`task_id`, `project_id`) — обязательны и формата UUID. Остальное (обязательность полей тела, перечисления, формат даты, длины) проверяет API и возвращает свои коды (`validation_error`, `due_date_in_past`…) | Полная проверка по JSON Schema на стороне инструмента | Иначе «создание без описания» дало бы локальный код вместо 422 `validation_error` (AC-44), и правила разошлись бы с сервером. Проверка UUID не даёт подставить в путь `../admin/...` |
| PD-15 | Транспорт инструментов (NFR-3, NFR-6, FR-38) | Конфигурация из окружения процесса: `GOSTRACKER_URL` (только origin `https://host[:port]`; `http://` — только `localhost`, `127.0.0.1`, `[::1]`), `GOSTRACKER_API_KEY`, необязательный `GOSTRACKER_CA_FILE` (сертификат поставки самоподписанный). Переадресации не выполняются (3xx → ошибка `redirect_not_allowed`): иначе ключ ушёл бы по новому адресу. Таймаут 30 с. Ключ не логируется; в stderr — только имя инструмента и HTTP-статус. Нет ключа → каждый `tools/call` без сетевого запроса отдаёт ошибку 401 `not_authenticated`; неверный URL → ошибка `config_error`; `tools/list` работает всегда | Читать ключ из параметров инструмента | FR-38. Переадресация 80 → 443 nginx при `http://` отправила бы ключ открытым текстом — поэтому `http://` вне loopback запрещён конфигурацией |
| PD-16 | Интерфейс без новых файлов `frontend/src` | `UserName({ user })` — новый экспорт `shared/ui/UserPicker.tsx`; раздел ключей — компонент `AgentKeys` внутри `features/admin/UsersPage.tsx`; строка «Автор» — в `TaskPage.tsx` в конце `dl.ui-props` | Новые `shared/ui/UserName.tsx`, `features/admin/AgentKeys.tsx` + правка белого списка `test_t21_src_files_only_expected` | Как в 006 (PD-3, RK-10): правка белого списка — решение владельца. План Б — RK-11 |
| PD-17 | Однократный показ секрета в интерфейсе (FR-6, FR-40) | Как одноразовый пароль в `UsersPage`: прямой вызов `issueApiKey` и `useState`, без `useMutation` (кэш мутаций держит `data` до сборки мусора) и без записи в кэш TanStack Query. Окно с полем только для чтения, кнопкой «Копировать» (`navigator.clipboard.writeText`) и предупреждением; закрытие окна обнуляет состояние | `useMutation` | Секрет не должен пережить окно (AC-37) |
| PD-18 | Совместимость API (AC-47, NFR-1) | Копия `docs/api/openapi.json` на `f7f19cf` в `backend/tests/api/openapi_baseline_f7f19cf.json`; тест сравнивает: пути и методы базы присутствуют; у компонент-схем базы свойства не удалены и `type`/`$ref`/`format`/`enum` не изменились; у схем тел запросов набор `required` не вырос | `git show f7f19cf:…` в тесте | В CI возможен неполный клон; файл фиксирует базу навсегда |
| PD-19 | Замер NFR-2 (AC-48) | Модуль `backend/tests/perf/test_api_key_overhead_007.py`: по умолчанию 20 + 20 запросов карточки без порога (CI); при `GT_PERF=1` — 200 + 200 после 20 прогревочных, p95 по ключу − p95 по сессии ≤ 20 мс | Отдельный скрипт в `scripts/` | Переиспользует фикстуры БД и мира §5 |
| PD-20 | ADR | `docs/adr/0015-agent-access.md`: учётная запись агента, формат и хранение ключа, заголовок, объём доступа, лимиты, транспорт MCP, ограничения (Basic перед API, `http` только loopback) | — | NFR-7 |
| PD-21 | Коммиты | R7-T05 + R7-T06 — один коммит (после R7-T05 OpenAPI и типы фронтенда не перегенерированы). Остальные — по одному. R7-T14 — код событий, правки существующих тестов §6.2 и абзац `docs/data-model.md` одним коммитом | — | Каждый коммит — зелёный `scripts/check.sh` |
| PD-22 | Приоритет в `task.updated` (FR-42, Q-11, AC-51, AC-47) | В каталоге (`domain/events/catalog.py`) у `task.updated`: `fields` = `{status, assignee_id, due_date, priority, title, description}`, `value_fields` = `{status, assignee_id, due_date, priority}`. Изменение приоритета пишет имя поля и **значения до/после** (`{"field": "priority", "old": "medium", "new": "high"}`), как у статуса. Порядок `changed_fields` — постоянный кортеж `EVENT_FIELDS = ("status", "assignee_id", "due_date", "priority", "title", "description")` (только реально изменившиеся) | (а) только имя поля без значений (как `title`/`description`); (б) приоритет вне перечня (прежний whitelist) | (б) отменено владельцем (Q-11). (а) отвергнуто: приоритет — закрытое перечисление, не текстовое бизнес-значение (BR-2 запрещает значения только у текстов: `title`, `description`, `name`, `body` — `test_br2_*` остаются зелёными); статус, срок и исполнитель уже пишутся со значениями; отложенная лента 001/FR-38 исключает старое и новое значение только у названия и описания («правка названия или описания отражается событием без старого и нового значения»). Правка `value_fields` в `test_event_catalog.py` — та же проверка допустимого состава полей `task.updated`, что исключение AC-47 v0.4 (см. З-11). План Б при несогласии ревьюера/владельца: убрать `priority` из `value_fields` (одна строка каталога и одна строка теста) |
| PD-23 | Событие при переносе по доске (FR-42, Q-12, AC-52) | В `tasks.service.move` после `_load_task`: `await positions.lock_task_columns(db, task, target)` (тот же порядок, что в `update_task`: колонки → строка; повторный вызов внутри `move_task` под уже взятыми блокировками не ждёт), затем `old = TaskStatus(task.status)` — статус свежей строки под блокировкой. После `move_task` и `flush`: если `old != target` — одно `task.updated`, `changed_fields=["status"]`, `changes=[{"field": "status", "old": old, "new": target}]`, `project_id`, `api_key_id=actor.api_key_id`. Внутри колонки (`old == target`) — без события. Отказы (403, 404, 422 `invalid_neighbors`, 503) — до записи, транзакция откатывается | (а) `positions.move_task` возвращает прежний статус; (б) сравнивать со снимком `_load_task` до блокировок | (а) меняет контракт модуля позиций и его тестов (`test_positions.py`) ради одного вызывающего. (б) гонка: параллельный перенос между чтением и блокировкой дал бы неверное «было» или лишнее/потерянное событие. Порядок карточек (`position`) в перечень не входит (FR-42) |
| PD-24 | `comment.deleted` (FR-42, Q-13, AC-53) | Пишется только в `comments.service.delete_comment` (прямое удаление), после `flush`: `entity_id` = комментарий, `project_id` = проект задачи, автор — актор. Каскады `tasks.service.delete_task` (задача, подзадача) и `projects.service.delete_project` не меняются и событий не пишут. Повторное удаление — 404 из `_lock_live_comment` до записи. Правка комментария (`edit_comment`) — без события | Писать `comment.deleted` и при каскаде | Отвергнуто владельцем (Q-13); каскад — одна операция над задачей/проектом, а `task.deleted` вне рамок (spec §6) |

## 3. Затрагиваемые модули и файлы

**Бэкенд** (`backend/app`):
- `migrations/versions/0008_agent_api_keys.py` — новая миграция (R7-T02).
- `domain/users/models.py` (`is_agent`), `domain/api_keys/__init__.py`, `domain/api_keys/models.py`
  (новые), `domain/events/models.py` (`api_key_id`), `domain/registry.py` (импорт) — R7-T02.
- `core/security/api_keys.py` (новый), `core/logging.py` — R7-T03.
- `core/errors.py` (`TooManyRequests`, коды), `domain/events/catalog.py`, `domain/events/writer.py` — R7-T04.
- `domain/users/directory.py`, `domain/projects/members.py`, `domain/projects/queries.py`,
  `domain/comments/service.py`, `api/v1/schemas/common.py` — `is_agent` в ссылках (R7-T05).
- `domain/access/roles.py` (`Actor.is_agent`), `api/deps.py`, `api/v1/schemas/auth.py`, `api/v1/me.py`,
  `domain/users/service.py` (`UserAccount.is_agent`), `api/v1/schemas/admin.py` (`AdminUser.is_agent`) — R7-T06.
- `domain/users/service.py` (`create_agent`, правила агента, отзыв ключей при блокировке, публичные
  обёртки), `domain/auth/service.py` (вход агента) — R7-T07.
- `api/v1/schemas/admin.py` (`CreateAgentRequest`), `api/v1/admin_agents.py` (новый), `api/v1/__init__.py` — R7-T08.
- `domain/api_keys/service.py` (новый) — R7-T09. `api/v1/schemas/admin.py`, `api/v1/admin_agents.py` — R7-T10.
- `domain/api_keys/auth.py` (новый), `domain/access/roles.py` (`api_key_id`, `session_id`),
  `domain/auth/service.py` (`SessionActor`) — R7-T11.
- `api/deps.py` (ключ в `get_actor`, `require_agent_scope`), `main.py` (регистрация) — R7-T12.
- `domain/projects/queries.py` (`list_projects` по ключу), `domain/access/policy.py` — R7-T13.
- `domain/tasks/service.py` (`create_task`, `create_subtask`, `update_task`, `move`),
  `domain/comments/service.py` (`create_comment`, `delete_comment`), `domain/events/catalog.py`
  (приоритет в `task.updated`, PD-22) — события FR-42, R7-T14.
- `app/agent_mcp.py` (новый) — R7-T17, R7-T18; `pyproject.toml` (`[project.scripts]`) — R7-T18.
- **Не меняются:** маршруты задач, проектов и комментариев (`api/v1/tasks.py`, `projects.py`,
  `comments.py`, `boards.py`), схемы задач и комментариев, `auth/sessions.py`, `auth/provider.py`,
  `domain/tasks/positions.py`, `domain/projects/service.py` и `domain/projects/members.py` (каскад
  удаления и снятие исполнителя событий не пишут), `domain/ops/demo.py` (демо — прямые вставки,
  событий задач нет).

**Сгенерированные:** `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` —
`bash scripts/gen-api.sh` в R7-T06, R7-T08, R7-T10.

**Фронтенд** (`frontend/src`, новых файлов нет): `shared/ui/UserPicker.tsx` (`UserName`),
`shared/ui/ui.css`, `shared/i18n/ru.ts`, `features/tasks/TaskPage.tsx`, `features/comments/Comments.tsx`
(R7-T19); `features/boards/BoardView.tsx`, `features/tasks/TaskList.tsx` (R7-T20);
`features/admin/api.ts`, `features/admin/UsersPage.tsx` (R7-T21, R7-T22); `features/admin/AuditPage.tsx` (R7-T22).

**Инфраструктура:** `deploy/web/default.conf.template` (`log_format`) — R7-T16.

**Документы:** `docs/data-model.md` (R7-T02 — столбцы и таблица; R7-T14 — абзац «События» и
каталог: что пишется по FR-42); `docs/adr/0015-agent-access.md`, `docs/agents.md`,
`README.md`, `docs/acceptance/mvp-demo.md`, `docs/glossary.md` (R7-T24); `specs/001-pilot-r1/spec.md` (R7-T25).

## 4. Интерфейсы

### 4.1. Модель данных и миграция 0008 (R7-T02)

```python
# backend/app/domain/users/models.py — AppUser
is_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

# backend/app/domain/api_keys/models.py
class ApiKey(UUIDPkMixin, Base):
    __tablename__ = "api_key"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 100", name="name_length"),
        CheckConstraint("octet_length(secret_digest) = 32", name="digest_length"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint("rate_count >= 0", name="rate_count_nonnegative"),
        CheckConstraint("(revoked_at IS NULL) = (revoked_by IS NULL)", name="revoked_pair"),
        Index("ix_api_key_workspace_id_user_id", "workspace_id", "user_id"),
    )
    workspace_id: Mapped[UUID]          # FK workspace.id RESTRICT, deferrable
    user_id: Mapped[UUID]               # FK app_user.id RESTRICT (агент)
    name: Mapped[str]                   # Text NOT NULL
    secret_digest: Mapped[bytes]        # LargeBinary NOT NULL UNIQUE (uq_api_key_secret_digest)
    created_at: Mapped[datetime]        # timestamptz NOT NULL, default utcnow
    created_by: Mapped[UUID]            # FK app_user.id RESTRICT NOT NULL (ТА)
    expires_at: Mapped[datetime]        # timestamptz NOT NULL
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[UUID | None]     # FK app_user.id RESTRICT
    last_used_at: Mapped[datetime | None]
    rate_window_start: Mapped[datetime | None]
    rate_count: Mapped[int]             # Integer NOT NULL, server_default 0

# backend/app/domain/events/models.py — DomainEvent
api_key_id: Mapped[UUID | None]        # FK api_key.id RESTRICT deferrable, NULL
```

`0008_agent_api_keys.py`: `revision="0008"`, `down_revision="0007"`. Upgrade: `ADD COLUMN is_agent
… DEFAULT false NOT NULL` → `CREATE TABLE api_key` → `ALTER TABLE domain_event ADD COLUMN
api_key_id` + FK. Downgrade — в обратном порядке (потеря ключей и признака при откате —
ожидаемо, ADR-0015). Триггеры неизменяемости `domain_event` на `ALTER TABLE` не влияют
(добавление столбца без значения по умолчанию строки не переписывает). Тестовые фабрики:
`tests/factories.py::make_user(..., is_agent: bool = False)`, `make_api_key(db, *, user, created_by,
secret=None, created_at, expires_at, revoked_at=None, revoked_by=None, last_used_at=None) -> ApiKeyRow`
(`ApiKeyRow`: `id`, `secret`).

### 4.2. Секрет ключа (R7-T03)

```python
# backend/app/core/security/api_keys.py
API_KEY_PREFIX: Final = "gtk_"
API_KEY_RANDOM_BYTES: Final = 32
API_KEY_FORMAT: Final = re.compile(r"gtk_[A-Za-z0-9_-]{43}", re.ASCII)       # fullmatch
API_KEY_LEAK_PATTERN: Final = re.compile(r"gtk_[A-Za-z0-9_-]{8,}", re.ASCII)  # для логов

def generate_api_key() -> str: ...          # gtk_ + urlsafe_b64(token_bytes(32)) без '='
def is_api_key_format(value: str) -> bool: ...
def api_key_digest(value: str) -> bytes: ... # sha256(value.encode("ascii")).digest(); не по формату -> ValueError без значения в тексте

# backend/app/core/logging.py: redact_text(text) дополнительно
#   if API_KEY_PREFIX in text: text = API_KEY_LEAK_PATTERN.sub(MASK, text)
```

### 4.3. Ошибки и события (R7-T04)

```python
# backend/app/core/errors.py
class ErrorCode(StrEnum):  # [007] дополнение
    agent_role_not_allowed = "agent_role_not_allowed"          # агенту роль ТА
    agent_password_not_allowed = "agent_password_not_allowed"  # сброс пароля агенту
    not_an_agent = "not_an_agent"                              # ключ не агенту
    api_key_limit_reached = "api_key_limit_reached"            # шестой действующий ключ

class TooManyRequests(AppError):
    status_code = 429; code = "too_many_requests"; default_detail = "Слишком много запросов"
    def __init__(self, *, retry_after: int) -> None: ...      # retry_after >= 1, иначе ValueError
# _app_error_handler: TooManyRequests -> заголовок {"Retry-After": str(retry_after)}; ServiceBusy — как сейчас

# backend/app/domain/events/catalog.py — EventAction + EVENT_CATALOG (_USER_AUDITED)
USER_AGENT_CREATED = "user.agent_created"
USER_API_KEY_ISSUED = "user.api_key_issued"
USER_API_KEY_REVOKED = "user.api_key_revoked"
# [R7-T14, PD-22] EventAction.TASK_UPDATED:
#   fields=frozenset({"status","assignee_id","due_date","priority","title","description"}),
#   value_fields=frozenset({"status","assignee_id","due_date","priority"})

# backend/app/domain/events/writer.py
class UserEventDetails(TypedDict, total=False):
    role_from: str | None; role_to: str | None
    api_key_id: str | None; api_key_name: str | None
async def record_event(db, *, workspace_id, actor_id, action, entity_id, changed_fields=(),
                       project_id=None, deal_id=None, changes=None, details=None,
                       api_key_id: UUID | None = None) -> int: ...   # пишет domain_event.api_key_id
```

### 4.4. Признак «агент» в ответах (R7-T05, R7-T06)

```python
# domain/users/directory.py
@dataclass(frozen=True) class UserRef: id: UUID; login: str; is_agent: bool
@dataclass(frozen=True) class DirectoryUser: id: UUID; login: str; role: Role; is_agent: bool
# user_refs / list_directory выбирают AppUser.is_agent; members.py, projects/queries.py
# (владелец), comments/service.py (запасной UserRef(..., is_agent=False)) — то же.

# api/v1/schemas/common.py:  UserRef.is_agent: bool;  DirectoryUser.is_agent: bool
# api/v1/schemas/auth.py:    MeResponse.is_agent: bool
# api/v1/schemas/admin.py:   AdminUser.is_agent: bool
# domain/users/service.py:   UserAccount.is_agent: bool (list_accounts, get_account, _Target)
# domain/access/roles.py:    Actor.is_agent: bool = False  (get_actor читает AppUser.is_agent)
```

### 4.5. Учётная запись агента (R7-T07, R7-T08)

```python
# backend/app/domain/users/service.py
async def create_agent(db, actor, hasher, *, login: str, role: Role | None) -> UserAccount:
    """403 (MANAGE_ACCOUNTS; при role is not None ещё ASSIGN_ROLES) -> role == TECH_ADMIN:
    422 agent_role_not_allowed -> login_invalid -> login_taken -> Argon2 случайного значения ->
    lock_for_account_change -> INSERT app_user(is_agent=True, must_change_password=False) +
    workspace_member(role) -> одно событие USER_AGENT_CREATED, details={"role_to": role|None}."""
async def lock_for_account_change(db, workspace_id: UUID, target_id: UUID, actor_id: UUID) -> None
async def load_account(db, workspace_id: UUID, user_id: UUID) -> UserAccount   # 404 NotFound
# set_role: после _load_target, если target.is_agent и new_role is Role.TECH_ADMIN -> 422 agent_role_not_allowed
# reset_password: после первого _load_target (404), если is_agent -> 422 agent_password_not_allowed
# block_user: после UPDATE app_user -> UPDATE api_key ... (PD-7), событие одно (user.blocked)

# backend/app/domain/auth/service.py — login(): в выборке строки AppUser.is_agent;
#   row is None or row.is_blocked or row.is_agent -> commit_durably; InvalidCredentials()

# backend/app/api/v1/schemas/admin.py
class CreateAgentRequest(BaseModel):  # extra="forbid"
    login: Annotated[str, Field(max_length=MAX_CREDENTIAL_LENGTH)]
    role: Role | None                  # обязательный ключ, null = «без роли»

# backend/app/api/v1/admin_agents.py
router = APIRouter(prefix="/admin/agents", tags=["admin-agents"],
                   dependencies=[Depends(require_capability(Capability.MANAGE_ACCOUNTS))],
                   responses=error_responses(401, 403))
@router.post("", status_code=201, response_model=AdminUser, responses=error_responses(400, 422))
async def create_agent(body: CreateAgentRequest, request: Request, db: DbSession, actor: CurrentActor) -> AdminUser
```

### 4.6. Ключи: сервис и API ТА (R7-T09, R7-T10)

```python
# backend/app/domain/api_keys/service.py
MAX_ACTIVE_KEYS: Final = 5
DEFAULT_TTL_DAYS: Final = 90
MAX_TTL_DAYS: Final = 365

class ApiKeyState(StrEnum): ACTIVE = "active"; EXPIRED = "expired"; REVOKED = "revoked"

def key_state(*, expires_at: datetime, revoked_at: datetime | None, now: datetime) -> ApiKeyState

@dataclass(frozen=True)
class ApiKeyView:
    id: UUID; name: str; created_at: datetime; created_by: UserRef | None
    expires_at: datetime; last_used_at: datetime | None; revoked_at: datetime | None; state: ApiKeyState

@dataclass(frozen=True)
class IssuedApiKey:
    key: ApiKeyView
    secret: str = field(repr=False)

async def issue_api_key(db, actor, user_id: UUID, /, *, name: str, ttl_days: int) -> IssuedApiKey:
    """403 MANAGE_ACCOUNTS -> 1 <= ttl_days <= 365 и 1 <= len(name) <= 100, без NUL, иначе 422
    validation_error -> lock_for_account_change -> load_account (404) -> не агент: 422 not_an_agent
    -> заблокирован: 422 user_blocked -> действующих >= 5: 422 api_key_limit_reached ->
    generate_api_key, INSERT (expires_at = now + ttl_days суток) -> USER_API_KEY_ISSUED
    (entity_id = агент, details {api_key_id, api_key_name})."""
async def list_api_keys(db, actor, user_id: UUID, params: PageParams) -> tuple[list[ApiKeyView], bool]:
    """403 -> load_account (404) -> ключи агента created_at DESC, id DESC; у не агента — []."""
async def revoke_api_key(db, actor, user_id: UUID, key_id: UUID, /) -> None:
    """403 -> lock -> load_account (404) -> ключ этого пользователя в пространстве (404) ->
    revoked или expired: return (без события) -> UPDATE revoked_at/revoked_by -> USER_API_KEY_REVOKED."""
```

```python
# backend/app/api/v1/schemas/admin.py
class ApiKeyInfo(BaseModel):         # from_attributes; ровно 8 полей, секрета нет
    id: UUID; name: str; created_at: datetime; created_by: UserRef | None
    expires_at: datetime; last_used_at: datetime | None; revoked_at: datetime | None; state: ApiKeyState
class IssueApiKeyRequest(BaseModel):  # extra="forbid"
    name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[^\x00]*$")]
    expires_in_days: Annotated[int, Field(ge=1, le=365)] = 90
class IssuedApiKeyResponse(BaseModel):
    key: ApiKeyInfo
    secret: str                        # description: «Показывается один раз»

# backend/app/api/v1/admin_agents.py (дополнение)
GET  /{user_id}/api-keys                  name="list_api_keys"   -> Page[ApiKeyInfo]   (PageParams)
POST /{user_id}/api-keys                  name="issue_api_key"   -> 201 IssuedApiKeyResponse, Cache-Control: no-store
POST /{user_id}/api-keys/{key_id}/revoke  name="revoke_api_key"  -> 204
```

### 4.7. Аутентификация по ключу (R7-T11, R7-T12)

```python
# backend/app/domain/api_keys/auth.py
RATE_LIMIT_PER_MINUTE: Final = 120
RATE_WINDOW: Final = timedelta(seconds=60)

@dataclass(frozen=True)
class KeyPrincipal: key_id: UUID; user_id: UUID; workspace_id: UUID
@dataclass(frozen=True)
class RateLimited: retry_after: int            # секунды, >= 1

async def authenticate_api_key(db, digest: bytes, *, now: datetime) -> KeyPrincipal | RateLimited | None:
    """Один UPDATE api_key ... RETURNING (PD-5). None — ключа нет, отозван или истёк
    (expires_at <= now). Не фиксирует транзакцию: это делает вызывающий (commit_durably)."""

# backend/app/domain/access/roles.py — Actor
session_id: bytes | None        # None — запрос по ключу
api_key_id: UUID | None = None  # не None — запрос по ключу (FR-30)
is_agent: bool = False          # (R7-T06)
# domain/auth/service.py: SessionActor.session_id -> bytes | None; change_own_password первым
# шагом: actor.session_id is None -> Forbidden() (по ключу недостижимо, защита).

# backend/app/api/deps.py
AGENT_OPERATIONS: Final[frozenset[str]] = frozenset({
    "me", "list_projects", "list_my_tasks", "list_project_tasks", "get_task",
    "create_task", "create_subtask", "update_task", "list_comments", "create_comment"})

def presented_api_key(request: Request) -> str | None:
    """None — заголовка Authorization нет. Иначе значение после «Bearer » (регистр схемы не
    важен); пустая строка — заголовков несколько, схема не Bearer или значение пустое."""

async def require_agent_scope(request: Request) -> None:
    """App-level (после check_origin): ключ есть и scope["route"].name не в AGENT_OPERATIONS
    -> Forbidden(). БД не трогает."""

async def get_actor(request: Request, db: DbSession) -> Actor:
    """Ключ есть -> _actor_from_api_key; иначе путь cookie без изменений (+ is_agent из БД)."""

async def _actor_from_api_key(request: Request, db: AsyncSession, raw: str) -> Actor:
    """не формат -> NotAuthenticated; digest -> authenticate_api_key -> commit_durably ->
    None -> NotAuthenticated; RateLimited -> TooManyRequests(retry_after) ->
    строка AppUser+WorkspaceMember (user_id, workspace_id), нет/заблокирован/не агент ->
    NotAuthenticated -> Actor(session_id=None, api_key_id=..., is_agent=True,
    must_change_password=False, role из БД); request.state.user_id для access-лога.
    Сессии и cookie не трогаются (FR-15)."""
# main.py: dependencies=[Depends(check_origin), Depends(require_agent_scope)]
```

Порядок для запроса по ключу к маршруту из перечня: `check_origin` → `require_agent_scope`
(пропускает) → 400 битого JSON → `require_capability` → `get_active_actor` → `get_actor`
(401 / 429) → 403 `no_role` → 403 `forbidden` раздела → 422 схемы → 404 → 403 → 422 домена.
Маршрут вне перечня: → 403 `forbidden` (ключ не проверяется, З-4).

### 4.8. Операции по ключу: проекты, права, события (R7-T13, R7-T14)

```python
# domain/projects/queries.py — list_projects: фильтр участия, если
#   actor.role is not Role.BUSINESS_ADMIN or actor.api_key_id is not None   (FR-19)
# domain/access/policy.py — первой строкой (FR-17, PD-3):
#   can_delete_task, can_edit_comment, can_delete_comment: if a.api_key_id is not None: return False
# domain/tasks/service.py  (FR-42; PD-9, PD-22, PD-23)
EVENT_FIELDS: Final = ("status", "assignee_id", "due_date", "priority", "title", "description")
EVENT_VALUE_FIELDS: Final = frozenset({"status", "assignee_id", "due_date", "priority"})
def _json_value(value: object) -> JsonValue: ...   # UUID -> str, date -> isoformat, Enum -> .value, None -> None
async def _record_task_updated(db, actor: Actor, task: Task,
                               old: Mapping[str, object], new: Mapping[str, object]) -> None:
    """changed_fields = [f for f in EVENT_FIELDS if f in new]; пусто -> ничего не пишет;
    changes = [{field, old, new} для f из changed_fields ∩ EVENT_VALUE_FIELDS] или None;
    record_event(TASK_UPDATED, entity_id=task.id, project_id=task.project_id,
                 actor_id=actor.user_id, api_key_id=actor.api_key_id)."""
#   create_task / create_subtask: после flush ->
#     record_event(..., actor_id=actor.user_id, api_key_id=actor.api_key_id,
#                  action=TASK_CREATED, entity_id=task.id, project_id=...)
#   update_task: после второго `changed = _changes(task, patch)` (свежая строка под FOR NO KEY
#     UPDATE) и `_authorize` — old = {f: getattr(task, f) for f in changed} ДО move_task/setattr;
#     после flush -> _record_task_updated(old, changed) (одно событие на запрос; пустой
#     changed — return раньше, события нет, D-46/AC-28)
#   move: _load_task -> positions.lock_task_columns(db, task, target) -> old = TaskStatus(task.status)
#     -> positions.move_task(...) -> flush -> если old != target:
#     _record_task_updated(old={"status": old}, new={"status": target})   (внутри колонки — нет)
#   delete_task — без изменений (каскад событий не пишет)
# domain/comments/service.py  (FR-42; PD-24)
#   create_comment: после flush -> COMMENT_CREATED (entity comment.id, project_id=ctx.project.project_id)
#   delete_comment: после flush -> COMMENT_DELETED (entity comment.id, project_id=project.project_id)
#   edit_comment — без события
```

### 4.9. Инструменты MCP (R7-T17, R7-T18)

```python
# backend/app/agent_mcp.py — только стандартная библиотека; импортов app.* нет
PROTOCOL_VERSIONS: Final = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO: Final = {"name": "gostracker", "version": "0.1.0"}
ENV_URL, ENV_KEY, ENV_CA = "GOSTRACKER_URL", "GOSTRACKER_API_KEY", "GOSTRACKER_CA_FILE"

@dataclass(frozen=True)
class ApiResponse: status: int; body: object; retry_after: int | None
class TransportError(Exception):          # code: "connection_error" | "redirect_not_allowed" | "invalid_response"
    def __init__(self, code: str, detail: str) -> None: ...
class Transport(Protocol):
    def request(self, method: str, path: str, *, query: Mapping[str, str] | None = None,
                body: Mapping[str, object] | None = None) -> ApiResponse: ...
class UrllibTransport:
    def __init__(self, base_url: str, api_key: str, *, cafile: str | None = None, timeout: float = 30.0) -> None
        # ValueError (без ключа в тексте), если base_url не по PD-15
@dataclass(frozen=True)
class ToolSpec:
    name: str; description: str; input_schema: Mapping[str, object]
    method: str; path: str                 # шаблон, напр. "/api/v1/tasks/{task_id}"
    path_params: tuple[str, ...] = (); query_params: tuple[str, ...] = (); body_params: tuple[str, ...] = ()
TOOLS: Final[tuple[ToolSpec, ...]]         # 11, порядок таблицы ниже (R7-T18)
class McpServer:
    def __init__(self, transport: Transport | None, *, config_error: str | None = None,
                 tools: Sequence[ToolSpec] = TOOLS) -> None   # transport None — нет ключа
    def handle(self, message: object) -> dict[str, object] | None   # ответ JSON-RPC или None
    def call_tool(self, name: str, arguments: object) -> dict[str, object]  # CallToolResult
def serve(instream: BinaryIO, outstream: BinaryIO, server: McpServer) -> None  # построчно до EOF, flush после ответа
def build_server(environ: Mapping[str, str]) -> McpServer
def main() -> int   # serve(sys.stdin.buffer, sys.stdout.buffer, build_server(os.environ)); логи — stderr
```

Ответы `tools/call` (`CallToolResult`):
- успех: `{"content": [{"type": "text", "text": <JSON тела ответа API>}], "structuredContent": <тело>, "isError": false}`;
- отказ: `{"content": [{"type": "text", "text": <JSON>}], "structuredContent": {"error": {"status": int | null, "code": str, "detail": str | list, "retry_after_seconds": int | null}}, "isError": true}`.
  Источники: ответ API (статус, `code`, `detail`, `Retry-After`); нет ключа — `401`,
  `not_authenticated`, «Требуется вход в систему» (без сети); `config_error`,
  `connection_error`, `redirect_not_allowed`, `invalid_response`, `invalid_arguments` —
  `status: null`. Трассировок нет. Неизвестный инструмент — ошибка JSON-RPC `-32602`;
  неизвестный метод — `-32601`; битый JSON — `-32700` (`id: null`), соединение продолжается;
  исключение внутри — `-32603` без текста исключения.

| Инструмент | FR | Запрос API | Параметры (обязательные **жирным**) |
|---|---|---|---|
| `whoami` | FR-18 | `GET /api/v1/me` | — |
| `list_projects` | FR-19 | `GET /api/v1/projects` | `page`, `page_size` (1…100) |
| `list_my_tasks` | FR-20 | `GET /api/v1/me/tasks` | `page`, `page_size` |
| `list_project_tasks` | FR-21 | `GET /api/v1/projects/{project_id}/tasks` | **`project_id`** (uuid), `status` (enum 4), `assignee_id` (uuid), `page`, `page_size` |
| `get_task` | FR-22 | `GET /api/v1/tasks/{task_id}` | **`task_id`** |
| `create_task` | FR-23 | `POST /api/v1/projects/{project_id}/tasks` | **`project_id`**, **`title`**, **`description`**, **`due_date`** (`format: date`, `YYYY-MM-DD`), `priority` (enum 3, по умолчанию `medium`), `assignee_id` |
| `create_subtask` | FR-24 | `POST /api/v1/tasks/{task_id}/subtasks` | **`task_id`** (родитель), **`title`**, `description`, `due_date`, `priority`, `assignee_id` |
| `set_task_status` | FR-25 | `PATCH /api/v1/tasks/{task_id}` тело `{status}` | **`task_id`**, **`status`** (enum 4) |
| `update_task` | FR-26 | `PATCH /api/v1/tasks/{task_id}` | **`task_id`**, `title`, `description`, `due_date` (строка или `null`), `priority`, `assignee_id` (uuid или `null`); `status` нет |
| `list_comments` | FR-27 | `GET /api/v1/tasks/{task_id}/comments` | **`task_id`**, `page`, `page_size` |
| `add_comment` | FR-27 | `POST /api/v1/tasks/{task_id}/comments` | **`task_id`**, **`body`** (1…10 000) |

Схемы: `{"type": "object", "properties": …, "required": […], "additionalProperties": false}`;
статус — `enum: ["todo","in_progress","review","done"]`, приоритет — `enum: ["low","medium","high"]`,
срок — `{"type": "string", "format": "date", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}` с описанием
«YYYY-MM-DD». Описание `create_task` называет обязательные поля (название, описание, срок) и
правило «срок не раньше сегодняшней даты по Europe/Moscow»; исполнитель по умолчанию — сам
агент, другого может назначить только агент с ролью БА. Описание `set_task_status`: «Закрыть
задачу — перевести в `done`; переходы не ограничены». Описания и тексты — на русском.

Подключение Claude Code (инструкция R7-T24):
`claude mcp add gostracker --env GOSTRACKER_URL=https://<хост>:<порт> --env GOSTRACKER_API_KEY=<ключ>
[--env GOSTRACKER_CA_FILE=<путь к tls.crt>] -- python3 -I <репозиторий>/backend/app/agent_mcp.py`
(область по умолчанию `local`, в репозиторий не попадает; в `.mcp.json` проекта ключ — только
ссылкой `${GOSTRACKER_API_KEY}`).

### 4.10. Интерфейс (R7-T19…R7-T22)

```tsx
// frontend/src/shared/ui/UserPicker.tsx — новый экспорт
/** Логин и, для учётной записи агента, метка «ИИ» (007/FR-31). */
export function UserName({ user }: { user: { login: string; is_agent: boolean } }): JSX.Element;
// <span className="ui-user">{login}{is_agent && <abbr className="ui-agent-mark" title={t("users.agent_mark_title")}>{t("users.agent_mark")}</abbr>}</span>
```
- `TaskPage.tsx`: исполнитель — через `UserName`; новая пара `dt` «Автор» (`tasks.author_label`) /
  `dd[data-field="author"]` **последней** в `dl.ui-props` (порядок прежних строк не меняется).
- `Comments.tsx`: `span[data-field="author"]` → `UserName`.
- `BoardView.tsx` (карточка, `data-field="assignee"`), `TaskList.tsx` (`td[data-field="assignee"]`) — `UserName`.
- `UsersPage.tsx`: `td[data-field="login"]` — `UserName`. Форма создания: флажок
  `input[type=checkbox][name="is_agent"]` «Учётная запись ИИ-агента»; при включённом — поле
  пароля и генерация скрыты, появляется `select[name="role"]` (П по умолчанию, БА, «Без роли»);
  отправка → `createAgent({login, role})`, сообщение «Учётная запись агента создана» без окна
  пароля. У строки агента: нет «Сбросить пароль», в выборе роли нет ТА, есть кнопка
  `data-action="keys"` «Ключи».
- `AgentKeys` (в `UsersPage.tsx`): `section[data-section="agent-keys"]` с заголовком «Ключи
  доступа: <логин>»; таблица (название, кто и когда выпустил, срок, последнее использование или
  «не использовался», состояние «действует» / «истёк» / «отозван <время>»), `Pagination`; у
  действующего — «Отозвать» → `ConfirmDialog` → `revokeApiKey`. Форма выпуска: название
  (`TextField`, 1…100), `select[name="expires_in_days"]` 30 / 90 (по умолчанию) / 180 / 365,
  «Выпустить ключ». После 201 — окно `role="dialog"` с `input[readonly]` секрета, «Копировать»,
  предупреждением и «Закрыть» (PD-17). Время — `Intl.DateTimeFormat` с `timeZone: "Europe/Moscow"`,
  как в `AuditPage`.
- `AuditPage.tsx`: `ACTION_CODES` + три действия; `detailsText`: `user.agent_created` → роль,
  `user.api_key_issued`/`revoked` → «Ключ «{name}»».

```ts
// frontend/src/features/admin/api.ts
export type ApiKeyInfo = components["schemas"]["ApiKeyInfo"];
export type IssuedApiKey = components["schemas"]["IssuedApiKeyResponse"];
export async function createAgent(body: { login: string; role: Role | null }): Promise<AdminUser>;
export async function listApiKeys(userId: string, p: PageParams): Promise<Page<ApiKeyInfo>>;
export async function issueApiKey(userId: string, body: { name: string; expires_in_days: number }): Promise<IssuedApiKey>;
export async function revokeApiKey(userId: string, keyId: string): Promise<void>;
```

Словарь (`ru.ts`): `users.agent_mark` «ИИ», `users.agent_mark_title` «ИИ-агент»,
`tasks.author_label` «Автор» (R7-T19); `admin.users.agent_label` «Учётная запись ИИ-агента»,
`admin.users.role_label` «Роль», `admin.users.agent_created` «Учётная запись агента создана»,
`admin.users.keys` «Ключи», `error.agent_role_not_allowed` «Агенту нельзя назначить роль
технического администратора», `error.agent_password_not_allowed` «У учётной записи агента нет
пароля», `error.not_an_agent` «Ключи выпускаются только учётным записям агентов»,
`error.api_key_limit_reached` «У агента уже 5 действующих ключей», `error.too_many_requests`
(если нет) (R7-T21); `admin.keys.*` (заголовок, столбцы, состояния, «не использовался», форма,
сроки, окно секрета: «Скопируйте ключ сейчас: после закрытия окна он не будет показан. Не
вставляйте ключ в текст запроса к модели, не коммитьте и не пересылайте его», «Копировать»,
«Скопировано», «Закрыть», подтверждение отзыва «Отозвать ключ «{name}»? Агент с этим ключом
сразу потеряет доступ. Действие необратимо.»), `admin.audit.action.user.agent_created`
«Создание учётной записи агента», `…api_key_issued` «Выпуск ключа доступа», `…api_key_revoked`
«Отзыв ключа доступа», `admin.audit.api_key` «Ключ «{name}»» (R7-T22). CSS: `.ui-agent-mark`
(отступ, рамка `var(--…)`, без `font-size`).

## 5. Данные и эксперименты

ML-кода, датасетов, обучения и GPU нет (NFR-5). Утечка между сплитами неприменима.

- **Время.** Бэкенд: фикстура `fixed_clock`; тесты 007 ставят `CLOCK = 2026-11-02T07:00:00Z`
  (spec §5: 10:00 по Москве). Граничные моменты: AC-10 — `CLOCK + 90 суток − 1 с` и `CLOCK + 90
  суток`; AC-40 — 120 запросов в один момент, затем `+60 с`. Доменные тесты с `utcnow()`
  запрашивают `fixed_clock` явно. Фронтенд: `vi.setSystemTime(...)`, `vi.stubEnv("TZ", "UTC")`.
- **Случайность.** Секреты — `secrets` (не детерминированы по замыслу); тест AC-41 проверяет
  формат, длину 32 байта после декодирования и попарное различие 1 000 ключей. Демо-данные не
  меняются (агентов в демо нет).
- **Мир spec §5** — `backend/tests/agents007_support.py` (новый; создаётся в R7-T08, помощники
  добавляются в R7-T10 и R7-T12): `make_agent(env, login, role) -> UserRow` (вставка в БД,
  `is_agent=true`, хеш случайного значения), `make_key(env, user, *, created_by, name="k",
  created_at=CLOCK, ttl=timedelta(days=90), revoked_at=None) -> ApiKeyRow`, `bearer(secret) ->
  dict[str, str]`, `make_world007(env) -> World007` (`ta1`, `ba1`, `u1`, `agent_u`, `agent_ba`,
  проекты `P`, `P2`, задачи `T1`, `T2`, `T3` (срок 2026-10-01, пустое описание, вставка в БД),
  `T9`, комментарий `c1`, ключи `K_u`, `K_ba`, cookie `ta1`/`ba1`/`u1`). Второе пространство для
  AC-16 — фабриками уровня БД (`make_workspace`, `make_project`, `make_task`).
- **MCP в тестах (NFR-4).** Тестовый клиент `backend/tests/mcp_support.py` (новый, R7-T18):
  `BridgeTransport(env, loop, secret)` реализует `Transport.request` через
  `asyncio.run_coroutine_threadsafe(env.client.request(...), loop).result()`; сервер
  `McpServer` вызывается из `asyncio.to_thread`, поэтому цикл теста свободен для запроса. Клиент
  `McpTestClient` шлёт `initialize`, `notifications/initialized`, `tools/list`, `tools/call`.
  Проверка stdio — подпроцесс `sys.executable -I backend/app/agent_mcp.py` (без ключа и с
  недостижимым `http://127.0.0.1:9`). Транспорт `urllib` — против `http.server` на `127.0.0.1` в
  потоке теста. Интернет и языковая модель не используются.
- **БД.** Только тестовая `*_test`; миграционный цикл R7-T02 — маркер `committed`, alembic
  подпроцессом, как `test_priority_upgrade_006.py`.

## 6. Тестовая стратегия и трассировка

### 6.1. AC → реализация → тест

| AC | Где реализуется | Тест (уровень) | Задача |
|---|---|---|---|
| AC-1 | `users.service.create_agent`, `reset_password`, `auth.service.login`; `POST /admin/agents` | `backend/tests/domain/test_agent_accounts_007.py::test_007_ac1_*` (домен); `backend/tests/api/test_agent_accounts_007.py::test_007_ac1_*` (API) | R7-T07, R7-T08 |
| AC-2 | `create_agent`, `set_role` | те же файлы, `test_007_ac2_*` | R7-T07, R7-T08 |
| AC-3 | без изменений (существующие маршруты) + `is_agent` | `test_agent_accounts_007.py::test_007_ac3_*` (API) | R7-T08 |
| AC-4 | `block_user` (PD-7), `authenticate_api_key` | `test_agent_accounts_007.py` (домен: отзыв при блокировке); `backend/tests/api/test_api_key_auth_007.py::test_007_ac4_*` | R7-T07, R7-T12 |
| AC-5 | `get_active_actor` для `Actor` по ключу | `test_api_key_auth_007.py::test_007_ac5_*` (все 10 маршрутов) | R7-T12 |
| AC-6 | `issue_api_key`, `ApiKeyInfo` | `backend/tests/domain/test_api_keys_service_007.py`, `backend/tests/api/test_api_keys_admin_007.py::test_007_ac6_*`; «кто я» по секрету — `test_api_key_auth_007.py::test_007_ac6_*` | R7-T09, R7-T10, R7-T12 |
| AC-7 | гейт `MANAGE_ACCOUNTS`; `require_agent_scope`; правила выпуска | `test_api_keys_admin_007.py::test_007_ac7_*` (`ba1`, `u1`, 422); `test_api_key_auth_007.py::test_007_ac7_*` (`agent.ba` по ключу) | R7-T10, R7-T12 |
| AC-8 | `list_api_keys`, `key_state`, `last_used_at` | `test_api_keys_admin_007.py::test_007_ac8_*` (время использования записано в БД); `test_api_key_auth_007.py::test_007_ac8_*` (по реальному запросу) | R7-T10, R7-T12 |
| AC-9 | `revoke_api_key` | `test_api_keys_admin_007.py::test_007_ac9_*`; 401 после отзыва — `test_api_key_auth_007.py` | R7-T10, R7-T12 |
| AC-10 | `expires_at > now` | `backend/tests/domain/test_api_key_auth_007.py::test_007_ac10_*` (домен); API — `test_api_key_auth_007.py` | R7-T11, R7-T12 |
| AC-11, AC-12 | `IssueApiKeyRequest`, `issue_api_key` | `test_api_keys_admin_007.py::test_007_ac11_*`, `test_007_ac12_*` | R7-T10 |
| AC-13…AC-15 | `get_actor` (ключ), FR-15 | `test_api_key_auth_007.py::test_007_ac13…15_*` | R7-T12 |
| AC-16 | фильтры `workspace_id` (без изменений) | `backend/tests/api/test_agent_reads_007.py::test_007_ac16_*` | R7-T13 |
| AC-17 | `MeResponse.is_agent` | `test_api_key_auth_007.py::test_007_ac17_*` | R7-T12 |
| AC-18 | `list_projects` по ключу | `test_agent_reads_007.py::test_007_ac18_*` | R7-T13 |
| AC-19…AC-21 | существующие запросы; `permissions` | `test_agent_reads_007.py::test_007_ac19…21_*` | R7-T13 |
| AC-22…AC-27, AC-29…AC-32, AC-34 | существующие сервисы задач и комментариев | `backend/tests/api/test_agent_writes_007.py::test_007_acN_*` (только тесты) | R7-T15 |
| AC-28 | `update_task` (D-46: пустой `changed` — без события) | `test_agent_writes_007.py::test_007_ac28_*` (422, статус); «новых событий нет» — `backend/tests/api/test_agent_events_007.py::test_007_ac28_*` | R7-T15, R7-T14 |
| AC-33 | `require_agent_scope`, `policy.py` | `test_api_key_auth_007.py::test_007_ac33_*` (14 действий + люди); обход всех маршрутов — `backend/tests/api/test_agent_scope_007.py` | R7-T12 |
| AC-35 | `record_event(api_key_id)` в сервисах (PD-9) | `test_agent_events_007.py::test_007_ac35_*` | R7-T14 |
| AC-36 | `UserRef`/`DirectoryUser.is_agent` | `backend/tests/api/test_agent_flag_007.py::test_007_ac36_*` (данные агента вставлены в БД) | R7-T05/R7-T06 |
| AC-37 | `UserName`, `UsersPage`, `AgentKeys` | *ручной*: пункт `007/AC-37` в `docs/acceptance/mvp-demo.md`; автотесты компонентов — `frontend/tests/features/tasks/AgentMark.test.tsx`, `frontend/tests/features/boards/AgentMarkBoard.test.tsx`, `frontend/tests/features/admin/UsersPageAgents.test.tsx`, `frontend/tests/features/admin/AgentKeys.test.tsx` (`007_fr31_*`, `007_fr40_*`) | R7-T19…R7-T22, R7-T24 |
| AC-38 | PD-11, PD-15 | API, журнал, события: `backend/tests/api/test_api_key_leaks_007.py::test_007_ac38_*`; инструменты: `backend/tests/api/test_agent_mcp_tools_007.py::test_007_ac38_*`, `backend/tests/cli/test_agent_mcp_stdio_007.py` (stderr) | R7-T16, R7-T17, R7-T18 |
| AC-39 | PD-1 | `test_api_key_leaks_007.py::test_007_ac39_*` (выгрузка всех таблиц) | R7-T16 |
| AC-40 | PD-5 | `backend/tests/domain/test_api_key_auth_007.py` (счётчик, окно); `test_api_key_auth_007.py::test_007_ac40_*` (API) | R7-T11, R7-T12 |
| AC-41 | `generate_api_key` | `backend/tests/unit/test_api_key_secret_007.py::test_007_ac41_*` | R7-T03 |
| AC-42 | `TOOLS` | `test_agent_mcp_tools_007.py::test_007_ac42_*` (ровно 11 имён по §4.9) | R7-T18 |
| AC-43…AC-45 | `McpServer`, `TOOLS`; события AC-43 — сервисы FR-42 (PD-9) | `test_agent_mcp_tools_007.py::test_007_ac43…45_*`; протокол — `backend/tests/unit/test_agent_mcp_protocol_007.py` | R7-T14 (события), R7-T17, R7-T18 |
| AC-46 | — | *ручной*: пункт `007/AC-46` (Claude Code по `docs/agents.md`) | R7-T24, R7-T26 |
| AC-47 | NFR-1 | `backend/tests/api/test_api_compat_007.py` (PD-18); прогон всего набора — R7-T26; `origin_mismatch` — существующие `test_route_guards.py`; явные правки существующих тестов (признак «агент», счётчики событий FR-42, приоритет в составе полей `task.updated`) — перечень §6.2 | R7-T01, R7-T05, R7-T06, R7-T14, R7-T26 |
| AC-48 | — | *вне CI*: `backend/tests/perf/test_api_key_overhead_007.py` при `GT_PERF=1` (в CI — короткий прогон) | R7-T23 |
| AC-49 | `create_task`, `create_subtask`, `update_task`, `create_comment`, `delete_comment` (PD-9) | `test_agent_events_007.py::test_007_ac49_*` (API, cookie `ba1`, `u1`; порядок событий по `domain_event.id`; журнал аудита `ta1`; ключи верхнего уровня карточки и комментария = свойства схем базы `openapi_baseline_f7f19cf.json`, З-12) | R7-T14 |
| AC-50 | откат транзакции при отказе (`get_db`); `delete_task` без событий; демо без изменений | `test_agent_events_007.py::test_007_ac50_*`; демо — существующий `cli/test_demo_data.py::test_d55_no_project_or_task_events` (без правок) | R7-T14 |
| AC-51 | каталог `task.updated` + `priority`, `_record_task_updated` (PD-22) | `test_agent_events_007.py::test_007_ac51_*` (последний пункт — по `K_u`); каталог — `unit/test_event_catalog.py`; запись — `db/test_event_log.py::test_007_ac51_*` | R7-T14 |
| AC-52 | `tasks.service.move` (PD-23) | `test_agent_events_007.py::test_007_ac52_*` (API `POST /tasks/{id}/move`); домен — `domain/test_tasks_move.py::test_d55_move_writes_no_events` (правка §6.2) | R7-T14 |
| AC-53 | `delete_comment` (PD-24); каскады без изменений | `test_agent_events_007.py::test_007_ac53_*` (данные — фабриками уровня БД, «помечены удалёнными» — запрос к `comment`); домен — существующий `domain/test_tasks_update_delete.py::test_d56_delete_task_cascades_to_subtasks_and_comments_with_one_batch` (без правок, `events == []`) | R7-T14 |

Требования без отдельного AC: FR-16 (точность — R7-T11), FR-36 (описания — R7-T18), FR-37
(R7-T17, R7-T18), FR-38 (R7-T17, R7-T18), FR-39 (R7-T24), NFR-3 (R7-T03, R7-T17), NFR-6
(`test_no_telemetry.py` без изменений + AST-тест модуля MCP, R7-T17), NFR-7 (ADR и инструкция —
R7-T24; `docs/data-model.md` — R7-T02, R7-T14; spec 001, включая запись событий FR-42 вместо
plan 001 D-55, — R7-T25), FR-42 (AC-49…AC-53, R7-T14).

### 6.2. Существующие тесты, которые дополняются

Правило (как 006 §6.2): проверки не ослабляются; дополнение — новое поле, новый элемент
перечня, новая голова миграций. Поле «Старые тесты → AC» сверяет ревьюер.

| Файл | Что меняется | Задача |
|---|---|---|
| `backend/tests/db/test_migrations.py` | голова `0008` | R7-T02 |
| `backend/tests/db/test_identity_models.py`, `backend/tests/db/test_r11_models.py` (если перечисляют столбцы) | `app_user.is_agent`, `domain_event.api_key_id` | R7-T02 |
| `backend/tests/unit/test_logging.py` | случай ключа `gtk_…` | R7-T03 |
| `backend/tests/unit/test_event_catalog.py` (`test_fr41_catalog_has_all_r11_actions_and_user_actions_only`) | +3 действия `user.*` | R7-T04 |
| `backend/tests/api/test_errors.py` | каталог кодов +4, `TooManyRequests` | R7-T04 |
| тесты с точным набором полей ответов (`UserRef`, `DirectoryUser`, `AdminUser`, `MeResponse`), например `test_users_directory.py`, `test_admin_users.py`, `test_auth_login.py`/`test_sessions.py` (`/me`), `test_projects.py`, `test_tasks.py`, `test_comments.py` | + `is_agent` | R7-T05, R7-T06 |
| фронтенд: фикстуры, типизированные `UserRef`/`AdminUser`/`MeResponse` | + `is_agent: false` — только где требует `npm run typecheck` | R7-T06 |
| `backend/tests/unit/test_event_catalog.py` (`EXPECTED["task.updated"]`) | `fields` и `value_fields` + `priority` (AC-47 v0.4, PD-22) | R7-T14 |
| `backend/tests/db/test_event_log.py::test_ac65_changed_field_outside_whitelist_is_rejected` | недопустимое поле `priority` → `position` (нет в перечне FR-42): `changed_fields=["status", "position"]`, в тексте ошибки `position` (AC-47 v0.4) | R7-T14 |
| `backend/tests/db/test_event_log.py::test_br2_exception_text_has_no_values_for_invalid_changed_field` | `changed_fields=["priority"]` → `["position"]`, прочее без изменений (иначе запись проходит и тест теряет смысл) | R7-T14 |
| `backend/tests/domain/test_tasks_create.py::test_d55_create_writes_no_events` | `== 0` → ровно два новых события `task.created` (задача, подзадача): `entity_id`, `actor_id = ba`, `api_key_id IS NULL`, `project_id`, `in_audit = false` (FR-42) | R7-T14 |
| `backend/tests/domain/test_tasks_update_delete.py::test_d55_update_and_delete_write_no_events` | после `update_task` — ровно одно `task.updated`, `changed_fields == ["status", "assignee_id", "title"]` (порядок `EVENT_FIELDS`), `changes` по `status` и `assignee_id` (было/стало из строки); после `delete_task` — новых событий нет (проверка остаётся строгой) | R7-T14 |
| `backend/tests/domain/test_tasks_move.py::test_d55_move_writes_no_events` | перенос `todo` → `done` — ровно одно `task.updated`, `changed_fields == ["status"]`, `changes == [{"field": "status", "old": "todo", "new": "done"}]` (FR-42, Q-12) | R7-T14 |
| `backend/tests/domain/test_comments_service.py::test_d55_no_events_and_no_mentions_written` | создание + правка + удаление — ровно два новых события `comment.created`, `comment.deleted` по этому комментарию (правка не пишет); часть про упоминания без изменений | R7-T14 |
| `backend/tests/api/test_ba_tasks_002.py::test_002_ac13_ba_member_deletes_foreign_comment_c1` (строка 63) | `after["events"] == before["events"]` → `== before["events"] + 1` (прямое удаление c1 → `comment.deleted`) | R7-T14 |
| `frontend/tests/features/admin/UsersPage.test.tsx`, `AuditPage.test.tsx` | точные перечни кнопок строки / действий журнала | R7-T21, R7-T22 |

Правило для правок R7-T14 (AC-47): имена тестов не меняются (трассировка в `git diff`); в
докстринге — «D-55 заменено 007/FR-42»; ожидание `== []`/`== before` заменяется **точным**
списком новых событий (тип, объект, автор), а не ослаблением до «не меньше».

**Проверены и не меняются** (успешных операций с задачами/комментариями между замерами нет или
FR-42 требует «нет события»): `backend/tests/projects_api_support.py::event_count` (помощник);
`backend/tests/roles002_support.py::snapshot` и его сравнения в `test_ba_tasks_002.py` (стр. 106,
142, 335, 368, 403) и `test_ba_projects_002.py` — после отказов; `test_role_values_002.py` —
роли; `test_projects.py` — владение; `cli/test_maintenance.py` — сессии; прочие тесты
`db/test_event_log.py` — прямые `record_event`; `test_tasks_update_delete.py::test_d56_delete_task_cascades_…`
(каскад, Q-13); `domain/test_project_members_service.py` (снятие исполнителя, FR-42);
`domain/test_projects_service.py` (проекты); `cli/test_demo_data.py::test_d55_no_project_or_task_events`
(демо); `db/test_priority_upgrade_006.py` (вставки фабрикой); `api/test_audit.py::test_t72_d55_*`
(журнал аудита, `in_audit = false`); `infra/test_docs_static.py::test_t88_data_model_mvp_section`
(текст `docs/data-model.md` R7-T14 обязан сохранить фразу «проекты … событий не пишут» и «D-55»).

## 7. Зависимости

Новых пакетов нет: `backend/tests/arch/test_dependencies_allowlist.py` не меняется,
`frontend/package.json` и `package-lock.json` не меняются. MCP реализован на стандартной
библиотеке (PD-12). В `backend/pyproject.toml` добавляется только `[project.scripts]
gostracker-mcp = "app.agent_mcp:main"` (не зависимость; R7-T18).

## 8. Порядок поставок и критический путь

| Коммит | Задачи | Состояние после коммита |
|---|---|---|
| 1 | R7-T01 | тест совместимости API зелёный на базе |
| 2–4 | R7-T02, R7-T03, R7-T04 | схема 0008, секрет, ошибки и каталог; поведение API прежнее |
| 5 | R7-T05 + R7-T06 | `is_agent` во всех ответах, OpenAPI и типы перегенерированы |
| 6–7 | R7-T07, R7-T08 | ТА создаёт агентов по API |
| 8–9 | R7-T09, R7-T10 | ТА выпускает, видит, отзывает ключи |
| 10–11 | R7-T11, R7-T12 | запросы по ключу работают в пределах 10 операций |
| 12 | R7-T13 | FR-19, права в карточке |
| 13 | R7-T14 | события задач и комментариев FR-42 для всех авторов, с идентификатором ключа |
| 14–15 | R7-T15, R7-T16 | приёмка операций записи и утечек |
| 16–17 | R7-T17, R7-T18 | инструменты MCP |
| 18–21 | R7-T19…R7-T22 | интерфейс |
| 22–24 | R7-T23, R7-T24, R7-T25 | замер, документы, spec 001 |

Критический путь: R7-T02 → R7-T05 → R7-T06 → R7-T07 → R7-T08 → R7-T09 → R7-T10 → R7-T12 →
R7-T14 → R7-T15 → R7-T18 → R7-T24 → R7-T25 → R7-T26 (14 задач). Параллельно: R7-T01, R7-T03,
R7-T04 (после T02), R7-T11 (после T02, T03, T06), R7-T13 и R7-T16 (после T12/T14), R7-T17 (без
зависимостей), R7-T23 (после T12), интерфейс R7-T19…R7-T22 (после T06, T08, T10).

## 9. Риски и план Б

- **RK-1. Закрыт 2026-10-30.** Владелец подтвердил запись событий для всех авторов (spec v0.3,
  FR-42) и ответил на Q-11…Q-13 (v0.4). Остаточный риск — правки существующих тестов D-55
  (§6.2): ревьюер R7-T14 сверяет, что каждая правка — точный список событий FR-42, а не
  ослабление; R7-T26 повторяет сверку по `git diff f7f19cf`.
- **RK-13. Двойной вызов `lock_task_columns` в `move`** (PD-23). Повторный вызов в той же
  транзакции не ждёт (advisory-блокировки реентерабельны, строка уже под `FOR NO KEY UPDATE`),
  но добавляет 2–3 запроса. Тесты гонок `test_tasks_move.py` (`test_t73_*`, `test_t74_*`) и
  `db/test_positions.py` остаются зелёными без правок; если нет — `PLAN_ISSUE`, план Б:
  `positions.move_task` возвращает прежний статус (правка `positions.py` решением архитектора).
- **RK-14. Текст `docs/data-model.md`** (R7-T14) проверяется регулярными выражениями
  `test_t88_data_model_mvp_section`: в разделе «Мягкое удаление и события в MVP» должны
  остаться фраза о том, что проекты (и удаление задач) событий не пишут, и «D-55». Тест не
  меняется.
- **RK-2. Пульсация типов фронтенда** из-за обязательного `is_agent` (R7-T06). Смягчение: коммит
  R7-T05 + R7-T06 одним; правятся только фикстуры, на которые указывает `typecheck`.
- **RK-3. `scope["route"]` у лениво включённых роутеров FastAPI 0.143** (в `test_route_guards.py`
  упомянут `_IncludedRouter`). R7-T12 первым тестом проверяет имя маршрута для всех 10 операций и
  для маршрута вне перечня. **План Б:** при старте приложения собрать `{endpoint: name}` из
  обхода `app.routes` и сравнивать `scope["endpoint"]`.
- **RK-4. Ошибка порядка в `get_actor`** (лимит, `commit_durably`) приводит к потере счётчика при
  429 или фиксации лишнего. Тест AC-40 проверяет: 121-й запрос — 429, задача не создана, через
  60 с — 200.
- **RK-5. Расхождение протокола MCP с версией Claude Code.** Поддержаны три версии; ручной AC-46.
  **План Б:** отчёт исполнителя с журналом обмена, правка согласования версии.
- **RK-6. Самоподписанный сертификат поставки.** Без `GOSTRACKER_CA_FILE` инструменты получат
  `connection_error`; инструкция FR-39 описывает, где взять `tls.crt` (`deploy/tls`).
- **RK-7. Маска `gtk_…` в логах** скроет и пользовательский текст с таким префиксом — допустимо
  (тексты задач в логи не пишутся).
- **RK-8. Запись в `api_key` на каждый запрос** (NFR-2). Замер AC-48; **план Б:** обновлять
  `last_used_at` не чаще раза в минуту (точность FR-16 — 5 минут), счётчик оставить.
- **RK-9. Откат 0008** теряет ключи, признак агента и `domain_event.api_key_id`; ADR-0015 и
  `docs/data-model.md` это фиксируют.
- **RK-10. Размер `UsersPage.tsx`** (~600 строк после R7-T22). **План Б (RK-11).**
- **RK-11. Белый список `frontend/src`.** Если исполнитель R7-T22 не укладывается в один файл —
  `PLAN_ISSUE`; новый `features/admin/AgentKeys.tsx` + правка `test_t21_src_files_only_expected`
  только решением владельца.
- **RK-12. nginx `log_format`** может задеть стековые тесты `test_web_hardening.py`
  (`infra_stack`). R7-T16 проверяет статически; стековые тесты — на финальной приёмке.

## 10. Замечания к spec

Открытых противоречий нет. З-1 решён владельцем (spec v0.3/v0.4). Остальное — уточнения, план
их закрывает решениями.

- **З-1 (РЕШЕНО 2026-10-30, владелец; spec v0.3 FR-42, v0.4 Q-11…Q-13).** Раздел 0 spec
  исправлен, события задач и комментариев пишутся для всех авторов; план — PD-9, PD-22…PD-24,
  R7-T14. Исходный текст замечания (v0.2) сохранён ниже для истории.
  Раздел 0 «Исходное состояние» утверждал: «Каждое изменение задачи и
  комментария записывается в хранилище событий с автором (`task.created`, `task.updated`…,
  `comment.created`, `comment.deleted`)». В коде на `f7f19cf` таких записей нет: `record_event`
  вызывают только `users/service.py`, `projects/service.py` (передача владения) и демо; сервисы
  задач и комментариев событий не пишут (001 plan SC-8: лента отложена; тест
  `test_d55_no_project_or_task_events`). При буквальном FR-30 («так же, как такое же изменение
  человеком») агент тоже не должен писать событий, а AC-35 и AC-43 требуют три события агента и
  событие `task.updated` от `ba1`. План следует AC-35: R7-T14 вводит запись `task.created`,
  `task.updated`, `comment.created` для всех авторов в трёх функциях (`create_task`,
  `create_subtask`, `update_task`, `create_comment`); удаление, восстановление, перенос по доске
  событий по-прежнему не пишут. Нужны подтверждение владельца и правка раздела 0 spec.
  *Устарело в v0.4:* перенос по доске в другую колонку и прямое удаление комментария события
  пишут (PD-23, PD-24), приоритет входит в перечень (PD-22). Действует только PD-9, PD-22…PD-24.
- **З-2.** FR-1 «создаёт так же, как обычную: логин, роль, признак» — обычное создание роль не
  принимает (назначается отдельным действием с отдельной записью журнала) и требует
  одноразовый пароль; AC-1 требует одну запись о создании. План: отдельный маршрут
  `POST /admin/agents` и одно событие `user.agent_created` (PD-4).
- **З-3.** FR-35 «по одному инструменту на каждую операцию FR-18…FR-27» — число операций не
  задано однозначно (FR-27 — две операции, FR-25/FR-26 — один `PATCH`). План фиксирует 11
  инструментов (PD-13), AC-42 проверяет ровно этот список.
- **З-4.** Spec не задаёт порядок FR-13 (401) и FR-17 (403) для маршрута вне перечня с
  недействительным ключом. План: 403 `forbidden` без проверки ключа (PD-3); для 10 операций
  агента — 401 по FR-13.
- **З-5.** FR-16 «последнего успешного запроса» — план считает успешной аутентификацию в
  пределах лимита (ответ обработчика может быть 4xx); точность — точное время.
- **З-6.** FR-22 «состав прав тот же, что в карточке обычного API» и FR-17 (удаление по ключу
  запрещено): поля `permissions` те же, но значения по ключу правдивы — `delete=false`, у
  комментариев `edit=false`, `delete=false` (PD-3).
- **З-7.** FR-31 требует метку у автора в карточке задачи, но интерфейс сейчас автора не
  показывает. План добавляет строку «Автор» (единственное новое поле карточки). Подписи новых
  действий журнала аудита (FR-11) — тоже изменение интерфейса вне FR-31/FR-40; без них журнал
  показывал бы сырые коды.
- **З-8.** NFR-3 «только по HTTPS»: поставка использует самоподписанный сертификат и
  переадресацию 80 → 443. План: инструменты не ходят по `http://` вне loopback, не следуют
  переадресациям, принимают файл сертификата (PD-15).
- **З-9.** FR-9 «срок в прошлом, нулевой» — API принимает срок в сутках (`expires_in_days`,
  1…365): «в прошлом» — отрицательное число. Если владельцу нужна абсолютная дата окончания —
  правка PD-6.
- **З-10.** AC-47 «существующие проверки без изменений, кроме признака агент» — кроме `is_agent`
  дополняются: голова миграций, точный каталог действий, каталог кодов ошибок, описание модели
  данных. Счётчики событий FR-42 и приоритет в составе полей `task.updated` spec v0.4 сама
  вносит в исключения AC-47. Все правки — дополнения (§6.2), не ослабления.
- **З-11.** AC-47 v0.4 разрешает правку проверок «допустимого состава изменённых полей
  `task.updated`». План (PD-22) пишет у приоритета и значения до/после, поэтому в
  `test_event_catalog.py` меняется не только `fields`, но и `value_fields` записи `task.updated`.
  План считает это той же проверкой состава полей; если ревьюер или владелец не согласны —
  план Б PD-22 (только имя поля).
- **З-12.** AC-49 «формат ответов тот же, что на `f7f19cf` (событий и ленты в ответах нет)»: по
  FR-31 во вложенных ссылках на пользователя появляется `is_agent`. План проверяет набор ключей
  верхнего уровня карточки задачи и элемента комментария по схемам базы
  `openapi_baseline_f7f19cf.json` (новых ключей нет); вложенные `UserRef` отличаются только
  `is_agent`.
