# Plan: OAuth 2.1 на /mcp (028)

- **Spec:** ./spec.md (DRAFT) · **ADR:** 0022 (обновлён 2026-11-12)
- **Статус:** DRAFT — не начинать, пока spec.md не APPROVED и миграция `0014` не согласована оркестратором.

## 1. Подход
Authorization server живёт в том же процессе api (`backend/app/oauth/…`) и не зависит от сессионного слоя REST, кроме экрана согласия: он использует
существующую сессию пользователя (cookie `gt_session`) через SPA-страницу `/oauth/authorize` и два API-вызова (контекст и решение). Машинные endpoint
(`register`, `token`, `revoke`) — публичные JSON/form-маршруты под `/api/v1/oauth/`. Метаданные (`/.well-known/*`) — отдельный роутер без префикса `/api/v1`.
Токены — непрозрачные, хранятся как SHA-256 (как `gtrk_`); `/mcp` различает их по префиксу (`gtrk_` / `gtat_`). Издатель и ресурс строятся из `PUBLIC_BASE_URL`.

## 2. Решения
| Решение | Выбрано | Отвергнутые | Почему |
|---|---|---|---|
| PO-1 AS | свой минимальный внутри api | внешний OIDC; шлюз в DMZ | нет внешнего провайдера; пользователи и сессии в трекере; шлюз снят поправкой ADR-0022 |
| PO-2 Регистрация | DCR (RFC 7591), публичные клиенты, `token_endpoint_auth_method=none` | CIMD; `client_secret` | поддерживают ChatGPT и Claude; без исходящих запросов (NFR-3) |
| PO-3 Токены | непрозрачные, хеш в БД, проверка в БД на каждый запрос | JWT | мгновенный отзыв и общая логика с `gtrk_`; не нужен ключ подписи и ротация ключей |
| PO-4 Хранение access | отдельная таблица `oauth_token` | строки `api_token` | у `api_token` лимит 10 активных и интерфейс списка; access меняется каждый час, засорил бы список |
| PO-5 Refresh | ротация + семейство; повтор → отзыв гранта | долгоживущий статичный | требование спеки MCP для публичных клиентов; Claude ждёт `invalid_grant` |
| PO-6 Согласие | SPA-страница + `context`/`decision` API, контекст подписан HMAC | серверный HTML | UI-кит и i18n уже в SPA; HMAC не даёт подменить параметры; CSP и Origin уже на месте |
| PO-7 Пути | token/register под `/api/v1/oauth/`; только `/.well-known/*` — новые location в nginx | `/oauth/token`, `/oauth/register` | один новый блок в серверном nginx вместо трёх |
| PO-8 Audience | `resource` = `<PUBLIC_BASE_URL>/mcp`; нет `resource` → канонический по умолчанию | требовать всегда | Claude, по документации, `resource` не гарантирует; ChatGPT присылает |
| PO-9 Лимиты | таблица `oauth_attempt` (по образцу `registration_attempt`: хеш ключа, окно) | in-memory | несколько процессов/перезапуски; без новых зависимостей |

