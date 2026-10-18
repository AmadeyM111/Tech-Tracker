# Финальная приёмка 004 «Задача в боковом меню, без создания на Доске» — ACCEPT WITH REMARKS
Блокирующих замечаний нет. Ручные AC-37 (клавиатура и экранный диктор), AC-40 (скорость диалога, 50 проектов), AC-43 (сверка с `docs/ui/button-task.png`) — за владельцем (`docs/acceptance/mvp-demo.md`).
## Прогоны
- `git diff --stat e43d435 -- backend docs/api frontend/src/shared/api/schema.d.ts` и `frontend/package*.json` — пусто.
- frontend: lint, typecheck чисто; `npm test` — 43 файла, 1196 passed.
- `pytest -q -m infra_static backend/tests/infra/test_docs_static.py backend/tests/infra/test_frontend_scaffold.py` — 290 passed.
- НЕ выполнялись: `bash scripts/check.sh`, полный `pytest -q backend/tests` (бэкенд не тронут; указание владельца).
- Мёртвый код: `boards.add_task|create_*`, `.ui-add-task`, `.ui-create-form*`, `CreateResult`, `createTask` в boards/api.ts, `canCreate` у BoardView — отсутствуют.
## Покрытие AC
AC-1…AC-36, AC-41, AC-42 — зелёные тесты (таблица AC → тест в отчёте ревьюера; файлы: BoardCreate, BoardFilter, CreateTaskDialog, CreateTaskDialogSubmit, create-task-button, preselect, projects/api, create-button, theme, sidebar, navigation, icons); AC-37, AC-40, AC-43 — ручные; AC-38, AC-39 — частично (check.sh и полный backend-pytest не запускались).
## Отклонения от plan (не внесены в plan; описаны в reviews и tasks.md)
1. Инвалидация кэша без ожидания (`void`), `onCreated` сразу после 201 (R5-T03-1).
2. Окно привязано к пути (`createPath`), закрывается при смене пути (router.tsx).
3. Флаг «смонтирован» и ref `created`; исключение `onCreated` — в console.error (R5-T03-1).
4. `.ui-create-dialog { width: min(24rem, 100%) }`.
## Остаток (желательные)
1. AC-4: тест кладёт новую карточку в «Готово», а не в «К выполнению» — поправить тест или формулировку AC.
2. AC-9/AC-12 на реальной карточке `/tasks/<id>`; AC-27 — открыть вкладку «Задачи» до создания; убрать запасной литерал `?? "Задача"`.
3. Описание подготовки данных в пункте 004/AC-40 (кто создаёт 25 проектов, чем мерить).
4. Внести отклонения 2–4 в plan §4.4; после щелчка по подложке Shift+Tab в Chromium может увести фокус за окно (нет `inert`) — тот же образец у окна смены пароля.
5. Остатки ревью R5-T01 (параллельность карточек, переименование теста в `004_ac41_*`), R5-T02, R5-T06-T07 (имя describe, нумерация контракта в helpers.tsx), 003 FINAL (GuestOnly, FOREIGN state, фокус при «Назад», переименование `admin.home_*_link`).
