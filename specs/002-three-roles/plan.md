# Plan: Три роли — упразднение роли «Смешанная»

- **Spec:** ./spec.md v0.2 (утверждена владельцем продукта 2026-10-16 по сообщению оркестратора;
  в шапке spec статус ещё DRAFT, см. §9, П-1)
- **Статус:** DRAFT
- **Основа:** `specs/001-pilot-r1/plan.md` §4.5, §4.6, §11.5, §11.8 (D-63), §11.12 (миграция 0005
  как образец). Файлы 001 (`spec.md`, `plan.md`, `tasks.md`) этот план **не правит** (spec 002 §7).
  Что из 001 заменяется, перечислено в §10.
- **Нумерация:** решения этого плана — `D-1…` (снаружи — `002/D-1`), задачи — `R3-T01…`, тесты
  на критерии 002 называются `test_002_acN_*`. Так их не спутать с `test_acN_*` из 001.

## 1. Подход

Работа идёт в четыре этапа, и после каждой задачи `bash scripts/check.sh` остаётся зелёным.

1. **Права БА без удаления СМ** (R3-T01…R3-T03). В матрице `roles.py` и в чистых функциях
   `policy.py` БА получает прежние права СМ на проекты (любой проект) и права на задачи и
   комментарии по участию. Ветки `Role.MIXED` пока остаются и ведут себя как прежде, поэтому
   тесты СМ не падают. Код меняется в 2 файлах, тесты 001 с «БА-не владелец → 403» переводятся
   на критерии 002.
2. **Тесты без СМ** (R3-T04…R3-T07, только тесты). Тесты, где СМ — актор (администратор
   учётных записей или менеджер проекта), переписываются на ТА или БА по таблице §6.2.
   Добавляются тесты 002/AC-3…AC-10 (несколько ТА, FR-7, гонки). Код ТА менять почти не нужно:
   инвариант FR-69 в `users/service.py` уже глобальный, с advisory-блокировкой и проверкой
   устаревшего инициатора (§4.4).
3. **Удаление `mixed`** (R3-T08…R3-T13). Сначала демо перестаёт создавать `demo.mixed`
   (R3-T08): иначе тест 001/AC-131 входит пользователем `mixed` и падает на `Role('mixed')`.
   Затем фронтенд перестаёт ссылаться на `mixed` как на роль (R3-T09, R3-T10). После этого
   значение удаляется из `Role`, контракт пересобирается (R3-T11) и чистятся тексты (R3-T12).
   Последней идёт миграция `0006` (R3-T13): снятие роли, запись в журнал от «системы», FR-16 и
   новый CHECK — одной транзакцией alembic.
4. **Проверка обновления и документы** (R3-T14…R3-T17): поведение API после обновления,
   обновление с демо-данными (*инфра*), ADR-0013, README и чек-лист (AC-27 *ручной*).

Почему этапы идут в таком порядке: значение `mixed` нельзя убрать из БД, пока тестовые фабрики и
«миры» создают пользователей СМ. Поэтому сначала права БА (тесты СМ переносятся на БА без потерь),
потом чистка тестов, и только потом удаление значения и CHECK.

## 2. Решения

| ID | Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---|---|---|---|
| D-1 | Где задаётся «БА управляет любым проектом» | Возможность `Capability.PROJECT_MANAGE_ANY` добавляется в `_BUSINESS_ADMIN_CAPS`; `can_manage_project(a, p) = a.can(PROJECT_MANAGE_ANY)` | (а) проверка `a.role == BUSINESS_ADMIN` в policy, при этом возможность ни у кого (мёртвое значение); (б) удалить `PROJECT_MANAGE_ANY` | Сохраняется образец 001: матрица `ROLE_CAPABILITIES` описывает права роли, policy — объектные проверки. Вариант (б) меняет перечень `Capability` в OpenAPI сверх FR-1 и нарушает NFR-1. Следствие: в `GET /me` у БА в `capabilities` появляется `project_manage_any`. Поле и перечень значений не меняются, это данные (риск R-3) |
| D-2 | «Свой проект» БА | `is_own_project(a, p)`: БА — участник (`p.actor_is_member`), иначе `False`; `can_edit_task_fully`: БА — участник | Отдельные функции `ba_can_*`; оставить владельца как особый случай | 002 §5.3 п.3 и FR-9: права БА определяются участием, владение роли не играет. Формулы `can_change_assignee`, `can_delete_task`, `can_create_subtask` не меняются, они наследуют новый смысл |
| D-3 | Самодобавление БА | `can_add_member = can_manage_members` (запрет OI-13 снят) | — | FR-8 |
| D-4 | FR-7 (несколько ТА) | `ACCOUNT_ADMIN_ROLES = {TECH_ADMIN}`; код `users/service.py` (протокол блокировок, `ensure_account_admin_remains`, 403 для устаревшего инициатора) **не меняется** | Отдельный счётчик ТА; блокировка `SERIALIZABLE`; новые коды ошибок | Разбор §4.4: каждая ветка FR-7 и AC-10 (а)–(г) уже даёт требуемый результат. Проигравший при ожидании advisory-блокировки сверх серверного `lock_timeout` получает 503 `service_busy`, это допускает FR-7 |
| D-5 | Где снимается роль СМ | Миграция alembic `0006_three_roles.py` на чистом SQL: смена ролей, запись `domain_event` с `actor_id = NULL`, замена CHECK | (а) шаг в `run_bootstrap` после миграций через `record_event`; (б) отдельная команда оператора; (в) ленивое снятие при входе | FR-17 требует, чтобы версия схемы, роли и журнал откатывались вместе. В alembic всё обновление идёт **одной транзакцией** (`env.py`: `context.begin_transaction()` без `transaction_per_migration`, транзакционный DDL PostgreSQL), отметка `alembic_version` пишется в ней же. При (а) миграция и запись данных были бы разными транзакциями (CHECK нельзя ввести до снятия ролей), при (б) нарушается NFR-2. Миграции до сих пор аудит не писали. Это первое исключение, оно фиксируется в ADR-0013 (spec FR-15) |
| D-6 | Константы в миграции | Литералы (`'mixed'`, `'user.role_removed'`, `'user.role_changed'`, `'user'`), без импорта `Role`/`EventAction` | Импортировать перечисления приложения | Миграция должна выполняться одинаково и при будущих изменениях перечислений. Совпадение литералов с `EventAction` и каталогом (`in_audit = true`) проверяет тест R3-T13 |
| D-7 | Время записи миграции | `occurred_at = now()` (время транзакции БД, `timestamptz`, у всех записей одной миграции одно значение) | `utcnow()` из Python | Миграция идёт в подпроцессе alembic, подменить часы там нельзя без тестового крючка в коде. Тесты проверяют попадание в окно `[t_до, t_после]` и равенство времени у всех записей (§5, П-4) |
| D-8 | Внедрение сбоя (AC-29) | Тест ставит в БД **временный триггер**: `BEFORE UPDATE ON alembic_version` с `RAISE EXCEPTION` (сбой после ролей, журнала и CHECK, до отметки версии). Второй вариант — `AFTER INSERT ON domain_event` по `entity_id` второго бывшего СМ (сбой посреди записи журнала) | Переменная окружения или флаг `-x` в коде миграции | В коде поставки нет тестовых крючков. Триггер воспроизводит сбой «в любой момент» средствами БД; «сбой устранён» означает `DROP TRIGGER` |
| D-9 | Блокировки миграции | Первыми идут `LOCK TABLE workspace_member IN ACCESS EXCLUSIVE MODE` и `LOCK TABLE app_user IN SHARE MODE` | Без явных блокировок | Штатно миграцию выполняет `gostracker bootstrap` в `docker-entrypoint.sh` **до** запуска uvicorn, конкурентов нет. Блокировки — страховка от ручного запуска при работающем API: сразу берётся самый сильный режим, без повышения блокировки посреди транзакции. `env.py` ставит `lock_timeout = 0`. Если сработает deadlock-детектор, откатится вся миграция (FR-17), повторный `bootstrap` даст тот же результат |
| D-10 | Откат (`downgrade`) | Вернуть CHECK с четырьмя значениями; роли бывших СМ и журнал не трогать | Восстанавливать `mixed` по журналу | spec §7: роли после отката возвращает ТА вручную; журнал только дописывается (append-only триггер 0002) |
| D-11 | Порядок записей журнала миграции | `ORDER BY workspace_id, login, user_id` | Без порядка | Детерминированные `id` упрощают тесты и чтение журнала |
| D-12 | «Предыдущая версия» в тестах обновления | `committed`-тест: схема head → `alembic downgrade 0005` → данные в схеме 0005 (фабрики с ролью `NULL` + `UPDATE workspace_member SET role = 'mixed'` чистым SQL; сессии — через `SessionStore`/фабрику, не через вход) → `alembic upgrade head` → `db_engine.dispose()` | Хранить дамп БД предыдущей версии; поднимать образ прежней версии | Так же устроен тест 001/AC-131 (`db/test_login_display_upgrade.py`). Вход пользователем `mixed` в схеме 0005 через новый код невозможен (`Role('mixed')` → ошибка), поэтому сессию S создаёт фабрика |
| D-13 | Предыдущее демо (AC-30) | Тест подменяет (`monkeypatch`) в `ops/demo.py` строку `("demo.ba4", "business_admin")` на `("demo.mixed", "mixed")` и константу `_ALL_PROJECTS_BA` на `"demo.mixed"`, в схеме 0005 запускает `load_demo_data(seed=1)`, затем обновляет систему командой оператора `gostracker bootstrap` | Сборка образа прежней версии из git (`git worktree`) в инфра-стеке | Состав 001/FR-49 (1 ТА, 1 СМ, 3 БА, 7 П) воспроизводится точно, без Docker. Чтобы подмена работала, `demo.ba4` в R3-T08 стоит **на месте** `demo.mixed` (второй элемент `_USERS`), а логин «участника обоих проектов» вынесен в константу |
| D-14 | Название `mixed` в интерфейсе | `ru.ts` сохраняет ключ `admin.role.mixed` = «Смешанная роль»; `AuditPage.ROLE_VALUES` (тип `string[]`) сохраняет `"mixed"` для исторических записей; из `UsersPage.ROLES`, `ProjectPage.OWNER_ROLES` и проверки `canPickAssignee` значение удаляется | Отдельный словарь для журнала | FR-20, FR-21 |
| D-15 | Тексты API со «СМ» | Docstring обработчиков и схем правятся в отдельной задаче R3-T12 с пересборкой контракта | Править в R3-T01…T03 | Docstring уходят в `description` OpenAPI: каждая правка требует `scripts/gen-api.sh`. Одна задача — одна пересборка |
| D-16 | Охрана от возврата `mixed` | Тест `unit/test_no_mixed_role.py`: в `backend/app/**/*.py` нет `mixed`/`MIXED`/`\bСМ\b`/«смешан»; во `frontend/src/**` слово `mixed` есть только в `features/admin/AuditPage.tsx` и `shared/i18n/ru.ts` (история журнала, D-14); в `docs/api/openapi.json` и `frontend/src/shared/api/schema.d.ts` его нет | Ручная проверка grep-ом | FR-1, FR-21: дешёвая регрессия |