## 3. Модули и файлы
- `backend/app/oauth/` — новый пакет: `models.py` (`OauthClient`, `OauthGrant`, `OauthCode`, `OauthToken`, `OauthAttempt`), `metadata.py` (документы RFC 9728/8414), `registration.py` (DCR, allowlist URI), `authorize.py` (проверка запроса, подписанный контекст, выдача кода), `tokens.py` (code→tokens, refresh, ротация, отзыв, resolve `gtat_`), `limits.py`, `service.py` (грант: список, отзыв).
- `backend/app/api/v1/oauth.py` — `register`, `token`, `revoke`, `authorize/context`, `authorize/decision`; `backend/app/api/v1/me_oauth.py` — `GET/DELETE /me/oauth-grants`; `backend/app/api/wellknown.py` — роутер `/.well-known/*` (подключение в `main.py` вне `/api/v1`).
- `backend/app/api/mcp/endpoint.py` — `WWW-Authenticate` на 401 и ветка `gtat_`; `backend/app/domain/tokens/service.py` — общий `resolve_principal` (или обёртка).
- `backend/app/core/config.py` — `oauth_redirect_allowlist` (дополнительные шаблоны), лимиты; проверка `PUBLIC_BASE_URL` (https).
- `backend/app/domain/events/{catalog,writer}.py` — действия `user.oauth_granted`, `user.oauth_revoked`, ключ `client` в `details`; русские названия в `ru.ts`.
- `backend/app/domain/ops/maintenance.py` — очистка клиентов, кодов, токенов (+ строки в выводе `gtrack maintenance`).
- `backend/migrations/versions/0014_mcp_oauth.py`, `docs/data-model.md`, `backend/app/core/db_roles.py` (права на новые таблицы), `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`.
- Фронт: `features/oauth/ConsentPage.tsx` (+ `api.ts`, `oauth.css`), маршрут `/oauth/authorize` в `app/router.tsx`, возврат после входа в `features/auth/LoginPage.tsx`, блок «Облачные клиенты» в `features/tokens/*`, `shared/i18n/ru.ts`, `backend/tests/infra/test_frontend_scaffold.py`.
- Деплой: `deploy/web/default.conf.template` (+ шаблон PR #23), `docs/ai-integration.md` (подключение ChatGPT/Claude.ai), `README.md`, `docs/acceptance/mvp-demo.md`; серверный `/etc/task-tracker/nginx.conf` правит оркестратор.

## 4. Интерфейсы (эскиз)
```
GET  /.well-known/oauth-protected-resource[/mcp]   -> {resource, authorization_servers, scopes_supported, bearer_methods_supported}
GET  /.well-known/oauth-authorization-server       -> RFC 8414 (+ authorization_response_iss_parameter_supported)
POST /api/v1/oauth/register   (json)               -> 201 {client_id, client_id_issued_at, client_name, redirect_uris, grant_types, response_types, token_endpoint_auth_method:"none", scope}
GET  /oauth/authorize?...                           -> SPA
GET  /api/v1/oauth/authorize/context?...           -> {client_name, redirect_host, scope, request_token}   (сессия)
POST /api/v1/oauth/authorize/decision {request_token, allow} -> {redirect_to}                              (сессия, Origin)
POST /api/v1/oauth/token  (form)                   -> {access_token, token_type:"Bearer", expires_in, refresh_token, scope} | {error, error_description}
POST /api/v1/oauth/revoke (form)                   -> 200
GET  /api/v1/me/oauth-grants / DELETE /api/v1/me/oauth-grants/{id}
```
Подписанный контекст: HMAC-SHA256 от канонической строки параметров и `user_id`, ключ — `secret_key` приложения; срок 10 минут.

## 5. Данные
Миграция `0014_mcp_oauth` (аддитивная): `oauth_client`, `oauth_grant`, `oauth_code`, `oauth_token`, `oauth_attempt`; индексы по хешам (`UNIQUE`), `grant_id`, `user_id` (активные); `ON DELETE CASCADE` от пользователя. Откат — `DROP TABLE` в обратном порядке. Проверка `db_roles` (рабочая роль) и тест миграций обновляются.

## 6. Тестовая стратегия и трассировка
| AC | Тест |
|---|---|
| AC-1, AC-2 | `backend/tests/api/test_028_metadata.py` (в т.ч. за прокси со схемой `http`, без `PUBLIC_BASE_URL`) |
| AC-3 | `test_028_register.py` (allowlist, лимиты) |
| AC-4, AC-5 | `test_028_authorize.py` + фронт `ConsentPage.test.tsx` |
| AC-6, AC-7 | `test_028_token.py` (PKCE, одноразовость, истечение с `FixedClock`, ротация, повтор → отзыв, потолок 90 суток) |
| AC-8 | `test_028_mcp_oauth.py` (audience, блокировка, `must_change_password`, регрессия `gtrk_`, `gtat_` на REST → 401) |
| AC-9, AC-10 | `test_028_grants.py` (отзыв, чужой грант, аудит, лента) |
| AC-11 | `test_028_limits_maintenance.py` |
| AC-12 | vitest + ручная проверка 360 px |
| AC-13 | вручную на стенде пилота: ChatGPT и Claude.ai (скриншоты, `reviews/FINAL-acceptance.md`) |
Безопасность: параметризованные негативные тесты (неверный verifier/redirect/client, повтор кода, повтор refresh, чужой audience, подмена контекста решения, токен в query).

## 7. Зависимости
Новых пакетов нет (`hmac`, `hashlib`, `secrets` — стандартная библиотека). `mcp` и FastAPI — как сейчас.

## 8. Риски
- Клиенты отклоняются от спеки (особенно ChatGPT: `iss`, стабильный/специфичный redirect, DCR-кэш метаданных у ChatGPT при смене URL — сообщения сообщества). Смягчение: AC-13 на живом стенде до выкатки на прод; страницы §2 перечитать.
- Открытый DCR привлекает сканеры: allowlist URI, лимиты, очистка.
- Исходный `Host` за двумя прокси: все URL — из `PUBLIC_BASE_URL`; тест.
- Позднее открытие маршрутов `/.well-known/*` в серверном nginx: без них discovery вернёт HTML от SPA; пункт чек-листа деплоя.
- ИБ по провайдерам (GigaChat, DeepSeek) не закончена: проверка этих клиентов — после, по факту.
