# Spec: evidence, mode и classify_task

- **ID:** 036-evidence-and-classify
- **Статус:** DRAFT
- **Дата:** 2026-11-18
- **Кастдев:** CD-07 + CD-11 + CD-10, 2026-11-18
- **ADR:** 0032
- **Миграция:** 0019 (та же, что спека 033; `down_revision` 0018)
- **Связано:** 033 (DoD/блокер), 035 (`propose_entities`)

## 1. Контекст и цель
CD-01 не пускает `done` без критериев, но не требует внешнего факта. Крупная задача
без источника, полноты и проверки — не задача. Нужны тип `evidence`, `task.mode`
и классификатор `routine|research`. Слой знаний (CD-08) в этом PR нет.

## 2. Функциональные требования

### CD-07 evidence
- **FR-1:** У критерия `kind=checklist|evidence` (по умолчанию `checklist`).
  У `evidence`: `evidence_ref` (URL или id, 1–500) и `evidence_note` (текст, 0–500).
- **FR-2:** Обязательный `evidence` без `evidence_ref` считается открытым: `done` → 422 `dod_open`.
- **FR-3:** MCP `check_dod_criterion` с `evidence_ref` отмечает критерий; `done` при
  `human_close_only` агенту — 403. Человек при закрытых обязательных — 200.
- **FR-4:** `GET /tasks/{id}` и MCP `get_task`: в `dod.missing_artifacts` тексты открытых
  обязательных `evidence`.

### CD-11 research без DoD
- **FR-5:** `create_task` / `propose_entities` с `mode=research` без критериев, покрывающих
  «источник», «полнота», «проверка» → 422 `dod_required`, в `detail` шаблон этих трёх пунктов,
  задачи нет.
- **FR-6:** Подзадачи с `evidence` допустимы. Родитель не `done` при открытом своём DoD (033 FR-3).
- **FR-7:** `propose_entities` без `commit=true` — 0 строк (спека 035).

### CD-10 mode и classify_task
- **FR-8:** У задачи `mode=routine|research`, по умолчанию `routine`.
- **FR-9:** MCP `classify_task`: вход `text` и/или `task_id`; выход `mode`, `missing`
  (`source` / `completeness` / `verification` / `evidence`), `can_run_without_human`,
  `task_id`, `committed`. Без `commit` — 0 записей. С `commit=true` пишет только `mode`
  (нужен `task_id`), не `done`. Контракт ответа сверён со спекой 038.
- **FR-10:** `research` + агент `done` → 403. Слоя знаний (CD-08) нет:
  `can_run_without_human=false` (038 FR-8), не 500.

## 3. Приёмка
- **AC-07-1:** обязательный evidence пуст → PATCH `done` 422 `dod_open`.
- **AC-07-2:** агент отмечает evidence с URL → критерий закрыт, `client_name` в аудите;
  тот же агент `done` → 403.
- **AC-07-3:** все evidence закрыты, человек `done` → 200.
- **AC-11-1:** research только с заголовком → create 422 `dod_required`, задачи нет.
- **AC-11-2:** три дочерние с закрытым evidence, DoD родителя открыт → родитель `done` 422;
  DoD родителя закрыт → 200.
- **AC-11-3:** `propose_entities` без `commit` → 0 строк.
- **AC-10-1:** «сравни нас с конкурентом» без источников → `research` + `missing` с `source`, в БД 0.
- **AC-10-2:** routine, DoD и evidence закрыты, слоя CD-08 нет → `routine`, `can_run_without_human=false`.
- **AC-10-3:** research, агент `done` → 403.

## 4. Вне рамок
Авторазбор CI; Viking; `knowledge_record`; харнесс; merge/деплой.