## 3. Затрагиваемые модули и файлы

Backend:
- `backend/app/domain/access/roles.py` — изменяется: БА + `PROJECT_MANAGE_ANY` (R3-T01); удаление
  `Role.MIXED`, `ACCOUNT_ADMIN_ROLES = {TECH_ADMIN}` (R3-T11).
- `backend/app/domain/access/policy.py` — изменяется: формулы §4.2 (R3-T01…T03), удаление веток
  `MIXED` (R3-T11).
- `backend/app/domain/projects/queries.py` — фильтр списка проектов без `MIXED` (R3-T11).
- `backend/app/domain/access/recipients.py`, `backend/app/domain/users/directory.py` — только
  комментарии (R3-T11).
- `backend/app/domain/workspaces/models.py` — CHECK `role_valid` из трёх значений (R3-T13).
- `backend/migrations/versions/0006_three_roles.py` — новый (R3-T13).
- `backend/app/domain/ops/demo.py` — `demo.ba4` вместо `demo.mixed` (R3-T08).
- Docstring без «СМ» (R3-T12): `backend/app/api/v1/users.py`, `backend/app/api/v1/projects.py`,
  `backend/app/api/v1/comments.py`, `backend/app/api/v1/schemas/common.py`,
  `backend/app/api/v1/schemas/tasks.py`, `backend/app/domain/tasks/service.py`.
- **Не меняются:** `domain/users/service.py` (§4.4), `api/v1/admin_users.py`, `api/deps.py`,
  `domain/events/*` (журнал отдаёт `details` как есть, FR-20 уже выполняется),
  `projects/service.py`, `projects/members.py`, `tasks/*`, `comments/*`: они вызывают policy.
- Генерируемые: `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`
  (`bash scripts/gen-api.sh`; R3-T11, R3-T12).

Frontend:
- `frontend/src/features/admin/UsersPage.tsx` — выбор роли без `mixed` (R3-T09).
- `frontend/src/features/projects/ProjectPage.tsx` — кандидаты во владельцы только БА (R3-T10).
- `frontend/src/features/tasks/TaskList.tsx`, `frontend/src/features/tasks/CreateTaskForm.tsx` —
  выбор исполнителя только у БА (R3-T10).
- `frontend/src/features/admin/AuditPage.tsx`, `frontend/src/shared/i18n/ru.ts` — **без
  изменений** (D-14).

Документы (R3-T16, R3-T17): `docs/adr/0013-three-roles.md` (новый), `docs/adr/0003-mixed-role.md`
(только статус), `docs/adr/0004-auth-pilot.md`, `docs/adr/0006-audit-r1.md`,
`docs/adr/0012-mvp-task-tracker-first.md` (строка «Уточнено ADR-0013»), `docs/data-model.md`,
`README.md`, `docs/acceptance/mvp-demo.md`. Чужие незакоммиченные файлы — §11.

## 4. Интерфейсы

### 4.1. `domain/access/roles.py` (итог после R3-T11)

```python
class Role(StrEnum):
    """Роль в пространстве; значения совпадают с CHECK role_valid (002/FR-1, FR-2)."""
    TECH_ADMIN = "tech_admin"
    BUSINESS_ADMIN = "business_admin"
    USER = "user"

class Capability(StrEnum):          # перечень без изменений (NFR-1)
    ...
    PROJECT_MANAGE_ANY = auto()     # БА: правка, участники (в т.ч. себя), владение, удаление, архив — любой проект (002/FR-8)

_TECH_ADMIN_CAPS = frozenset({MANAGE_ACCOUNTS, ASSIGN_ROLES, VIEW_AUDIT})                     # без изменений
_BUSINESS_ADMIN_CAPS = frozenset({BUSINESS_ACCESS, PROJECT_CREATE, PROJECT_MANAGE_ANY,         # + PROJECT_MANAGE_ANY (R3-T01)
                                  TASK_ASSIGN_OTHERS, LABELS_MANAGE, CRM_READ, CRM_WRITE, PIPELINE_MANAGE})
ROLE_CAPABILITIES: Mapping[Role, frozenset[Capability]] = MappingProxyType({
    Role.TECH_ADMIN: _TECH_ADMIN_CAPS,
    Role.BUSINESS_ADMIN: _BUSINESS_ADMIN_CAPS,
    Role.USER: frozenset({Capability.BUSINESS_ACCESS}),
})
ACCOUNT_ADMIN_ROLES: Final = frozenset({Role.TECH_ADMIN})    # 002/FR-7: обладатель права — только ТА
```
До R3-T11 (переходный период) `Role.MIXED` и его строка в матрице остаются как есть: объединение
`_TECH_ADMIN_CAPS | _BUSINESS_ADMIN_CAPS | {PROJECT_MANAGE_ANY}`.

Следствия, которые проверяются, но не требуют кода: `users/directory._DIRECTORY_ROLES` (роли с
`BUSINESS_ACCESS`) становится `["business_admin", "user"]`; в `recipients` цель `PROJECT_OWNER`
(`PROJECT_CREATE`) — только БА (002/FR-11).

