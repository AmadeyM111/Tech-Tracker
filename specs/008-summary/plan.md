# Plan: «Сводка» (008-summary)

- **Spec:** ./spec.md (APPROVED; ответы §8 совпали с рекомендациями — пометки **[Q-n]** подтверждены)
- **Статус:** APPROVED

## 1. Подход
Новый модуль чтения `domain/overview/queries.py` строит одну базовую выборку «задачи сводки»
(неудалённые задачи неудалённых проектов пространства, где актор владелец или участник) и поверх неё
две операции: счётчики (`GROUP BY status` + `COUNT FILTER` для «Нужно проверить» — один запрос) и
страница списка с фильтрами. Границы дат пресетов считает чистая функция от `today_msk()`; в SQL идут
готовые даты. Роутер `api/v1/overview.py` — схема → вызов сервиса → схема. Фронт — `features/overview/`
с хуками TanStack Query и опросом `POLL_INTERVAL_MS`. Миграций нет: сначала замер (T-10), индекс —
отдельной миграцией R2 (`0011+`), только если замер покажет нужду.

## 2. Решения
| Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---|---|---|
| PS-1 Членство | `Project.owner_id == me OR EXISTS(project_member)`, как `list_my_tasks` | JOIN на `project_member` | без дублей строк, тот же предикат, что в R1 |
| PS-2 Счётчики | один SELECT: `COUNT(*) FILTER (WHERE status=…)` ×4 + `needs_review` | 5 запросов; COUNT на клиенте | NFR-1, один проход по индексу |
| PS-3 Даты пресетов | `due_window(preset, today) -> (op, from, to)` в домене, чистая | `now()` в SQL | ADR-0007: сегодня — Europe/Moscow, тестируется `FixedClock` |
| PS-4 Количество M | ответ списка = `Page` + `total` (отдельный `COUNT(*)` с теми же фильтрами) | без total (D-34) | FR-9 требует M; ломающих изменений нет — новый эндпоинт |
| PS-5 «Горит» | поле `hot: bool` в ответе, считается на сервере; `done` — никогда | расчёт на фронте | одно «сегодня» на сервере (ADR-0007) **[Q-3]** |
| PS-6 Статус в фильтре | `status` — одно значение **[Q-7]**; `needs_review=true` — отдельный флаг | спец-значение статуса | флаг не смешивается со статусом и сочетается с ним |
| PS-7 Сортировка | `due_date ASC NULLS LAST, id` **[Q-6]** | выбор колонки | минимум для R2 |
| PS-8 Подзадачи | входят **[Q-1]** | только верхний уровень | как «Мои задачи» |
| PS-9 Плитки | без учёта фильтров **[Q-2]** | с фильтрами | стабильный ориентир |
| PS-10 «Неделя» | `today ≤ due ≤ воскресенье` **[Q-4]** | пн–вс | без пересечения с «Просрочено» |

## 3. Затрагиваемые модули и файлы
- `backend/app/domain/overview/__init__.py`, `queries.py`, `due.py` — новые: выборка, счётчики, пресеты.
- `backend/app/api/v1/overview.py`, `backend/app/api/v1/schemas/overview.py` — новые; подключение в `api/v1/__init__.py`.
- `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` — через `scripts/gen-api.sh`.
- `frontend/src/features/overview/SummaryPage.tsx`, `api.ts`, `filters.ts` — новые; `app/router.tsx` (маршрут `/summary`, пункт меню), `shared/i18n/ru.ts`, `shared/ui/ui.css` (плитки, пресеты).
- `backend/tests/infra/test_frontend_scaffold.py` — белый список новых файлов фронта.
- Тесты: `backend/tests/api/test_008_overview.py`, `backend/tests/unit/test_008_due.py`,
  `frontend/src/features/overview/*.test.tsx`.

## 4. Интерфейсы
```python
class DuePreset(StrEnum): OVERDUE="overdue"; TODAY="today"; TOMORROW="tomorrow"; WEEK="week"; NONE="none"

def due_condition(preset: DuePreset, today: date) -> ColumnElement[bool]: ...
def is_hot(priority: str, due: date | None, status: str, today: date) -> bool: ...

@dataclass(frozen=True)
class OverviewCounts: total: int; todo: int; in_progress: int; review: int; done: int; needs_review: int

@dataclass(frozen=True)
class OverviewFilter:
    project_id: UUID | None; status: TaskStatus | None; priorities: frozenset[TaskPriority]
    due: DuePreset | None; needs_review: bool

async def overview_counts(db, actor) -> OverviewCounts: ...
async def overview_tasks(db, actor, f: OverviewFilter, params: PageParams) -> tuple[list[OverviewItem], bool, int]: ...
```
HTTP:
- `GET /api/v1/me/overview` → `{total, todo, in_progress, review, done, needs_review}`.
- `GET /api/v1/me/overview/tasks?project_id&status&priority=…&due=&needs_review&page&page_size`
  → `{items:[{id, title, project:{id,name}, parent_id, status, priority, due_date, assignee, hot}], page, page_size, has_next, total}`.
- Ошибки: 401, 403 (`forbidden`, нет `business_access`), 404 (`project_id` не мой), 422 (валидация).

## 5. Данные
Синтетические фабрики `backend/tests/factories.py`; часы — `use_clock(FixedClock(...))`.

## 6. Тестовая стратегия и трассировка
| AC | Где | Тест |
|---|---|---|
| AC-1, AC-2, AC-3 | `overview_counts` | API `test_008_ac1…ac3_*` |
| AC-4, AC-5, AC-9, AC-11 | `overview_tasks`, схема | API |
| AC-6, AC-7 | `due.py` | unit (граница суток, неделя) + API |
| AC-8 | `is_hot` | unit + API |
| AC-10 | роутер, `get_active_actor`, `load_project_facts` | API |
| AC-12, AC-13 | `SummaryPage` | vitest + ручная проверка `docs/acceptance/mvp-demo.md` |
| AC-14 | — | спека 016 |

## 7. Зависимости
Новых нет.

## 8. Риски
- `total` на 50 000 задач добавляет второй COUNT: если p95 > 500 мс — индекс `(workspace_id, project_id, status, due_date) WHERE deleted_at IS NULL` в миграции R2 по итогам T-10.
- Ответы на Q-1…Q-10 меняют PS-5…PS-10; код и тесты пишутся после утверждения spec.
