# Модель данных GOSTracker, этапы R1.0 и MVP

Документ описывает схему БД, которую создают миграции `0001`–`0006` (PostgreSQL 16). Источник
истины — модели `backend/app/domain/*/models.py` и миграции `backend/migrations/versions/`;
проектное обоснование — `specs/001-pilot-r1/plan.md`, §4.3 (решения D-2…D-8, D-26) и §11.6
(MVP: проекты, задачи, комментарии; D-56…D-58). Таблицы отложенных этапов (метки, упоминания,
вложения, CRM) здесь не описаны: они появятся вместе с отдельными миграциями.

## Общие соглашения

- Первичный ключ — `id uuid` (UUID v4, генерирует приложение); исключения: `domain_event.id`
  (`bigint`, identity), `user_session.id` (`bytea`, 32 байта), составной ключ `workspace_member`.
- Время — `timestamptz`, значения задаёт приложение (`utcnow()`), без `DEFAULT now()` в БД.
  В API и БД только UTC.
- `created_by uuid NULL` — автор записи (у `task` — `NOT NULL`); `NULL` означает «система» (например, первый
  администратор, созданный при первом запуске).
- Все внешние ключи — `DEFERRABLE INITIALLY IMMEDIATE` (D-26). `ON DELETE RESTRICT` везде, кроме
  `user_session.user_id`, `project_member.project_id`, `task.project_id`, `task.parent_id` и
  `comment.task_id` (`CASCADE`); внешние ключи `workspace_id` таблиц MVP — без действия
  (`NO ACTION`, как у `WorkspaceMixin`). Пользователи не удаляются: в интерфейсе и API нет операции
  удаления учётной записи, внешние ключи на `app_user` — `RESTRICT`; вместо удаления
  используется блокировка (`app_user.is_blocked`).
- Имена ограничений и индексов задаёт соглашение `NAMING_CONVENTION` (`backend/app/core/models.py`):
  `pk_<таблица>`, `fk_<таблица>_<столбец>_<целевая_таблица>`, `uq_<таблица>_<столбец>`,
  `ck_<таблица>_<имя>`, `ix_<таблица>_<столбцы>`.
- Пользователь — глобальная идентичность (`app_user` без `workspace_id`); принадлежность
  рабочему пространству и роль хранит `workspace_member`. В R1 у пользователя ровно одна строка
  `workspace_member`.

## Идентичность

### workspace

Рабочее пространство (арендатор). В R1 создаётся одно, при первом запуске.

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `id` | uuid | нет | первичный ключ `pk_workspace` |
| `created_at` | timestamptz | нет | момент создания |
| `updated_at` | timestamptz | нет | момент последнего изменения |

### app_user

Учётная запись (миграция 0001; `login_display` — миграция 0005).

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `id` | uuid | нет | первичный ключ `pk_app_user` |
| `login` | varchar(64) | нет | **ключ** логина (нормализованный вид, строчные): вход, уникальность, поиск, сортировка; наружу не отдаётся; `UNIQUE` (`uq_app_user_login`); `CHECK` `ck_app_user_login_format`: `^[a-z0-9][a-z0-9._-]{2,63}$` — заодно гарантирует нижний регистр, поэтому уникальность регистронезависима |
| `login_display` | varchar(64) | нет | логин в написании при создании (FR-73a, D-66): так он показывается во всех ответах API; `CHECK` `ck_app_user_login_display_lower`: `lower(login_display COLLATE "C") = login` (показ совпадает с ключом с точностью до регистра латинских букв); у существующих строк при миграции 0005 равен `login`; если не передан, приложение подставляет `login` |
| `password_hash` | text | нет | хеш Argon2id (пароль в открытом виде не хранится) |
| `must_change_password` | boolean | нет | требуется смена пароля при входе |
| `is_blocked` | boolean | нет | учётная запись заблокирована |
| `blocked_at` | timestamptz | да | момент блокировки |
| `failed_login_count` | integer | нет | подряд неудачных входов (значение по умолчанию 0 задаёт приложение) |
| `login_locked_until` | timestamptz | да | вход временно заблокирован до этого момента |
| `password_changed_at` | timestamptz | нет | момент последней смены пароля |
| `created_at` | timestamptz | нет | момент создания |
| `updated_at` | timestamptz | нет | момент последнего изменения |
| `created_by` | uuid | да | автор; FK `fk_app_user_created_by_app_user` → `app_user.id`, `RESTRICT`; `NULL` — система |

### workspace_member