### 4.2. `domain/access/policy.py`

Сигнатуры и `ProjectFacts`/`TaskFacts` не меняются (001 plan §11.5). Меняются только формулы:

| Функция | Было (001) | Итог 002 | Задача |
|---|---|---|---|
| `is_own_project(a, p)` | БА: владелец; СМ: участник | БА: `p.actor_is_member`; иначе `False` | R3-T03 |
| `can_view_project(a, p)` | БА, СМ: `True`; П: участник | БА: `True`; П: участник | R3-T11 (только убрать СМ) |
| `can_read_project_content` | `BUSINESS_ACCESS and member` | без изменений | — |
| `can_edit_task_fully(a, p, t)` | П: свой; БА: `is_own_project` или своя; СМ: участник | П: участник и `created_by == assignee_id == actor`; БА: `p.actor_is_member`; иначе `False` | R3-T03 |
| `can_change_task_status` | полная правка или участник-исполнитель | без изменений | — |
| `can_create_task` | участник и (себе или `TASK_ASSIGN_OTHERS`) | без изменений | — |
| `can_create_subtask` | `can_create_task and (fully(parent) or parent.assignee == actor)` | без изменений (БА-участник: `fully(parent)` истинно для любой задачи, FR-9) | — |
| `can_change_assignee(a, p, t)` | `TASK_ASSIGN_OTHERS and is_own_project` | без изменений (новый смысл `is_own_project`) | R3-T03 |
| `can_delete_task` | `== can_edit_task_fully` | без изменений | — |
| `can_edit_comment` | автор | без изменений (FR-9: правка — только автор) | — |
| `can_delete_comment(a, p, author_id)` | участник и (автор или (БА и владелец) или СМ) | `BUSINESS_ACCESS and member and (author == actor or a.role == BUSINESS_ADMIN)` | R3-T02 |
| `can_manage_project(a, p)` | (БА и владелец) или `PROJECT_MANAGE_ANY` | `a.can(PROJECT_MANAGE_ANY)` | R3-T01 |
| `can_manage_members` | `== can_manage_project` | без изменений | — |
| `can_add_member(a, p, user_id)` | `can_manage_members and not (БА and user_id == actor)` | `can_manage_members(a, p)` (параметр `user_id` остаётся в сигнатуре) | R3-T01 |
| `can_remove_self` | участник, не владелец | без изменений | — |

Переходные формы до R3-T11: в R3-T02 `... or a.role in (BUSINESS_ADMIN, MIXED)`. В R3-T03
`is_own_project` и `can_edit_task_fully` для БА и СМ одинаковы (участник). В R3-T11 ветки `MIXED`
удаляются, формулы приводятся к столбцу «Итог 002». Docstring модуля переписывается: правило
OI-127 (а) и D-54 больше не действуют (002 §5.3).

Сервисы (`projects/service.py`, `projects/members.py`, `tasks/service.py`, `tasks/queries.py`,
`comments/service.py`, `boards/service.py`) вызывают эти функции и не меняются. Косвенные
изменения FR-8 (каскад мягкого удаления D-56, сброс исполнителя при исключении, Q-7) уже
реализованы в `delete_project` и `remove_member` и не зависят от участия инициатора.

`domain/projects/queries.py::list_projects` (R3-T11): `if actor.role is not Role.BUSINESS_ADMIN:
stmt = stmt.where(_is_member_of(actor.user_id))`.

### 4.3. Матрица 002 §5.2 → код

| Строка матрицы 002 §5.2 | Где |
|---|---|
| Системные настройки, учётные записи, роли, журнал | `_TECH_ADMIN_CAPS` + гейты роутеров `admin_users.py`, `audit.py` (без изменений) |
| Создание проекта | `PROJECT_CREATE` (БА) |
| Список всех проектов, карточка | `list_projects`, `can_view_project` |
| Правка, участники (включая себя), владение, удаление, архив (отложено) | `PROJECT_MANAGE_ANY` → `can_manage_project`, `can_manage_members`, `can_add_member` |
| Чтение задач и комментариев — где участвует; чужих проектов — нет | `can_read_project_content` |
| Создание задачи/подзадачи себе, другому, без исполнителя | `can_create_task`, `can_create_subtask` |
| Изменение своей/чужой задачи, смена исполнителя, удаление задачи | `can_edit_task_fully`, `can_change_task_status`, `can_change_assignee`, `can_delete_task` |
| Удаление чужого комментария | `can_delete_comment` |
| Получатель владения — только участник с ролью БА | `recipients.PROJECT_OWNER` (`PROJECT_CREATE`) |

### 4.4. FR-7 и гонки при нескольких ТА (без изменений кода, кроме `ACCOUNT_ADMIN_ROLES`)

Действия над учётными записями (`users/service.py`) выполняются так:
`_require` (права из `get_actor`) → `_lock_for_account_change`, то есть advisory-блокировка
пространства, `FOR NO KEY UPDATE` строк «активные ТА ∪ цель» и проверка, что инициатор **сейчас**
активный ТА (иначе 403) → изменение → `ensure_account_admin_remains` (иначе 422
`last_account_admin`, откат) → удаление сессий → событие. Проверка по веткам FR-7:

| Ветка FR-7 / AC | Результат по коду |
|---|---|
| Единственный активный ТА снимает или меняет свою роль, блокирует себя (AC-6) | `ensure_account_admin_remains` → 422, откат: роль, статус, сессии и журнал не меняются (сессии удаляются после проверки) |
| Есть второй активный ТА (AC-7, AC-8, AC-9) | проверка проходит; `must_change_password` в условии «активный» не участвует (`_is_active_account_admin`: роль ТА и `NOT is_blocked`) |
| Устаревший инициатор (FR-7 п.3) | лишён роли или заблокирован до получения advisory-блокировки → 403 (`_lock_for_account_change`); сессия удалена до `get_actor` → 401 |
| AC-10 (а) оба снимают роль с себя | запросы идут строго по очереди; второй видит единственного ТА — себя → 422 |
| AC-10 (б) `ta1` блокирует себя, `ta2` меняет свою роль на П | второй (любой из них) → 422 |
| AC-10 (в) взаимная блокировка | второй: инициатор заблокирован → 403 или 401 |
| AC-10 (г) взаимное снятие роли | второй: инициатор без роли → 403 (на гейте `no_role` или в `_lock_for_account_change`) |
| Ожидание блокировки дольше серверного `lock_timeout` | 503 `service_busy` + `Retry-After` (001 D-40), откат |

Если тест R3-T04 на этой версии кода красный, это не ошибка теста: исполнитель возвращает
`PLAN_ISSUE`, а не правит сервис молча.

### 4.5. Миграция `backend/migrations/versions/0006_three_roles.py`

