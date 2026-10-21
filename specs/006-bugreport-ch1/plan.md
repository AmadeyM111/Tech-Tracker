# Plan: Баг-репорт «Ч1»: показ пароля, три приоритета, обязательные поля задачи, подзадачи подряд, прогресс, ссылка на родителя

- **Spec:** ./spec.md v0.2 (утверждена владельцем 2026-10-20, открытых вопросов нет)
- **Статус:** DRAFT
- **Основа:** код ветки `feat/r1.0-foundation` на `96c6d3b` (003, 004, 005 реализованы). База
  сравнения для ревью и AC-53 — `96c6d3b`.
- **Нумерация:** решения плана — `PD-1…` (чтобы не путать с допущениями spec `D-1…D-12`), риски —
  `RK-1…`, задачи — `R6-T01…`. Ссылки без префикса ведут на 006 (`AC-12` = 006/AC-12), на другие
  спецификации — с префиксом (`001/FR-20`, `004/AC-25`). Новые тесты: бэкенд —
  `test_006_acN_*`, фронтенд — `006_acN_*`.

## 1. Подход

Фича — шесть независимых по смыслу изменений. Порядок задан так, чтобы каждое состояние ветки
после коммита было рабочим продуктом и чтобы владелец мог выпустить простые исправления раньше.

1. **Только фронтенд, без зависимостей** (R6-T01…R6-T05): кнопка «глазок» в общем `TextField`
   и на двух экранах; строка «Родительская задача» в карточке подзадачи (название родителя —
   отдельным чтением `GET /tasks/{parent_id}`, API не меняется); подзадачи подряд — сначала
   тест воспроизведения (R6-T04), потом исправление (R6-T05) с собственной областью сообщений
   формы подзадачи.
2. **Только бэкенд, без изменения API** (R6-T06): формула прогресса с весами 100/50/0 в одной
   чистой функции, которую используют карточка и Доска.
3. **Приоритет — сквозная поставка** (R6-T07 + R6-T08, один коммит): перечисление
   `low/medium/high`, миграция 0007 (`base→medium`, откат `low/medium→base`), значения по
   умолчанию, демо-данные, перегенерация OpenAPI и типов, подписи и варианты во фронтенде.
   Перечисление попадает в `schema.d.ts`, поэтому бэкенд и фронтенд приоритета разделить на
   два зелёных коммита нельзя.
4. **Обязательные поля — сначала фронтенд, потом сервер** (R6-T09…R6-T14). Формы (вкладка
   «Задачи», диалог 004, карточка) начинают отправлять описание, срок и (у БА) исполнителя и
   проверять их до отправки. Текущий сервер такие тела уже принимает, поэтому после каждого
   фронтенд-коммита продукт работает. Затем сервер начинает требовать поля при создании
   (R6-T13) и запрещать их снятие изменением (R6-T14). Так «бэкенд и диалог 004» выходят
   согласованно: нет коммита, после которого диалог шлёт тело, отклоняемое сервером.
5. **Документы и приёмка** (R6-T15…R6-T17).

Новых файлов в `frontend/src` нет (белый список `test_t21_src_files_only_expected` не
меняется). Новых зависимостей нет. GPU, датасетов и ML-кода нет.

## 2. Решения

