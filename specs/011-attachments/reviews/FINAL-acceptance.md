# Финальная приёмка 011 «Вложения»

- **Дата:** 2026-11-08 · **Ветка:** `feat/r2-attachments` · **Spec:** APPROVED 2026-11-08
- **Итог:** автоматические AC закрыты; ручная проверка в браузере — `docs/acceptance/mvp-demo.md`, раздел 8.
- **Ревью:** независимое ревью безопасности — 8 замечаний, все исправлены (plan §9).

| AC | Проверка |
|---|---|
| AC-1 | `api/test_011_attachments.py::test_011_ac1_size_boundaries`, `unit/test_011_storage.py` (лимит без `Content-Length`) |
| AC-2 | `unit/test_011_types.py`, `api/test_011_attachments.py::test_011_ac2_types_over_http` |
| AC-3 | `test_011_ac3_permissions`, `test_011_permissions_checked_before_size` |
| AC-4 | `test_011_ac4_limit_per_task`, `test_011_ac4_parallel_uploads_respect_limit` |
| AC-5 | `test_011_ac5_download_headers`, `test_011_cp1251_text_is_served_with_its_charset` |
| AC-6 | `test_011_ac6_name_never_in_path`, `unit/test_011_types.py::test_011_ac6_clean_name` |
| AC-7 | `test_011_ac7_delete_rules_and_soft_delete`, `cli/test_011_maintenance.py` |
| AC-8 | `test_011_ac8_feed_shows_file_name` |
| AC-9 | `test_011_ac9_disk_full_blocks_upload_not_tasks`, `unit/test_011_storage.py` |
| AC-10 | `cli/test_export_import.py::test_011_*` (круг с файлами, подмена, отсутствие и порча файла) |
| AC-11 | `frontend/tests/features/attachments/Attachments.test.tsx` |

Отклонения:
- Список вложений отдаётся страницей (`Page`, ADR-0012), как остальные списки.
- Имя файла передаётся в заголовке `X-File-Name`, а не `?name=`: так оно не попадает в журнал nginx (уточнение §7 spec).
- Тест R1 `test_t69_deferred_tables_are_absent` больше не проверяет `attachment`: таблица введена spec 011.

Перед выкаткой на прод проверить `client_max_body_size` в nginx прода (`/etc/task-tracker/nginx.conf`): не меньше 12m.

Интерфейс свёрстан по утверждённым макетам (`Shared/Design/gtrack-r2-attachments-notifications`, 2026-11-08):
раздел «Вложения», «Открыть» перед «Скачать», «Удалить» — вторичная кнопка с подтверждением
(«Окончательно он удалится через 30 дней» — совпадает с FR-7), счётчик «Вложений: N из 20», состояние
лимита, ошибки внутри раздела, строка для не участника. Отклонение: индикатор загрузки без процентов —
fetch не отдаёт прогресс отправки (вопрос оркестратору 2026-11-08).