```python
"""Три роли: снятие роли «Смешанная», запись в журнал от «системы», CHECK role_valid
(spec 002 FR-2, FR-13…FR-17; plan 002 D-5…D-11).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16
"""
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None

_CHECK = "ck_workspace_member_role_valid"
_ROLES_002 = "role IN ('tech_admin','business_admin','user')"
_ROLES_001 = "role IN ('tech_admin','business_admin','mixed','user')"

def upgrade() -> None:
    # D-9: самые сильные блокировки сразу, без повышения внутри транзакции
    op.execute("LOCK TABLE workspace_member IN ACCESS EXCLUSIVE MODE")
    op.execute("LOCK TABLE app_user IN SHARE MODE")
    # План: всем бывшим СМ — NULL; активным — tech_admin, если в их пространстве нет
    # активного ТА (FR-16; «активный» = роль tech_admin и NOT is_blocked; одноразовый пароль не мешает)
    op.execute("""
        CREATE TEMP TABLE gt_0006_mixed ON COMMIT DROP AS
        SELECT m.workspace_id, m.user_id, u.login,
               CASE WHEN NOT u.is_blocked AND NOT EXISTS (
                        SELECT 1 FROM workspace_member t JOIN app_user tu ON tu.id = t.user_id
                        WHERE t.workspace_id = m.workspace_id
                          AND t.role = 'tech_admin' AND NOT tu.is_blocked)
                    THEN 'tech_admin' END AS new_role
        FROM workspace_member m JOIN app_user u ON u.id = m.user_id
        WHERE m.role = 'mixed'
    """)
    op.execute("""
        UPDATE workspace_member m SET role = c.new_role, updated_at = now()
        FROM gt_0006_mixed c
        WHERE m.workspace_id = c.workspace_id AND m.user_id = c.user_id
    """)
    # FR-15: ровно одна запись на бывшего СМ, как у set_role (001/FR-41); автор «система»
    op.execute("""
        INSERT INTO domain_event (workspace_id, occurred_at, actor_id, entity_type, entity_id,
                                  action, changed_fields, project_id, deal_id, in_audit,
                                  changes, details)
        SELECT c.workspace_id, now(), NULL, 'user', c.user_id,
               CASE WHEN c.new_role IS NULL THEN 'user.role_removed' ELSE 'user.role_changed' END,
               '{}'::text[], NULL, NULL, true, NULL,
               jsonb_build_object('role_from', 'mixed', 'role_to', c.new_role)
        FROM gt_0006_mixed c
        ORDER BY c.workspace_id, c.login, c.user_id
    """)
    # FR-2: после снятия ролей (иначе новый CHECK не пройдёт проверку строк)
    op.drop_constraint(op.f(_CHECK), "workspace_member", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workspace_member", _ROLES_002)

def downgrade() -> None:
    # D-10: роли бывших СМ не восстанавливаются, журнал не меняется (spec 002 §7)
    op.drop_constraint(op.f(_CHECK), "workspace_member", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workspace_member", _ROLES_001)
```

Свойства, которые проверяют тесты R3-T13:
- **Атомарность (FR-17).** Отметка версии, роли, журнал и CHECK фиксируются одной транзакцией
  (`env.py`, D-5). Любой сбой (D-8) откатывает всё: версия 0005, роли `mixed`, журнал N, CHECK
  принимает `mixed`. Повтор после устранения сбоя даёт результат AC-20.
- **Идемпотентность.** Повторный `upgrade head` или `gostracker bootstrap` после успеха — no-op
  alembic. Сам SQL тоже идемпотентен: нет строк `mixed` — нет изменений и записей (AC-21).
- **Пустой случай.** Пользователей `mixed` нет — записей в журнале нет (FR-15, AC-21). На чистой
  установке журнал пуст (001/AC-114).
- **Запись равна ручной.** Для одного и того же перехода роли запись миграции совпадает с записью
  `set_role` по `entity_type`, `action`, `changed_fields`, `project_id`, `deal_id`, `in_audit`,
  `changes`, `details`. Различаются только `actor_id` (`NULL`) и `occurred_at`.
- **Сессии, пароли, признаки** `is_blocked` и `must_change_password`, владение, участие,
  исполнители и авторство не меняются (FR-14): миграция трогает только `workspace_member.role`,
  `workspace_member.updated_at` и `domain_event`.
- **Пространства.** FR-16 считается по каждому пространству отдельно (в R1 оно одно, но схема
  допускает несколько, 001 D-5).
- **`alembic check`** чист: модель (§4.6) и миграция согласованы. Отметим, что autogenerate не
  сравнивает CHECK, поэтому текст CHECK отдельно проверяет `db/test_identity_models.py`.

### 4.6. Модель `domain/workspaces/models.py`

```python
CheckConstraint("role IN ('tech_admin','business_admin','user')", name="role_valid")
```
Тест сверяет множество значений в тексте CHECK с `{r.value for r in Role}`.

### 4.7. Демо-данные `domain/ops/demo.py` (R3-T08; 002/FR-22, D-13)

```python
_ALL_PROJECTS_BA: Final = "demo.ba4"   # БА — участник обоих проектов, не владелец (вместо demo.mixed)
_USERS = (
    ("demo.ta", "tech_admin"),
    ("demo.ba4", "business_admin"),     # на месте прежнего ("demo.mixed", "mixed"), D-13
    ("demo.ba1", "business_admin"), ("demo.ba2", "business_admin"), ("demo.ba3", "business_admin"),
    *((f"demo.user{i}", "user") for i in range(1, 8)),
)
# в построении проектов: logins = (owner, other_ba, _ALL_PROJECTS_BA, *users)
```
Остальное без изменений: 12 пользователей + первый ТА = 13, 2 проекта, 30 задач, отказ на
непустой системе, пароли, события `user.created`/`user.role_assigned` от «системы». Если
`load_demo_data` читает `_USERS` и `_ALL_PROJECTS_BA` как глобальные имена модуля во время
вызова, `monkeypatch.setattr` в тесте AC-30 работает без дополнительного кода. Если функция
копирует их при импорте, это нужно исправить в R3-T08.

### 4.8. Контракт API (NFR-1, AC-1)

- Все поля текущей роли используют компонент `Role`: `AdminUser.role`, `SetRoleRequest.role`,
  `LoginResponse`/`SessionUser.role`, `Me.role`, `ProjectMember.role`, `DirectoryUser.role`.
  После R3-T11 `components.schemas.Role.enum == ["tech_admin", "business_admin", "user"]`.
- `AuditEntry.details`: `dict[str, str | None] | None` — строки без перечня, `mixed` в
  исторических записях допустим (FR-20). Схема не меняется.
- Запрос с `role: "mixed"` (и `MIXED`, `admin`, `""`) отклоняется валидацией тела →
  422 `validation_error`. Гейты роутера (`require_capability`) выполняются раньше разбора тела:
  401 → 403 → 422 (FR-18, docstring `admin_users.py`).
- Пересборка: `source .venv/bin/activate && bash scripts/gen-api.sh` (пишет
  `docs/api/openapi.json` и `frontend/src/shared/api/schema.d.ts`). Синхронность проверяют
  `cli/test_openapi.py::test_fr44_committed_openapi_json_matches_generation` и
  `infra/test_frontend_api_types.py`.
- `GET /me` у БА: `capabilities` дополняется `project_manage_any` (D-1).

### 4.9. Фронтенд (R3-T09, R3-T10; FR-20, FR-21)

- `UsersPage.tsx`: `const ROLES: readonly Role[] = ["tech_admin", "business_admin", "user"];` —
  выбор: «Без роли» + три роли (AC-27).
- `ProjectPage.tsx`: `const OWNER_ROLES: ReadonlyArray<ProjectMember["role"]> = ["business_admin"];`
  — кандидаты во владельцы — незаблокированные участники-БА (FR-11).
- `TaskList.tsx`: `const canPickAssignee = actorRole === "business_admin";` (+ комментарий);
  `CreateTaskForm.tsx` — только комментарий (FR-9).
- Видимость элементов управления проектом и задачей уже определяется полями `permissions.*` из
  ответов сервера, поэтому БА, который не владелец, видит их после R3-T01…T03 без правок кода
  (FR-21). Фронтенд-тесты это закрепляют.
- `AuditPage.tsx` и `ru.ts` не меняются: «Смешанная роль» показывается только в журнале (D-14).
- Типы фронтенда собираются вместе с тестами (`tsconfig.json`: `include: ["src", "tests", …]`).
  Поэтому до пересборки `schema.d.ts` (R3-T11) ни один файл `src`/`tests` не должен присваивать
  `"mixed"` значению типа `Role` или `ProjectMember["role"]`. Это делают R3-T09 и R3-T10.

### 4.10. Документы (NFR-5, spec §10; R3-T16, R3-T17)

- `docs/adr/0013-three-roles.md` (по `docs/adr/TEMPLATE.md`): статус «принято (владелец продукта,
  2026-10-16)»; «Заменяет ADR-0003; уточняет ADR-0004, ADR-0005, ADR-0006, ADR-0009, ADR-0012».
  Содержание — все пункты spec §10 (отличия 1–3 от ТЗ §4 по spec §5.3; несколько ТА без признака
  «первичный»; FR-7 и гонки; замена владельца любым БА; запись миграции от «системы» — первая
  миграция, пишущая в журнал; FR-16 и последствия; риск Q-5 о неаудируемом самодобавлении БА).