| ID | Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---|---|---|---|
| PD-1 | Название родителя в карточке подзадачи (FR-32, FR-33) | Фронтенд: отдельный `useQuery({ queryKey: ["tasks", "parent", parentId], queryFn: () => getTask(parentId), enabled: parentId !== null, retry: false, refetchOnWindowFocus: false })` в `TaskCard`. Без опроса. Пока нет данных или ошибка — текст «Открыть родительскую задачу», адрес тот же | (а) расширить `TaskDetail` полем `parent {id, title}`; (б) общий ключ `["tasks","card",pid]` с карточкой родителя | (а) меняет API, OpenAPI, контрактные тесты (`DETAIL_FIELDS` — точный набор) и запрос карточки; NFR-1 это не требует. (б) ошибка чтения названия попала бы в кэш карточки родителя и при переходе показала бы «Не найдено» до перечитывания. Права на родителя и подзадачу совпадают (001/FR-19), поэтому отдельное чтение всегда разрешено. Название читается при каждом открытии карточки подзадачи (staleTime 0) — это «текущее название» в момент открытия; опрос названия не нужен (§10, З-4) |
| PD-2 | «Сегодня» на сервере | Существующая `app.core.clock.today_msk()` (часы приложения через `ContextVar`, в тестах — `FixedClock`). Вызывается один раз на проверку в сервисе | Новая функция; `date.today()` | Правило ADR-0007, 001/BR-12 уже реализовано; `FixedClock` подменяет время во всех API-тестах (NFR-6) |
| PD-3 | «Сегодня» во фронтенде (D-11) | Чистая `todayMsk(now = new Date()): string` в `features/tasks/CreateTaskForm.tsx`: `Intl.DateTimeFormat` с `timeZone: "Europe/Moscow"`, `formatToParts` → `YYYY-MM-DD`. Сравнение со сроком — сравнением строк `YYYY-MM-DD` | (а) новый файл `features/tasks/rules.ts` или `shared/date.ts`; (б) `new Date().toISOString().slice(0,10)` | (а) запрещено белым списком `test_frontend_scaffold.py` (нужна правка теста — решение владельца; не требуется). (б) даёт дату по UTC, а не по Москве. Образец `timeZone: "Europe/Moscow"` уже есть в `Comments.tsx`, `AuditPage.tsx`. Общего кода сервера и фронтенда нет (разные языки); согласованность проверяется одинаковыми граничными моментами в тестах (AC-23 и AC-28/AC-33: `2026-10-19T21:30:00Z` → `2026-10-20`) |
| PD-4 | Коды приоритета | `TaskPriority(StrEnum)`: `LOW="low"`, `MEDIUM="medium"`, `HIGH="high"` (порядок объявления = порядок FR-8 и в OpenAPI). CHECK `ck_task_priority_valid`: `priority IN ('low','medium','high')`. По умолчанию `medium` в `TaskCreate`, `TaskCreateData`, демо | Сохранить `base` как код «Среднего» | D-1 spec; внешних клиентов нет. Ломающее изменение API — запись ADR-0014 (AGENTS.md, «Ломающие изменения API требуют записи в docs/adr/») |
| PD-5 | Миграция 0007 | `backend/migrations/versions/0007_three_priorities.py`, `revision="0007"`, `down_revision="0006"`. Upgrade: `LOCK TABLE task IN ACCESS EXCLUSIVE MODE` → `DROP` CHECK → `UPDATE task SET priority='medium' WHERE priority='base'` → `CREATE` CHECK (`low/medium/high`). Downgrade: блокировка → `DROP` CHECK → `UPDATE … SET priority='base' WHERE priority IN ('low','medium')` → CHECK (`base/high`). Литералы, без импорта перечислений приложения (как 0006, D-6 плана 002). `updated_at` не трогается: сырой SQL, триггеров у `task` нет (D-12). Журнал не пишется (FR-10). Мягко удалённые строки обновляются тем же `UPDATE` (фильтра по `deleted_at` нет) | (а) `ALTER … ADD CONSTRAINT … NOT VALID`; (б) запрет отката при наличии `low` | Одна транзакция на весь `alembic upgrade` (`env.py` без `transaction_per_migration`, как в 0006) → прерванная миграция не оставляет смеси (NFR-4, AC-54). (б) отвергнуто spec (D-2) |
| PD-6 | Где проверять обязательные поля при создании (FR-15…FR-18) | В сервисе `create_task`, **после** проверки прав. Схема `TaskCreate` остаётся общей для задачи и подзадачи и требует только `title` (`required == {"title"}`; контрактный тест `test_t77_request_schemas_forbid_extra_and_have_no_null_where_required` не меняется). Обязательность описывается в docstring `TaskCreate` (попадает в OpenAPI как `description`) | (а) отдельные схемы `TaskCreate`/`SubtaskCreate` с `required` в OpenAPI; (б) проверка в Pydantic | Pydantic-ошибки возникают до сервиса (порядок «422 схемы → 404 → 403»), и тогда не участник получал бы 422 вместо 403 — нарушение FR-18/AC-24. (а) меняет оба маршрута и сгенерированные типы без выигрыша в поведении |
| PD-7 | Правила задачи верхнего уровня в сервисе | Одна функция `_check_top_level(values: Mapping[str, Any], today: date) -> None` проверяет только присутствующие ключи `description`, `due_date`, `assignee_id`. Создание передаёт все три, изменение (FR-23) — только реально меняющиеся (`changed` из существующего `_changes`, D-46 плана 001) и только если `task.parent_id is None`. Порядок внутри: пустое/пробельное описание → `validation_error`; срок `None` → `validation_error`; исполнитель `None` → `validation_error`; срок `< today` → `due_date_in_past` | Два отдельных набора проверок для POST и PATCH | Одно правило (FR-15…FR-17 и FR-23 — одни и те же условия), «проверяются только изменяемые поля» получается из `changed` даром. Снятие исполнителя при исключении участника (001/FR-15a) идёт другим путём (сервис проектов) и не затрагивается |
| PD-8 | Исполнитель по умолчанию | `_effective_assignee(actor, data, *, top_level: bool)`: не передан → для задачи — создатель (любая роль, D-4); для подзадачи — как сейчас (`USER` → сам, БА → `None`). Передан (в т.ч. `None`) → как передан. Затем `can_create_task`/`can_create_subtask` (403), затем `_validate`, затем `_check_top_level` (только задача) | Менять `policy.py` | Права не меняются (NFR-1: «новые права и роли не вводятся»): «Пользователь» с `null` или чужим исполнителем по-прежнему получает 403 из `can_create_task`, БА с `null` проходит права и получает 422 из `_check_top_level` |
| PD-9 | Код ошибки срока в прошлом | `ErrorCode.due_date_in_past = "due_date_in_past"` (422) в `core/errors.py`; ключ словаря `error.due_date_in_past` = «Срок не может быть раньше сегодняшнего дня». В OpenAPI коды ошибок не перечисляются (только описание `422: … код из каталога`), поэтому код упоминается в docstring `TaskCreate` и `TaskUpdate` | Общий `validation_error` | D-5 spec. Фронтенд различает код и показывает сообщение у поля срока (FR-21, AC-32, AC-56) |
| PD-10 | Формула прогресса | `progress(*, done: int, in_work: int, total: int) -> int \| None` = `(100*done + 50*in_work) // total`, `None` при `total == 0`. `in_work` — подзадачи в `in_progress` и `review`. Карточка (`queries.get_task`) считает по списку подзадач, Доска (`boards/service.py`) — добавляет в агрегат `count().filter(status IN ('in_progress','review'))` | Передавать список статусов в функцию | Одна функция для карточки и Доски (AC-44: значения совпадают); агрегат Доски остаётся одним SQL-запросом (D-62 плана 001). Ключевые аргументы исключают перепутывание позиционных счётчиков |
| PD-11 | Тип ошибок у полей формы (FR-19, FR-23, FR-28) | Новый экспорт `FieldError({ id, message })` в `shared/ui/ErrorAlert.tsx`: `<p id={id} role="alert" className="ui-error">` без перехвата фокуса; `null` → ничего. Поле получает `aria-invalid="true"` и `aria-describedby={id}`. Фокус на первое неверное поле ставит форма | (а) `ErrorAlert` у каждого поля; (б) новый файл компонента | (а) `ErrorAlert` забирает фокус при появлении — несколько сообщений боролись бы за фокус, а FR-19 требует фокус на поле. (б) белый список |
| PD-12 | Видимый признак обязательности | В `<label>` после текста — `<span className="ui-required" aria-hidden="true">{t("tasks.required_mark")}</span>` («*»); у поля `aria-required="true"` (у `UserPicker` — новый проп `required`). Правило `.ui-required { color: var(--danger); margin-left: 4px; }` | Атрибут `required` у `input` | `required` включает встроенную проверку браузера (у форм `noValidate`, но атрибут влияет на `:invalid`-стили и чтение диктором «недопустимо» до ввода). Звёздочка из словаря — NFR-2 |
| PD-13 | Исполнитель в формах создания | Состояние `assignee: { id, login } \| null`, по умолчанию `currentUser`; после успеха и (в диалоге) при смене проекта — снова `currentUser`. БА: тело всегда содержит `assignee_id` выбранного (по умолчанию свой id); `null` в теле не отправляется — пустой выбор ловит проверка до отправки («Выберите исполнителя»). «Пользователь»: ключа `assignee_id` нет, показывается `t("tasks.assignee_fixed", { login })` | БА без выбора — не слать ключ | Явный `assignee_id` даёт один и тот же результат на старом и новом сервере (старый для БА без ключа ставит `null`), поэтому фронтенд выходит раньше сервера без регрессии. AC-31, AC-33 |
| PD-14 | Профиль в формах | Диалог: новые пропсы `currentUser: { id: string; login: string }`, `canPickAssignee: boolean` (в `Sidebar`: `profile.capabilities.includes("task_assign_others")`). Вкладка «Задачи»: `router.tsx` передаёт `currentLogin={profile.login}` в `ProjectPage`, далее `ProjectTaskList` → `CreateTaskForm` (`currentUser`) | Читать `["auth","me"]` из кэша в форме | Явные пропсы, без лишних `GET /me` (004/AC-13, 003/AC-36 проверяют точный набор запросов) |
| PD-15 | Участники проекта в диалоге (FR-20, FR-25) | Новый экспорт `listAllMembers(projectId): Promise<ProjectMember[]>` в `features/projects/api.ts` (страницы по 100 до `has_next`). Диалог: `useQuery({ queryKey: ["projects", projectId, "members-all"], queryFn, enabled: canPickAssignee && projectId !== "", retry: false })`; кандидаты — не заблокированные и с ролью. Локальные копии `listAllMembers` в `ProjectPage.tsx` (R6-T10) и `TaskPage.tsx` (R6-T12) заменяются импортом | Третья копия в `CreateTaskForm.tsx` | AHA: третье повторение — выносим. Файлы уже затронуты этими задачами |
| PD-16 | Подзадачи подряд (FR-26…FR-29) | `SubtaskList({ task, onCreated })` — без пропса `alert`; своё состояние сообщения и `FieldError` внутри секции «Подзадачи». `busy` защищает только запрос создания: снимается после ответа `POST`, а перечитывание карточки (`onCreated()`) не блокирует следующую отправку. После 201: поле пустое, фокус в поле, сообщение снято. Проверка до отправки: пусто/пробелы → «Введите название подзадачи»; длина `> 255` → «Название подзадачи — не более 255 символов». Ошибка сервера → `errorMessage(code)` в той же области. Точная причина п. 6 — из отчёта R6-T04; если она не покрыта этим описанием, исполнитель R6-T05 сообщает `PLAN_ISSUE` | Оставить общую область карточки и поменять текст | FR-28/D-8. Гипотезы причины — §9, RK-1 |
| PD-17 | Кнопка «глазок» | Проп `reveal?: { label: string; shown: boolean; onToggle: () => void }` у `TextField` (только при `type="password"`). Состояние видимости хранит экран (`LoginPage` — одно, `ChangePasswordPage` — три `useState(false)`), при каждой отправке формы экран ставит все в `false` до любых проверок (FR-5, D-7). Размонтирование сбрасывает само (FR-2, AC-8). Кнопка: `button[type=button].ui-reveal[aria-pressed][aria-label=label][disabled=disabled поля]`, внутри `<Icon name={shown ? "eye-off" : "eye"} />`. Поле и кнопка — в `div.ui-input-row`; кнопка в DOM сразу после поля (порядок Tab, AC-6) | (а) состояние внутри `TextField` + «счётчик сброса»; (б) имя «Показать/Скрыть» | (а) сброс при отправке требует управления снаружи; управляемый проп проще (KISS). (б) запрещено D-6 spec (имя постоянное, состояние — `aria-pressed`). Цвета кнопки — общий стиль `button` (контраст `--button-text`/`--button-bg` уже проверен тестами темы) |
| PD-18 | Миграционные тесты прежних поставок (002) | `tests/upgrade002_support.py`: данные «предыдущей версии» (схема 0005) пишутся с `priority="base"` явно; `data_fingerprint` для таблицы `task` берёт строку с приоритетом, приведённым по FR-10 (`CASE priority WHEN 'base' THEN 'medium' ELSE priority END`) в обоих снимках. `db/test_three_roles_demo_upgrade.py`: демо-данные прежней версии загружаются с `demo._REGULAR_PRIORITY = "base"` (monkeypatch, как уже подменяется `_USERS`), снимок `task` — с тем же приведением. `make_task` по умолчанию — `"medium"` | (а) сравнивать в тестах 002 до `0006`, а не до head; (б) исключить столбец `priority` из снимков | (б) — ослабление проверки (запрещено). (а) меняет смысл многих тестов 002 и их HTTP-шагов (план Б, RK-2). Приведение сохраняет строгость: все прочие поля сравниваются побайтно, а приоритет — по правилу FR-10 |
| PD-19 | Порядок и единицы коммита | §8. R6-T04 + R6-T05 и R6-T07 + R6-T08 — один коммит на пару. Остальные задачи — коммит на задачу | Каждая задача — свой коммит | R6-T04 оставляет красный тест (по замыслу), R6-T07 меняет `schema.d.ts`, и фронтенд не проходит `typecheck` до R6-T08 |
| PD-20 | ADR | `docs/adr/0014-task-rules-006.md`: коды приоритета `low/medium/high` (без псевдонима `base`), обязательные поля задачи при создании, запрет снятия при изменении, код `due_date_in_past` | Без ADR | AGENTS.md: «Ломающие изменения API требуют записи в docs/adr/». В spec не названо — §10, З-2 |

