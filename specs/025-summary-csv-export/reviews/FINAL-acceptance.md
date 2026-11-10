# Финальная приёмка 025 «Сводка: выгрузка CSV»

- **Дата:** 2026-11-10 · **Ветка:** `feat/r3-summary-csv` · **Spec:** APPROVED 2026-11-10 · **ADR:** 0023
- **Итог:** автоматические AC закрыты; ручная проверка «файл открывается в Excel без настроек» и вид кнопки на 360 px — по чек-листу `docs/acceptance/mvp-demo.md`, раздел 9, на стенде (не выполнялась).

| AC | Проверка | Результат |
|---|---|---|
| AC-1, AC-2 | `backend/tests/api/test_025_csv.py::test_025_ac1_ac2_*` | автотест |
| AC-3 | `test_025_ac3_*`, `unit/test_role_matrix.py::test_025_*`, `api/test_deps_gates.py`, `api/test_sessions.py` | автотест |
| AC-4, AC-5 | `unit/test_025_csv_render.py`, `test_025_ac4_ac5_*` | автотест |
| AC-6 | `unit/test_025_csv_render.py::test_025_ac6_*`, `test_025_ac6_*` | автотест |
| AC-7 | `test_025_ac7_*` | автотест |
| AC-8 | `test_025_ac8_*` | автотест |
| AC-9 | `test_025_ac9_*` | автотест |
| AC-10 | `test_025_ac10_*`, `frontend/tests/features/admin/AuditPage.test.tsx` («025 audit label») | автотест |
| AC-11 | `frontend/tests/features/overview/SummaryPage.test.tsx` («025 CSV export button») | автотест + ручной 360 px |
| AC-12 | `unit/test_025_csv_render.py::test_025_ac12_*`, `test_025_ac12_*` | автотест |

Отклонения от плана: модуль формирования файла назван `export_csv.py` (а не `csv.py`: не затеняет стандартный `csv`). Запрос выгрузки не принимает `page`/`page_size`
и параметры диапазона дат: они появятся после слияния спеки 024 (в ветку подтягивается `main`). Кнопка использует `ui-btn-secondary` из общего `ui.css` (без правок самого файла).