- `docs/adr/0003-mixed-role.md`: строка статуса → «заменено ADR-0013 (2026-10-16)». Остальной
  текст не меняется.
- `docs/adr/0004-auth-pilot.md`, `0006-audit-r1.md`, `0012-mvp-task-tracker-first.md`: в строку
  «Связано» или «Статус» добавляется «Уточнено ADR-0013: роль «Смешанная» упразднена, её системные
  права — у ТА, права на проекты — у БА». Исторический текст не переписывается (C-6).
- `docs/data-model.md`: вступление «миграции `0001`–`0006`»; роль — `tech_admin`,
  `business_admin`, `user`, `NULL`; строка миграции `0006` в таблице миграций; правило «записи
  журнала от «системы» при обновлении 0006» в разделе `domain_event`.
- `README.md` (ru и en): `demo.mixed` → `demo.ba4`, `demo.ba1`…`demo.ba4`; права БА в сценарии
  демо по FR-9 (БА-участник правит любую задачу; владение передаёт любой БА; получатель —
  участник с ролью БА).
- `docs/acceptance/mvp-demo.md`: пункт UF-3 переписывается по FR-8/FR-9. Новый пункт
  `- [ ] 002/AC-27 …` (ручной): журнал со «Смешанная роль», выбор роли из трёх и «Без роли»,
  элементы управления у `ba.member`, самодобавление `ba.out`, на демо-учётных записях
  (`demo.ba4` или `demo.ba2` — участник, `demo.ba3` — не участник).

## 5. Данные и эксперименты

ML-кода нет (NFR-4). Тестовые данные:
- **Фикстуры раздела 6 spec (AC-1…AC-19, AC-24).** Отдельное пространство на тест. Логины
  синтетические (`ta1`, `ta2`, `ba.owner`, `ba.member`, `ba.out`, `u1`, `u2`, `u3`, `ba.blocked`,
  `ba.free`, `nr`; BR-9). Пароли постоянные. Проект P, задачи T1/T1.1/T3/T3.1, комментарии
  c1/c2/c3 создаются фабриками `tests/factories.py`. Общая фикстура — модуль
  `backend/tests/roles002_support.py` (R3-T01; расширяется в R3-T02/T03).
- **Фикстуры обновления (AC-20…AC-23, AC-25, AC-26, AC-29).** Модуль
  `backend/tests/upgrade002_support.py` (R3-T13), схема D-12. Функции:
  `async def to_schema_0005(env) -> None`, `async def to_head(env) -> None` (с `dispose`),
  `async def make_mixed(env, ws, login, *, blocked=False, must_change_password=False,
  session=False) -> tuple[UserRow, str | None]`, `async def audit_rows(env) -> list[Row]`,
  `async def install_failure(env, *, on: Literal["version", "event"], entity_id=None) -> None`,
  `async def remove_failure(env) -> None`.
- **Часы и seed.** Код приложения — `FixedClock` (`FIXED_NOW`), демо — `seed=1`. Время записей
  миграции берётся из БД (D-7): тест проверяет окно `[t0, t1]` реального времени и одинаковое
  `occurred_at` у всех записей одной миграции.
- **Параллельность (AC-10).** `committed`-тест, 4 сценария × **20 повторов**. Каждый повтор
  восстанавливает фикстуру: обе роли `tech_admin`, `is_blocked = false`, старые сессии удаляются,
  новые создаются заново. Журнал append-only, поэтому проверяется прирост числа записей
  (`+1`). Запросы идут одновременно (`asyncio.gather` двух HTTP-запросов через `committed_api_env`,
  как `test_ac78_parallel_requests_never_leave_zero_active_admins`). Допустимые исходы
  проигравшего — код из AC или 503 `service_busy` с `Retry-After`.
- **Деструктивные операции** — только в тестовой БД `*_test` (`committed`: `DROP SCHEMA` +
  `upgrade head`). Тома Docker не трогаются.
- **Smoke.** Отдельного не нужно. Самые долгие тесты — AC-10 (80 раундов) и тесты обновления
  (`committed` + две миграции подпроцессом). Если AC-10 превысит 60 с на машине разработчика,
  число повторов не уменьшается (NFR-3): ускоряется подготовка (сессии фабрикой, не входом).

## 6. Тестовая стратегия и трассировка

Пути — относительно `backend/tests/` (кроме фронтенда и документов). Уровни: unit (чистые
функции), domain (сервис + БД), API (httpx + БД), DB (схема, миграции), CLI, infra-static, docs.

### 6.1. AC 002 → задача → тест

| AC | Где реализуется | Задача | Тест |
|---|---|---|---|
| AC-1 | `Role` (§4.8), пересборка контракта | R3-T11 | `cli/test_openapi_roles.py::test_002_ac1_*` (по `docs/api/openapi.json` и `app.openapi()`) |
| AC-2 | CHECK (§4.5, §4.6) | R3-T13 | `db/test_identity_models.py::test_002_ac2_*` |
| AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9 | `users/service.py` (без изменений), `roles.py` | R3-T04 (тесты), R3-T11 (`ACCOUNT_ADMIN_ROLES`) | `api/test_tech_admins_002.py::test_002_ac{3..9}_*` |
| AC-10 | §4.4 | R3-T04 | `api/test_tech_admin_races_002.py::test_002_ac10_{a,b,c,d}_*` (`committed`, ×20) |
| AC-11, AC-12, AC-17, AC-18, AC-19 | `can_manage_project`, `can_add_member` (§4.2) | R3-T01 | `api/test_ba_projects_002.py::test_002_ac{11,12,17,18,19}_*` |
| AC-16 | П без изменений (запреты для `u1` действуют уже в 001) | R3-T01 (критерий целиком) | `api/test_ba_projects_002.py::test_002_ac16_*` |
| AC-13, AC-14, AC-15 | `is_own_project`, `can_edit_task_fully`, `can_delete_comment` | R3-T02 (комментарии), R3-T03 (задачи, сценарии целиком) | `api/test_ba_tasks_002.py::test_002_ac{13,14,15}_*` |
| AC-11…AC-19: общая фикстура spec §6 | — | R3-T01 (создаёт), R3-T02, R3-T03 (дополняют) | `roles002_support.py::make_world_002(env) -> World002` |
| AC-20 | миграция 0006 | R3-T13 (роли, журнал, данные), R3-T14 (сессия S, вход, 403, смена пароля) | `db/test_three_roles_upgrade.py::test_002_ac20_*`, `db/test_three_roles_after_upgrade.py::test_002_ac20_*` |
| AC-21 | миграция 0006, alembic | R3-T13 | `db/test_three_roles_upgrade.py::test_002_ac21_*` |
| AC-22 | FR-16 в миграции | R3-T13 (роли, журнал, обе ветки), R3-T14 (вход, создание учётной записи, передача PM) | `db/test_three_roles_upgrade.py::test_002_ac22_*`, `db/test_three_roles_after_upgrade.py::test_002_ac22_*` |
| AC-23 | policy (R3-T01, T03) + миграция | R3-T14 | `db/test_three_roles_after_upgrade.py::test_002_ac23_*` |
| AC-24 | валидация `SetRoleRequest.role` | R3-T11 | `api/test_role_values_002.py::test_002_ac24_*` |
| AC-25 | ответы API (`Role`/`null`), справочник | R3-T14 | `db/test_three_roles_after_upgrade.py::test_002_ac25_*` |
| AC-26 | журнал (без изменений) | R3-T14 | `db/test_three_roles_after_upgrade.py::test_002_ac26_*` |
| AC-27 *ручной* | фронтенд §4.9 | R3-T09, R3-T10 (автотесты vitest вспомогательно), R3-T17 (пункт чек-листа) | `docs/acceptance/mvp-demo.md` (пункт `002/AC-27`); `infra/test_docs_static.py::test_002_ac27_*` проверяет наличие пункта |
| AC-28 *инфра* | демо §4.7 | R3-T08 | `cli/test_demo_data.py::test_002_ac28_*` (как 001/AC-41, AC-104 — тест команды оператора) |
| AC-29 | атомарность (D-5, D-8) | R3-T13 | `db/test_three_roles_upgrade.py::test_002_ac29_*` (`committed`) |
| AC-30 *инфра* | миграция + демо | R3-T15 | `db/test_three_roles_demo_upgrade.py::test_002_ac30_*` (`committed`; обновление командой `gostracker bootstrap`, D-13) |