## 3. Затрагиваемые модули и файлы

**Бэкенд** (`backend/app`):
- `domain/tasks/progress.py` — новая формула (R6-T06).
- `domain/tasks/queries.py` — счётчики `done`/`in_work` в `get_task` (R6-T06).
- `domain/boards/service.py` — `in_work` в агрегате подзадач (R6-T06).
- `domain/tasks/models.py` — `TaskPriority`, CHECK (R6-T07).
- `migrations/versions/0007_three_priorities.py` — новый (R6-T07).
- `domain/tasks/service.py` — умолчание приоритета (R6-T07); `_effective_assignee`,
  `_check_top_level`, `create_task` (R6-T13); `_authorize` для FR-23 (R6-T14).
- `api/v1/schemas/tasks.py` — умолчания `MEDIUM` (R6-T07); docstring `TaskCreate` (R6-T13),
  `TaskUpdate` (R6-T14).
- `domain/ops/demo.py` — `_REGULAR_PRIORITY` (R6-T07).
- `core/errors.py` — `due_date_in_past` (R6-T13).
- **Не меняются:** `domain/access/policy.py`, `api/v1/tasks.py` (маршруты и `_create_data`/`_patch_data`
  уже различают «не передано» и `null` через `model_fields_set`), сервис проектов (FR-15a).

**Сгенерированные:** `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` —
`bash scripts/gen-api.sh` в R6-T07, R6-T13, R6-T14.

**Фронтенд** (`frontend/src`, новых файлов нет):
- `shared/ui/TextField.tsx`, `shared/ui/Icon.tsx` (`eye`, `eye-off`), `shared/ui/ui.css`
  (`.ui-input-row`, `.ui-reveal`) — R6-T01; `.ui-required` — R6-T10.
- `features/auth/LoginPage.tsx`, `features/auth/ChangePasswordPage.tsx` — R6-T02.
- `features/tasks/TaskPage.tsx` — ссылка на родителя (R6-T03), `SubtaskList` без `alert`
  (R6-T05), `PRIORITIES` (R6-T08), правила FR-23 (R6-T12).
- `features/tasks/SubtaskList.tsx`, `shared/ui/ErrorAlert.tsx` (`FieldError`) — R6-T05.
- `features/tasks/CreateTaskForm.tsx` — `PRIORITIES`/умолчание (R6-T08), `todayMsk`,
  `taskDraftErrors` (R6-T09), форма вкладки (R6-T10), диалог (R6-T11).
- `features/projects/api.ts` (`listAllMembers`), `shared/ui/UserPicker.tsx` (`required`,
  `invalid`, `describedBy`) — R6-T09.
- `features/tasks/TaskList.tsx`, `features/projects/ProjectPage.tsx` — проп `currentUser`
  (R6-T10); `app/router.tsx` — `currentLogin` (R6-T10), пропсы диалога (R6-T11).
- `shared/i18n/ru.ts` — ключи §4.10 (в задачах, где они впервые нужны: R6-T02, R6-T03,
  R6-T05, R6-T08, R6-T09, R6-T10).
- **Не меняются:** `features/boards/BoardView.tsx` (подпись берётся по коду через `t`),
  `TaskList` (таблица — так же), `polling.ts`, `client.ts`, `package.json`.

**Документы:** `docs/data-model.md`, `docs/acceptance/mvp-demo.md`, `docs/adr/0014-task-rules-006.md`
(R6-T15); `specs/001-pilot-r1/spec.md`, `specs/004-no-board-create/spec.md` (R6-T16).

## 4. Интерфейсы

### 4.1. Приоритет и миграция (R6-T07)

```python
# backend/app/domain/tasks/models.py
class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
# __table_args__: CheckConstraint("priority IN ('low','medium','high')", name="priority_valid")

# backend/app/api/v1/schemas/tasks.py
class TaskCreate(BaseModel):  ...; priority: TaskPriority = TaskPriority.MEDIUM
class TaskUpdate(BaseModel):  ...; priority: TaskPriority = Field(default_factory=lambda: TaskPriority.MEDIUM)

# backend/app/domain/tasks/service.py
@dataclass(frozen=True)
class TaskCreateData: ...; priority: str | TaskPriority = TaskPriority.MEDIUM.value
# _validate: сообщение «Приоритет: low, medium или high»

# backend/app/domain/ops/demo.py
_REGULAR_PRIORITY: Final[str] = TaskPriority.MEDIUM.value   # было TaskPriority.BASE.value (задачи и подзадачи)
```

