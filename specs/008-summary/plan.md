# Plan: «Сводка» (008-summary), короткая версия F1a–F1d

- **Spec:** ./spec.md (статус DRAFT, короткая версия). Открытые вопросы спеки §8 помечены **[Q-n]**
  и остаются открытыми; при другом ответе меняется помеченное.
- **Статус:** DRAFT
- **Оценка:** ~2,5 дня разработки + ревью (разбивка — в tasks.md).

## 1. Подход
Новый модуль чтения `domain/overview/queries.py` строит одну базовую выборку «задачи сводки»
(неудалённые задачи и подзадачи неудалённых проектов пространства, где актор владелец или участник) и поверх
неё: счётчики (`GROUP BY status` + `COUNT FILTER` для «Нужно проверить» — один запрос) и страницу списка
с фильтрами (проект, статус, приоритет, пресет срока). Границы пресетов считает чистая функция от
`today_msk()`; в SQL идут готовые даты. Роутер `api/v1/overview.py` — схема → вызов сервиса → схема.
Фронт — `features/overview/` с хуками TanStack Query и опросом `POLL_INTERVAL_MS`.
Миграций нет. Индекс — только по итогам замера T-10 (номер `0011+` по REGISTRY).

## 2. Решения
| Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---|---|---|
| PS-1 Членство | `Project.owner_id == me OR EXISTS(project_member)`, как `list_my_tasks` | JOIN на `project_member` | без дублей строк, тот же предикат, что в R1 |
| PS-2 Счётчики | один SELECT: `COUNT(*) FILTER (WHERE status=…)` ×4 + `needs_review` | 5 запросов; COUNT на клиенте | NFR-1, один проход по индексу |
| PS-3 Даты пресетов | `due_condition(preset, today)` в домене, чистая функция | `now()` в SQL | ADR-0007: сегодня — Europe/Moscow, тестируется `FixedClock` |
| PS-4 Количество M | ответ списка = `Page` + `total` (отдельный `COUNT(*)` с теми же фильтрами) | без total | FR-9 требует M; новый эндпоинт, ломающих изменений нет |
| PS-5 «Горит» | поле `hot: bool` в ответе: `priority = 'high' AND due_date <= today AND status <> 'done'` **[Q-18]** | расчёт на фронте; включать `done` | одно «сегодня» на сервере (ADR-0007); D-3 + Q-3 |
| PS-6 Статус и пресет | `status` — одно значение **[Q-7]**; пресет — один **[Q-7]**; `needs_review=true` — отдельный флаг | спец-значение статуса | флаг не смешивается со статусом и сочетается с ним |
| PS-7 Сортировка | `due_date ASC NULLS LAST, id` (Q-6 задачного списка — решено) | выбор колонки | минимум для R2 |
| PS-8 Подзадачи | входят (Q-1 задачного списка — решено) | только верхний уровень | как «Мои задачи» |
| PS-9 Плитки | без учёта фильтров (Q-2 задачного списка — решено) | с фильтрами | стабильный ориентир |
| PS-10 «Неделя» | `сегодня ≤ due ≤ воскресенье` — текст как есть; вариант пн–вс **[Q-4]** | — | прошедшие дни уже в «Просрочено», без пересечения пресетов |

## 3. Затрагиваемые модули и файлы
- `backend/app/domain/overview/__init__.py`, `queries.py`, `due.py` — новые: выборка, счётчики, пресеты.
- `backend/app/api/v1/overview.py`, `backend/app/api/v1/schemas/overview.py` — новые; подключение в
  `api/v1/__init__.py`. Эндпоинты: `/me/overview` и `/me/overview/tasks`.
- `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` — через `scripts/gen-api.sh`.
- `frontend/src/features/overview/SummaryPage.tsx`, `api.ts`, `filters.ts` — новые;
  `app/router.tsx` (маршрут `/summary`, пункт меню), `shared/i18n/ru.ts`, `shared/ui/ui.css`.
- `backend/tests/infra/test_frontend_scaffold.py` — белый список новых файлов фронта.
- Тесты: `backend/tests/api/test_008_overview.py`, `backend/tests/unit/test_008_due.py`,
  `frontend/src/features/overview/SummaryPage.test.tsx`.