FR/NFR без отдельного AC:
- FR-21 (элементы управления) — R3-T09/T10 (vitest) + AC-27.
- NFR-5 (ADR) — R3-T16, `infra/test_docs_static.py::test_002_nfr5_*`.
- NFR-1 (`capabilities` БА) — R3-T01, `api/test_sessions.py` (таблица `EXPECTED_CAPABILITIES`).
- FR-1 (нет `mixed` в коде) — R3-T12, `unit/test_no_mixed_role.py` (D-16).

### 6.2. Старые тесты → AC 002 (NFR-3)

Правила для test-writer и ревьюера:
1. Тест 001, который проверял поведение СМ или запрет, снятый 002, **не удаляется без замены**.
   Разрешены три действия: (а) **заменить актора** (СМ-не участник `sm` → БА-не участник `ba3`,
   СМ-участник `sm_m` → БА-участник `ba2`, СМ как администратор учётных записей → второй ТА) при
   неизменных assert-ах; (б) **обратить ожидание** (403 → успех) там, где 002 прямо меняет
   правило, со ссылкой на AC 002 в docstring; (в) **удалить**, если тест дублирует новый тест
   `test_002_*` — в docstring заменителя (или в отчёте задачи) указывается имя удалённого теста.
2. Assert-ы, не связанные с ролью СМ, не ослабляются и не удаляются.
3. Значение `mixed` в `details` журнала (`db/test_event_log.py`, `AuditPage.test.tsx`) — история
   (FR-20). Такие тесты остаются как есть.
4. Имена тестов, в которых упомянута СМ, переименовываются по смыслу (`…_mixed_…` →
   `…_ba_non_member_…`). Ложные совпадения со словом `mixed` («mixed case» — регистр логина,
   «json_invalid_mixed», `unit/test_logging.py`) не трогаются.

