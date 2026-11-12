# Tasks: OAuth 2.1 на /mcp (028)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор. Spec DRAFT: задачи не берутся до APPROVED; миграцию `0014` согласует оркестратор.

## Общие условия
- ID — `M28-Tnn`; рамки: `python scripts/task_scope.py M28-Tnn`. Не трогать `CLAUDE.md`, `AGENTS.md`, `docs/adr/**`, `spec.md`, применённые миграции, общий `ui.css`.
- БД — только `*_test`. Проверка: `bash scripts/check.sh`. Оценка пакета ≈ 9–11 дней.

## M28-T01 — Миграция и модели
- **Статус:** TODO · **AC:** — · **Оценка:** 1 день
- **Файлы:** `backend/migrations/versions/0014_mcp_oauth.py`, `backend/app/oauth/models.py`, `backend/app/oauth/__init__.py`, `backend/app/domain/registry.py`, `backend/app/core/db_roles.py`, `docs/data-model.md`, `backend/tests/db/test_028_schema.py`, `backend/tests/db/test_migrations.py`, `backend/tests/db/test_007_schema.py`, `backend/tests/upgrade002_support.py`
- **Готово, когда:** upgrade/downgrade 0013 ↔ 0014 проходят; права рабочей роли проверены.

## M28-T02 — Настройка, метаданные, 401 с `resource_metadata`
- **Статус:** TODO · **AC:** AC-1, AC-2 · **Оценка:** 1 день · **Зависит от:** M28-T01
- **Файлы:** `backend/app/core/config.py`, `backend/app/oauth/metadata.py`, `backend/app/api/wellknown.py`, `backend/app/main.py`, `backend/app/api/mcp/endpoint.py`, `backend/tests/api/test_028_metadata.py`
- **Готово, когда:** документы совпадают с §4 спеки; `issuer` не зависит от `Host`/`X-Forwarded-*`.

## M28-T03 — Динамическая регистрация и лимиты
- **Статус:** TODO · **AC:** AC-3 · **Оценка:** 1 день · **Зависит от:** M28-T01
- **Файлы:** `backend/app/oauth/registration.py`, `backend/app/oauth/limits.py`, `backend/app/api/v1/oauth.py`, `backend/app/api/v1/__init__.py`, `backend/tests/api/test_028_register.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`
- **Готово, когда:** allowlist URI, 20/ч с IP, потолок клиентов, `invalid_redirect_uri`.

## M28-T04 — Запрос авторизации, подписанный контекст, выдача кода
- **Статус:** TODO · **AC:** AC-4, AC-5 · **Оценка:** 1,5 дня · **Зависит от:** M28-T03
- **Файлы:** `backend/app/oauth/authorize.py`, `backend/app/api/v1/oauth.py`, `backend/tests/api/test_028_authorize.py`
- **Готово, когда:** ошибки `client_id`/`redirect_uri` без редиректа, `iss` во всех ответах, подмена контекста отклоняется.

## M28-T05 — Token endpoint (code, refresh, ротация, отзыв)
- **Статус:** TODO · **AC:** AC-6, AC-7 · **Оценка:** 1,5 дня · **Зависит от:** M28-T04
- **Файлы:** `backend/app/oauth/tokens.py`, `backend/app/api/v1/oauth.py`, `backend/tests/api/test_028_token.py`
- **Готово, когда:** PKCE S256, одноразовость кода, ротация и обнаружение повтора, потолок 90 суток, `invalid_grant`.

## M28-T06 — Проверка `gtat_` на `/mcp`, лента и аудит
- **Статус:** TODO · **AC:** AC-8, AC-10 · **Оценка:** 1 день · **Зависит от:** M28-T05
- **Файлы:** `backend/app/api/mcp/endpoint.py`, `backend/app/domain/tokens/service.py`, `backend/app/domain/events/catalog.py`, `backend/app/domain/events/writer.py`, `backend/tests/unit/test_event_catalog.py`, `backend/tests/api/test_028_mcp_oauth.py`
- **Готово, когда:** audience, блокировка, `must_change_password`; `gtrk_` без регрессий; клиент в ленте.

## M28-T07 — Гранты пользователя и отзыв
- **Статус:** TODO · **AC:** AC-9 · **Оценка:** 0,75 дня · **Зависит от:** M28-T06
- **Файлы:** `backend/app/oauth/service.py`, `backend/app/api/v1/me_oauth.py`, `backend/app/api/v1/__init__.py`, `backend/tests/api/test_028_grants.py`, `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`
- **Готово, когда:** список, отзыв, идемпотентность, чужой грант — 404; RFC 7009 revoke.

## M28-T08 — Очистка и лимиты token endpoint
- **Статус:** TODO · **AC:** AC-11 · **Оценка:** 0,5 дня · **Зависит от:** M28-T05
- **Файлы:** `backend/app/domain/ops/maintenance.py`, `backend/app/cli/commands/maintenance.py`, `backend/tests/cli/test_maintenance.py`, `backend/tests/api/test_028_limits_maintenance.py`
- **Готово, когда:** счётчики в выводе `gtrack maintenance`, `Retry-After` на 429.

## M28-T09 — Экран согласия, возврат после входа
- **Статус:** TODO · **AC:** AC-5, AC-12 · **Оценка:** 1,25 дня · **Зависит от:** M28-T04 (макет Design Agent до старта)
- **Файлы:** `frontend/src/features/oauth/ConsentPage.tsx`, `frontend/src/features/oauth/api.ts`, `frontend/src/features/oauth/oauth.css`, `frontend/src/app/router.tsx`, `frontend/src/features/auth/LoginPage.tsx`, `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/oauth/ConsentPage.test.tsx`, `backend/tests/infra/test_frontend_scaffold.py`
- **Готово, когда:** vitest, lint, typecheck зелёные; возврат только на `/oauth/authorize`.

## M28-T10 — Блок «Облачные клиенты» в «Доступе для агентов»
- **Статус:** TODO · **AC:** AC-9, AC-12 · **Оценка:** 0,75 дня · **Зависит от:** M28-T07
- **Файлы:** `frontend/src/features/tokens/AgentAccessPage.tsx`, `frontend/src/features/tokens/CloudClients.tsx`, `frontend/src/features/tokens/api.ts`, `frontend/src/features/tokens/agent-connect.css`, `frontend/src/shared/i18n/ru.ts`, `frontend/tests/features/tokens/CloudClients.test.tsx`
- **Готово, когда:** карточки на 360 px, отзыв с подтверждением.

## M28-T11 — nginx, документация, чек-лист деплоя
- **Статус:** TODO · **AC:** AC-1 · **Оценка:** 0,5 дня · **Зависит от:** M28-T02
- **Файлы:** `deploy/web/default.conf.template`, `deploy/web/README.md`, `backend/tests/infra/test_nginx_variants.py` (если PR #23 слит), `docs/ai-integration.md`, `README.md`
- **Готово, когда:** новые `location /.well-known/oauth-*` в шаблоне; в README — шаги для серверного nginx и проверка `curl`.

## M28-T12 — Безопасность и интероперабельность
- **Статус:** TODO · **AC:** AC-13 · **Оценка:** 2 дня (1,5 тесты безопасности + 0,5 разбор итераций) · **Зависит от:** M28-T10, M28-T11
- **Файлы:** `backend/tests/api/test_028_security.py`, `docs/acceptance/mvp-demo.md`, `specs/028-mcp-oauth/reviews/FINAL-acceptance.md`
- **Готово, когда:** негативные тесты зелёные; ChatGPT и Claude.ai (веб) подключены на стенде пилота, результат записан.
