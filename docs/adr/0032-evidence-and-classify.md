# ADR 0032: evidence, mode и classify_task на миграции 0019

- Статус: предложено
- Дата: 2026-11-18
- Спека: 036 (CD-07, CD-10, CD-11); расширяет 033

## Решение
Новых ревизий alembic нет. Миграция **0019** (`down_revision=0018`) добавляет колонки
DoD/блокера (033) **и** `task.mode`, `task_dod_criterion.kind` / `evidence_ref` /
`evidence_note`. Номера 0020 и 0021 заняты другими сессиями.

`mode` — `routine|research`, по умолчанию `routine`. Классификатор MCP `classify_task`
без LLM: эвристика по тексту и критериям. Без `commit` не пишет. Слой знаний (CD-08)
в этом срезе отсутствует: `can_run_without_human=false` (спека 038 FR-8), не 500.
Коды `missing`: `source`, `completeness`, `verification`, `evidence`.

Research без трёх критериев (источник, полнота, проверка) не создаётся (`dod_required`).
`done` по-прежнему только человек (`human_close_only`).