Членство пользователя в пространстве и его роль (миграция 0001; набор ролей — миграция 0006).

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `workspace_id` | uuid | нет | часть первичного ключа `pk_workspace_member`; FK → `workspace.id`, `RESTRICT` |
| `user_id` | uuid | нет | часть первичного ключа; FK → `app_user.id`, `RESTRICT` |
| `role` | text | да | `tech_admin`, `business_admin`, `user`; `NULL` — роль не назначена; `CHECK` `ck_workspace_member_role_valid` допускает только эти три значения (ADR-0013) |
| `created_at` | timestamptz | нет | момент создания |
| `updated_at` | timestamptz | нет | момент последнего изменения |
| `created_by` | uuid | да | автор; FK → `app_user.id`, `RESTRICT`; `NULL` — система |

Индекс: `ix_workspace_member_workspace_id_role` на `(workspace_id, role)`.

### user_session

Серверные сессии (миграции 0001 и 0003).

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `id` | bytea | нет | первичный ключ `pk_user_session`: HMAC-SHA256 токена сессии (32 байта; `CHECK` `ck_user_session_id_length`: `octet_length(id) = 32`, миграция 0003); сам токен хранится только в cookie |
| `user_id` | uuid | нет | FK → `app_user.id`, `ON DELETE CASCADE` |
| `workspace_id` | uuid | нет | FK → `workspace.id`, `RESTRICT` |
| `created_at` | timestamptz | нет | момент входа |
| `last_activity_at` | timestamptz | нет | последняя активность (простой — 8 часов) |
| `absolute_expires_at` | timestamptz | нет | абсолютный срок жизни (7 суток) |

Индекс: `ix_user_session_user_id` на `(user_id)`. Истёкшие сессии удаляет команда
`gostracker maintenance`.

## Проекты, задачи, комментарии (MVP)

Миграция 0004 (plan §11.6). Общее для четырёх таблиц: `workspace_id uuid NOT NULL` (FK →
`workspace.id`, индекс `ix_<таблица>_workspace_id`), `created_at`/`updated_at` — `timestamptz`
без `DEFAULT`; мягкое удаление (`project`, `task`, `comment`) — `deleted_at timestamptz NULL` и
`deleted_batch_id uuid NULL`, строка остаётся. Серверных `DEFAULT` нет: значения (в том числе
`description = ''`) задаёт приложение. Нет таблиц `label`, `task_label`, `mention`, `attachment`,
расширения `pg_trgm`, GIN-индексов и столбца `project.status` (D-58).

### project

Проект. Отдельного статуса (архива) нет.

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `id` | uuid | нет | первичный ключ `pk_project` |
| `workspace_id` | uuid | нет | FK → `workspace.id` |
| `name` | varchar(255) | нет | название; `CHECK` `ck_project_name_length`: `char_length(name) BETWEEN 1 AND 255` |
| `description` | text | нет | описание, `''` если пусто; `CHECK` `ck_project_description_length`: не больше 10000 символов |
| `owner_id` | uuid | нет | владелец; FK → `app_user.id`, `RESTRICT` |
| `created_by` | uuid | да | автор; FK → `app_user.id`, `RESTRICT`; `NULL` — система |
| `created_at` | timestamptz | нет | момент создания |
| `updated_at` | timestamptz | нет | момент последнего изменения |
| `deleted_at` | timestamptz | да | момент мягкого удаления |
| `deleted_batch_id` | uuid | да | пакет удаления (каскад проект → задачи → комментарии) |

Индекс: `ix_project_workspace_id` на `(workspace_id)`.

### project_member

Участник проекта.

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `project_id` | uuid | нет | часть первичного ключа `pk_project_member`; FK → `project.id`, `CASCADE` |
| `user_id` | uuid | нет | часть первичного ключа; FK → `app_user.id`, `RESTRICT` |
| `workspace_id` | uuid | нет | FK → `workspace.id` |
| `created_at` | timestamptz | нет | момент добавления |
| `updated_at` | timestamptz | нет | момент последнего изменения |
| `created_by` | uuid | да | кто добавил; FK → `app_user.id`, `RESTRICT`; `NULL` — система |

Индексы: `ix_project_member_user_id` на `(user_id)`; `ix_project_member_workspace_id` на
`(workspace_id)`.

### task

