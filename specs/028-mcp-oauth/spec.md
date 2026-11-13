# Spec: OAuth 2.1 на /mcp для облачных клиентов (ChatGPT, Claude.ai и др.)

- **ID:** 028-mcp-oauth
- **Статус:** APPROVED (владелец, 2026-11-12: «да делай»; решения по §12 — ниже, раздел «Решения владельца»)
- **Дата:** 2026-11-12
- **Пакет:** T-14 (поправка к ТЗ). Основание: решение владельца 2026-11-12 «ставим»; ADR-0022 (вариант B подтверждён 2026-11-08, обновлён 2026-11-12), ADR-0018 (токены `gtrk_`, MCP; его отказ от OAuth для облачных клиентов пересмотрен ADR-0025), макеты Design Agent `Shared/Design/gtrack-oauth/` (6 состояний), спека 020, спека 026 (карточка «Подключить ИИ-агента»).

## 1. Контекст и цель
`/mcp` сейчас принимает только `Authorization: Bearer gtrk_…` (ADR-0018). ChatGPT обращается к `/mcp` без токена (10 ответов 401 за сутки) и
требует «завершить авторизацию»: облачный клиент не умеет вводить персональный токен, ему нужен OAuth. Цель — чтобы пользователь в ChatGPT или Claude.ai
нажал «подключить», вошёл в GTrack, нажал «Разрешить» и дальше агент работал от его имени с его правами, а отозвать доступ можно в «Доступе для агентов».
Локальные клиенты (Claude Code, Codex CLI) и `gtrk_` не меняются.

## 2. Требования облачных клиентов (проверено по официальной документации 2026-11-12)
Статус проверки: **[прочитано]** — страница открыта и разобрана целиком; **[сниппет]** — видно только в результатах поиска, до реализации перечитать; **[не проверено]**.

**Спецификация MCP, авторизация** ([modelcontextprotocol.io/specification/2025-06-18/basic/authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)) [прочитано]:
- MCP-сервер ДОЛЖЕН реализовать Protected Resource Metadata (RFC 9728) с полем `authorization_servers`; при 401 ДОЛЖЕН отдавать `WWW-Authenticate` с `resource_metadata`.
- Authorization server ДОЛЖЕН отдавать метаданные RFC 8414; клиенты и серверы СЛЕДУЕТ поддерживать динамическую регистрацию клиентов (RFC 7591).
- Клиенты ДОЛЖНЫ слать `resource` (RFC 8707) в запросах авторизации и токена; сервер ДОЛЖЕН проверять, что токен выдан именно для него (audience), и НЕ ДОЛЖЕН принимать чужие токены или передавать свой дальше (token passthrough запрещён).
- PKCE обязателен; redirect URI сверяются точно со зарегистрированными; все endpoint авторизации — по HTTPS; токен — только в заголовке, не в query; refresh-токены публичных клиентов ротируются; access-токены СЛЕДУЕТ делать короткими.

