# Plan: «Сводка» — диапазон дат (024)

- **Spec:** ./spec.md (DRAFT)
- **Статус:** DRAFT

## 1. Подход
В `domain/overview/due.py` добавляется чистая функция `range_condition(due_from, due_to)`; `OverviewFilter` получает
`due_from`/`due_to`. Взаимоисключение с пресетом и порядок дат проверяются в схеме запроса (`OverviewTaskQuery`,
`model_validator`) — 422 тем же `validation_error`, что и остальные ошибки параметров. Фронт: `SummaryFilters` расширяется
двумя полями, обработчики пресета и диапазона очищают друг друга; валидация «с ≤ по» на клиенте не отправляет запрос.
Миграций и новых эндпоинтов нет.

## 2. Решения
| Решение | Выбрано | Отвергнутые | Почему |
|---|---|---|---|
| PD-1 Параметры | `due_from`, `due_to` (даты) в `/tasks` | `due=range:a..b`; отдельный эндпоинт | типизированные параметры, OpenAPI и тесты проще, как у остальных фильтров |
| PD-2 Конфликт | 422 при `due` вместе с диапазоном | молча приоритет пресета | «последний победил» скрывает ошибку клиента (как с повтором параметров 008) |
| PD-3 Границы | `due_date >= from`, `due_date <= to` над типом `date` | сравнение по UTC-времени | срок хранится датой (ADR-0007), часовой пояс нужен только «сегодня» |
| PD-4 Ввод | нативный `<input type="date">` | своя маска/календарь | доступность, 44 px, без зависимостей |
| PD-5 Ошибка | клиентская проверка + серверный 422 | только сервер | мгновенная обратная связь по макету, защита на сервере остаётся |

## 3. Затрагиваемые файлы
- `backend/app/domain/overview/due.py`, `queries.py` — `range_condition`, поля фильтра.
- `backend/app/api/v1/schemas/overview.py`, `backend/app/api/v1/overview.py` — параметры, валидатор, `_SINGLE`.
- `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` — `scripts/gen-api.sh`.
- `frontend/src/features/overview/{filters.ts,api.ts,SummaryPage.tsx,summary.css}`, `frontend/src/shared/i18n/ru.ts`.
- Тесты: `backend/tests/unit/test_024_range.py`, `backend/tests/api/test_024_range.py`, `frontend/tests/features/overview/DateRange.test.tsx`.
- `scripts/explain_r2_queries.py` — случай диапазона; `docs/acceptance/mvp-demo.md` — сценарий.

## 4. Интерфейсы
```python
def range_condition(due_from: date | None, due_to: date | None) -> ColumnElement[bool]: ...
class OverviewTaskQuery(PageParams):
    due_from: date | None = None
    due_to: date | None = None   # model_validator: due & (from|to) -> 422; from > to -> 422
```
HTTP: `GET /api/v1/me/overview/tasks?due_from=2026-11-16&due_to=2026-11-20&…`; ответ без изменений.

## 5. Тестовая стратегия и трассировка
| AC | Тест |
|---|---|
| AC-1…AC-3, AC-6 | `test_024_range.py` (API, FixedClock) |
| AC-4 | API, параметризация 422 |
| AC-5 | API + `use_clock` 21:00Z |
| AC-7…AC-9 | `DateRange.test.tsx` |

## 6. Риски
- Нативное поле даты в Safari старых версий — текстовое поле; формат тот же `YYYY-MM-DD`, ошибка формата уйдёт как 422.
- Без индекса выборка идёт тем же полным проходом, что и пресеты (замер: десятки мс на 50 000).