Задача и подзадача (подзадача — строка с `parent_id`).

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `id` | uuid | нет | первичный ключ `pk_task` |
| `workspace_id` | uuid | нет | FK → `workspace.id` |
| `project_id` | uuid | нет | FK → `project.id`, `CASCADE` |
| `parent_id` | uuid | да | родительская задача; FK → `task.id`, `CASCADE`; `NULL` — задача верхнего уровня |
| `title` | varchar(255) | нет | название; `CHECK` `ck_task_title_length`: `char_length(title) BETWEEN 1 AND 255` |
| `description` | text | нет | описание, `''` если пусто; `CHECK` `ck_task_description_length`: не больше 10000 символов |
| `status` | text | нет | `todo`, `in_progress`, `review`, `done`; `CHECK` `ck_task_status_valid` |
| `priority` | text | нет | `base`, `high`; `CHECK` `ck_task_priority_valid` |
| `due_date` | date | да | срок |
| `assignee_id` | uuid | да | исполнитель; FK → `app_user.id`, `RESTRICT` |
| `position` | bigint | да | позиция в колонке доски; только у задач верхнего уровня: `CHECK` `ck_task_position_top_level`: `(parent_id IS NULL) = (position IS NOT NULL)` |
| `created_by` | uuid | нет | автор; FK → `app_user.id`, `RESTRICT` |
| `created_at` | timestamptz | нет | момент создания |
| `updated_at` | timestamptz | нет | момент последнего изменения |
| `deleted_at` | timestamptz | да | момент мягкого удаления |
| `deleted_batch_id` | uuid | да | пакет удаления |

#### Индексы

| Индекс | Столбцы | Условие | Назначение |
|---|---|---|---|
| `ix_task_workspace_id` | `(workspace_id)` | — | граница пространства |
| `ix_task_parent_id` | `(parent_id)` | — | подзадачи |
| `ix_task_project_id_status_position_created_at` | `(project_id, status, position, created_at)` | `WHERE deleted_at IS NULL AND parent_id IS NULL` | доска проекта |
| `ix_task_workspace_id_assignee_id_due_date` | `(workspace_id, assignee_id, due_date)` | `WHERE deleted_at IS NULL` | личный список |
| `ix_task_project_id_created_at` | `(project_id, created_at DESC)` | `WHERE deleted_at IS NULL` | список задач проекта |

### comment

Комментарий к задаче (простой текст).

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `id` | uuid | нет | первичный ключ `pk_comment` |
| `workspace_id` | uuid | нет | FK → `workspace.id` |
| `task_id` | uuid | нет | FK → `task.id`, `CASCADE` |
| `body` | text | нет | текст; `CHECK` `ck_comment_body_length`: `char_length(body) BETWEEN 1 AND 10000` |
| `edited_at` | timestamptz | да | момент последнего редактирования |
| `created_by` | uuid | да | автор; FK → `app_user.id`, `RESTRICT`; `NULL` — система |
| `created_at` | timestamptz | нет | момент создания |
| `updated_at` | timestamptz | нет | момент последнего изменения |
| `deleted_at` | timestamptz | да | момент мягкого удаления |
| `deleted_batch_id` | uuid | да | пакет удаления |

Индексы: `ix_comment_workspace_id` на `(workspace_id)`; `ix_comment_task_id_created_at` на
`(task_id, created_at)`.

### Мягкое удаление и события в MVP

Решения plan §11 (D-55, D-56) и ADR-0012 п.3.

**Мягкое удаление без корзины.**

- Удаление проекта, задачи и комментария мягкое: строка остаётся, в `deleted_at` ставится момент
  удаления, в `deleted_batch_id` - идентификатор пакета удаления. Физически строки не удаляются.
- Каскад (D-56): проект → его задачи → подзадачи → комментарии; задача → подзадачи →
  комментарии; подзадача → её комментарии. Все строки одной операции получают одинаковые
  `deleted_at` и `deleted_batch_id`; комментарий, удалённый отдельно, получает собственный пакет.
- Удалённое не видно в списках, на доске и в счётчиках, а обращение к нему по идентификатору
  отвечает 404. Комментарий в списке комментариев задачи показывается заглушкой без текста.
- Корзины, восстановления, окончательного удаления и автоочистки в MVP нет (отложены).
  `deleted_batch_id` хранится, чтобы корзина следующей версии (ADR-0010) могла восстановить
  данные, удалённые в MVP. Команда `gostracker maintenance` в MVP удаляет только истёкшие сессии.
- Пользователи не удаляются совсем (см. «Общие соглашения»).

**События (D-55).** В `domain_event` в MVP пишутся только события аудита:

- `user.*` из каталога R1.0 (создание, блокировка, сброс пароля, роли и т. д.);
- `project.ownership_transferred` - передача владения проектом.