```python
# backend/migrations/versions/0007_three_priorities.py
revision = "0007"; down_revision = "0006"
_CHECK = "ck_task_priority_valid"
_PRIORITIES_006 = "priority IN ('low','medium','high')"
_PRIORITIES_001 = "priority IN ('base','high')"
def upgrade() -> None:   # LOCK → drop CHECK → UPDATE base→medium → create CHECK (op.f(_CHECK))
def downgrade() -> None: # LOCK → drop CHECK → UPDATE low,medium→base → create CHECK
```

Тестовые фабрики: `tests/factories.py::make_task(priority="medium")`.

### 4.2. Создание и изменение задачи (R6-T13, R6-T14)

```python
# backend/app/core/errors.py, ErrorCode
due_date_in_past = "due_date_in_past"

# backend/app/domain/tasks/service.py
def _effective_assignee(actor: Actor, data: TaskCreateData, *, top_level: bool) -> UUID | None:
    """Не передан: задача — создатель (006/FR-17, D-4); подзадача — «Пользователь» сам, БА — None."""

def _check_top_level(values: Mapping[str, Any], today: date) -> None:
    """006/FR-15…FR-17, FR-23. Проверяет только присутствующие ключи:
    description — не пусто после str.strip() (иначе 422 validation_error);
    due_date — не None (иначе 422 validation_error);
    assignee_id — не None (иначе 422 validation_error);
    due_date < today — 422 due_date_in_past. Сначала все проверки validation_error, потом срок."""

async def create_task(db, actor, project_id, data) -> UUID:
    # 404 проект -> FOR SHARE -> assignee = _effective_assignee(..., top_level=True)
    # -> can_create_task (403) -> _validate(data) (422) ->
    # _check_top_level({"description": data.description, "due_date": data.due_date,
    #                   "assignee_id": assignee}, today_msk()) -> _check_assignee (422 коды получателя) -> запись

async def create_subtask(...):  # _effective_assignee(..., top_level=False); _check_top_level НЕ вызывается (FR-24)

def _authorize(actor, project, task, changed) -> None:
    # как сейчас (права -> _validate) + если task.parent_id is None: _check_top_level(changed, today_msk())
```

Поведение API (тело `POST /projects/{id}/tasks`, схема без изменений, `required: ["title"]`):

| Вход | Ответ |
|---|---|
| нет прав / не участник / ТА | 403 (раньше любых проверок полей); нет проекта — 404 |
| `description` нет, `""`, пробельное | 422 `validation_error` |
| `due_date` нет или `null` | 422 `validation_error` |
| `due_date` не `YYYY-MM-DD` или некорректная дата | 422 `validation_error` (схема, как 001/AC-68) |
| `due_date < today_msk()` | 422 `due_date_in_past` |
| `assignee_id` нет | исполнитель — создатель |
| `assignee_id: null` от БА | 422 `validation_error`; от «Пользователя» — 403 |
| `priority` нет | `medium`; `base`/иное — 422 (схема) |

`PATCH /tasks/{id}` у задачи без родителя: в `changed` `assignee_id: null`, `due_date: null`,
пробельное `description` → 422 `validation_error`; `due_date < today` → 422 `due_date_in_past`;
задача не меняется ни в одном поле (всё или ничего, как сейчас). У подзадачи — без изменений.

### 4.3. Прогресс (R6-T06)

```python
# backend/app/domain/tasks/progress.py
def progress(*, done: int, in_work: int, total: int) -> int | None:
    """006/FR-30: ⌊(100·done + 50·in_work) / total⌋; None, если total == 0."""

# queries.get_task:  done = #DONE, in_work = #(IN_PROGRESS|REVIEW), total = len(subs)
# boards/service.py: subs-агрегат + func.count().filter(Task.status.in_(("in_progress","review"))).label("in_work")
```

### 4.4. Кнопка показа пароля (R6-T01, R6-T02)

```ts
// frontend/src/shared/ui/TextField.tsx
export interface TextFieldReveal {
  /** Постоянное доступное имя из словаря (006/D-6). */
  label: string;
  shown: boolean;
  onToggle: () => void;
}
export interface TextFieldProps { /* прежние поля */ reveal?: TextFieldReveal }
// type === "password" && reveal: input type = shown ? "text" : "password";
// autoComplete, autoCapitalize="off", spellCheck=false, aria-describedby (подсказка) не зависят от shown (FR-7).
```

Разметка:
```
div.ui-field
  label[for=id]
  div.ui-input-row                      (только при reveal)
    input#id
    button[type=button].ui-reveal[aria-pressed=true|false][aria-label=reveal.label][disabled=disabled]
      svg.ui-icon[aria-hidden=true]     (Icon "eye" при shown=false, "eye-off" при shown=true)
  span#id-hint.ui-hint                  (если hint)
```
`Icon.tsx`: `IconName` += `"eye" | "eye-off"`, `PATHS`: глаз — контур и зрачок; перечёркнутый —
тот же глаз + диагональ (`M3 3l18 18`). `ui.css`: `.ui-input-row { display: flex; gap: 8px;
align-items: center; }`, `.ui-input-row input { flex: 1; min-width: 0; }`,
`.ui-reveal { min-width: 24px; min-height: 24px; padding: 4px 10px; }` — без цветов и
`font-size`.

Экраны: `LoginPage` — `const [shown, setShown] = useState(false)`; в начале `onSubmit` —
`setShown(false)`. `ChangePasswordPage` — три состояния, в начале `onSubmit` все `false`.
Ключи: `auth.show_password` «Показать пароль», `auth.show_current_password` «Показать текущий
пароль», `auth.show_new_password` «Показать новый пароль», `auth.show_confirm_password`
«Показать повтор нового пароля». В `ChangePasswordPage` кнопки «глазка» попадают в ловушку Tab
окна автоматически (селектор `button` уже есть).

### 4.5. Правила черновика задачи во фронтенде (R6-T09)

```ts
// frontend/src/features/tasks/CreateTaskForm.tsx
/** 006/D-11: «сегодня» по Europe/Moscow, YYYY-MM-DD; не зависит от пояса браузера. */
export function todayMsk(now?: Date): string;

export type DraftField = "title" | "description" | "due_date" | "assignee";
/** Порядок полей в формах: первое неверное получает фокус (FR-19). */
export const DRAFT_FIELDS: readonly DraftField[]; // ["title", "description", "due_date", "assignee"]
export type DraftErrors = Partial<Record<DraftField, MessageKey>>;

/**
 * 006/FR-19, FR-23. Проверяет только переданные ключи:
 * title       — trim() === ""        → "tasks.error_title_required"
 * description — trim() === ""        → "tasks.error_description_required"
 * dueDate     — ""                   → "tasks.error_due_required"; < today → "tasks.error_due_past"
 * assigneeId  — null                 → "tasks.error_assignee_required" (undefined — не проверяется)
 */
export function taskDraftErrors(
  draft: { title?: string; description?: string; dueDate?: string; assigneeId?: string | null },
  today: string,
): DraftErrors;
```

```ts
// frontend/src/features/projects/api.ts
/** Все участники проекта: страницы по 100 до has_next (006 PD-15). */
export async function listAllMembers(projectId: string): Promise<ProjectMember[]>;

// frontend/src/shared/ui/UserPicker.tsx — новые необязательные пропсы
required?: boolean;      // aria-required="true" у combobox
invalid?: boolean;       // aria-invalid="true"
describedBy?: string;    // aria-describedby
```

