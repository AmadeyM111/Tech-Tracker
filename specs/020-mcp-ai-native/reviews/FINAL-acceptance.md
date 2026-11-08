# Финальная приёмка: AI Native через MCP (фича 020)

- **Дата:** 2026-11-08
- **Ветка:** `work3` (worktree `Tech-Tracker-work3`), коммиты M20-T01…T11 и исправление совместимости
- **Проверка:** `bash scripts/check.sh` — зелёно (ruff, format, mypy, alembic check, pytest 4184 passed / 81 skipped, frontend 58 файлов / 1509 тестов)

| AC | Статус | Как проверено |
|---|---|---|
| AC-1 | выполнено | `test_m20_ac1_*`, `test_m20_t06_tokens_api` (токен один раз, в БД хеш) |
| AC-2 | выполнено | `test_m20_t07_mcp_core` (401 без токена и с неверным) |
| AC-3 | выполнено | `test_m20_t03`, `test_m20_t06` (отзыв) |
| AC-4 | выполнено | `test_m20_t05_block_revokes_tokens` |
| AC-5 | выполнено | `test_m20_t08_mcp_tools::test_ac5_*` (403 forbidden, задача не создана) |
| AC-6 | выполнено | `test_m20_t07_mcp_core::test_ac6_*`, `test_registry_lists_ten_tools_for_business_roles` |
| AC-7 | выполнено | `test_m20_t08_mcp_tools::test_ac7_*` (видно в REST) |
| AC-8 | выполнено | `test_m20_t04_client_name::test_m20_ac8_*`, `test_m20_t08_mcp_tools::test_ac8_*` |
| AC-9 | **не выполнено** | ручная проверка: подключение Claude Code к живому серверу. Автоматически покрыто `test_m20_t09_mcp_bridge` (клиентская сессия к приложению) |
| AC-10 | выполнено | `test_m20_t07_mcp_core::test_ac10_foreign_origin_is_403` |
| AC-11 | выполнено | новых внешних адресов нет; `scripts/check.sh` зелёно |
| AC-12 | выполнено | `test_m20_t11_docs` (docs/ai-integration.md: Claude Code и Codex CLI) |

## Открыто
- **Ссылка в меню** на «Доступ для агентов» (M20-T10) не добавлена: сломает проверки меню разделов 003 и 004. Страница доступна по `/profile/agents`. Нужно решение владельца.
- **AC-9** выполняет владелец вручную.

## Отступления от плана (зафиксированы в tasks.md)
- Версия SDK `mcp` 1.30 вместо 2.x (PN-9, спайк M20-T01).
- Имя клиента в журнале передаётся контекстной переменной, а не полем `Actor` (PN-6).
- Команда называется `gtrack mcp` (как остальные подкоманды), а не `gtrack mcp`.
- Для `Actor.session_id` токена используется id строки токена (сессионных эндпоинтов MCP нет).