| Файл (функции) | Действие | AC 002 | Задача |
|---|---|---|---|
| `unit/test_role_matrix.py` (`test_br1_mixed_is_union…`, `test_ac26_ac39_account_capabilities_only_ta_and_mixed`, `test_fr69_account_admin_roles_is_tech_admin_and_mixed`, `test_fr8_role_values_are_db_strings`) | БА с `PROJECT_MANAGE_ANY` (T01); три роли, админ — только ТА; тест «union» удаляется | AC-1, AC-3, AC-5, FR-1, FR-8 | R3-T01, R3-T11 |
| `unit/test_policy.py` (`test_oi127_*`, `test_ac48_*`, `test_ac73_can_add_member`, `test_ac103_can_delete_comment`, таблицы `ROLES`/`MIXED`) | `test_oi127_*` обращаются: БА-участник правит, удаляет, переназначает чужое; `can_add_member` БА себе — `True`; `MIXED` убирается из таблиц | AC-11, AC-13, AC-14, AC-15 | R3-T01…T03, R3-T11 |
| `unit/test_recipients.py` | `MIXED` убирается; владелец — только БА | AC-17, AC-18 | R3-T11 |
| `api/test_deps_gates.py` (таблица возможностей, `test_fr67_*` со сменой на `mixed`) | `PROJECT_MANAGE_ANY` у БА (T01); строки `mixed` удаляются; смена роли на `business_admin` вместо `mixed` | AC-3, AC-5 (матрица разделов), 001/AC-76 в редакции 002 §9 | R3-T01, R3-T11 |
| `api/test_sessions.py` (`EXPECTED_CAPABILITIES`, `test_fr67_me_reflects_role_change_without_relogin`) | БА + `project_manage_any` (T01); ключ `mixed` удаляется, смена на БА (T11) | NFR-1, D-1 | R3-T01, R3-T11 |
| `domain/test_projects_service.py` (`test_ac110_sm_*`, `test_ac52_sm_*`, `test_ac72_sm_*`, `test_ac48_non_owner_cannot_delete`, `test_ac52_owner_transfers_to_ba_member_and_loses_manage`, `test_ac52_ac72_transfer_by_non_manager_is_403`) | «БА-не владелец → 403» → выполнено; «теряет право» отменено; `sm` → `ba3` | AC-11, AC-12, AC-17, AC-18 | R3-T01 (обращение), R3-T05 (`sm`) |
| `domain/test_project_members_service.py` (`test_ac54_ba_cannot_add_self`, `test_ac73_ac54_others_cannot_add/remove…`, `test_ac73_sm_*`) | БА добавляет себя и управляет составом любого проекта; запрет остаётся для П и ТА | AC-11, AC-16, AC-19 | R3-T01, R3-T05 |
| `api/test_projects.py` (`test_ac52_owner_transfers_to_member_ba_and_loses_delete_right`, `test_ac52_non_owner_roles_get_403_on_transfer`, `test_ac48_other_roles_get_403_on_delete`, `test_ac110_other_roles_get_403…`, `test_ac48_mixed_non_member_can_delete`, `test_ac52_ac72_mixed_non_member_transfers…`, `test_ac52_transfer_to_mixed_member_is_allowed`, `test_ac51_mixed_creates_project…`, `test_ac55_fr17_ba_and_sm_see_all…`) | 403 остаётся для П, ТА, без роли; для БА — выполнено; «передача участнику-СМ» → «участнику-БА»; СМ-тесты → `ba3` | AC-12, AC-15 (список), AC-16, AC-17 | R3-T01, R3-T05 |
| `api/test_project_members.py` (`test_ac54_ba_non_member_adding_himself_is_403`, `test_fr15_ac54_ba_member_not_owner_adding_other_is_403`, `test_ac73_mixed_*`, `test_fr15_ac54_mixed_non_member_adding_himself_is_204`, `test_d45_members_visible_to_ba_sm…`) | 403 → 204 для БА; СМ-тесты → `ba3`/`ba2` | AC-11, AC-19 | R3-T01, R3-T05 |
| `api/test_audit.py` (`test_t72_ac65_*` — неудачная передача участником-БА; `test_t18_roles_tech_admin_and_mixed_can_view`, `test_t18_filter_entity_type_and_actor_id`) | неудачная передача — от П; журнал читает только ТА, второй актор — второй ТА | AC-3, AC-5, AC-12, AC-17 | R3-T01, R3-T04 |
| `domain/test_comments_service.py` (`test_ac58_ba_non_owner_member_cannot_delete_foreign_403`, `test_ac103_sm_*`, `test_fr23_edit_sm_author_non_member_403`, `test_s11_5_list_permissions_per_actor`) | БА-участник удаляет чужой комментарий; правка — только автор; `sm`/`sm_m` → `ba3`/`ba2` | AC-13, AC-15 | R3-T02, R3-T07 |
| `api/test_comments.py` (`test_ac58_owner_ba_and_sm_member_delete_foreign`, `test_ac103_sm_becomes_able_after_membership`) | `sm_m` → `ba2` (удаляет чужой); `sm` → `ba3` | AC-13, AC-15 | R3-T02, R3-T06 |
| `domain/test_tasks_update_delete.py` (`test_ac48_ba_not_owner_*`, `test_ac99_ba_not_owner_cannot_delete_foreign_task`, `test_ac43_ba_not_owner_403_sm_member_ok…`, `test_ac103_sm_*`, `test_ac99_sm_*`, `test_fr20_ba_sm_may_clear_assignee`, `test_ac47_mixed_patch…`, `test_t75_*` с владельцем-БА) | «БА-не владелец → 403» → выполнено (правка всех полей, исполнитель, удаление); `test_t75_*` (гонки с «владельцем») сохраняют смысл, где переназначает БА-участник; `sm_m` → `ba2` | AC-13, AC-14 | R3-T03, R3-T07 |
| `domain/test_tasks_create.py` (`test_t70_ba_member_not_owner_subtask_rules`, `test_ac56_ba_sm_*`, `test_br1_ba_sm_*`, `test_ac109_subtask_defaults_by_role`) | БА-участник создаёт подзадачу к любой задаче любому участнику и без исполнителя | AC-13 | R3-T03, R3-T07 |
| `domain/test_tasks_move.py` (`test_ac48_ba_not_owner_moves_only_own_task`, `test_ac103_sm_member_moves_non_member_403`) | БА-участник переносит любую задачу; неучастник — 403 | AC-13, AC-15 | R3-T03, R3-T07 |
| `domain/test_tasks_queries.py` (`test_fr19_permissions_member_ba_not_owner_not_assignee_nothing`, `test_fr19_permissions_ba_non_owner_own_task_edit_no_reassign`, `test_fr19_permissions_mixed_member_everything`, `test_fr19_permission_flags_match_service_outcomes_matrix`) | флаги БА-участника — всё `True`; «mixed everything» → «ba member everything» | AC-13 | R3-T03, R3-T07 |
| `api/test_tasks.py`, `api/test_subtasks.py`, `api/test_task_permissions.py` (`test_t74_review_6_ba_member_not_owner_subtask_formula`, `test_ac99_mixed_member_deletes_foreign_task_ba_member_cannot`, `test_ac103_mixed_non_member_adds_himself…`, `test_ac103_sm_non_member_becomes_member_and_creates`, `test_owner_and_mixed_member_create_subtask…`, `test_ac46_*` с БА-не владельцем) | обращение для БА-участника; `sm` → `ba3`, `sm_m` → `ba2` | AC-13, AC-15 | R3-T03, R3-T06 |
| `api/test_reassign_blocked.py` (`test_ac43_ba_member_not_owner_gets_403_mixed_member_reassigns`) | БА-участник переназначает; П — 403 | AC-14 | R3-T03 |
| `api/test_board_move.py` (`test_fr19b_ba_member_non_owner_moves_own_assigned_task_only`, `test_move_allowed_for_owner_and_mixed_member…`, `test_move_non_member_is_403…`) | БА-участник переносит любую карточку; `sm*` → `ba*` | AC-13, AC-15 | R3-T03, R3-T06 |
| `api/test_soft_delete.py` (`test_ac99_*`) | удаляют `usr`, `ba`, `ba2` | AC-13 | R3-T03 |
| `api/test_board.py`, `api/test_personal_tasks.py`, `api/test_project_task_list.py`, `api/test_not_found_vs_forbidden.py`, `api/test_workspace_isolation.py` | `sm` → `ba3`, `sm_m` → `ba2` в перечнях ролей; СМ-администратор второго пространства → ТА | AC-15 (неучастник — 403, карточка — 200), 001/AC-21 (не про СМ) | R3-T05, R3-T06 |
| `api/test_role_change_effect.py` (`changer_role` `mixed`, `test_t77_ac77_…_mixed_reassigns`) | меняет роль только ТА; переназначает БА-участник | AC-14, 001/AC-76/77 в редакции 002 §9 | R3-T04 |
| `api/test_admin_roles.py` (`test_fr12_ta_and_mixed_may_change_own_role`, `test_ac78_last_admin_may_switch_between_admin_roles`, `test_ac78_parallel_requests_never_leave_zero_active_admins`, `test_ac26_non_admins…`) | своя смена роли — ТА при втором активном ТА на БА; «единственный ТА → mixed» удаляется (заменён AC-6 и AC-24); параллельность — два ТА | AC-4, AC-6, AC-7, AC-10, AC-24 | R3-T04 |
| `api/test_admin_users.py` (`test_fr42_mixed_role_has_access_to_admin_section`, `test_ac2_get_user_returns_admin_view`, тело `{"role": "mixed"}` в гейт-тесте) | доступ к разделу — второй ТА; карточка — с ролью БА; тело гейт-теста — `"user"` | AC-3, AC-5 | R3-T04 |
| `api/test_e2e_accounts.py` (001/AC-64) | ТА при втором активном ТА меняет свою роль на БА | AC-4 (001/AC-64 по 002 §9) | R3-T04 |
| `api/test_admin_roles.py::test_fr12_every_role_value_can_be_assigned` (параметр `"mixed"`) | три значения назначаются (200); `"mixed"` → 422 `validation_error`, роль не изменилась | AC-24, FR-1 | R3-T11 |
| `api/test_e2e_accounts.py::test_ac2_ta_creates_12_users_with_4_roles…` (`ROLES` с `"mixed"`) | 12 пользователей по составу демо: 1 ТА, 4 БА, 7 П | AC-24, FR-1, AC-28 | R3-T11 |
| `domain/test_user_admin_service.py` (`test_ac26_tech_admin_and_mixed_can_run_account_actions`, `test_ac78_last_admin_may_become_mixed`, `test_ac78_with_second_active_admin…`, `test_ac78_concurrent_mutual_demotion…`, `test_t16_review_three_admins…`, `test_ac67_*`, `test_fr67_*`, `test_ac21_*`, `test_ac26_self_assignment…`) | СМ → ТА; «last admin may become mixed» удаляется (AC-6, AC-24); трое админов — трое ТА | AC-3, AC-6, AC-7, AC-10 | R3-T04 |
| `api/test_login_display.py` (001/AC-129, `Mixed.Admin`) | учётные записи и журнал — от ТА `Admin.Main`; проекты — от БА | 001/AC-129 по 002 §9 (не СМ-поведение) | R3-T07 |
| `api/test_route_guards.py` (`new_user(role="mixed")`, параметр `mixed_one_time_password`) | роль `business_admin`; параметр удаляется (`ta_one_time_password` остаётся) | FR-1 | R3-T07 |
| `api/test_users_directory.py`, `domain/test_directory.py` (`mixed` в справочнике) | справочник — БА и П | AC-25 | R3-T07 |
| `cli/test_demo_data.py` (`demo.mixed`, счётчик ролей) | `demo.ba4`, `business_admin: 4` | AC-28 | R3-T08 |
| `db/test_login_display_upgrade.py` (001/AC-131, актор `demo.mixed`) | актор — первый ТА `admin`; «журнал не изменился» остаётся в силе (`mixed` в демо нет) | 001/AC-131 по 002 §9, AC-21 | R3-T08 |
| `db/test_identity_models.py` (`role="mixed"` в UNIQUE/D-5, `test_fr66_four_roles_are_accepted`) | три роли принимаются, `mixed`/`admin` — `23514`; в UNIQUE/D-5 — `business_admin` | AC-2 | R3-T13 |
| `db/test_migrations.py` (`script.get_heads() == ["0005"]`, `test_t93_downgrade_0004…` с `mixed`) | голова — `0006`; цепочка 0005 → 0006; `mixed` в подготовке данных — только в схеме ≤ 0005 | AC-21, AC-29 | R3-T13 |
| `infra/test_docs_static.py::test_t93_data_model_documents_login_display_and_migration_0005` | «0001–0005» → «0001–0006» (остальные проверки без изменений) | NFR-5 | R3-T16 |
| Фронтенд: `UsersPage.test.tsx`, `admin/helpers.tsx` | варианты выбора — `["", "business_admin", "tech_admin", "user"]`; сценарий «назначить mixed» → «назначить business_admin» | AC-27, FR-21 | R3-T09 |
| Фронтенд: `ProjectPage.test.tsx`, `projects/helpers.tsx` (`M_ME`, `M_BLOCKED_MIXED`, кандидаты «BA и mixed»), `CreateTaskForm.test.tsx`, `TaskList.test.tsx`, `tasks/helpers.tsx`, `tasks/taskpage-helpers.tsx`, `BoardCreate.test.tsx`, `shared/UserPicker.test.tsx` | `mixed` → `business_admin`; кандидаты во владельцы — только БА; выбор исполнителя — только БА | AC-17, AC-27, FR-21 | R3-T10 |
| Фронтенд: `AuditPage.test.tsx` | без изменений; добавляется явный тест FR-20 | AC-26, AC-27 | R3-T09 |

### 6.3. Инфраструктурные и ручные AC

- **AC-28 *инфра*** — `cli/test_demo_data.py` в обычном прогоне pytest (тест команды
  оператора `demo-data` против тестовой БД, как 001/AC-41, AC-104).
