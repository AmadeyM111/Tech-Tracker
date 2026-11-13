# Spec: усиление OAuth на /mcp — allowlist redirect URI и потолок refresh-токена

- **ID:** 030-oauth-hardening
- **Статус:** APPROVED (задача оркестратора 2026-11-13; бэклог спеки 028 §12 «Окончательно», решения владельца 2026-11-12/13)
- **Дата:** 2026-11-13
- **Основание:** спека 028 (OAuth на `/mcp`, PR #47), ADR-0022, ADR-0025.

## 1. Контекст и цель
В 028 динамическая регистрация клиентов принимает любой `https`-адрес возврата, а refresh-токен продлевается при каждом использовании без предела.
Это два открытых места усиления: (а) открытая регистрация даёт площадку для фишинга (злоумышленник регистрирует клиента со своим адресом и просит согласие
под именем «ChatGPT»); (б) украденный refresh-токен при регулярном использовании живёт бесконечно. Спека закрывает оба без миграций.

## 2. Требования
- **FR-1 (allowlist redirect URI):** `POST /api/v1/oauth/register` ДОЛЖЕН принимать `redirect_uri` только с хостом из списка `OAUTH_REDIRECT_HOSTS` (через запятую, без учёта
  регистра, точное совпадение хоста: субдомены и «похожие» хосты не проходят). По умолчанию список — `chatgpt.com,claude.ai,claude.com`: callback-хосты облачных клиентов
  по их официальной документации (§4). Значение `*` отключает проверку хоста (осознанное ослабление; в README помечено). Остальные правила 028 не меняются: только `https`,
  без userinfo и фрагмента, не IP и не `localhost` (в том числе при `*`). Один недопустимый адрес в `redirect_uris` отклоняет всю регистрацию: 400 `invalid_redirect_uri`.
- **FR-2 (потолок refresh):** refresh-токены гранта ДОЛЖНЫ действовать не позже `grant.created_at + OAUTH_REFRESH_MAX_DAYS` (по умолчанию 90 суток; допустимо 1–365).
  `expires_at` нового refresh = `min(выдача + 90 суток, потолок)`. Предъявление refresh после потолка — `invalid_grant`, а грант отзывается (access-токены перестают действовать, в списке
  «Облачные клиенты» статус «Отключён»); дальше — только новая авторизация (экран согласия). Ротация и обнаружение повторного использования refresh (028 FR-8) не меняются.
- **FR-3 (без миграций):** изменения — настройки и логика сервиса; схема БД не меняется.

## 3. Критерии приёмки
- **AC-1** (FR-1): Given настройка по умолчанию When регистрация с `https://chatgpt.com/connector_platform_oauth_redirect`, `https://chatgpt.com/connector/oauth/abc`, `https://claude.ai/api/mcp/auth_callback`, `https://claude.com/api/mcp/auth_callback` Then 201; `https://example.com/cb`, `https://sub.chatgpt.com/cb`, `https://chatgpt.com.evil.example/cb` Then 400 `invalid_redirect_uri`; список с одним чужим адресом — 400.
- **AC-2** (FR-1): Given `OAUTH_REDIRECT_HOSTS=example.com` Then принимается только он; `*` — любой https-хост, но `http`, `localhost`, IP по-прежнему 400.
- **AC-3** (FR-2): Given потолок 120 суток When refresh используется на 89-й и 118-й день Then 200; на 121-й — `invalid_grant`.
- **AC-4** (FR-2): Given потолок 100 суток When refresh на 80-й день Then новый refresh истекает на 100-й день (не на 170-й).
- **AC-5** (FR-2): Given потолок по умолчанию (90) When refresh на 91-й день Then `invalid_grant` и грант отозван.

## 4. Источники для allowlist (официальная документация, прочитано 2026-11-13)
- OpenAI, «Authentication» ([developers.openai.com/apps-sdk/build/auth](https://developers.openai.com/apps-sdk/build/auth)): стабильный `https://chatgpt.com/connector_platform_oauth_redirect` и специфичный `https://chatgpt.com/connector/oauth/{callback_id}`; единственный назван хост `chatgpt.com`; отдельных тестовых и устаревших хостов страница не называет; в allowlist сервера авторизации — точный URI из панели управления сервером.
- Anthropic, «Authentication for connectors» ([claude.com/docs/connectors/building/authentication](https://www.claude.com/docs/connectors/building/authentication)): `https://claude.ai/api/mcp/auth_callback` для claude.ai, Desktop, мобильных и Cowork; справочная статья ([support.anthropic.com/en/articles/11503834](https://support.anthropic.com/en/articles/11503834)) предупреждает о возможном переходе на `https://claude.com/api/mcp/auth_callback`, поэтому `claude.com` включён заранее. Claude Code — loopback `http://localhost:<порт>/callback`: наш сервер loopback не принимает, Claude Code остаётся на токенах `gtrk_` (ADR-0018).
- Повторная проверка документации (страницы OpenAI и Anthropic) — при выкатке и при смене требований облачных клиентов; новые хосты добавляются настройкой `OAUTH_REDIRECT_HOSTS` без релиза.

## 5. Вне рамок
Проверка пути `redirect_uri` (только хост); allowlist по `client_name`; один грант на пару пользователь+клиент; CIMD.

## 6. Оценка
≈ 0,5 дня: настройки и сервис, тесты, документация.
