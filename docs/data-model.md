# Модель данных GOSTracker, этап R1.0

Документ описывает схему БД, которую создают миграции `0001`–`0003` (PostgreSQL 16). Источник
истины — модели `backend/app/domain/*/models.py` и миграции `backend/migrations/versions/`;
проектное обоснование — `specs/001-pilot-r1/plan.md`, §4.3 (решения D-2…D-8, D-26). Таблицы
следующих этапов (проекты, задачи, CRM) здесь не описаны: они появятся вместе с миграциями R1.1+.

## Общие соглашения

- Первичный ключ — `id uuid` (UUID v4, генерирует приложение); исключения: `domain_event.id`
  (`bigint`, identity), `user_session.id` (`bytea`, 32 байта), составной ключ `workspace_member`.
- Время — `timestamptz`, значения задаёт приложение (`utcnow()`), без `DEFAULT now()` в БД.
  В API и БД только UTC.
- `created_by uuid NULL` — автор записи; `NULL` означает «система» (например, первый
  администратор, созданный при первом запуске).
- Все внешние ключи — `DEFERRABLE INITIALLY IMMEDIATE` (D-26). `ON DELETE RESTRICT` везде, кроме
  `user_session.user_id` (`CASCADE`). Пользователи не удаляются: в интерфейсе и API нет операции
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

Учётная запись (миграция 0001).

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `id` | uuid | нет | первичный ключ `pk_app_user` |
| `login` | varchar(64) | нет | логин; `UNIQUE` (`uq_app_user_login`); `CHECK` `ck_app_user_login_format`: `^[a-z0-9][a-z0-9._-]{2,63}$` — заодно гарантирует нижний регистр, поэтому уникальность регистронезависима |
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

Членство пользователя в пространстве и его роль (миграция 0001).

| Столбец | Тип | NULL | Описание |
|---|---|---|---|
| `workspace_id` | uuid | нет | часть первичного ключа `pk_workspace_member`; FK → `workspace.id`, `RESTRICT` |
| `user_id` | uuid | нет | часть первичного ключа; FK → `app_user.id`, `RESTRICT` |
| `role` | text | да | `tech_admin`, `business_admin`, `mixed`, `user`; `NULL` — роль не назначена; `CHECK` `ck_workspace_member_role_valid` |
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
| `entity_type` | text | нет | тип объекта: `user` (в R1.0 только он) |
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

Запись события выполняется в той же транзакции, что и изменение; откат изменения откатывает и
событие. Первый запуск (создание первого администратора) событий аудита не пишет.

## Миграции

| Ревизия | Содержание |
|---|---|
| `0001` | `workspace`, `app_user`, `workspace_member`, `user_session` |
| `0002` | `domain_event`, индексы, функция и триггеры append-only |
| `0003` | `CHECK` длины `user_session.id` |

Применённые миграции не правятся; любое изменение модели — новая миграция. Проверка соответствия
моделей миграциям — `alembic -c backend/alembic.ini check` (входит в `scripts/check.sh` и CI).
