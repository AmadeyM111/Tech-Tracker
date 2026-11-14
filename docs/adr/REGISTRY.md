# Реестр номеров ADR, спек и миграций

Номер занимается записью в этот файл **до** создания документа. Проверка перед записью:
`git fetch --all && git ls-tree --name-only -r <ветка> docs/adr specs backend/migrations/versions`
по всем веткам (`git branch -r`). Снимок: 2026-11-11 (R3: спеки 024–026 APPROVED; 027 DRAFT).

## ADR
| № | Тема | Где | Статус |
|---|---|---|---|
| 0001–0014 | см. файлы `docs/adr/` | main | принято |
| 0015 | `0015-activity-feed-returned.md` и `0015-export-import-in-mvp.md` — дубль номера (исторический) | main | принято; не переиспользовать |
| 0016 | `0016-export-import-in-mvp.md` | main | принято |
| 0017 | Сброс пароля по email | main | принято |
| 0018 | MCP-доступ агентов | main | принято |
| 0019 | Самостоятельная регистрация по email (фича 019) | `feat/self-registration` | предложено |
| 0020 | `0020-agent-access.md` (ключи агентов R7) | `feat/r1.0-foundation` | занят |
| 0021 | Удаление пользователей (спека 023) | предложено спеке 023 | резерв |
| 0022 | Облачные MCP-клиенты: OAuth 2.1 на /mcp (вариант B; обновлён 2026-11-12, спека 028) | `docs/adr/0022-cloud-mcp-clients.md` | принято |
| 0023 | Выгрузка выборки «Сводки» в CSV: право, формат, предел, аудит (спека 025) | `docs/adr/0023-summary-csv-export.md` | принято (R3, 2026-11-10) |
| 0025 | Пересмотр ADR-0018 в части OAuth: облачные клиенты через OAuth 2.1 на /mcp (спека 028) | `docs/adr/0025-oauth-revises-adr-0018.md` | принято 2026-11-12 |
| 0024 | Личные проекты «Пользователя» (спека 027) | `docs/adr/0024-personal-projects.md` (ветка `docs/personal-projects-spec`) | принято 2026-11-11 |
| 0026 | Внешние провайдеры входа и правила привязки (спека 029) | `docs/adr/0026-external-login-and-linking.md` (ветка `docs/login-simplify-spec`) | принято |
| 0027+ | ADR — с 0027 (0025 занят OAuth, 0026 — входом) | — | свободно |

## Спеки
| № | Тема | Где |
|---|---|---|
| 001–007 | R1, роли, экраны, сброс пароля | main |
| 007 | `007-ai-agent-tools` (дубль номера) | `feat/r1.0-foundation` |
| 008 | «Сводка» (R2 T-03) | `feat/r2-dashboard` |
| 009 | Резервная копия и восстановление (R2 T-01) | резерв R2 |
| 010 | Роли БД и защита журнала (R2 T-02) | резерв R2 |
| 011 | Вложения (R2 T-04) | резерв R2 |
| 012 | Упоминания и уведомления (R2 T-05) | резерв R2 |
| 016 | Нагрузочный замер (R2 T-10) | резерв R2 |
| 019 | Регистрация | main |
| 024 | «Сводка»: диапазон дат срока «с / по» (R3) | `specs/` (R3), APPROVED 2026-11-10 |
| 025 | «Сводка»: выгрузка CSV для БА (R3) | `specs/` (R3), APPROVED 2026-11-10 |
| 026 | Карточка «Подключить ИИ-агента» на «Сводке» (R3, T-13) | `specs/` (R3), APPROVED 2026-11-10 |
| 030 | Усиление OAuth: allowlist redirect URI и потолок refresh (APPROVED 2026-11-13) | `specs/030-oauth-hardening/` (ветка `feat/oauth-hardening`) |
| 028 | OAuth 2.1 на /mcp для облачных клиентов (ChatGPT, Claude.ai), T-14 — APPROVED 2026-11-12 | `specs/028-mcp-oauth/` (ветка `docs/mcp-oauth-spec-028`) |
| 027 | Личные проекты «Пользователя» (APPROVED 2026-11-11, ветка `docs/personal-projects-spec`) | `specs/027-personal-projects/` |
| 029 | Упрощённый вход: email или логин, «Запомнить меня», magic link, Яндекс ID / VK ID / Google (DRAFT, ветка `docs/login-simplify-spec`) | `specs/029-login-simplify/` |
| 020 | MCP AI Native | main |
| 021–023 | заняты (023 — удаление пользователей, черновик) | — |

## Миграции alembic
| № | Тема | Где |
|---|---|---|
| 0001–0009 | R1, роли, приоритеты, сброс пароля, MCP | main (0009 на проде) |
| 0008 | `0008_agent_api_keys` — конфликт с main | `feat/r1.0-foundation` |
| 0010 | `0010_self_registration` | `feat/self-registration` |
| 0011–0013 | R2: `backup_run`, `attachment`, `notification` | main (на проде, 2026-11-10) |
| 0014 | свободен (резерв под 026 снят: состояние в браузере) | — |
| 0015 | Упрощённый вход: внешние идентичности, токены входа, `password_hash` nullable (спека 029, предварительно — номер подтвердить после `0014` из `feat/mcp-oauth`) | предложено, ветка `docs/login-simplify-spec` |
