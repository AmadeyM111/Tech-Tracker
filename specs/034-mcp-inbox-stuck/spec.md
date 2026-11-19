# Spec: inbox MCP и застрявшая работа

- **ID:** 034-mcp-inbox-stuck
- **Статус:** DRAFT
- **Дата:** 2026-11-16
- **Кастдев:** CD-02, CD-04 (ПМ 2026-11-16)

## 1. Контекст и цель
Агент уже сидит в Telegram. Нужно класть входящие в трекер через MCP, без веб-бота.
ПМ не ставит статусы: нужен список «застряло» — нет движения, а не просрочка сводки 008.

Дельта к 020/028. Не учётка агента (022), не DoD/блокер (0019 — другая сессия).

## 2. Пользовательские сценарии
- Как агент в Telegram, я хочу создать задачу или комментарий из сообщения, чтобы повтор
  того же сообщения не плодил дубликаты.
- Как ПМ, я хочу спросить агента, что зависло без галки, даже если срок ещё не вышел.

## 3. Функциональные требования
- **FR-1:** MCP `ingest_message`: `project_id`, `source` (старт — `telegram`), `external_id`,
  `text`, необязательные `task_id` и `url`. Пишущий инструмент. Права как у `create_task` /
  `add_comment`. Чужой проект — 404/403 как у `create_task`.
- **FR-2:** Нет `task_id` — создать задачу: описание = `text`, название — первая непустая
  строка (обрезка до 255), срок = сегодня по Europe/Moscow, исполнитель = вызывающий.
  Источник пишется в `external_message` (`task_id` задан, `comment_id` NULL).
- **FR-3:** Есть `task_id` — `add_comment` с телом `text`, статус задачи не менять.
  `external_message.comment_id` задан. Задача из другого проекта — как ненайденная.
- **FR-4:** Идемпотентность: повтор `(workspace_id, source, external_id)` — та же сущность,
  HTTP/MCP 200, новая строка не создаётся.
- **FR-5:** `get_task` показывает `source` и `source_url` задачи, если она создана ingest
  (строка с `comment_id IS NULL`). `list_comments` — то же у комментария из ingest.
  Иначе оба поля `null`. REST те же поля.
- **FR-6:** MCP `list_stuck_work` — только чтение, виден при `mcp:read`. Задачи в проектах,
  где актор участник или владелец, не `done`, последнее движение (max `task.updated_at`
  и `comment.created_at`) не позже чем 48 часов назад. Просроченный `due_date` — поле
  `overdue`, не единственный критерий попадания в список. Сводку 008 не дублировать.
- **FR-7:** `blocked` и `open_dod`: если колонок нет в схеме процесса — `null`, без ошибки.
  Когда 0019 в main, оркестратор довяжет.

## 4. Нефункциональные требования
- **NFR-1:** миграция 0020 — новая таблица `external_message`, без ALTER `task`.
  `down_revision=0019` (после 0021→0019 на main).
- **NFR-2:** веб-бота Telegram нет.

## 5. Критерии приёмки
- **AC-1** (FR-2, FR-5): Given ingest без `task_id` When `get_task` Then описание = текст,
  `source=telegram`, `source_url` = переданный url.
- **AC-2** (FR-3, FR-5): Given ingest с `task_id` When `list_comments` Then новый комментарий
  с тем текстом, `source=telegram`; статус задачи прежний.
- **AC-3** (FR-4): Given повтор тех же `source`+`external_id` Then та же `task_id`/`comment_id`,
  число задач не выросло.
- **AC-4** (FR-1): Given проект, где актор не участник When ingest Then `forbidden`
  (как `create_task` в том же пространстве), строки `external_message` нет.
- **AC-5** (FR-6): Given задача не `done` без комментариев 48 ч When `list_stuck_work`
  Then она в списке; `overdue` true только если срок раньше сегодняшней даты МСК.
- **AC-6** (FR-6): Given комментарий только что When `list_stuck_work` Then этой задачи нет.
- **AC-7** (FR-6, FR-7): Given `mcp:read` When `tools/list` Then `list_stuck_work` есть,
  `ingest_message` нет; `blocked` и `open_dod` в ответе — `null`, пока нет колонок.

## 6. Вне рамок
- Веб-бот Telegram, CRM, харнесс, `is_agent`, DoD-таблица, ALTER `task`, спека 020, 022.

## 7. Допущения
- Ключ идемпотентности — `(workspace_id, source, external_id)`.
- Пишущие tools при read-only по-прежнему `forbidden` (032).