- **AC-30 *инфра*** — `db/test_three_roles_demo_upgrade.py` в обычном прогоне (`committed`).
  Предыдущая версия воспроизводится по D-13, обновление — командой оператора
  `gostracker bootstrap` (`app.cli.main.main(["bootstrap"])` в отдельном потоке с окружением
  тестовой БД, по образцу `cli/test_bootstrap.py`). Стек Docker не нужен.
  `infra/test_stack_first_run.py` (чужая правка) не трогается: в нём нет `mixed` и демо (проверено).
- **AC-27 *ручной*** — пункт чек-листа `docs/acceptance/mvp-demo.md`, проверяется в браузере
  при приёмке. Автотесты vitest (R3-T09, T10) покрывают его части без браузера.

## 7. Зависимости

Новых пакетов нет (backend и frontend). Используются уже установленные alembic, SQLAlchemy,
pytest, vitest, openapi-typescript.

## 8. Риски

- **R-1. Объём правок тестов.** Около 45 backend- и 11 frontend-файлов тестов. Снижение риска:
  этапы (§1), отдельные задачи «только тесты» и таблица §6.2. Если в задаче падает тест из файла,
  которого нет в её списке, исполнитель останавливается с `PLAN_ISSUE` (без правок вне списка).
- **R-2. Неявные зависимости тестов от «БА-не владелец → 403».** Поиск по коду мог пропустить
  тест, где БА-участник используется как «без прав». Такие файлы перечислены в группах `(+ …)`
  задач R3-T01…T03 как допустимые к правке.
- **R-3. `capabilities` БА в `GET /me` (D-1).** Схема та же, но в списке у БА появляется
  `project_manage_any`. Фронтенд эту возможность не использует (проверено: только `assign_roles`
  и пункты меню). Если владелец сочтёт это нарушением NFR-1, есть альтернатива D-1 (а).
- **R-4. Время записей миграции не фиксируется** (D-7), тест проверяет окно. Если ревьюер
  потребует фиксированные часы и для миграции, нужен тестовый крючок в коде поставки. План его
  отвергает.
- **R-5. Ручной запуск миграции при работающем API** может упасть по deadlock (D-9). Тогда
  откатывается всё, повторный запуск даёт тот же результат. Штатный путь (`docker-entrypoint.sh`)
  запускает миграцию до uvicorn.
- **R-6. Откат версии (`downgrade 0005`)** возвращает CHECK, но не роли. Старый код увидит
  бывших СМ без роли. Так задумано (spec §7), ТА восстанавливает роли по журналу. Это
  документируется в ADR-0013.
- **R-7. AC-10: долгий тест и редкие 503.** Допускаются spec. Если 503 у проигравшего
  встречается часто, тест не ослабляется: проверяются инварианты (один активный ТА, одна новая
  запись).
- **R-8. Порядок задач фронтенда.** Если R3-T11 (пересборка `schema.d.ts`) выполнить раньше
  R3-T09/T10, `npm run typecheck` упадёт на тестах с `"mixed"`. Зависимости в `tasks.md` это
  исключают.

## 9. Противоречия и неполнота spec (не исправлены; на решение владельца или spec-writer)

- **П-1. Статус spec.** В шапке v0.2 — «DRAFT», но оркестратор передал, что владелец её утвердил.
  План исходит из утверждения. Шапку нужно привести к APPROVED (spec-writer).
- **П-2. spec §7 и §10 о файлах 001.** §7 выносит правку `specs/001-pilot-r1/plan.md` и
  `tasks.md` за рамки 002 («синхронизация — после утверждения 002»), а §10 относит её к
  архитектору «при планировании 002». План 001 не правит: замены перечислены в §10 этого плана
  для будущей синхронизации.
- **П-3. ADR-0005 — чужая незакоммиченная правка.** По `git status` файл
  `docs/adr/0005-project-no-deadline.md` изменён, spec §10 называет его «(чужая правка)», но в
  списке запретов оркестратора его нет. Он вынесен в §11 (нужно разрешение владельца).
- **П-4. NFR-3 «фиксированные часы» и FR-15 «время обновления (UTC)».** Миграция идёт в
  подпроцессе alembic, и время записи берётся из БД (D-7). Тест проверяет окно времени, а не
  фиксированное значение. Если нужно буквальное соблюдение NFR-3 и для миграции, это решение
  владельца (R-4).
- **П-5. AC-22: парольный статус `m1` не задан.** Общие условия раздела 6 к AC-20…AC-23 не
  применяются, а `m1` в AC-22 должен войти и создать учётную запись без смены пароля. План
  принимает, что у `m1` постоянный пароль (как у `m1` в AC-20).
- **П-6. NFR-1 и `capabilities`** — см. R-3 и D-1: spec не говорит о списке возможностей в
  `GET /me`.

## 10. Связь с 001 plan (что заменено; файлы 001 не правятся)

| 001 plan | Заменено в 002 plan |
|---|---|
| §4.5 `ACCOUNT_ADMIN_ROLES = {TECH_ADMIN, MIXED}`, строка СМ в матрице | §4.1 |
| §4.6 SQL `role IN ('tech_admin','mixed')` в `ensure_account_admin_remains` (строка ~658) | §4.1 (`ACCOUNT_ADMIN_ROLES`), §4.4 |
| §11.5 формулы `is_own_project`, `can_edit_task_fully`, `can_change_assignee`, `can_delete_comment`, `can_manage_project`, `can_add_member`; recipients «БА/СМ» | §4.2 |
| D-45 (видимость для СМ), D-54 («свой проект» БА = владелец) | §4.2, 002 §5.3 п.3 |
| §11.8, D-63 (состав демо: 1 СМ) | §4.7 |
| §4.3, `ck_workspace_member_role_valid` с `mixed` | §4.5, §4.6 |
| §11.7 строки AC-43, AC-48, AC-52, AC-54, AC-72, AC-73, AC-99, AC-103, AC-109, AC-110 | §6.1, §6.2 |
| §11.12.8 строки AC-129 (`Mixed.Admin`), AC-131 (`demo.mixed`) | §6.2 |

## 11. Документы, требующие разрешения владельца (не задачи)

В этих файлах есть чужие незакоммиченные правки, или их запретил трогать оркестратор. Ниже —
предлагаемые правки (по spec §10), вносятся только с разрешения владельца:
- `docs/adr/0009-permissions-refinement.md` — «Связано»: + ADR-0013; п.1: «БА — в любом
  проекте, включая себя», сужение «БА-не владелец не добавляет» снять; п.3 «Смешанная роль в
  проектах» → «Бизнес-администратор в проектах» (права по участию, добавить себя — в любой
  проект); п.4: нового владельца назначает любой БА, фразу «ТА выдаёт роль СМ бизнес-сотруднику,
  а не себе» удалить; п.5: обладатель права — только ТА, ТА может быть несколько, ссылка на
  002/FR-7; п.6: «у смешанной роли» → «у БА»; разделы «Причины», «Альтернативы», «Последствия»
  без СМ.
- `docs/glossary.md` — строки «Техадминистратор» (+ «таких пользователей может быть несколько»),
  «Бизнес-администратор» (по 002 §5.2), «Смешанная роль» (пометка «упразднена, ADR-0013;
  встречается только в старых записях журнала»), «Менеджер», «Своя задача», «Свой проект»,
  «Метка», «Владелец проекта», «Журнал аудита» — по spec §10.
- `docs/open-questions.md` — вопрос 1 («Роль «Смешанная»») и строки со СМ: пометка
  «пересмотрено: ADR-0013, spec 002».
- `docs/adr/0005-project-no-deadline.md` (П-3) — строка «Уточнено ADR-0013», если в файле есть
  упоминание СМ.
- `docs/reviews/` — правок не требуется.
- `backend/tests/infra/test_stack_first_run.py` — правок не требуется (`mixed` и демо в нём нет).
- `CLAUDE.md` — правок не требуется.
- `docs/STATE.md` — после завершения 002: отметить состояние (три роли, миграция 0006, ADR-0013).