```tsx
// frontend/src/shared/ui/ErrorAlert.tsx (R6-T05)
/** Сообщение у поля: role="alert", фокус не забирает (006/FR-19, FR-28). */
export function FieldError({ id, message }: { id: string; message: string | null }): JSX.Element | null;
```

### 4.6. Форма вкладки «Задачи» (R6-T10)

```ts
export interface CreateTaskFormProps {
  projectId: string;
  canPickAssignee: boolean;
  assigneeIds: readonly string[];
  /** 006/FR-19: исполнитель по умолчанию; строка «Исполнитель: <логин>» у «Пользователя». */
  currentUser: { id: string; login: string };
}
// ProjectTaskListProps += currentUser; ProjectPage props += currentLogin: string;
// router.tsx: <ProjectPage currentUserId={profile.id} currentLogin={profile.login} currentRole={profile.role} />
```
Поведение:
- Состояние: `title ""`, `description ""`, `dueDate = todayMsk()`, `priority "medium"`,
  `assignee = currentUser`, `errors: DraftErrors`. Те же значения после каждого 201 (AC-31).
- Поля «Название задачи», «Описание задачи», «Срок выполнения», «Исполнитель» (у БА) —
  `.ui-required` в подписи и `aria-required="true"`. У «Пользователя» вместо выбора —
  `<p data-field="fixed-assignee">{t("tasks.assignee_fixed", { login })}</p>`.
- У БА: строка «Выбран: <логин>» и «Сбросить» (как сейчас); сброс → `assignee = null`.
- Отправка: `busy` → выход. `errors = taskDraftErrors({title, description, dueDate,
  assigneeId: canPickAssignee ? assignee?.id ?? null : undefined}, todayMsk())`. Есть ошибки →
  показать у полей (`FieldError` + `aria-invalid` + `aria-describedby`), фокус на первое по
  `DRAFT_FIELDS`, запроса нет, общий alert пуст. Иначе тело
  `{ title: title.trim(), description, due_date: dueDate, priority, ...(canPickAssignee ? { assignee_id: assignee.id } : {}) }`.
- 422 `due_date_in_past` → `errors.due_date = "tasks.error_due_past"`, значения сохраняются
  (FR-21). Прочие ошибки — `errorMessage(code)` в существующий `ErrorAlert` формы.
- Тип тела в `features/tasks/api.ts` не меняется: `TaskCreate` (описание, срок, исполнитель —
  необязательные ключи) уже покрывает тело.

### 4.7. Диалог «Новая задача» (R6-T11)

```ts
export interface CreateTaskDialogProps {
  currentProjectId: string | null;
  /** 006/FR-20: исполнитель по умолчанию. */
  currentUser: { id: string; login: string };
  /** 006/FR-20: выбор исполнителя только у БА. */
  canPickAssignee: boolean;
  onClose: () => void;
  onCreated: (task: TaskDetail) => void;
}
// router.tsx, Sidebar: currentUser={{ id: profile.id, login: profile.login }}
//   canPickAssignee={profile.capabilities.includes("task_assign_others")}
```
Разметка состояния «готово»: проект, «Название задачи», «Описание задачи» (`textarea`),
«Срок выполнения» (`input[type=date]`), у БА — `UserPicker` (кандидаты по PD-15) со строкой
выбранного и «Сбросить», у «Пользователя» — строка `tasks.assignee_fixed`; затем «Создать
задачу», «Отмена». Поля приоритета нет. `DIALOG_FOCUSABLE` дополняется `textarea` (иначе Tab
выпадает из окна). Смена проекта → `assignee = currentUser`. Проверка до отправки —
`taskDraftErrors` (+ «проект не выбран» — прежнее `errorMessage("validation_error")` в общем
`ErrorAlert` окна, 004/FR-13). Тело: `{ title, description, due_date, ...(БА ? { assignee_id } : {}) }`
без `priority`. 422 `due_date_in_past` → сообщение у срока. Остальное поведение 004 (загрузка,
ошибки списка, `busy`, Escape, ловушка Tab, `onCreated`) не меняется.

### 4.8. Карточка задачи (R6-T03, R6-T05, R6-T12)

- **Родитель (R6-T03).** При `task.parent_id !== null` в `dl.ui-props` сразу после пары
  «Проект»: `dt` `t("tasks.parent_label")`, `dd[data-field="parent"]` с
  `<Link to={`/tasks/${task.parent_id}`}>{parent.data?.title ?? t("tasks.parent_open")}</Link>`
  (PD-1). Ошибка чтения родителя не попадает в `ErrorAlert` карточки. У задачи без родителя
  строки нет.
- **Подзадачи (R6-T05).** `<SubtaskList task={task} onCreated={...} />` — без `alert` (PD-16).
- **FR-23 (R6-T12)**, только при `task.parent_id === null`:
  - кнопки `clear-assignee` нет;
  - в `onSave` кроме прежней проверки названия: `taskDraftErrors` для **изменённых** полей
    (`description`, если `edits.description !== task.description`; `dueDate`, если
    `edits.due_date !== (task.due_date ?? "")`). Есть ошибки → `FieldError` у поля,
    `aria-invalid`, `aria-describedby`, фокус на первое неверное, запроса нет, `edits`
    сохраняются;
  - ответ PATCH 422 `due_date_in_past` → сообщение у срока, общий alert пуст, `edits` сохраняются;
  - сообщения у полей снимаются при следующем сохранении.
  У подзадачи всё как сейчас (AC-56, последний пункт). Локальная `listAllMembers` заменяется
  импортом из `projects/api.ts`.

### 4.9. Форма подзадачи (R6-T05)

```
section[data-section="subtasks"]
  h2, прогресс, список (как сейчас)
  form[data-form="create-subtask"][noValidate]
    label[for=<id>-name] t("tasks.subtask_title_label")
    input#<id>-name[name=title][aria-invalid?][aria-describedby=<id>-error?]   (ref для фокуса)
    FieldError id=<id>-error                                      (ввод или ответ сервера)
    button[type=submit]
```
`onSubmit`: `busy` → выход; сообщение снимается; `trim()` пусто → «Введите название подзадачи»;
`title.trim().length > 255` → «Название подзадачи — не более 255 символов»; иначе `POST` с
`{ title: name }`. 201 → `setTitle("")`, фокус в поле, `busy=false`, затем `void onCreated()`.
Ошибка → `errorMessage(code)` в `FieldError` секции, название сохраняется. Граница 255 —
по длине обрезанной строки (сервер проверяет длину как введено, а отправляется обрезанное
название).

### 4.10. Словарь (`ru.ts`)

| Ключ | Значение | Задача |
|---|---|---|
| `auth.show_password`, `auth.show_current_password`, `auth.show_new_password`, `auth.show_confirm_password` | §4.4 | R6-T02 |
| `tasks.parent_label`, `tasks.parent_open` | «Родительская задача», «Открыть родительскую задачу» | R6-T03 |
| `tasks.subtask_error_title_required`, `tasks.subtask_error_title_too_long` | «Введите название подзадачи», «Название подзадачи — не более 255 символов» | R6-T05 |
| `tasks.priority.low`, `tasks.priority.medium` (новые), `tasks.priority.high` (остаётся); **удалить** `tasks.priority.base` | «Низкий», «Средний», «Высокий» | R6-T08 |
| `tasks.error_title_required`, `tasks.error_description_required`, `tasks.error_due_required`, `tasks.error_due_past`, `tasks.error_assignee_required` | «Введите название задачи», «Введите описание задачи», «Укажите срок», «Срок не может быть раньше сегодняшнего дня», «Выберите исполнителя» | R6-T09 |
| `tasks.assignee_fixed`, `tasks.required_mark`, `error.due_date_in_past` | «Исполнитель: {login}», «*», «Срок не может быть раньше сегодняшнего дня» | R6-T10 |

