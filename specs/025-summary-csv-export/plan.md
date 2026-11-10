# Plan: «Сводка» — CSV (025)

- **Spec:** ./spec.md (APPROVED) · **ADR:** 0023 (черновик)
- **Статус:** APPROVED

## 1. Подход
Выборка строится той же `_filter_conditions`, что у списка, но без пагинации и с `LIMIT CSV_MAX_ROWS + 1` одним запросом
(снимок данных, NFR-2): если вернулось больше лимита — 422 `export_too_large` до записи чего-либо. Строки формирует чистая
функция `render_csv(rows, base_url)` (BOM, `;`, CRLF, кавычки, защита формул) — она тестируется без БД и HTTP. Эндпоинт
отвечает `Response` с готовым телом (до 10 000 строк — единицы МБ). Возможность `export_overview` — только БА (по образцу
`onboard_accounts`), попадает в `capabilities` и скрывает кнопку. Событие аудита пишется в той же транзакции после успешной
сборки. Фронт: кнопка в `SummaryPage`, загрузка через общий клиент (`Accept: text/csv`), сохранение через `Blob` и временную ссылку.

## 2. Решения
| Решение | Выбрано | Отвергнутые | Почему |
|---|---|---|---|
| PC-1 Права | новая возможность `export_overview` у БА | проверка роли по имени; `BUSINESS_ACCESS` | единый механизм прав, UI читает `capabilities`, тест матрицы |
| PC-2 Предел | отказ 422 при > `CSV_MAX_ROWS` | усечение; потоковая выдача без лимита | честный результат; предел защищает память и БД |
| PC-3 Формулы | ведущий `'` для `= + - @ \t \r` | нет экранирования; префикс пробел | рекомендация OWASP, Excel скрывает апостроф |
| PC-4 Тело | собирается в памяти | `StreamingResponse` | ≤ 10 000 строк ≈ 2–3 МБ; ошибка лимита возможна до заголовков ответа |
| PC-5 Аудит | событие `user.overview_exported` (сущность — пользователь-автор, детали `rows` — число строк строкой, как все значения `details`) | новая `EntityType`; отдельная таблица | журнал и вывод уже есть; ключ деталей добавляется в белый список `UserEventDetails` (BR-2) — ADR-0023 |
| PC-6 Ссылка | `PUBLIC_BASE_URL` + `/tasks/<id>` | относительная | в Excel нужна рабочая ссылка |
| PC-7 Скачивание | `fetch` через общий клиент + `Blob` | `<a href>` на эндпоинт | единый обработчик ошибок и заголовков (`X-GT-Background` не нужен) |

## 3. Затрагиваемые файлы
- `backend/app/domain/access/roles.py` — `EXPORT_OVERVIEW` у БА; тесты матрицы ролей, `GET /me`.
- `backend/app/domain/overview/export_csv.py` — новый: `render_csv`, `escape_cell`.
- `backend/app/domain/overview/queries.py` — `overview_rows_for_export` (общие условия, лимит).
- `backend/app/api/v1/overview.py`, `schemas/overview.py` — маршрут `/tasks.csv`; `backend/app/core/config.py` — `csv_max_rows`; `core/errors.py` — код `export_too_large`.
- `backend/app/domain/events/catalog.py`, `writer.py` — действие и ключ деталей; фронт-словарь действий журнала (`admin.audit.action.*`).
- `frontend/src/features/overview/{SummaryPage.tsx,api.ts,summary.css}`, `shared/i18n/ru.ts`, `shared/api/schema.d.ts`, `docs/api/openapi.json`.
- Тесты: `backend/tests/unit/test_025_csv.py`, `backend/tests/api/test_025_csv.py`, `frontend/tests/features/overview/CsvExport.test.tsx`.
- `docs/acceptance/mvp-demo.md`, `docs/data-model.md` (если ключи деталей) — документация.

## 4. Интерфейсы
```python
def escape_cell(value: str) -> str: ...      # ведущий ' для = + - @ \t \r
def render_csv(rows: Sequence[ExportRow], *, base_url: str | None) -> bytes: ...  # BOM + ; + CRLF
async def overview_rows_for_export(db, actor, f: OverviewFilter, *, limit: int) -> list[ExportRow]: ...  # limit+1
```
HTTP: `GET /api/v1/me/overview/tasks.csv?…` → 200 `text/csv` | 401 | 403 | 404 (чужой `project_id`) | 422 (`validation_error`, `export_too_large`).

## 5. Тестовая стратегия и трассировка
| AC | Тест |
|---|---|
| AC-4, AC-5, AC-6, AC-12 | `test_025_csv.py` (unit: разбор `csv`-модулем, BOM, CRLF, экранирование) |
| AC-1, AC-2, AC-7, AC-9 | `test_025_csv.py` (API) |
| AC-3 | API + матрица ролей |
| AC-8 | API с `CSV_MAX_ROWS=5` |
| AC-10 | API + журнал аудита |
| AC-11 | `CsvExport.test.tsx` |

## 6. Риски
- Excel может склеить длинные числа и даты в названиях — не лечим (данные пользователя); апостроф защищает только формулы.
- 10 000 строк в памяти × параллельные выгрузки: ограничено числом БА пилота; при росте — потоковая выдача (отдельное решение).
- `PUBLIC_BASE_URL` с неверным значением даёт нерабочие ссылки в файле — проверка при выкатке (README).
