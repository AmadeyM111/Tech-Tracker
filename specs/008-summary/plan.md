# Plan: «Сводка» (008-summary)

- **Spec:** ./spec.md (статус DRAFT). План исходит из решений владельца 2026-11-08: рекомендации по Q-1…Q-6
  приняты; CSV и диапазон дат — в пакете. Открытые вопросы спеки §8 помечены **[Q-n]**; при другом ответе
  меняется помеченное.
- **Статус:** DRAFT

## 1. Подход
Новый модуль чтения `domain/overview/queries.py` строит одну базовую выборку «задачи сводки»
(неудалённые задачи неудалённых проектов пространства, где актор владелец или участник) и поверх неё:
счётчики (`GROUP BY status` + `COUNT FILTER` для «Нужно проверить» — один запрос), страницу списка с
фильтрами и выборку для CSV (та же выборка без пагинации, с лимитом строк [Q-15]). Границы пресетов и
диапазона считает чистая функция от `today_msk()`; в SQL идут готовые даты. CSV формируется в памяти
(`render_csv` → `bytes`, BOM и «;») и отдаётся одним ответом; объём ограничен лимитом. Потоковая отдача —
только если замер T-10 покажет нужду. Роутер `api/v1/overview.py` — схема → вызов сервиса → схема. Фронт —
`features/overview/` с хуками TanStack Query и опросом `POLL_INTERVAL_MS`. Миграций по умолчанию нет.
Возможные миграции (номер по REGISTRY, `0011+`): расширение CHECK `entity_type` для аудита выгрузки [Q-16]
и индекс — только по итогам замера T-10.

## 2. Решения
| Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---|---|---|
| PS-1 Членство | `Project.owner_id == me OR EXISTS(project_member)`, как `list_my_tasks` | JOIN на `project_member` | без дублей строк, тот же предикат, что в R1 |
| PS-2 Счётчики | один SELECT: `COUNT(*) FILTER (WHERE status=…)` ×4 + `needs_review` | 5 запросов; COUNT на клиенте | NFR-1, один проход по индексу |
| PS-3 Даты пресетов | `due_window(preset, today) -> (op, from, to)` в домене, чистая | `now()` в SQL | ADR-0007: сегодня — Europe/Moscow, тестируется `FixedClock` |
| PS-4 Количество M | ответ списка = `Page` + `total` (отдельный `COUNT(*)` с теми же фильтрами) | без total (D-34) | FR-9 требует M; ломающих изменений нет — новый эндпоинт |
| PS-5 «Горит» | поле `hot: bool` в ответе: `priority = 'high' AND due_date <= today AND status <> 'done'` | расчёт на фронте; включать `done` | одно «сегодня» на сервере (ADR-0007); Q-3 решено |
| PS-6 Статус в фильтре | `status` — одно значение **[Q-7]**; `needs_review=true` — отдельный флаг | спец-значение статуса | флаг не смешивается со статусом и сочетается с ним |
| PS-7 Сортировка | `due_date ASC NULLS LAST, id` (Q-6 решено) | выбор колонки | минимум для R2 |
| PS-8 Подзадачи | входят (Q-1 решено) | только верхний уровень | как «Мои задачи» |
| PS-9 Плитки | без учёта фильтров (Q-2 решено) | с фильтрами | стабильный ориентир |
| PS-10 «Неделя» | `сегодня ≤ due ≤ воскресенье` (Q-4 решено: вариант б) | пн–вс | прошедшие дни уже в «Просрочено», без пересечения пресетов |
| PS-11 Диапазон дат | `due_from`/`due_to` в `OverviewFilter`, границы включительно; `due_from > due_to` → 422 в схеме. Сочетание с пресетом **[Q-12]**; пустая граница **[Q-13]** | диапазон только вместе с пресетом | Q-14 задачного списка: диапазон входит в R2 |
| PS-12 CSV | тот же `overview_tasks` без пагинации; только роль `business_admin` (ADR-0013), иначе 403; `Content-Type: text/csv; charset=utf-8`; BOM, разделитель «;»; `Content-Disposition: attachment`. Лимит строк **[Q-15]**; экранирование ячеек **[Q-17]** | второй запрос под CSV; отдельный сервис выгрузки | одна выборка для списка, `total` и CSV: расхождений между экраном и файлом нет (FR-13) |
| PS-13 Аудит выгрузки | событие в `domain_event` с `in_audit=true`, `actor_id` = БА, `changed_fields='{}'`, без значений полей. Тип сущности и место для числа строк **[Q-16]** | отдельная таблица выгрузок | журнал аудита ADR-0006; выгрузка CSV — новое событие R2 (NFR-06 задачного списка) |

## 3. Затрагиваемые модули и файлы
- `backend/app/domain/overview/__init__.py`, `queries.py`, `due.py` — новые: выборка, счётчики, пресеты, диапазон.
- `backend/app/domain/overview/csv.py` — новый: `render_csv(items) -> bytes` (BOM, «;», экранирование [Q-17]).
- `backend/app/api/v1/overview.py`, `backend/app/api/v1/schemas/overview.py` — новые; подключение в `api/v1/__init__.py`.
  Эндпоинты: два под `/me/overview*` и `/me/overview/tasks.csv`.