Подписи «Описание задачи» (`tasks.description_label`) и «Срок выполнения» (`tasks.due_label`)
уже есть. Если их значения отличаются от текста spec — сообщить `PLAN_ISSUE`, не менять.

## 5. Данные и эксперименты

ML-кода, датасетов, обучения и GPU нет. Seed нужен только генератору демо-данных — он уже
фиксирован (`seed=1` в тестах), и состав демо не меняется (AC-17).

- **Время.** Бэкенд: фикстура `fixed_clock` (`2026-10-13T09:00:00Z` по умолчанию); тесты 006
  ставят `fixed_clock.set(datetime(2026, 10, 20, 9, 0, tzinfo=UTC))` (`CLOCK` spec) и граничные
  моменты AC-23. Доменные тесты, которые вызывают `create_task` напрямую, явно запрашивают
  `fixed_clock` (иначе срок «сегодня» зависит от реальной даты). Фронтенд:
  `vi.useFakeTimers({ toFake: ["Date"] })` или `shouldAdvanceTime: true` +
  `vi.setSystemTime(new Date("2026-10-19T21:30:00Z"))`, пояс среды — `vi.stubEnv("TZ", "UTC")`
  (AC-28, AC-33). Тесты не зависят от реальной даты и пояса CI (NFR-6).
- **Фикстуры API (spec §5):** `P`, `BA1`, `BA2`, `U1`, `U2`, `UB`, `BA3`, `U3`, `TA` строятся
  из `make_api_world` (`tasks_api_support.py`: `ba`, `ba2`, `usr`, `ba3`, `usr2`, `ta`,
  `blocked`) и `extra_user`. `FULL` — константа в новых тестовых модулях: `{"title": "Задача",
  "description": "Описание", "due_date": "2026-10-20"}`.
- **Миграция.** Только тестовая БД `*_test` (гард `assert_test_database_url`), маркер
  `committed`, alembic подпроцессом (`upgrade002_support.alembic_ok`). Цикл: head →
  `downgrade 0006` → вставка строк с `base`/`high` (в т.ч. `deleted_at`) → `upgrade head` →
  проверки → `downgrade 0006` → `upgrade head`. Сбой — `install_failure(on="version")`.
- **Утечки между сплитами** не применимо.

## 6. Тестовая стратегия и трассировка

### 6.1. AC → реализация → тест

| AC | Где реализуется | Тест (уровень) | Задача |
|---|---|---|---|
| AC-1 | `TextField` + `LoginPage` | `features/auth/LoginPage.test.tsx::006_ac1_*` (vitest) | R6-T02 |
| AC-2 | `ChangePasswordPage`; `UsersPage` без изменений | `ChangePasswordPage.test.tsx::006_ac2_*`, `features/admin/UsersPage.test.tsx::006_ac2_*` | R6-T02 |
| AC-3 | `TextField` (`reveal`) | `tests/shared/TextField.test.tsx::006_ac3_*` (новый); `LoginPage.test.tsx::006_ac3_*` | R6-T01, R6-T02 |
| AC-4 | `ChangePasswordPage` | `ChangePasswordPage.test.tsx::006_ac4_*` | R6-T02 |
| AC-5 | `type=button`; Enter в поле | `LoginPage.test.tsx::006_ac5_*` | R6-T02 |
| AC-6 | порядок DOM, `Icon` | `LoginPage.test.tsx::006_ac6_*`, `tests/app/password-modal.test.tsx::006_ac6_*`, `TextField.test.tsx` (иконки разные) | R6-T01, R6-T02 |
| AC-7, AC-8 | сброс `shown` при отправке; размонтирование | `LoginPage.test.tsx`, `ChangePasswordPage.test.tsx`, `password-modal.test.tsx` (`006_ac7_*`, `006_ac8_*`) | R6-T02 |
| AC-9 | `disabled` кнопки = поля | `TextField.test.tsx::006_ac9_*`; экраны `006_ac9_*` | R6-T01, R6-T02 |
| AC-10 | атрибуты поля не зависят от `shown` | `TextField.test.tsx::006_ac10_*`; экраны (сеть: число вызовов `fetch` не меняется) | R6-T01, R6-T02 |
| AC-11 | — | *ручной*: пункт `006/AC-11` в `mvp-demo.md` (R6-T15); статически — `tests/shared/reveal-css.test.ts::006_nfr3_*` (размер `.ui-reveal` ≥ 24px, цвета только `var(--…)`) | R6-T01, R6-T15, R6-T17 |
| AC-12, AC-13 | `TaskPriority`, умолчания | `backend/tests/api/test_priority_006.py` (API) | R6-T07 |
| AC-14, AC-15, AC-54 | миграция 0007 | `backend/tests/db/test_priority_upgrade_006.py` (миграция, `committed`) | R6-T07 |
| AC-16 | `PRIORITIES`, словарь | `frontend/tests/features/tasks/priority-006.test.tsx` (список, Доска, карточка, форма) | R6-T08 |
| AC-17 | `demo.py` | `backend/tests/cli/test_demo_data.py::test_006_ac17_*` | R6-T07 |
| AC-18 | схемы; `gen-api.sh` | `test_priority_006.py::test_006_ac18_*` (перечисление и `default`); существующие `test_fr44_committed_openapi_json_matches_generation`, `infra/test_frontend_api_types.py` | R6-T07 |
| AC-19…AC-25, AC-41 | `service.create_task`, `create_subtask` | `backend/tests/api/test_required_fields_006.py` (API) | R6-T13 |
| AC-26, AC-27 | `service._authorize` | `backend/tests/api/test_task_update_006.py` (API) | R6-T14 |
| AC-28…AC-32 | `CreateTaskForm` | `frontend/tests/features/tasks/CreateTaskForm.test.tsx` (`006_ac28…32_*`); функции — `tests/features/tasks/draft-rules.test.ts` (R6-T09) | R6-T09, R6-T10 |
| AC-32 (диалог), AC-33 | `CreateTaskDialog` | `CreateTaskDialog.test.tsx`, `CreateTaskDialogSubmit.test.tsx` (`006_ac32_*`, `006_ac33_*`) | R6-T11 |
| AC-34 | `UserPicker` + кандидаты | существующие тесты выбора (без правок) + `CreateTaskDialog.test.tsx::006_ac34_*` | R6-T10, R6-T11 |
| AC-35 | — | *ручной* (`mvp-demo.md`, `006/AC-35`) | R6-T15, R6-T17 |
| AC-36, AC-37 | `SubtaskList` | `frontend/tests/features/tasks/SubtaskSequence.test.tsx` (новый; написан до исправления) | R6-T04, R6-T05 |
| AC-38…AC-40 | `SubtaskList`, `FieldError` | `SubtaskList.test.tsx::006_ac38…40_*` | R6-T05 |
| AC-42 | — | *ручной* (`mvp-demo.md`, `006/AC-42`) | R6-T15, R6-T17 |
| AC-43, AC-44 | `progress`, `get_task`, Доска | `backend/tests/unit/test_progress.py` (таблица AC-43), `backend/tests/api/test_progress_006.py` (API, карточка = Доска) | R6-T06 |
| AC-45 | без изменений (предупреждение по `status !== "done"`) | API: `test_progress_006.py::test_006_ac45_*`; фронтенд: `frontend/tests/features/tasks/progress-006.test.tsx::006_ac45_*` | R6-T06 |
| AC-46 | без изменений (текст `{percent}%`) | `progress-006.test.tsx::006_ac46_*` (карточка и Доска) | R6-T06 |
| AC-47…AC-51 | `TaskPage` (PD-1) | `frontend/tests/features/tasks/ParentLink.test.tsx` (новый) | R6-T03 |
| AC-52 | `ru.ts` | `frontend/tests/shared/i18n.test.ts::006_ac52_*` (все строки NFR-2, нет «Обычный» и `tasks.priority.base`, `errorMessage("due_date_in_past")`) | R6-T12 |
| AC-53 | — | команды NFR-7; `backend/tests/arch/test_dependencies_allowlist.py`; сверка тестов с `96c6d3b` | R6-T17 |
| AC-55 | — | *ручной* (`mvp-demo.md`) | R6-T15, R6-T17 |
| AC-56 | `TaskPage` FR-23 | `frontend/tests/features/tasks/TaskPageRules006.test.tsx` (новый) | R6-T12 |