События ленты (`project.updated`, `member.*`, `task.*`, `comment.*`) в MVP не пишутся: лента
проекта отложена. Создание, изменение и удаление проектов, участников, задач и комментариев
событий не пишут, поэтому лента следующей версии для данных MVP начнётся пустой. Демо-данные
(`gostracker demo-data`) пишут только `user.created` и `user.role_assigned` с `actor_id = NULL`
(автор - «система»); проекты и задачи демо-данных событий не порождают.

**Миграция 0004.** `CHECK` `ck_domain_event_entity_type_valid` допускает семь значений
`entity_type`. Если в `domain_event` уже есть строка с другим значением, `upgrade 0004` не
применится, а удалить строку нельзя: журнал append-only. В установке, созданной этим репозиторием,
пишется только `entity_type = user`, поэтому на практике это недостижимо.

## Журнал событий

### domain_event

Единый журнал доменных событий (миграция 0002). Из него строятся журнал аудита (`in_audit`),
а в следующих этапах — лента проекта и история сделки.

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `id` | bigint | нет | первичный ключ `pk_domain_event`, `GENERATED ... AS IDENTITY`; порядок вставки |
| `workspace_id` | uuid | нет | FK → `workspace.id`, `RESTRICT` |
| `occurred_at` | timestamptz | нет | момент события (`created_at`/`updated_at` в таблице нет — строка не меняется) |
| `actor_id` | uuid | да | автор действия; FK → `app_user.id`, `RESTRICT`; `NULL` — система |
| `entity_type` | text | нет | тип объекта: `user`, `project`, `task`, `comment`, `attachment`, `stage`, `deal`; `CHECK` `ck_domain_event_entity_type_valid` (миграция 0004); в R1.0 пишется только `user` |
| `entity_id` | uuid | нет | идентификатор объекта; внешнего ключа нет — запись переживает удаление объекта |
| `action` | text | нет | действие, например `user.created` |
| `changed_fields` | text[] | нет | имена изменённых полей, по умолчанию `'{}'` |
| `project_id` | uuid | да | проект для ленты проекта (R1.1+); внешнего ключа нет |
| `deal_id` | uuid | да | сделка для истории сделки (R1.3); внешнего ключа нет |
| `in_audit` | boolean | нет | событие попадает в журнал аудита |
| `changes` | jsonb | да | список `{field, old, new}` (с R1.1); в API аудита не отдаётся |
| `details` | jsonb | да | только для `entity_type = user`: `role_from`, `role_to`; паролей и секретов нет |

#### Индексы

Все индексы описаны в миграции 0002.

| Индекс | Столбцы | Условие | Назначение |
|---|---|---|---|
| `ix_domain_event_workspace_id_project_id_id` | `(workspace_id, project_id, id DESC)` | `WHERE project_id IS NOT NULL` | лента проекта |
| `ix_domain_event_workspace_id_deal_id_id` | `(workspace_id, deal_id, id DESC)` | `WHERE deal_id IS NOT NULL` | история и лента сделки |
| `ix_domain_event_workspace_id_id_audit` | `(workspace_id, id DESC)` | `WHERE in_audit` | журнал аудита |
| `ix_domain_event_entity_type_entity_id` | `(entity_type, entity_id)` | — | события объекта |

Частичного индекса по `actor_id` нет: фильтр журнала по автору при большом объёме потребует
отдельного индекса (решение по замеру NFR-2, R1.4).

#### Append-only и триггеры

Таблица append-only: строки только добавляются. Неизменяемость обеспечивают триггеры БД
(миграция 0002), а не код приложения:

- `trg_domain_event_forbid_update_delete` — `BEFORE UPDATE OR DELETE ... FOR EACH ROW`;
- `trg_domain_event_forbid_truncate` — `BEFORE TRUNCATE ... FOR EACH STATEMENT`.

Оба вызывают функцию `gt_forbid_event_mutation()`, которая завершает операцию исключением
(`restrict_violation`). Любые `UPDATE`, `DELETE` и `TRUNCATE` над `domain_event` в обычной работе
приложения отклоняются.

Ограничение: приложение подключается к БД ролью `tracker`, которая является суперпользователем и
владельцем таблицы (plan D-8), поэтому триггеры не защищают от неё: она может отключить их
(`ALTER TABLE ... DISABLE TRIGGER`). Отдельная роль БД без `SUPERUSER` с `REVOKE UPDATE, DELETE,
TRUNCATE` — в бэклоге (plan D-8).

Откат миграции 0002 (`downgrade 0002`, то есть `alembic downgrade 0001`) удаляет триггеры,
функцию и таблицу `domain_event` вместе со всеми записями без подтверждения.

## Каталог событий R1.0