- Аудит: запись в `domain_event` через существующий механизм событий. Миграция — только по [Q-16]
  (`backend/migrations/versions/0011_*`, номер по REGISTRY).
- `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` — через `scripts/gen-api.sh`.
- `frontend/src/features/overview/SummaryPage.tsx`, `api.ts` (включая скачивание CSV), `filters.ts`
  (пресеты и диапазон) — новые; `app/router.tsx` (маршрут `/summary`, пункт меню), `shared/i18n/ru.ts`
  (включая «Скачать CSV» и подписи диапазона), `shared/ui/ui.css` (плитки, пресеты, поля диапазона).
- `backend/tests/infra/test_frontend_scaffold.py` — белый список новых файлов фронта.
- Тесты: `backend/tests/api/test_008_overview.py`, `backend/tests/api/test_008_overview_csv.py`,
  `backend/tests/unit/test_008_due.py`, `backend/tests/unit/test_008_csv.py`, `frontend/src/features/overview/*.test.tsx`.

## 4. Интерфейсы
```python
class DuePreset(StrEnum): OVERDUE="overdue"; TODAY="today"; TOMORROW="tomorrow"; WEEK="week"; NONE="none"

def due_condition(preset: DuePreset | None, due_from: date | None, due_to: date | None,
                  today: date) -> ColumnElement[bool] | None: ...   # сочетание и пустые границы — [Q-12], [Q-13]
def is_hot(priority: str, due: date | None, status: str, today: date) -> bool: ...   # status != 'done'
def render_csv(items: list[OverviewItem]) -> bytes: ...               # BOM + «;»; колонки FR-13

@dataclass(frozen=True)
class OverviewCounts: total: int; todo: int; in_progress: int; review: int; done: int; needs_review: int

@dataclass(frozen=True)
class OverviewFilter:
    project_id: UUID | None; status: TaskStatus | None; priorities: frozenset[TaskPriority]
    due: DuePreset | None; due_from: date | None; due_to: date | None; needs_review: bool

async def overview_counts(db, actor) -> OverviewCounts: ...
async def overview_tasks(db, actor, f: OverviewFilter, params: PageParams | None
                         ) -> tuple[list[OverviewItem], bool, int]: ...
# params=None — выборка для CSV: без пагинации, с лимитом строк [Q-15]
```
HTTP:
- `GET /api/v1/me/overview` → `{total, todo, in_progress, review, done, needs_review}`.
- `GET /api/v1/me/overview/tasks?project_id&status&priority=…&due=&due_from=&due_to=&needs_review&page&page_size`
  → `{items:[{id, title, project:{id,name}, parent_id, status, priority, due_date, assignee, created_at, updated_at, hot}], page, page_size, has_next, total}`.
- `GET /api/v1/me/overview/tasks.csv?…` — те же фильтры, без `page`/`page_size`. Ответ `200`, `text/csv; charset=utf-8`.
- Ошибки: 401; 403 (`forbidden`: сводка — нет `business_access`; CSV — роль не БА); 404 (`project_id` не мой); 422 (валидация, включая `due_from > due_to`).

## 5. Данные
Синтетические фабрики `backend/tests/factories.py`; часы — `use_clock(FixedClock(...))`. Для CSV — задачи с
кириллицей, кавычками и `;` в названии, пустым исполнителем и значением, начинающимся с `=` (проверка [Q-17]).

## 6. Тестовая стратегия и трассировка
| AC | Где | Тест |
|---|---|---|
| AC-1, AC-2, AC-3 | `overview_counts` | API `test_008_ac1…ac3_*` |
| AC-4, AC-5, AC-9, AC-11, AC-15 | `overview_tasks`, схема | API |
| AC-6, AC-7 | `due.py` | unit (граница суток, неделя, понедельник) + API |
| AC-8 | `is_hot` | unit + API (включая `done`) |
| AC-10 | роутер, `get_active_actor`, `load_project_facts` | API |
| AC-16, AC-18 | роутер `tasks.csv`, состав выборки | API `test_008_overview_csv.py` |
| AC-17 | `render_csv` | unit (BOM, «;», кодировка) |
| AC-19 | сервис выгрузки, `domain_event` | API |
| AC-12, AC-13 | `SummaryPage` | vitest + ручная проверка `docs/acceptance/mvp-demo.md` |
| AC-14 | — | спека 016 (T-10) |

## 7. Зависимости
- Новых внешних зависимостей нет: CSV — стандартная библиотека.
- Миграции — только по [Q-16] (CHECK `entity_type`) и по итогам T-10 (индекс). Номера — по REGISTRY, `0011+`.
- От T-13 (карточка ИИ-агента) и T-11 (токены) спека 008 не зависит.

## 8. Риски
- `total` на 50 000 задач добавляет второй COUNT: если p95 > 500 мс — индекс `(workspace_id, project_id, status, due_date) WHERE deleted_at IS NULL` в миграции R2 по итогам T-10.
- CSV на большой выборке: размер и время. Лимит строк [Q-15]; замер в T-10 (AC-14).
- CSV-инъекция формул в Excel — [Q-17].
- Ответы на открытые Q-n (spec §8) меняют PS-5…PS-13; код и тесты пишутся после статуса APPROVED.
