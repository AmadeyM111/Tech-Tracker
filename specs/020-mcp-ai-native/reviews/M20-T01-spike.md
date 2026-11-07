# M20-T01. Спайк MCP SDK

- **Дата:** 2026-11-08
- **Исполнитель:** оркестратор (Claude), вне репозитория — `/tmp/mcp-spike/probe.py`

## Результат
Выбрана версия **`mcp>=1.30,<2`** (вместо `mcp>=2.3,<3` из PN-9 плана). Основание — план PN-9
предусматривал откат на 1.x, если 2.x неудобна.

## Почему не 2.x
- В 2.3.0 нет `Server.list_tools()` / `call_tool()` декораторов; `mcp.server.fastmcp` переименован
  в `mcp.server.mcpserver.MCPServer`; API сервера переписан (`ServerRequestContext`, модерн-протокол
  `DiscoverRequest`). Миграционный гайд SDK прямо советует `mcp<2` для существующего кода.
- Публичного API, которое мы знаем и можем проверить здесь, в 2.x не нашлось за разумное время.

## Что проверено на 1.30.0 (probe)
- `StreamableHTTPSessionManager(app=Server, stateless=True, json_response=True)` + `handle_request(scope, receive, send)`
  как ASGI-приложение: `initialize` → 200 `application/json`, `tools/list` → 200, `tools/call` → 200.
- Контекстная переменная, выставленная ASGI-обёрткой до вызова `handle_request`, доступна внутри
  обработчика `call_tool` (`user=alice`). Этим передаётся `Actor` без глобального состояния.
- Клиент: `mcp.client.streamable_http.streamablehttp_client(url, headers=..., httpx_client_factory=...)` —
  есть для моста `gtrack mcp`; фабрика HTTP-клиента позволяет указать CA-файл (`GTRACK_CA_FILE`).
- Серверный stdio: `mcp.server.stdio.stdio_server`; `ClientSession` — для моста.

## Зависимости 1.30.0
anyio, httpx, httpx-sse, jsonschema, pydantic, pydantic-settings, pyjwt, python-multipart,
sse-starlette, starlette, typing-extensions, typing-inspection, uvicorn. Лицензия MIT.
Новых зависимостей сверх `mcp` нет, кроме транзитивных.

## Открыто до M20-T07
- Монтирование `handle_request` в FastAPI и запуск `session_manager.run()` в lifespan — проверить в T07.
- В AGENTS.md упомянут `backend/tests/arch/test_dependencies_allowlist.py`, но такого файла в
  репозитории нет. Проверка списка зависимостей — `backend/tests/test_toolchain.py`.