## 4. Интерфейсы
```python
class DuePreset(StrEnum): OVERDUE="overdue"; TODAY="today"; TOMORROW="tomorrow"; WEEK="week"; NONE="none"

def due_condition(preset: DuePreset | None, today: date) -> ColumnElement[bool] | None: ...  # «неделя» — [Q-4]
def is_hot(priority: str, due: date | None, status: str, today: date) -> bool: ...          # status != 'done' [Q-18]

@dataclass(frozen=True)
class OverviewCounts: total: int; todo: int; in_progress: int; review: int; done: int; needs_review: int

@dataclass(frozen=True)
class OverviewFilter:
    project_id: UUID | None; status: TaskStatus | None; priorities: frozenset[TaskPriority]
    due: DuePreset | None; needs_review: bool                                 # status — одно значение [Q-7]

async def overview_counts(db, actor) -> OverviewCounts: ...
async def overview_tasks(db, actor, f: OverviewFilter, params: PageParams
                         ) -> tuple[list[OverviewItem], bool, int]: ...
```
HTTP:
- `GET /api/v1/me/overview` → `{total, todo, in_progress, review, done, needs_review}`.
- `GET /api/v1/me/overview/tasks?project_id&status&priority=…&due=&needs_review&page&page_size`
  → `{items:[{id, title, project:{id,name}, parent_id, status, priority, due_date, assignee, created_at, updated_at, hot}], page, page_size, has_next, total}`.
- Ошибки: 401; 403 (`forbidden`: нет `business_access`); 404 (`project_id` не мой); 422 (валидация: `priority`, `due`).

## 5. Данные
Синтетические фабрики `backend/tests/factories.py`; часы — `use_clock(FixedClock(...))`. Для «Горит» и
пресетов — задачи с приоритетами `high`/`medium`, сроками вчера, сегодня, завтра, без срока и в `done`.

## 6. Тестовая стратегия и трассировка
| AC | Где | Тест |
|---|---|---|
| AC-1, AC-2, AC-3 | `overview_counts` | API `test_008_overview.py` |
| AC-4, AC-5, AC-9, AC-11 | `overview_tasks`, схема | API |
| AC-6, AC-7 | `due.py` | unit `test_008_due.py` (граница суток, неделя, понедельник) + API |
| AC-8 | `is_hot` | unit + API (включая `done`) |
| AC-10 | роутер, `get_active_actor`, `load_project_facts` | API |
| AC-12, AC-13 | `SummaryPage` | vitest + ручная проверка `docs/acceptance/mvp-demo.md` |
| AC-14 | — | спека 016 (T-10) |

## 7. Зависимости
- Новых внешних зависимостей нет.
- Миграций нет. Если замер T-10 покажет нужду в индексе — номер `0011+` по REGISTRY.
- От карточки ИИ-агента (T-13, R3) и токенов (T-11) спека 008 не зависит. Облачный шлюз (ADR-0022) не влияет.

## 8. Риски и открытые вопросы
**Риски**
- `total` на 50 000 задач добавляет второй COUNT: если p95 > 500 мс — индекс
  `(workspace_id, project_id, status, due_date) WHERE deleted_at IS NULL` в миграции R2 по итогам T-10.

**Открытые вопросы (открыто; план на них не отвечает)**
- **Q-4** («На этой неделе»: сегодня–вс или пн–вс) — открыто; PS-10.
- **Q-7** (статус и пресет: одно значение или мультивыбор) — открыто; PS-6.
- **Q-8** (самоисполнитель в «Нужно проверить») — открыто; FR-3 спеки.
- **Q-9** (P-S1: положение и акцент плитки «Нужно проверить») — открыто; блокирует S08-T04.
- **Q-10** (стартовый экран «Сводка») — открыто; вне плана.
- **Q-11** (фильтр по исполнителю) — открыто; вне рамок.
- **Q-14** (`done` в «Сегодня», «Завтра», «На этой неделе») — открыто; блокирует часть S08-T01.
- **Q-18** (исключение `done` из «Горит») — открыто; PS-5.

Ответы на открытые Q-n меняют PS-5, PS-6, PS-10; код и тесты пишутся после статуса APPROVED.