Каталог — `backend/app/domain/events/catalog.py`. В R1.0 пишутся только действия `user.*`;
все они попадают в журнал аудита (`in_audit = true`), в ленту проекта и историю сделки — нет.

| Действие | Что хранится |
|---|---|
| `user.created` | только метаданные |
| `user.blocked` | только метаданные |
| `user.unblocked` | только метаданные |
| `user.password_reset` | только метаданные (пароль не сохраняется) |
| `user.sessions_revoked` | только метаданные |
| `user.role_assigned` | `details.role_from`, `details.role_to` |
| `user.role_changed` | `details.role_from`, `details.role_to` |
| `user.role_removed` | `details.role_from`, `details.role_to` |

**Записи от «системы» при обновлении 0006.** Миграция 0006 добавляет в `domain_event` по одной
записи на каждого бывшего пользователя с ролью «Смешанная» (СМ; роль `mixed` в журнале
хранится в `details.role_from`): `entity_type = user`, `action = user.role_removed` (роль
снята) или `user.role_changed` (роль заменена на `tech_admin`), `details.role_to` — `NULL`
или `tech_admin`, `actor_id = NULL` (автор — «система»), `in_audit = true`. Это первое
обновление схемы, пишущее в журнал аудита.
На чистой установке журнал пуст (001/AC-114). Если пользователей с ролью `mixed` нет, миграция
0006 записей не добавляет. Записи с `role_from = mixed` остаются в журнале навсегда
(append-only); в интерфейсе журнала `mixed` показывается как «Смешанная роль».

Запись события выполняется в той же транзакции, что и изменение; откат изменения откатывает и
событие. Первый запуск (создание первого администратора) событий аудита не пишет.

## Миграции

| Ревизия | Содержание |
|---|---|
| `0001` | `workspace`, `app_user`, `workspace_member`, `user_session` |
| `0002` | `domain_event`, индексы, функция и триггеры append-only |
| `0003` | `CHECK` длины `user_session.id` |
| `0004` | `project`, `project_member`, `task`, `comment`, их индексы; `CHECK` `ck_domain_event_entity_type_valid` на `domain_event.entity_type` (откат удаляет таблицы и `CHECK`) |
| `0005` | `app_user.login_display` (заполняется `login`) и `CHECK` `ck_app_user_login_display_lower` (откат удаляет столбец и `CHECK`; написание теряется) |
| `0006` | три роли (ADR-0013): у всех пользователей с ролью `mixed` роль снимается (`NULL`), а если в пространстве нет активного ТА, активные бывшие СМ получают `tech_admin` (FR-16); на каждого бывшего СМ одна запись `domain_event` от «системы» (`actor_id = NULL`); `CHECK` `ck_workspace_member_role_valid` пересоздаётся с тремя значениями; всё в одной транзакции (откат `downgrade 0005` возвращает прежний `CHECK`, но роли `mixed` не возвращает и журнал не меняет) |

Применённые миграции не правятся; любое изменение модели — новая миграция. Проверка соответствия
моделей миграциям — `alembic -c backend/alembic.ini check` (входит в `scripts/check.sh` и CI).

### Порядок обновления

Код этапа «три роли» требует схему `0006` и не работает на схеме ≤ `0005`, если в ней есть
пользователь с ролью `mixed` (её снимает миграция 0006): такой пользователь даёт ответ 500.
Порядок обеспечивает `backend/docker-entrypoint.sh`:
`gostracker bootstrap` (блокировка, `alembic upgrade head`, первый запуск) выполняется до
`exec uvicorn`, при ошибке миграции API не стартует. При ручном запуске сначала
`gostracker bootstrap`, потом API; после восстановления БД из резервной копии версии 001 при
работе на коде этапа «три роли» перезапустить сервис `api` (`dc restart api`; миграция 0006
снова снимет роль «Смешанная»); чтобы остаться на 001, запускать на ней образ 001 (в нём нет
миграции 0006). `dc restart api` образ не пересобирает: если на стеке перед этим поднимали образ
001, нужен `dc up -d --build --wait` из клона на коде этапа «три роли», а не `restart`. Если порт
80 занят другим стеком, обновлять только API (`dc up -d --build --wait api`), а веб-часть
пересобрать, когда порт свободен (ADR-0013, «Порядок обновления», «Правила»). Команды Compose —
через функцию `dc` с `-p <имя>` стека, если из клона запущено несколько стеков (ADR-0013,
«Команды чек-листа»).
Подробности и чек-лист владельца — `docs/adr/0013-three-roles.md`, раздел «Порядок обновления».
