# Spec: слои знаний (`knowledge_record`)

- **ID:** 037-knowledge-records
- **Статус:** DRAFT
- **Дата:** 2026-11-18
- **Кастдев:** CD-08, CD-09, аналитик Яндекса 2026-11-18
- **ADR:** 0033
- **Миграция:** 0021 `knowledge_record` (`down_revision=0018`; 0019 и 0020 не занимать)
- **Связано:** спека 035 (commit как у `propose_entities`), ADR-0018

## 1. Контекст и цель
Урок из проекта не переносится в новый, если живёт только в нём. Слой пространства
держит факты среды выше проектов. Запись, на которую можно опереться, — решение,
причина или договорённость, не пересказ чата. Агент предлагает, человек подтверждает
`commit=true` (как CD-06).

## 2. Пользовательские сценарии
- Как участник проекта B, я вижу space-записи, сделанные в проекте A.
- Как участник только B, я не вижу project-записи проекта A.
- Как агент, я читаю слой пространства до работы в проекте.
- Как человек, я подтверждаю запись `commit=true`; без commit в БД 0 строк.

## 3. Функциональные требования
- **FR-1:** Таблица `knowledge_record`: `scope` `space`|`project`, `project_id` NULL
  при `space` и NOT NULL при `project`, `kind` `decision`|`reason`|`agreement`,
  `title` (1–255), `body` (1–10000), `confirmed_by`, `client_name` (имя MCP-клиента
  или NULL), `confirmed_with` обязательно при `agreement`.
- **FR-2:** Проект видит свои записи и слой пространства. Чужие project-записи скрыты.
- **FR-3:** MCP `list_knowledge` (чтение): фильтры `scope`, `project_id`, страница.
  С `project_id` — проверка как у проекта (404 чужое пространство / 403 не-участник),
  в выдаче — записи этого проекта и space. Без `project_id` — space плюс project-слой
  проектов, где актор участник.
- **FR-4:** MCP `get_knowledge` (чтение): space — как чтение space; project — как
  содержимое проекта. Не-участник: 403/404 как у проекта.
- **FR-5:** Запись в space: БА этого пространства (`business_admin` в
  `workspace_member`). Не «глобальный БА» вне пространства. «Пользователь» пишет
  только project-слой проектов, где участник.
- **FR-6:** MCP `upsert_knowledge` (запись). Аргументы: `scope`, `project_id`
  (нужен при `scope=project`), `type`, `title`, `body`, `confirmed_with` (для
  `agreement`), `commit` (по умолчанию false), необязательный `knowledge_id` (обновление).
- **FR-7:** Без `type` из `decision`|`reason`|`agreement` или без обязательных полей
  (что решили / почему / кто подтвердил; для agreement — с кем) — 422
  `knowledge_unstructured`, 0 строк.
- **FR-8:** Без `commit=true` ответ — черновик, **0** строк в `knowledge_record`.
  С `commit=true` — INSERT/UPDATE и `client_name` текущего MCP-клиента.
- **FR-9:** Описание каждого инструмента ≤ 100 символов.

## 4. Нефункциональные требования
- **NFR-1:** без wiki, векторного поиска, Viking, LLM на сервере.
- **NFR-2:** UI списка/карточки не обязателен: MCP покрывает AC.
- **NFR-3:** миграция аддитивна, без ALTER `task`.

## 5. Критерии приёмки
- **AC-1:** Given запись `scope=space` When участник второго проекта `list_knowledge`
  Then запись в `items`.
- **AC-2:** Given запись `scope=project` A When участник только проекта B Then её нет
  в списке.
- **AC-3:** Given не-участник When `list_knowledge` с `project_id` Then 403/404 как у проекта.
- **AC-4:** Given текст без `type` When `upsert_knowledge` Then 422 `knowledge_unstructured`,
  в БД 0.
- **AC-5:** Given `decision` + причина без `commit` When вызов Then черновик, в БД 0.
- **AC-6:** Given `commit=true` When вызов Then запись видна команде в слое; `client_name`
  токена сохранён.

## 6. Вне рамок
Viking, векторный поиск, wiki, харнесс, CRM, DoD, `task.mode`, ingest/stuck.

## 7. Допущения
- «Пространство» = `workspace`. Владельца у `workspace` нет: пишет БА пространства.
- Аудит `client_name` — колонка записи (каталог `domain_event` §10.5 не расширяем).