### 6.2. Старые тесты, которые переписываются (NFR-5)

Правило: тест снятого поведения переписывается в том же файле на критерий 006 (AC в имени
`006_acN_*`/`test_006_acN_*` или в комментарии); удаление — только если заменитель уже есть и
назван в комментарии. Помощники, создающие задачи только с названием, дополняются
обязательными полями — это не ослабление. Поле «Старые тесты → AC» каждой задачи сверяет
ревьюер.

| Файл | Что меняется | Задача |
|---|---|---|
| `backend/tests/unit/test_progress.py` | вызовы `progress(done, total)` → ключевые аргументы; ожидания по таблице AC-43 | R6-T06 |
| `backend/tests/api/test_tasks.py` | `test_ac7_progress_floor_deleted_excluded_and_review_not_closed` → «На проверке» даёт 50 (AC-43/AC-45) | R6-T06 |
| `backend/tests/api/test_board.py`, `test_board_move.py`, `test_subtasks.py`, `backend/tests/domain/test_tasks_queries.py` | ожидаемые значения прогресса со статусами `in_progress`/`review` | R6-T06 |
| `backend/tests/factories.py` | `make_task(priority="medium")` | R6-T07 |
| `backend/tests/db/test_r11_models.py` | множество `TaskPriority`; допустимые `low/medium/high`, недопустимые `""`, `base`, `normal`, `HIGH` | R6-T07 |
| `backend/tests/api/test_tasks.py` | `priority == "base"` (AC-49) → `medium`; перечисление в OpenAPI → `{low, medium, high}`; `("priority", "base")` в правке | R6-T07 |
| `backend/tests/api/test_subtasks.py`, `backend/tests/domain/test_tasks_create.py`, `test_tasks_update_delete.py` | `base` → `medium` | R6-T07 |
| `backend/tests/upgrade002_support.py`, `backend/tests/db/test_three_roles_demo_upgrade.py` (+ `test_three_roles_upgrade.py`, `test_three_roles_after_upgrade.py`, `test_login_display_upgrade.py` — если падают) | PD-18 | R6-T07 |
| `backend/tests/cli/test_demo_data.py` | приоритеты демо | R6-T07 |
| фронтенд: `tasks/helpers.tsx`, `boards/helpers.tsx`, `taskpage-helpers.tsx`, `CreateTaskForm.test.tsx`, `TaskPage.test.tsx`, `TaskList.test.tsx`, `BoardView.test.tsx`, `CreateTaskDialog.test.tsx`, `app/create-task-button.test.tsx` | `"base"` → `"medium"`, `ru["tasks.priority.base"]` → `medium`, варианты `["low","medium","high"]` | R6-T08 |
| `frontend/tests/features/tasks/SubtaskList.test.tsx`, контракт `taskpage-helpers.tsx` («не более одного `role=alert`», пустое название → `validation_error` в общей области) | FR-27, FR-28: сообщение в секции, свой текст | R6-T05 |
| `frontend/tests/features/tasks/CreateTaskForm.test.tsx`, `TaskList.test.tsx`, `features/projects/ProjectPage.test.tsx` | умолчания (срок, исполнитель), пустые описание/срок больше не «необязательные», сообщения у полей | R6-T10 |
| `CreateTaskDialog.test.tsx`, `CreateTaskDialogSubmit.test.tsx`, `create-dialog-helpers.tsx`, `tests/app/create-task-button.test.tsx` | 004/AC-14, AC-23, AC-25 и сценарии «только название» (раздел 9.2 spec) | R6-T11 |
| `TaskPage.test.tsx`, `taskpage-helpers.tsx` | `clear-assignee` у задачи верхнего уровня → у подзадачи; PATCH `due_date: null` у задачи → у подзадачи или AC-56 | R6-T12 |
| `backend/tests/api/test_tasks.py` (создание: `test_ac49_ac24_create_minimal_body_defaults_and_shape`, `test_ac109_ac56_ba_without_assignee_or_with_null_get_null`, `test_ac109_user_*`, `test_ac9_*`, `test_ac68_d51_*`, `test_ac108_*`, `_create`), `test_ba_tasks_002.py`, `test_soft_delete.py`, `test_not_found_vs_forbidden.py`, `backend/tests/domain/test_tasks_create.py` (`_data`), `backend/tests/api/test_errors.py` (каталог кодов дополняется) | FR-15…FR-17: тела дополняются `description`/`due_date` при фиксированных часах; «БА без исполнителя → null» → «→ сам» (AC-19), «БА с null → 201» → 422 (AC-20) | R6-T13 |
| `backend/tests/api/test_tasks.py` (`test_patch_null_due_date_and_null_assignee_clear_the_values`, `test_ac68_d51_patch_*`), `backend/tests/domain/test_tasks_update_delete.py` | снятие у задачи верхнего уровня → 422 (AC-27); прежняя проверка «снимает значение» переносится на подзадачу | R6-T14 |

## 7. Зависимости

Новых пакетов нет (NFR-7, AC-53). `frontend/package.json`, `frontend/package-lock.json`,
`backend/pyproject.toml` не меняются.

## 8. Порядок поставок (коммитов)

| Коммит | Задачи | Состояние продукта после коммита |
|---|---|---|
| 1 | R6-T01 | `TextField` умеет «глазок», экраны ещё не используют |
| 2 | R6-T02 | п. 1 готов |
| 3 | R6-T03 | п. 8 готов |
| 4 | R6-T04 + R6-T05 | п. 6 готов (тест воспроизведения и исправление — вместе) |
| 5 | R6-T06 | п. 7 готов (API не меняется) |
| 6 | R6-T07 + R6-T08 | п. 2 готов (БД, API, типы, интерфейс) |
| 7–10 | R6-T09, R6-T10, R6-T11, R6-T12 | формы шлют полные тела и проверяют ввод; старый сервер их принимает |
| 11 | R6-T13 | сервер требует поля при создании (пп. 3–4) |
| 12 | R6-T14 | сервер запрещает снятие полей изменением (Q-2 б) |
| 13–14 | R6-T15, R6-T16 | документы |

**Ранний выпуск** (по желанию владельца): коммиты 1–4 (только фронтенд) и 5 (только бэкенд,
без миграции и изменения API). Второй выпуск — 6–14. Нельзя выпускать R6-T13 без R6-T10 и
R6-T11 (диалог и форма отправляли бы тело, которое сервер отклонит).

