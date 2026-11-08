# Финальная приёмка 008 «Сводка»

- **Дата:** 2026-11-08 · **Ветка:** `feat/r2-dashboard` · **Spec:** APPROVED 2026-11-08
- **Итог:** автоматические AC закрыты; ручные AC-12 (360 px), AC-13 (визуально) и опрос — по чек-листу
  `docs/acceptance/mvp-demo.md`, раздел 7, на стенде (не выполнялись). AC-14 (p95) — спека 016.

| AC | Проверка | Результат |
|---|---|---|
| AC-1, AC-2 | `backend/tests/api/test_008_overview.py::test_008_ac1_ac2_*` | автотест |
| AC-3, AC-4 | `test_008_ac3_ac4_needs_review_author_or_owner` | автотест |
| AC-5 | `test_008_ac5_priority_multiselect` | автотест |
| AC-6 | `test_008_ac6_today_boundary_follows_moscow_clock`, `unit/test_008_due.py` | автотест |
| AC-7 | `test_008_ac7_due_presets_moscow`, `unit/test_008_due.py` | автотест |
| AC-8 | `test_008_ac8_hot_flag_and_order`, `unit/test_008_due.py` | автотест |
| AC-9 | `test_008_ac9_total_and_paging` | автотест |
| AC-10 | `test_008_ac10_*` | автотест |
| AC-11 | `test_008_ac11_validation` | автотест |
| AC-12 | `frontend/tests/features/overview/SummaryPage.test.tsx` (пустое состояние, меню ТА), `tests/app/sidebar.test.tsx` | автотест + ручной 360 px |
| AC-13 | `SummaryPage.test.tsx::ac13_tile_click_sets_status_filter` | автотест + ручной |
| AC-14 | спека 016 (T-10) | не в этой ветке |
| AC-15 | `test_008_ac15_tiles_ignore_list_filters` | автотест |

Отклонения от плана: пункт меню «Сводка» стоит третьим (после «Мои задачи»), чтобы не менять порядок
ссылок 003/AC-19 и 004/AC-12; тесты порядка Tab дополнены новой ссылкой. Размер шрифта числа в плитке
(`.sum-count`, 2rem) добавлен в таблицу `typography.test.ts`; остальные размеры наследуются.