**ChatGPT** ([developers.openai.com/apps-sdk/build/auth](https://developers.openai.com/apps-sdk/build/auth), страница «Authentication») [прочитано]:
- Метаданные: `/.well-known/oauth-protected-resource` (поля `resource`, `authorization_servers`) и RFC 8414 `/.well-known/oauth-authorization-server` либо OIDC discovery; `issuer` ДОЛЖЕН точно совпадать со значением в `authorization_servers`; в метаданных ДОЛЖНО быть `code_challenge_methods_supported` с `S256`, иначе клиент «не поддерживается».
- Регистрация клиента: CIMD (HTTPS-адрес как `client_id`, предпочтительно) или DCR (`registration_endpoint`; ChatGPT вызывает его один раз на подключение и переиспользует клиента) или предзаданные клиенты.
- Redirect URI: стабильный `https://chatgpt.com/connector_platform_oauth_redirect` (если сервер поддерживает RFC 9207 `iss` во всех ответах авторизации) либо специфичный `https://chatgpt.com/connector/oauth/{callback_id}`; «allowlist the exact production URI shown on the MCP server's management page».
- `resource=<URL MCP-сервера>` добавляется к запросам авторизации и токена; сервер ДОЛЖЕН отклонять токены с чужим audience. Аутентификация клиента на token endpoint: `none` (публичный + PKCE) для CIMD; для DCR «обычно» `none`, `client_secret_post` или `client_secret_basic`.
- 401: `WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource", scope="…"`; access- и refresh-токены «могут истекать и ротироваться»; сроки не оговорены.
- Не поддерживаются client credentials, сервисные аккаунты, JWT-bearer, пользовательские API-ключи и клиентские сертификаты заказчика.
- Транспорт: публичный endpoint со Streamable HTTP, обычно `/mcp` ([developers.openai.com/apps-sdk/deploy/connect-chatgpt](https://developers.openai.com/apps-sdk/deploy/connect-chatgpt)) [сниппет]. Режим deep research ожидает инструменты `search` и `fetch` ([developers.openai.com/api/docs/mcp](https://developers.openai.com/api/docs/mcp)) [прочитано]; у нас таких нет — вне рамок (§6).
- Адреса ChatGPT для allowlist публикуются OpenAI в файле диапазонов ([developers.openai.com/api/docs/guides/ip-addresses](https://developers.openai.com/api/docs/guides/ip-addresses)); сообщения сообщества говорят о неполноте файла, OpenAI рекомендует mTLS и OAuth [сниппет]. Опираться только на IP нельзя.

**Claude.ai (веб, Desktop, мобильное), Claude Code** ([claude.com/docs/connectors/building/authentication](https://www.claude.com/docs/connectors/building/authentication)) [прочитано; в тексте — спека MCP 2025-11-25]:
- Регистрация: DCR (если есть `registration_endpoint`; клиент публичный) либо CIMD, либо учётные данные, которые держит Anthropic.
- Redirect URI: `https://claude.ai/api/mcp/auth_callback` для claude.ai/Desktop/мобильных; поддержка поправки на `https://claude.com/api/mcp/auth_callback` упоминается в справочной статье ([support.anthropic.com/en/articles/11503834](https://support.anthropic.com/en/articles/11503834)) [сниппет]; Claude Code — loopback `http://localhost:<порт>/callback` (порт любой, сравнивать без порта).
- PKCE `S256` на каждом запросе авторизации; в метаданных `code_challenge_methods_supported: ["S256"]`.
- Токен endpoint принимает `application/x-www-form-urlencoded`; `/register` — JSON. Таймаут Claude на discovery, регистрацию и токен — 10 с, на refresh — 30 с.
- Refresh: Claude обновляет токен при 401 и за 5 минут до истечения; при невалидном refresh сервер возвращает `invalid_grant`; refresh-токены публичных клиентов ротируются (новый выдаётся в том же ответе, старый становится недействительным).
- Scope берётся из `WWW-Authenticate` при 401, иначе из `scopes_supported`; `offline_access` добавляется, если он есть в `scopes_supported`.
- `resource` в метаданных защищённого ресурса ДОЛЖЕН точно совпадать с URL MCP-сервера, включая путь; из `authorization_servers` Claude использует только первый элемент; `WWW-Authenticate` на ответ 200 игнорируется.
- Исходящий трафик Claude идёт из `160.79.104.0/21`; WAF перед authorization server может блокировать discovery.

**GigaChat, DeepSeek и другие облачные клиенты** [не проверено]: документация по remote MCP/OAuth не искалась; список — в протоколе ИБ. Решение «MCP + OAuth 2.1 + DCR + PKCE» — общий знаменатель спецификации MCP, поэтому должно подойти любому клиенту, соблюдающему спеку; проверка — по факту подключения.

## 3. Пользовательские сценарии
- Как пользователь ChatGPT, я добавляю коннектор с адресом `https://<наш-адрес>/mcp`, меня перебрасывает в GTrack; я вхожу (если не вошёл), вижу «Разрешить «ChatGPT» доступ к GTrack?» и нажимаю «Разрешить».
- Как пользователь Claude.ai, я делаю то же самое для Claude.
- Как пользователь, я вижу подключённые облачные клиенты рядом с моими токенами в «Доступе для агентов» и отзываю любой из них; агент сразу теряет доступ.
- Как ТА, я блокирую учётную запись, и её облачные клиенты перестают работать вместе с `gtrk_`; в журнале аудита видно, кто и какому клиенту разрешил доступ.

## 4. Функциональные требования
- **FR-1 (метаданные ресурса, RFC 9728):** `GET /.well-known/oauth-protected-resource` и `GET /.well-known/oauth-protected-resource/mcp` (путь по RFC 9728 §3) ДОЛЖНЫ отдавать JSON `{resource: "<PUBLIC_BASE_URL>/mcp", authorization_servers: ["<PUBLIC_BASE_URL>"], scopes_supported: ["mcp","offline_access"], bearer_methods_supported: ["header"]}`; без аутентификации, `Cache-Control: no-store`.
- **FR-2 (метаданные AS, RFC 8414):** `GET /.well-known/oauth-authorization-server` ДОЛЖЕН отдавать `issuer` (= `PUBLIC_BASE_URL`, без слэша на конце), `authorization_endpoint` (`<PUBLIC_BASE_URL>/oauth/authorize`), `token_endpoint` и `registration_endpoint` (`<PUBLIC_BASE_URL>/api/v1/oauth/token`, `/api/v1/oauth/register`), `revocation_endpoint`, `response_types_supported: ["code"]`, `grant_types_supported: ["authorization_code","refresh_token"]`, `code_challenge_methods_supported: ["S256"]`, `token_endpoint_auth_methods_supported: ["none"]`, `scopes_supported`, `authorization_response_iss_parameter_supported: true` (Q-10). Алиас `GET /.well-known/openid-configuration` — тот же документ без OIDC-полей (Q-10).
- **FR-3 (401 на /mcp):** при отсутствии, истечении или недействительности токена `/mcp` ДОЛЖЕН отвечать 401 с `WWW-Authenticate: Bearer resource_metadata="<PUBLIC_BASE_URL>/.well-known/oauth-protected-resource/mcp", scope="mcp"` (и `error="invalid_token"` для невалидного токена). Тело — как сейчас (`{detail, code}`).
- **FR-4 (динамическая регистрация, RFC 7591):** `POST /api/v1/oauth/register` (JSON; без аутентификации) ДОЛЖЕН создавать публичного клиента: принимает `client_name` (1–64 символа), `redirect_uris` (1–5), `grant_types`, `response_types`, `token_endpoint_auth_method` (только `none`), `scope`; возвращает 201 с `client_id`, `client_id_issued_at`, принятыми полями (без `client_secret`). Каждый `redirect_uri` ДОЛЖЕН быть абсолютным `https`-адресом без userinfo и фрагмента, не IP-адресом и не `localhost`, и (если задана `OAUTH_REDIRECT_HOSTS`) принадлежать разрешённому хосту; иначе 400 `invalid_redirect_uri` (решение владельца 2026-11-12). Ограничения: 20 регистраций в час с IP, не более 500 клиентов всего (Q-7).
- **FR-5 (запрос авторизации):** `GET /oauth/authorize?response_type=code&client_id&redirect_uri&code_challenge&code_challenge_method=S256&state&resource&scope` — страница SPA. Сервер проверяет (`GET /api/v1/oauth/authorize/context`): клиент существует; `redirect_uri` точно совпадает с одним из зарегистрированных; `code_challenge_method=S256`; `response_type=code`; `resource` (если задан) равен каноническому `<PUBLIC_BASE_URL>/mcp` (со слэшем или без) — иначе `invalid_target`; `scope` ⊆ поддерживаемых. Ошибки в `client_id` и `redirect_uri` показываются на странице и НЕ ведут редиректом (OAuth 2.1 §4.1.2.1); остальные — редирект с `error`.
- **FR-6 (согласие):** без сессии пользователь уводится на `/login` и возвращается на `/oauth/authorize` с теми же параметрами (после входа; допустим только возврат на путь `/oauth/authorize`). Под сессией показывается экран согласия по макету `oauth-consent` (центрированная карточка как у входа; заголовок «<Клиент> просит доступ к вашему GTrack»; пояснение «<Клиент> сможет видеть и изменять ваши проекты и задачи от вашего имени»; пункты «Видеть ваши проекты и задачи», «Создавать и изменять задачи в ваших проектах»; строка «Вы вошли как <логин>»; кнопки «Разрешить» (основная, сверху) и «Отклонить» (вторичная, 44 px); мелко «Вернуться к: <адрес>» с `overflow-wrap: anywhere`). Название клиента — Q-15. Без сессии — экран `oauth-login-context` (форма входа с пояснением «Чтобы разрешить доступ <клиенту>, войдите в GTrack. После входа вы увидите запрос на доступ.»), затем `oauth-consent-after-login`. Ошибки клиента — экраны `oauth-error-unknown` («Клиент не найден. Вернитесь в <приложение> и начните подключение заново.») и `oauth-error-revoked` («Доступ для этого клиента отозван. Чтобы подключиться снова, начните подключение заново в <приложении>.») с одной кнопкой «Вернуться в GTrack». Тексты макета — предложения; в `ru.ts` переносятся после ответа владельца. Решение — `POST /api/v1/oauth/authorize/decision` под сессией, с проверкой Origin и подписанным (HMAC) контекстом запроса, чтобы параметры нельзя было подменить между показом и решением. Без роли, с `must_change_password` и ТА без бизнес-доступа согласие недоступно (те же гейты, что у MCP, Q-6).
- **FR-7 (код авторизации):** «Разрешить» создаёт одноразовый код (256 бит, в БД хеш; срок 60 с; привязан к клиенту, пользователю, `redirect_uri`, `code_challenge`, `resource`, `scope`) и перенаправляет браузер на `redirect_uri?code&state&iss=<issuer>` (`iss` — во всех ответах авторизации, включая ошибки; RFC 9207). «Отклонить» — редирект с `error=access_denied&state&iss`.
- **FR-8 (token endpoint):** `POST /api/v1/oauth/token` (`application/x-www-form-urlencoded`; клиент публичный). `grant_type=authorization_code`: проверка кода (не истёк, не использован, клиент, `redirect_uri`, `code_verifier` по S256); повторное использование кода отзывает уже выданные по нему токены. `grant_type=refresh_token`: ротация — в ответе новый refresh-токен, старый перестаёт действовать; предъявление уже использованного refresh-токена отзывает весь грант (обнаружение кражи). Ответ: `access_token`, `token_type=Bearer`, `expires_in`, `refresh_token`, `scope`. Ошибки — по RFC 6749 (`invalid_request`, `invalid_client`, `invalid_grant`, `unsupported_grant_type`, `invalid_scope`); недействительный refresh — всегда `invalid_grant` (клиент Claude на это опирается).
- **FR-9 (токены):** access-токен (`gtat_` + 256 бит) и refresh-токен (`gtrt_` + 256 бит) непрозрачные; в БД только SHA-256 (как `gtrk_`, ADR-0018 PN-1). Сроки: access 1 час; refresh 90 суток, при каждом использовании выдаётся новый refresh на 90 суток (ротация); согласие действует до отзыва. Токены не принимаются REST API (только `/mcp`), как `gtrk_`.
- **FR-10 (проверка на /mcp):** `/mcp` принимает `gtrk_` (как сейчас) и `gtat_`. Для `gtat_` проверяются: хеш найден, не истёк, не отозван, грант не отозван, audience равен каноническому URL `/mcp`, пользователь не заблокирован; роль и `must_change_password` читаются из БД на каждый запрос (как сейчас). Права — права пользователя (ADR-0018 п. 1, 7); набор инструментов — тот же. Токены, выданные не нашим AS, и `gtat_` с другим audience — 401. Токен никуда не пробрасывается (token passthrough запрещён).
- **FR-11 (отзыв и «Доступ для агентов»):** `GET /api/v1/me/oauth-grants` — подключённые облачные клиенты пользователя (клиент, дата подключения, последнее использование, статус); `DELETE /api/v1/me/oauth-grants/{id}` — отзыв гранта (все access- и refresh-токены сразу недействительны), идемпотентно, чужой грант — 404. Страница `/profile/agents` по макету `oauth-agents-clients` показывает два раздельных блока: «Облачные клиенты» (клиент, подключён, последнее использование, «Отключить»; таблица на 1280 px, карточки на 360 px; «Отключить» сразу закрывает доступ — Q-16) и «Токены для своих агентов» (`gtrk_`, «Активных токенов: N из 10»); облачные клиенты токенов не выпускают. Блокировка пользователя отключает его гранты без их удаления (проверка в FR-10). `POST /api/v1/oauth/revoke` (RFC 7009) отзывает по токену, всегда 200.
- **FR-12 (аудит и лента):** выдача гранта и отзыв пишутся в журнал аудита: `user.oauth_granted` и `user.oauth_revoked` (автор — пользователь; в `details` только название клиента `client`, без токенов, адресов и IP; IP — в журнал доступа приложения). Действия агента в ленте проектов подписываются клиентом: `ChatGPT (OAuth)` (поле `client_name`, ADR-0018 п. 6). Неудачные регистрации и отказы token endpoint в аудит не пишутся (только счётчик и журнал приложения).
- **FR-13 (лимиты):** регистрация — 20/час с IP; token endpoint — 60/мин с IP и 30/мин на клиента; согласий — не более 20 активных грантов на пользователя (21-й — ошибка на экране согласия); превышение — 429 `slow_down`/`rate_limited` с `Retry-After`. Неиспользуемые клиенты (без гранта) старше 7 суток и просроченные коды/токены удаляет `gtrack maintenance`.
- **FR-14 (безопасность ответов):** все ответы OAuth — `Cache-Control: no-store`, `Pragma: no-cache`; ошибки не раскрывают, существует ли пользователь; токены, коды и `code_verifier` не пишутся в логи и аудит.
- **FR-15 (настройка):** `PUBLIC_BASE_URL` ОБЯЗАТЕЛЕН для OAuth (без него метаданные и OAuth-endpoint отвечают 404 `feature_disabled`, `/mcp` ведёт себя как сейчас); схема `https`; издатель и `resource` строятся только из него, а не из `Host`/`X-Forwarded-*` (за nginx и Caddy схема запроса — `http`).

## 5. Нефункциональные требования
- **NFR-1 (безопасность):** OAuth 2.1 (только code + PKCE S256, без implicit, без пароля, без client credentials); точное сравнение `redirect_uri`; одноразовые коды; ротация и обнаружение повторного использования refresh; audience-проверка; короткий access; отзыв действует немедленно (проверка в БД на каждом запросе, как `gtrk_`); окно выдачи кода — 60 с.
- **NFR-2 (совместимость):** `gtrk_` и локальные клиенты работают без изменений (регрессионные тесты спеки 020); `/mcp` по-прежнему Streamable HTTP без сессий.
- **NFR-3 (исходящие запросы):** нет: DCR вместо CIMD (CIMD требует, чтобы AS скачивал документ клиента по URL), поэтому NFR-3 («трекер не делает исходящих запросов») не нарушается.
- **NFR-4 (производительность):** метаданные и `/mcp` с `gtat_` — p95 ≤ 200 мс на стенде пилота (один индексированный запрос по хешу); token endpoint — Argon2 не используется, только SHA-256.
- **NFR-5 (интерфейс):** экран согласия и блок «Облачные клиенты» — по UI-киту, строки в `ru.ts`, клавиатура, контраст AA, 360 px без горизонтальной прокрутки; макеты готовы: `Shared/Design/gtrack-oauth/` (2026-11-12).
- **NFR-6 (доступность для клиентов):** ответы discovery, регистрации и token укладываются в 10 с (требование Claude); WAF/прокси не блокируют диапазоны Anthropic `160.79.104.0/21` и OpenAI.

## 6. Вне рамок
CIMD (Client ID Metadata Documents; требует исходящих запросов — отдельная спека при необходимости, Q-2); `client_secret` и конфиденциальные клиенты (`client_secret_*`, `private_key_jwt`); OpenID Connect (`id_token`, `userinfo`); разные scope «только чтение» (Q-8); инструменты `search`/`fetch` для режима deep research ChatGPT; mTLS от OpenAI и IP-фильтрация (Q-12); шлюз в DMZ (ADR-0022, поправка 2026-11-12); облачные клиенты для ТА; отдельный AS (Keycloak и т. п.); протокол ИБ по провайдерам.

## 7. Модель угроз (кратко, обязательна до реализации)
| Угроза | Мера |
|---|---|
| Открытый DCR используют для спама и фишинга | allowlist `redirect_uri` (только известные клиенты и loopback), лимиты, потолок 500 клиентов, очистка неиспользуемых; согласие всегда показывает имя и домен |
| Подмена `client_name` («ChatGPT») злоумышленником | на экране согласия — домен `redirect_uri`; имя клиента — только по регистрации; на allowlisted хосты имя не доверяется «брендом» (Q-3) |
| Перехват кода | PKCE S256, код 60 с и одноразовый, привязка к `redirect_uri`; повторное использование отзывает токены |
| Кража refresh-токена | ротация, обнаружение повторного использования → отзыв гранта; потолок 90 суток |
| Токен выдан другому ресурсу / passthrough | audience = `<PUBLIC_BASE_URL>/mcp`; токен принимает только `/mcp`; REST токены OAuth не принимает |
| CSRF на «Разрешить» | сессионный cookie `SameSite=Lax`, проверка Origin, подписанный контекст запроса; решение — только POST |
| Clickjacking экрана согласия | CSP `frame-ancestors 'none'` и `X-Frame-Options: DENY` уже на всех ответах nginx |
| Open redirect | только точное сравнение с зарегистрированными и разрешёнными URI; ошибки `client_id`/`redirect_uri` — страница, не редирект |
| Раскрытие данных облачной модели | решение владельца 2026-11-08 (данные разрешены); права токена = права пользователя; отзыв и аудит; протокол ИБ — отдельно |
| Перебор токенов / код | 256 бит случайности, хеш в БД, лимиты на token endpoint |
| Неверный issuer за прокси | `issuer` только из `PUBLIC_BASE_URL`; тест на совпадение с `authorization_servers` |

## 8. Маршрутизация (для деплоя, прод: Caddy → nginx → api)
На проде nginx берётся из серверного `/etc/task-tracker/nginx.conf` (PR #23 переносит его в репозиторий; пока тот в draft, правки нужны в обоих местах). Сейчас `location /` отдаёт `index.html` для любого неизвестного пути, поэтому без новых блоков `/.well-known/oauth-*` вернёт HTML (200) вместо JSON, и клиент не пройдёт discovery.

| Путь | Куда | Изменение nginx |
|---|---|---|
| `/mcp` | api | уже есть (`location ~ ^/mcp/?$`); 401 с `WWW-Authenticate` проходит как есть |
| `/.well-known/oauth-protected-resource` и `…/mcp` | **api** | **новый** `location ^~ /.well-known/oauth-protected-resource` |
| `/.well-known/oauth-authorization-server`, `/.well-known/openid-configuration` | **api** | **новый** `location ^~ /.well-known/oauth-authorization-server` и `location = /.well-known/openid-configuration` |
| `/oauth/authorize` | **SPA** (страница согласия) | не нужно: `location /` уже отдаёт SPA |
| `/api/v1/oauth/*` (token, register, revoke, authorize/context, authorize/decision) | api | не нужно: `location /api/` уже проксирует; `client_max_body_size` достаточен |
| `/api/v1/me/oauth-grants*` | api | не нужно |

Прокси-блок для новых `location` — как у `/mcp` (`resolver`, `proxy_set_header Host $http_host`, `X-Forwarded-Proto/For`). Caddy: убедиться, что он передаёт на nginx все пути хоста (включая `/.well-known/*`; на нём возможны собственные обработчики ACME — они не затрагивают `oauth-*`). Токены в `Authorization` и заголовок `WWW-Authenticate` nginx не трогает. Если администратор предпочтёт держать OAuth-endpoint по путям `/oauth/token`, `/oauth/register`, понадобятся ещё два `location` на api — это Q-9 (рекомендация: не нужно, пути под `/api/v1/oauth/`).

## 9. Миграция (одна, аддитивная: `0014_mcp_oauth`)
Таблицы: `oauth_client` (client_id, client_name, redirect_uris, created_at, last_used_at), `oauth_grant` (user_id, client_id, scope, refresh-хеш, срок и потолок, ротационное «семейство», created_at, last_used_at, revoked_at), `oauth_code` (хеш, client_id, user_id, redirect_uri, challenge, resource, scope, expires_at, used_at), `oauth_token` (access: хеш, grant_id, expires_at, revoked_at), `oauth_attempt` (счётчики лимитов, по образцу `registration_attempt`). Номер `0014` свободен (REGISTRY); откат — `drop table`. Права рабочей роли БД (`gtrack_app`): SELECT/INSERT/UPDATE/DELETE; триггеры не нужны. Миграцию согласует оркестратор до написания.

## 10. Критерии приёмки
- **AC-1** (FR-1, FR-2, FR-15): Given `PUBLIC_BASE_URL=https://t.example` When `GET /.well-known/oauth-protected-resource/mcp` и `/.well-known/oauth-authorization-server` Then JSON с `resource=https://t.example/mcp`, `issuer=https://t.example`, `authorization_servers=[issuer]`, `code_challenge_methods_supported=["S256"]`; тесты за прокси со схемой `http` дают тот же `issuer`; без `PUBLIC_BASE_URL` — 404.
- **AC-2** (FR-3): Given `/mcp` без токена, с просроченным и с отозванным токеном Then 401 и `WWW-Authenticate: Bearer resource_metadata="https://t.example/.well-known/oauth-protected-resource/mcp"`; `gtrk_` работает как раньше (регрессия спеки 020).
- **AC-3** (FR-4): Given регистрация `redirect_uris=["https://chatgpt.com/connector/oauth/abc123"]` Then 201 и `client_id`, без `client_secret`; `http://…`, `https://localhost/…`, адрес с userinfo или фрагментом → 400 `invalid_redirect_uri`; 21-я регистрация за час с IP → 429.
- **AC-4** (FR-5): Given неверный `client_id` или `redirect_uri` Then страница ошибки без редиректа; `code_challenge_method=plain` → редирект с `invalid_request`; `resource=https://other.example/mcp` → `invalid_target`.
- **AC-5** (FR-6, FR-7): Given пользователь без сессии When открыт `/oauth/authorize?…` Then уход на `/login` и после входа возврат на тот же запрос; «Разрешить» → редирект на `redirect_uri?code&state&iss`; «Отклонить» → `error=access_denied&state&iss`; подмена параметров между показом и решением → ошибка.
- **AC-6** (FR-8): Given код и верный `code_verifier` Then 200 с `access_token`, `refresh_token`, `expires_in=3600`; неверный verifier, чужой `redirect_uri`, повторный код, просроченный код (61 с) → `invalid_grant`; повторное использование кода отзывает выданные токены.
- **AC-7** (FR-8, FR-9): Given refresh Then новый refresh, старый → `invalid_grant`; повторное предъявление старого refresh отзывает грант; refresh старше 90 суток от выдачи → `invalid_grant`.
- **AC-8** (FR-10): Given `gtat_` Then `/mcp` отвечает инструментами по роли пользователя; токен с чужим audience, просроченный, отозванный, при заблокированном пользователе, `must_change_password` → отказ; `gtat_` на `/api/v1/me` → 401.
- **AC-9** (FR-11): Given грант Then он виден в `GET /me/oauth-grants`; `DELETE` → следующий вызов `/mcp` — 401; чужой грант — 404; повтор — 204 без ошибки; блокировка пользователя отключает токены.
- **AC-10** (FR-12): Given выдача и отзыв Then в журнале аудита `user.oauth_granted` / `user.oauth_revoked` с автором и названием клиента без токенов; вызовы агента в ленте подписаны «ChatGPT (OAuth)».
- **AC-11** (FR-13): Given лимиты When превышены Then 429 с `Retry-After`; `gtrack maintenance` удаляет неиспользуемых клиентов старше 7 суток и просроченные коды и токены (счётчики в выводе).
- **AC-12** (NFR-2, NFR-5): Given экран согласия и блок «Облачные клиенты» Then 360 px без прокрутки, клавиатура, подписи из `ru.ts`; фокус на заголовке.
- **AC-13** (интеграция, вручную, стенд пилота): Given коннектор ChatGPT с адресом `https://<адрес>/mcp` Then подключение проходит от добавления до вызова инструмента; то же для Claude.ai (веб); результат и скриншоты — в `reviews/FINAL-acceptance.md`.

## 11. Допущения и зависимости
- Прод доступен из интернета по HTTPS (Caddy), `PUBLIC_BASE_URL` задан (используется письмами); проверить значение до выкатки.
- Зависит от PR #23 (nginx в репозитории) только в части репозиторного шаблона; прод правится на сервере оркестратором.
- ChatGPT и Claude.ai меняют требования; перед реализацией перечитать страницы из §2 (особенно отмеченные [сниппет]) и проверить подключение на живом стенде (AC-13).

## 12. Решения владельца (2026-11-12, «да делай»; вопросы Q-1…Q-18 закрыты ответами по умолчанию)
Спорные пункты помечены **[спорно]**: реализация не блокируется, решение можно пересмотреть отдельно.
- **Название клиента (Q-15)** — `client_name` из DCR, рядом домен `redirect_uri`; нет `client_name` — только домен. **[спорно]** Это отличается от моей рекомендации (подставлять название по хосту из allowlist): имя клиента указывает он сам и может назваться «ChatGPT»; защита — домен адреса возврата на том же экране.
- **«Отключить» (Q-16)** — сразу отзывает все access- и refresh-токены этого клиента у пользователя (весь грант).
- **Права (Q-8, Q-17)** — как у `gtrk_`: права пользователя; единственный scope `mcp`.
- **Сроки (Q-4, Q-18)** — согласие действует до отзыва; access-токен 1 час; refresh-токен 90 суток с ротацией при каждом использовании (потолок 90 суток от выдачи, который я предлагал, снят: пока клиент пользуется токеном, доступ не истекает; **[спорно]** — безопасность выше с потолком).
- **Хранение и аудит** — refresh и access хранятся хешем, как `gtrk_`; аудит выдачи и отзыва.
- **Лимиты (Q-7)** — ограничение частоты по IP для регистрации и `/oauth/token`; прочие числа — как в FR-13.
- **`redirect_uri` (Q-3)** — только `https`, точное совпадение с зарегистрированным; **allowlist хостов и loopback не вводятся** (Claude Code остаётся на `gtrk_`); при регистрации отвергаются адреса с userinfo, фрагментом, IP-адресом и `localhost`. Необязательная настройка оператора `OAUTH_REDIRECT_HOSTS` (список разрешённых хостов; пусто — любой https-хост) оставлена как защитный рычаг. **[спорно]** Открытая регистрация любого https-адреса повышает риск фишинга; смягчение — домен возврата на экране согласия, лимиты, очистка неиспользуемых клиентов.
- Остальные вопросы (Q-1, Q-2, Q-5, Q-6, Q-9…Q-14) — по рекомендациям §12 ниже. Q-5: каждое согласие — отдельный грант (повторное подключение того же клиента создаёт новый, старый остаётся в списке).
- Миграция `0014_mcp_oauth` разрешена, выкатку с `ALLOW_MIGRATIONS=1` делает оркестратор. Дизайн-проверка и сквозной тест с настоящим ChatGPT — после выкатки, вместе с владельцем.

**Окончательно (2026-11-13, подтверждено оркестратором):** вопросы Q-3, Q-4, Q-5 решены так, как одобрил владелец и как реализовано в PR #47 — `redirect_uri` только https с точным совпадением и без allowlist; refresh 90 суток с ротацией (без абсолютного потолка); каждое согласие — новый грант. Более раннее сообщение с allowlist, потолком 90 суток и одним грантом на пару пользователь+клиент отменено. **Бэклог (усиление на будущее):** allowlist redirect URI (настройка `OAUTH_REDIRECT_HOSTS` уже есть как рычаг оператора; фиксированный список ChatGPT/Claude по умолчанию — отдельной задачей), абсолютный потолок refresh 90 суток от выдачи гранта, один грант на пару пользователь+клиент.

## 12а. Вопросы и рекомендации (исходный список)
| # | Вопрос | Варианты | Рекомендация |
|---|---|---|---|
| Q-1 | Кто выдаёт токены | (а) свой минимальный AS в api; (б) внешний провайдер OIDC | (а): пользователи и сессии уже в трекере, внешнего провайдера нет; решено и в поправке к ADR-0022 |
| Q-2 | Регистрация клиентов | (а) только DCR; (б) DCR + CIMD | (а): оба клиента (ChatGPT, Claude) поддерживают DCR; CIMD требует исходящих запросов (NFR-3, SSRF) |
| Q-3 (снят решением владельца: только https, точное совпадение, без allowlist) | Какие `redirect_uri` разрешены при регистрации | (а) фиксированный список: `https://chatgpt.com/connector/oauth/*`, `https://chatgpt.com/connector_platform_oauth_redirect`, `https://claude.ai/api/mcp/auth_callback`, `https://claude.com/api/mcp/auth_callback`, loopback `http://localhost|127.0.0.1:<порт>/…`; новые — через настройку оператора; (б) любые HTTPS | (а): иначе открытая регистрация даёт фишинговые редиректы |
| Q-4 | Сроки токенов | access 1 ч; refresh 30 суток скользящий, потолок 90 суток (ADR-0022: ≤ 90) | как указано; короче access — чаще refresh, длиннее — дольше окно кражи |
| Q-5 | Повторное подключение одного клиента | (а) каждое согласие — новый грант (старый остаётся, виден в списке); (б) один грант на пару пользователь+клиент (новое согласие заменяет) | (б) по `client_name`+домену `redirect_uri` — список не засоряется; но (а) проще; выбор владельца |
| Q-6 | Кто может подключать облачные клиенты | БА и «Пользователь»; ТА — нет (у него нет бизнес-данных, ADR-0013) | как указано |
| Q-7 | Лимиты | регистрация 20/ч с IP, не более 500 клиентов; token 60/мин с IP; 20 активных грантов на пользователя | как указано |
| Q-8 | Права токена | (а) один scope `mcp` = все права пользователя (как у `gtrk_`); (б) добавить scope «только чтение» для ChatGPT | (а) сейчас; (б) — отдельной спекой, если ИБ потребует |
| Q-9 | Пути token/register | (а) под `/api/v1/oauth/…` (nginx менять не надо); (б) `/oauth/token`, `/oauth/register` | (а): меньше правок серверного nginx |
| Q-10 | Дополнительные метаданные | `authorization_response_iss_parameter_supported: true` и алиас `/.well-known/openid-configuration` | включить оба: ChatGPT при поддержке `iss` использует стабильный redirect, а discovery по OIDC — запасной путь |
| Q-11 | Что показывать на экране согласия | «Разрешить «<клиент>» доступ к GTrack? Он сможет видеть и менять ваши проекты и задачи с вашими правами», домен `redirect_uri`, «Разрешить»/«Отклонить» (макет — Design Agent) | подтвердить текст |
| Q-12 | mTLS от OpenAI и IP-фильтр ChatGPT/Claude | не делать в первой поставке | не делать: IP-списки неполны, mTLS требует настройки Caddy; вернуться после ИБ |
| Q-13 | Режим deep research ChatGPT (`search`/`fetch`) | вне рамок | вне рамок; отдельная спека, если понадобится |
| Q-15 | Откуда берутся название клиента и адрес возврата на экране согласия (вопрос Design Agent) | (а) название — из регистрации клиента (`client_name` при DCR, его вводит сам клиент и ему нельзя доверять); (б) для известных адресов из allowlist (chatgpt.com → «ChatGPT», claude.ai/claude.com → «Claude») название подставляет сервер, для остальных — `client_name` с пометкой «название указал сам клиент»; адрес возврата показывать всегда (мелко) | (б): имя из allowlist нельзя подделать; адрес не скрывать даже у «доверенных» — это защита от подмены |
| Q-16 | «Отключить» облачный клиент: что отзывается (вопрос Design Agent) | (а) весь грант: все access- и refresh-токены сразу, клиент должен пройти согласие заново; (б) только текущий access | (а): на макетах «сразу закрывает доступ»; единственный честный смысл отзыва |
| Q-17 | Набор прав (scope) облачного клиента: как у `gtrk_` или уже (вопрос Design Agent) | (а) один набор «видеть и изменять проекты и задачи» с правами пользователя, как у `gtrk_`; (б) выбор по пунктам или «только чтение» | (а) сейчас: макеты показывают один набор; (б) — отдельная спека (см. Q-8); экран согласия называет ровно то, что клиент сможет делать |
| Q-18 | Срок действия согласия и повторный вход (вопрос Design Agent) | (а) согласие живёт, пока не отозвано; access 1 ч, refresh 30 суток скользящий, потолок 90 суток от выдачи, после потолка клиент снова проходит согласие (вход в GTrack только если нет сессии); (б) требовать повторный вход каждые N дней | (а): тот же потолок 90 суток, что у `gtrk_` (ADR-0018); повторный ввод пароля не нужен, но экран согласия появится снова |
| Q-14 | Кого подключаем первым для проверки | ChatGPT и Claude.ai (веб) на стенде пилота с тестовыми данными, потом прод | как указано; реальные данные — после протокола ИБ (ADR-0022) |

## 13. Оценка
≈ 9–11 рабочих дней: ядро OAuth и миграция — 4; интеграция с `/mcp`, 401, лимиты, аудит, maintenance — 2; экран согласия, возврат после входа, блок «Облачные клиенты» — 2; nginx/доки/деплой — 0,5; тесты безопасности и интероперабельности — 1,5; живая проверка ChatGPT и Claude — 1. Риски: расхождение клиентов со спекой (требует итераций на живом стенде); ограничения регистрации с IP облаков; задержка протокола ИБ (не блокирует разработку, блокирует реальные данные).