Критический путь: R6-T07 → R6-T08 → R6-T09 → R6-T10 → R6-T11 → R6-T13 → R6-T15 → R6-T17
(R6-T12 → R6-T14 — параллельная ветка после R6-T10; R6-T01…R6-T06 — до R6-T07, независимы).

## 9. Риски и план Б

- **RK-1. Ошибка п. 6 не воспроизводится автотестом.** Гипотезы для R6-T04 (проверять по
  порядку): (1) `busy` в `SubtaskList` держится до конца перечитывания карточки (`await
  onCreated()`), и отправка во время медленного перечитывания молча теряется — AC-37 вариант 2;
  (2) общий `alert` карточки показывает чужое или устаревшее сообщение (правка полей, опрос,
  участники) «над статусом»; (3) ввод теряется при перерисовке карточки после опроса — AC-37
  вариант 1; (4) пустое поле после очистки отправляется повторным Enter и даёт
  `validation_error` в общей области. **План Б:** если ни AC-36, ни AC-37 не красные, R6-T04
  возвращает отчёт `NOT_REPRODUCED` с перечнем проверенных гипотез; оркестратор просит
  владельца воспроизвести по AC-42 (браузер, роль, шаги, вкладка Network); R6-T05 всё равно
  реализует FR-26…FR-29 (они — требования spec, а не только исправление) и оставляет тесты
  AC-36/AC-37 как регрессионные. Spec не меняется (раздел 7 spec).
- **RK-2. Миграция 0007 ломает миграционные тесты 002** (данные схемы 0005 и снимки `task`).
  Решение — PD-18. **План Б:** в тестах 002 сравнение снимков после `upgrade 0006`, затем
  `upgrade head` перед HTTP-шагами; решение фиксируется в отчёте R6-T07, ассерты не ослабляются.
- **RK-3. Объём переписывания бэкенд-тестов в R6-T13** (создание задач только с названием).
  Смягчение: централизованные помощники (`_create` в `test_tasks.py`, `_data` в
  `test_tasks_create.py`, `FULL`). **План Б:** разделить R6-T13 на R6-T13a (сервис + доменные
  тесты) и R6-T13b (API-тесты), коммит — после обеих.
- **RK-4. Рассинхрон поставок «диалог ↔ сервер».** Если R6-T13 окажется готов раньше R6-T10/R6-T11,
  его не коммитить до них (порядок §8). **План Б:** держать R6-T13 в рабочем дереве.
- **RK-5. Связка R6-T07 + R6-T08.** После R6-T07 фронтенд не проходит `typecheck`
  (перечисление в `schema.d.ts`). Коммит только после R6-T08. **План Б:** если R6-T08 не
  проходит ревью, откатить R6-T07 (`git restore`), не коммитить половину.
- **RK-6. Время и пояс в тестах.** Тест, забывший `fixed_clock` или `setSystemTime`, станет
  нестабильным около полуночи. Смягчение: явные моменты из spec; ревьюер проверяет каждый тест
  с датами. **План Б:** общий помощник в тестовом модуле, не в `conftest.py`.
- **RK-7. Несколько `role="alert"` на экране.** Старый контракт `taskpage-helpers.tsx` («не
  более одного alert») противоречит FR-19/FR-28. Spec — источник истины: контракт
  переписывается в R6-T05/R6-T12 с пометкой AC.
- **RK-8. Лишний запрос `GET /tasks/{parent}`** в тестах карточки подзадачи с точным набором
  маршрутов: неизвестный маршрут → `network_error` → ссылка-заглушка (без alert), тесты
  поведения не ломаются. Если тест считает все вызовы `fetch` — добавить маршрут родителя в
  `cardRoutes` (R6-T03).
- **RK-9. Статические CSS-тесты** (`theme.test.ts`, `typography.test.ts`, `create-button.test.ts`):
  новые правила — без `font-size`, цвета только `var(--…)`. **План Б:** при конфликте с
  тестом темы — убрать правило и опереться на стиль `button` по умолчанию.
- **RK-10. Белый список файлов `frontend/src`.** План новых файлов не требует. Если исполнитель
  решит, что без нового файла нельзя, — `PLAN_ISSUE`; правка
  `test_t21_src_files_only_expected` — только решением владельца (отдельная задача с
  обоснованием).
- **RK-11. Граница 255 символов у подзадачи.** Клиент проверяет длину обрезанной строки, сервер
  — как получено (обрезанной). Совпадает; если тест AC-39 подаёт строку с пробелами по краям —
  ожидание по обрезанной длине.

## 10. Замечания к spec (не блокируют plan)

Противоречий, требующих остановки, не найдено. Неполнота и уточнения:

- **З-1.** В шапке spec «Статус: APPROVED-кандидат (… ждёт утверждения владельцем)», а
  оркестратор сообщает об утверждении 2026-10-20. Строку статуса обновляет оркестратор
  (архитектор spec не меняет).
- **З-2.** Spec не упоминает ADR, а AGENTS.md требует запись в `docs/adr/` для ломающих
  изменений API (коды приоритета, обязательные поля). План добавляет ADR-0014 (PD-20, R6-T15).
- **З-3.** NFR-1 называет «новый код ошибки» частью OpenAPI, но каталог кодов в OpenAPI не
  перечисляется. Код упоминается в описании схем `TaskCreate`/`TaskUpdate` (PD-9).
- **З-4.** FR-32 «текущее название родителя» понимается как название на момент открытия
  карточки подзадачи (PD-1): отдельного опроса названия нет. Если владельцу нужно обновление по
  опросу — отдельная доработка.
- **З-5.** Раздел 9.3 spec перечисляет не все затрагиваемые тесты: дополнительно
  `backend/tests/upgrade002_support.py`, `db/test_three_roles_*.py`, `api/test_soft_delete.py`,
  `api/test_not_found_vs_forbidden.py`, `api/test_errors.py`, `features/admin/UsersPage.test.tsx`
  (§6.2).
- **З-6.** Контракт тестов карточки «на странице не более одного `role=alert`» (T84) снимается
  FR-19/FR-28 (RK-7).

## 11. Документы и спецификации (R6-T15, R6-T16)

- `docs/data-model.md`, строка `priority`: «`low`, `medium`, `high`; `CHECK`
  `ck_task_priority_valid`; миграция 0007: `base` → `medium`».
- `docs/acceptance/mvp-demo.md`: UF-4 (стр. 46–47) — «прогресс растёт с весами: "В работе" и
  "На проверке" — 50 %, "Выполнена" — 100 % (006/FR-30); подзадача "На проверке" закрытой не
  считается (предупреждение при закрытии родителя)»; стр. 83–84 — создание задач с описанием,
  сроком и исполнителем; новые пункты `- [ ] 006/AC-11`, `006/AC-35`, `006/AC-42`, `006/AC-55`.
  `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` должен остаться зелёным.
- `docs/adr/0014-task-rules-006.md` — по `docs/adr/TEMPLATE.md` (PD-20).
- `specs/001-pilot-r1/spec.md` — история версий v0.20 «пп. 1–8 баг-репорта Ч1 — дельта
  006/FR-1…FR-37» и правки по таблице 9.1 spec 006 (номера 001 не меняются).
- `specs/004-no-board-create/spec.md` — история версий v0.3 и правки по таблице 9.2 spec 006.
- Release notes не нужны (поручение оркестратора).
