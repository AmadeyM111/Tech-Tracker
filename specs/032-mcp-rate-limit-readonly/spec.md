# Spec: лимит частоты MCP и read-only scope

- **ID:** 032-mcp-rate-limit-readonly
- **Статус:** DRAFT
- **Дата:** 2026-11-15

## 1. Контекст и цель
Публичный `/mcp` принимает `gtrk_` и OAuth `gtat_`. При компрометации токена нет тормоза
на частоту вызовов. Наблюдателю (152-ФЗ, prompt injection в комментарии) нужен токен без записи.
Это дельта к 020/028, не учётки агента (022) и не короткий ключ задачи.

## 2. Пользовательские сценарии
- Как пользователь, я хочу выдать агенту токен только на чтение, чтобы он видел задачи и не менял их.
- Как пользователь, я хочу, чтобы скомпрометированный токен упёрся в 120 вызовов в минуту.

## 3. Функциональные требования
- **FR-1:** Система ДОЛЖНА ограничивать `tools/call` 120 вызовами в минуту на идентификатор
  токена (`api_token.id` или OAuth access id). Превышение — HTTP 429, `code=rate_limited`,
  заголовок `Retry-After`. `initialize` и `tools/list` в лимит не входят.
- **FR-2:** Система ДОЛЖНА принимать флаг `read_only` при выдаче `gtrk_`. Старые токены без флага —
  полный доступ. `tools/list` скрывает пишущие инструменты; вызов пишущего — `forbidden`.
- **FR-3:** OAuth scope `mcp:read` без `mcp` ДОЛЖЕН давать тот же read-only. Scope `mcp` — запись.
  `offline_access` не меняет права MCP.
- **FR-4:** На экране «Доступ для агентов» ДОЛЖЕН быть чекбокс «Только чтение», 44 px, кит.

## 4. Нефункциональные требования
- **NFR-1:** счётчик частоты — в памяти процесса, без Redis.
- **NFR-2:** миграция аддитивна: `api_token.read_only boolean NOT NULL default false`.

## 5. Критерии приёмки
- **AC-1** (FR-1): Given 120 `tools/call` за минуту When 121-й Then 429 `rate_limited` и `Retry-After`.
- **AC-2** (FR-1): Given 119 вызовов When 120-й Then 200, инструмент выполнен.
- **AC-3** (FR-2): Given `read_only=true` When `tools/list` Then нет `create_task`, `update_task`,
  `create_subtask`, `create_project`, `add_comment`; `list_my_tasks` есть.
- **AC-4** (FR-2): Given `read_only=true` When `tools/call` `create_task` Then ошибка `forbidden`.
- **AC-5** (FR-2): Given токен без флага (как до миграции) When `create_task` Then выполняется.
- **AC-6** (FR-4): Given форма выдачи When чекбокс включён Then POST `{name, read_only: true}`.

## 6. Вне рамок
- Учётка агента, `is_agent`, ключи `GT-12`, A2A, свой харнесс, правка спеки 020.

## 7. Допущения
- Один воркер API на пилоте; при нескольких процессах лимит считается отдельно.
- Пишущие инструменты: `create_task`, `create_subtask`, `update_task`, `create_project`, `add_comment`.
