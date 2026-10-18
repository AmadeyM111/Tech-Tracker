# Tasks: Создание задачи — кнопкой «Задача» в боковом меню вместо колонок Доски (spec 004)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия для всех задач R5

- Источник истины — `specs/004-no-board-create/spec.md` v0.2 (дельта к 001, 002, 003).
  Интерфейсы и решения — `specs/004-no-board-create/plan.md` (разделы указаны в задачах).
  Боковое меню, `Sidebar`, `RoleScreen` — `specs/003-no-home-screen/plan.md` §4.3. Ссылки без
  префикса ведут на 004 (`AC-9` = 004/AC-9), на другие спецификации — с префиксом
  (`003/AC-30`). Если задача противоречит spec или plan, вернуть `PLAN_ISSUE` и ничего не
  додумывать.
- **Начало — после R4-T11** (003 принята; решение владельца, Q-7).
- **Только фронтенд.** Код меняется в `frontend/src`, тесты — в `frontend/tests`. Не трогать:
  `backend/**`, `docs/api/**`, `frontend/src/shared/api/schema.d.ts`, `frontend/package.json`,
  `frontend/package-lock.json`, `CLAUDE.md`, `docs/STATE.md`, `specs/002-three-roles/*`,
  `specs/003-no-home-screen/spec.md`. `specs/001-pilot-r1/*` меняет только R5-T08.
- **Новых файлов в `frontend/src` не создавать** (003 plan D-7, 004 plan D-2). Новые файлы в
  `frontend/tests` разрешены.
- Окружение и команды — как в `specs/003-no-home-screen/tasks.md`, «Общие условия»: из
  `frontend/` выполняются `npx vitest run <файлы>`, `npm run lint`, `npm run typecheck`, полный
  `npx vitest run` разрешён.
- Тесты пишет test-writer, исполнитель их не меняет. В задаче **«только тесты»** код поставки
  не меняется. Красный тест на текущем коде — это `PLAN_ISSUE`.
- **Старые тесты (NFR-6)** — правила и таблица в plan §6.2. Тест создания из колонки
  удаляется, только если его заменитель уже есть и назван в комментарии. Без замены можно
  удалить только тесты, отмеченные так в spec, раздел 9. Поле «Старые тесты → AC» сверяет
  ревьюер.
- Новые тесты называются `004_acN_*`. Фикстуры — plan §5 (`create-dialog-helpers.tsx`).
  Строки интерфейса — только из `ru.ts`. «Задача» и «Новая задача» искать по роли и
  контейнеру (`button` в `.ui-sidebar`, `dialog`), а не по всему экрану (plan §8, R-3).
- «Проверки фронтенда» = `cd frontend && npm run lint && npm run typecheck && npx vitest run`
  (весь набор зелёный). «Бэкенд не тронут» = `git diff --stat e43d435 -- backend docs/api frontend/src/shared/api/schema.d.ts`
  пуст. Рамки файлов — `python scripts/task_scope.py R5-Tnn` из корня репозитория (выход 0).
- Линтер react-hooks 7: без `setState` в теле эффекта и без чтения `ref` при рендере.

Порядок и критический путь: R5-T01 → R5-T02 → R5-T03 → R5-T05 → R5-T06 → R5-T07 → R5-T08 →
R5-T10. R5-T04 можно делать параллельно с R5-T01…R5-T03 (нужна до R5-T05). R5-T09 можно
делать параллельно после R5-T05.

---

## R5-T01 — Доступные проекты и правило предвыбора (функции)
- **Статус:** TODO
- **AC:** AC-16, AC-17, AC-18 (отказ при ошибке) — на уровне функции; FR-9, FR-12 (правило
  для AC-20, AC-21, AC-41)
- **Файлы:** `frontend/src/features/projects/api.ts`, `frontend/src/features/tasks/CreateTaskForm.tsx`;
  тесты: `frontend/tests/features/projects/api.test.ts`, `frontend/tests/features/tasks/preselect.test.ts` (новый)
- **Зависит от:** R4-T11
- **Описание:** По plan §4.1 добавить в `projects/api.ts` `CreatableProject`,
  `CREATABLE_PAGE_SIZE = 100` и `listCreatableProjects()`: страницы `listProjects({ page, pageSize: 100 })`
  по очереди, пока `has_next`; затем `getProject(id)` для всех проектов через `Promise.all`;
  оставить `permissions.create_task === true` в порядке списка; вернуть `{ id, name }`. Любая
  ошибка — reject `ApiError` (без частичного результата). По plan §4.2 добавить в
  `CreateTaskForm.tsx` экспорт `preselectProject(projects, currentProjectId)`: проект страницы,
  если он в списке; иначе единственный; иначе `null`. Сам `CreateTaskForm` не менять.
  Test-writer: AC-16 (P1 = true, P2 = false, P3 = true → Альфа, Гамма); AC-17 (две страницы,
  запросы `?page=1` и `?page=2` с `page_size=100`, порядок сервера); пустой список → `[]` без
  запросов карточек; 500, 503 и сеть на списке или одной карточке → reject с кодом;
  `preselectProject` — все ветки FR-12 (страница доступна, недоступна + один доступный,
  недоступна + несколько, `null` + один, `null` + несколько, пустой список).
- **Старые тесты → AC:** нет.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/projects/api.test.ts tests/features/tasks/preselect.test.ts tests/features/tasks/CreateTaskForm.test.tsx`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R5-T01` → 0.
- **Попытки:** 0

## R5-T02 — Диалог «Новая задача»: состав, список, предвыбор, фокус, клавиатура
- **Статус:** TODO
- **AC:** AC-14 (кроме проверки «вне `nav`»), AC-15, AC-16, AC-17, AC-18, AC-19 (окно: текст,
  только «Закрыть», фокус на ней, Escape → `onClose`), AC-20, AC-21, AC-41 (по
  `currentProjectId`), AC-32 (Escape и «Отмена» → `onClose`, запросов нет), AC-33, AC-34;
  FR-8…FR-12, FR-19, FR-20
- **Файлы:** `frontend/src/features/tasks/CreateTaskForm.tsx`, `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/features/tasks/create-dialog-helpers.tsx` (новый),
  `frontend/tests/features/tasks/CreateTaskDialog.test.tsx` (новый)
- **Зависит от:** R5-T01
- **Описание:** По plan §4.2 (разметка и поведение) и D-3, D-5, D-6 добавить экспорт
  `CreateTaskDialog({ currentProjectId, onClose, onCreated })`. Загрузка через `useQuery`
  (`["projects","creatable"]`, `listCreatableProjects`, `retry: false`, `gcTime: 0`,
  `refetchOnMount: "always"`, `refetchOnWindowFocus: false`). Четыре состояния: загрузка,
  ошибка, пусто, готово. Выбор — `choice ?? preselectProject(...)`. Фокус: окно при монтаже,
  после загрузки — один перенос по FR-20. Ловушка Tab, Escape → `onClose()`, у подложки
  обработчика нет. Отправку в этой задаче не реализовывать: `onSubmit` только вызывает
  `preventDefault()` и ничего не отправляет (проверка ввода и запрос — R5-T03). В `ru.ts`
  добавить `tasks.project_label` «Проект», `tasks.project_placeholder` «Выберите проект»,
  `tasks.no_creatable_projects` «Нет проектов, в которых вы можете создавать задачи»,
  `tasks.dialog_close` «Закрыть».
  Test-writer: `create-dialog-helpers.tsx` по plan §5 (`P1`…`P3`, `projectCard`, `LIST_*`,
  две страницы, `T_NEW`, `renderDialog`, `deferred`). Тесты AC по шагам spec на окне без меню.
  AC-21 и AC-41 — через `currentProjectId: null` и id проекта задачи. AC-20 — `currentProjectId = P1`,
  а для `P2` (недоступен) проект не выбран и «Беты» нет. AC-33 — Tab и Shift+Tab (число
  элементов + 1) остаются внутри окна. AC-34 — `mouseDown` и `click` по `.ui-overlay` не
  вызывают `onClose`. Повторный монтаж запрашивает список заново (часть AC-18).
- **Старые тесты → AC:** нет.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/tasks/CreateTaskDialog.test.tsx tests/shared/i18n.test.ts`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R5-T02` → 0.
- **Попытки:** 0

## R5-T03 — Диалог: отправка, ошибки, повторная отправка, закрытие во время запроса
- **Статус:** TODO
- **AC:** AC-22, AC-23, AC-24, AC-25, AC-28, AC-30, AC-31 (Escape и «Отмена» во время запроса),
  AC-26 (вызов `onCreated` с задачей), AC-6 (форма вкладки «Задачи» без изменений); FR-13…FR-18
- **Файлы:** `frontend/src/features/tasks/CreateTaskForm.tsx`, `frontend/src/features/tasks/api.ts`;
  тесты: `frontend/tests/features/tasks/CreateTaskDialogSubmit.test.tsx` (новый)
  (+ `frontend/tests/features/tasks/create-dialog-helpers.tsx` — только добавить помощники)
- **Зависит от:** R5-T02
- **Описание:** По plan §4.3 добавить в `tasks/api.ts` `TaskCreateInput` и сменить тип
  параметра `createTask` (поведение не меняется). По plan §4.2 и D-8…D-10 реализовать
  отправку в `CreateTaskDialog`: защита `busy`; во время загрузки — выход; `trim`; пустое
  название или проект не выбран → одно `errorMessage("validation_error")`; иначе
  `createTask(projectId, { title })`. При 201 инвалидировать `["tasks","project",pid]`,
  `["board",pid]`, `["tasks","mine"]` и вызвать `onCreated(task)`. При ошибке —
  `errorMessage(code)`, введённое сохраняется. Пока запрос идёт: у кнопки отправки
  `aria-busy="true"` (без `disabled`), «Отмена» `disabled`, Escape игнорируется.
  Test-writer: AC-22 (`U`, предвыбор Альфа → выбрана Гамма → `POST …/P3/tasks`). AC-23 (`""`
  и `"   "`). AC-24. AC-25 (тело ровно `{ "title": "Отчёт" }`, для `BA` ключа `assignee_id`
  нет, `POST /tasks/*/move` нет). AC-28 (403 `forbidden`, 404, 422, 503 `service_busy`, сеть —
  одно `alert` в окне, `onCreated` не вызван, повтор шлёт второй запрос). AC-30 (два submit и
  клик — один запрос, `aria-busy` снимается после ответа). AC-31 (Escape и «Отмена» во время
  запроса — окно открыто, после 201 вызван `onCreated`). Успех: `onCreated` получил
  `T_NEW`, `onClose` не вызывался.
- **Старые тесты → AC:** нет (`CreateTaskForm.test.tsx` должен остаться зелёным без правок — AC-6).
- **Готово, когда:** `cd frontend && npx vitest run tests/features/tasks`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R5-T03` → 0.
- **Попытки:** 0

## R5-T04 — Вид кнопки «Задача»: иконка «+», раскладка меню, стиль-контракт
- **Статус:** TODO
- **AC:** AC-42 (CSS); FR-6 (цвета токенами, таблетка, одна строка, «Выйти» внизу)
- **Файлы:** `frontend/src/shared/ui/Icon.tsx`, `frontend/src/shared/ui/ui.css`;
  тесты: `frontend/tests/shared/create-button.test.ts` (новый), `frontend/tests/shared/theme.test.ts`
- **Зависит от:** R4-T11
- **Описание:** По plan §4.5 и D-7, D-11: в `Icon.tsx` добавить `"plus"` (`["M12 5v14", "M5 12h14"]`).
  В `ui.css`: из `.ui-sidebar button` убрать `margin-top: auto`, добавить
  `white-space: nowrap`; новое правило `.ui-sidebar [data-action="logout"] { margin-top: auto; }`.
  В `@media (max-width: 719px)` заменить правило `.ui-sidebar button { margin-top: 0; margin-left: auto; }`
  на `.ui-sidebar [data-action="logout"] { … }`. `.ui-overlay` — `z-index: 10`; новое правило
  `.ui-shell > .ui-overlay { margin: 0; }`. Новых цветов и токенов нет, правил `:hover` для
  кнопок нет. Кнопку «Задача» в разметку не добавлять (R5-T05).
  Test-writer: `create-button.test.ts::004_ac42_*` по plan §4.5 (статический разбор `ui.css`:
  цвета только `var(--…)`, `button` — `border-radius: 999px`, контраст `--button-text`/`--button-bg`
  ≥ 4.5 в обычном состоянии и при наведении, `--focus`/`--surface` ≥ 3; `.ui-sidebar [data-action="logout"]`
  с `margin-top: auto`; у `.ui-sidebar button` нет `margin-top: auto`; `.ui-sidebar button` —
  `white-space: nowrap`). Иконка `plus`: в `Icon.tsx` её `PATHS` отличается от `PATHS` других
  имён.
- **Старые тесты → AC:** `theme.test.ts`, блок «003: "Выйти" в боковом меню» (R4-T07):
  проверка `margin-top: auto` переносится с `.ui-sidebar button` на
  `.ui-sidebar [data-action="logout"]` → 003/AC-19, FR-6. `icons.test.tsx`, блок `.ui-icon styles`
  остаётся без правок (`.ui-sidebar button` — flex, `align-items: center`).
- **Готово, когда:** `cd frontend && npx vitest run tests/shared tests/app/icons.test.tsx`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R5-T04` → 0.
- **Попытки:** 0

## R5-T05 — Кнопка «Задача» в боковом меню и связка с диалогом
- **Статус:** TODO
- **AC:** AC-9, AC-10, AC-11, AC-12, AC-13, AC-14 (вне `nav`), AC-19 (кнопка видна, фокус на
  «Задача» после Escape), AC-20 (на вкладках «Доска», «Задачи», «Участники»), AC-26, AC-27,
  AC-29, AC-31 (путь после 201), AC-32 (фокус на «Задача»), AC-35, AC-36, AC-42 (разметка);
  FR-5, FR-6, FR-7, FR-15, FR-20…FR-22
- **Файлы:** `frontend/src/app/router.tsx`, `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/app/create-task-button.test.tsx` (новый), `frontend/tests/app/navigation.test.tsx`,
  `frontend/tests/app/icons.test.tsx`, `frontend/tests/app/sidebar.test.tsx`
  (+ `frontend/tests/features/projects/ProjectPage.test.tsx`, `frontend/tests/features/admin/UsersPage.test.tsx`,
  `frontend/tests/features/tasks/CreateTaskForm.test.tsx`, `frontend/tests/features/tasks/TaskList.test.tsx` —
  только если поиск по имени стал неоднозначным: уточнить контейнер или роль, проверку не
  ослаблять)
- **Зависит от:** R5-T03, R5-T04
- **Описание:** По plan §4.4 и D-7, D-9: в `Sidebar` при `business_access` между `nav` и
  «Выйти» — `button[type=button][data-action="create-task"][aria-haspopup="dialog"]` с
  `<Icon name="plus" />` и `t("nav.create_task")`. Состояние `createOpen`. Окно отрисовывается
  соседом `div.ui-sidebar` (`Sidebar` возвращает фрагмент), с
  `currentProjectId = useMatch("/projects/:projectId")?.params.projectId ?? null`. `onClose` —
  закрыть и вернуть фокус на кнопку. `onCreated` — закрыть и `navigate(`/tasks/${id}`)` (push).
  В `ru.ts` добавить `"nav.create_task": "Задача"`.
  Test-writer (`create-task-button.test.tsx`): AC-9 (`BA` и `U` на `/projects`,
  `/projects/P1` по вкладкам, `/tasks/:id`, `/my-tasks`, отказы `/admin/users` и `/admin/audit`:
  ровно одна кнопка, атрибуты, текст без иконки «Задача», первый дочерний — `svg[aria-hidden]`
  с рисунком, отличным от иконок меню и «Выйти»). AC-10, AC-11. AC-12 (порядок документа и
  Tab). AC-13 (точный набор запросов `/projects`, `/projects/P1`, `/my-tasks` — как без кнопки).
  AC-14 (`U` на `/my-tasks`, окно не внутри `nav`). AC-19 (`U` с пустым списком, `BA` со всеми
  `create_task = false`: Escape → фокус на «Задача»). AC-20 (вкладки). AC-26 (путь
  `/tasks/T_NEW`, `h1` карточки — активный элемент, «Назад» — исходный экран). AC-27 (после
  создания на `/my-tasks` открыть `/projects/P1`: карточка в «К выполнению» на Доске и на
  вкладке «Задачи» без тика опроса — фальшивые таймеры не продвигаются на 15 с). AC-29 (401 →
  `/login`). AC-31 (путь). AC-32 (Escape и «Отмена» → фокус на «Задача»). AC-35 (повторное
  открытие на `/projects/P1`: название пустое, Альфа, сообщений нет, список запрошен заново).
  AC-36 (одно окно, Tab не доходит до «Задача»). AC-42 (один `svg`, внутри нет других
  `button`, `a`, `[role]`).
- **Старые тесты → AC:** `navigation.test.tsx` — состав меню по ролям дополняется кнопкой →
  AC-9, AC-10; `icons.test.tsx` — проверка иконок `.ui-sidebar` охватывает «Задача» → AC-9;
  `sidebar.test.tsx::003_ac30_*` и `003_ac19_*` (`BA`, `U`) — порядок «ссылки, "Задача",
  "Выйти", содержимое», иконка первой у «Задача» → 003/AC-30, 003/AC-19, AC-12 (оговорка
  003/AC-30, spec 004, раздел 11).
- **Готово, когда:** `cd frontend && npx vitest run tests/app tests/features/projects tests/features/admin tests/features/tasks`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R5-T05` → 0.
- **Попытки:** 0

## R5-T06 — Доска без создания задач
- **Статус:** TODO
- **AC:** AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7; FR-1…FR-4; раздел 10 п. 3
- **Файлы:** `frontend/src/features/boards/BoardView.tsx`, `frontend/src/features/boards/api.ts`,
  `frontend/src/features/projects/ProjectPage.tsx`;
  тесты: `frontend/tests/features/boards/BoardCreate.test.tsx`, `frontend/tests/features/boards/BoardFilter.test.tsx`,
  `frontend/tests/features/boards/helpers.tsx`
- **Зависит от:** R5-T05
- **Описание:** По plan §4.6 и D-13 удалить из `BoardView.tsx` `CreateTask`, `CreateResult`,
  `onCreate`, проп `canCreate` (у `BoardView` и `Column`), `onInvalid`, неиспользуемые импорты.
  Шапку-комментарий исправить. Из `boards/api.ts` удалить `createTask` (остаются `getBoard`,
  `moveTask`, типы). В `ProjectPage.tsx` — `<BoardView projectId={project.id} />` (у
  `ProjectTaskList` `canCreate` остаётся). Оптимистичный перенос, блокировку, фильтр,
  объявления и общий блок сообщений не трогать (FR-2). Ключи `boards.*` и стили не удалять
  (R5-T07).
  Test-writer: `BoardCreate.test.tsx` переписать на тему «на Доске нет создания»: AC-1 (`BA`
  с правом, `U` с правом, `BA` без права — в колонках нет `button`, `form`, поля, текста
  `ru["boards.add_task"]`); AC-2 (перенос мышью и клавиатурой, фильтр, тик опроса, ошибка
  переноса — запросов `POST /api/v1/projects/{id}/tasks` нет); AC-7 (`U`, вкладка «Задачи» →
  один POST, задача в списке, вкладка «Доска» → карточка в «К выполнению», кнопки нет). Тест
  `t91_dictionary_keys_exist_with_expected_texts` пока оставить (R5-T07).
  `BoardFilter.test.tsx` — по plan §6.2 (AC-4, новый `004_ac5_*`). `helpers.tsx` — контракт и
  неиспользуемые помощники по plan §6.2.
- **Старые тесты → AC:** все строки plan §6.2 с задачей R5-T06 (`BoardCreate.test.tsx`: 14
  тестов → AC-1, AC-2, AC-23, AC-25, AC-28, AC-30, AC-31, AC-32, AC-35 или «без замены» по
  spec, раздел 9; `BoardFilter.test.tsx`: 2 теста → AC-4, AC-5; `helpers.tsx`). Перед
  удалением каждого теста убедиться, что названный заменитель существует и зелёный.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/boards tests/features/projects tests/features/tasks`
  зелёный; `git grep -n -E "add-task|board-create-task|cancel-create|CreateResult|canCreate" -- frontend/src/features/boards`
  пусто; `git grep -n "<BoardView" -- frontend/src/features/projects/ProjectPage.tsx` показывает
  `<BoardView projectId={project.id} />`; `git grep -n createTask -- frontend/src/features/boards/api.ts`
  пусто; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R5-T06` → 0.
- **Попытки:** 0

## R5-T07 — Словарь и стили создания из колонки удалены
- **Статус:** TODO
- **AC:** AC-8; NFR-2; раздел 10 пп. 1–2 (plan §9, П-1)
- **Файлы:** `frontend/src/shared/i18n/ru.ts`, `frontend/src/shared/ui/ui.css`;
  тесты: `frontend/tests/features/boards/BoardCreate.test.tsx`
- **Зависит от:** R5-T06
- **Описание:** Удалить из `ru.ts` ключи `boards.add_task`, `boards.create_form_label`,
  `boards.create_title_label`, `boards.create_submit`, `boards.create_cancel`,
  `boards.create_move_failed`. Удалить из `ui.css` правила `.ui-add-task`, `.ui-create-form`,
  `.ui-create-form-actions`. Перед удалением `git grep -n -E "boards\.(add_task|create_)|ui-add-task|ui-create-form" -- frontend/src`
  должен находить только сами определения.
  Test-writer: `BoardCreate.test.tsx::t91_dictionary_keys_exist_with_expected_texts` →
  `004_ac8_*`: ключей раздела 10 п. 1 нет; среди значений нет «Добавить задачу» и строки вида
  «Задача создана в колонке …, но не перенесена».
- **Старые тесты → AC:** `BoardCreate.test.tsx::t91_dictionary_keys_exist_with_expected_texts` → AC-8.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/boards tests/shared`
  зелёный; `git grep -n -E "boards\.(add_task|create_)|ui-add-task|ui-create-form" -- frontend/src`
  пусто; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R5-T07` → 0.
- **Попытки:** 0

## R5-T08 — Документы: spec 001 (v0.19) и пометка T91 в tasks 001
- **Статус:** TODO
- **AC:** spec 004, раздел 11 («Spec 001», пп. 1–2)
- **Файлы:** `specs/001-pilot-r1/spec.md`, `specs/001-pilot-r1/tasks.md`
- **Зависит от:** R5-T07
- **Описание:** По plan §10: дописать в пункт истории версий v0.19 (создан R4-T09) и в строку
  «Статус»: «создание задачи из колонки Доски (решение владельца 2026-10-16, T91, вне spec)
  снято; создание из бокового меню — дельта `specs/004-no-board-create/spec.md` v0.2
  (004/FR-1…FR-22)». Если v0.19 уже закоммичена отдельно и оркестратор требует новую версию,
  добавить v0.20 с тем же текстом. Текст требований 001 не менять (раздел 11 п. 3:
  противоречий нет). В `specs/001-pilot-r1/tasks.md`, T91, добавить строку
  `- **Пересмотрено:** …` по plan §10. Историю не переписывать.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `git diff` затрагивает только эти два файла: историю версий и статус в
  spec, одну строку в T91; бэкенд не тронут; `python scripts/task_scope.py R5-T08` → 0.
- **Попытки:** 0

## R5-T09 — Документы: пункты ручной проверки 004/AC-37, AC-40, AC-43
- **Статус:** TODO
- **AC:** AC-37, AC-40, AC-43 (*ручные*: пункты чек-листа)
- **Файлы:** `docs/acceptance/mvp-demo.md`
- **Зависит от:** R5-T05
- **Описание:** Добавить три незакрытых пункта `- [ ]` с шагами AC по spec на демо-данных:
  `004/AC-37` (`demo.ba1`, только клавиатура, Chromium, VoiceOver или NVDA: «Задача, кнопка»,
  «Новая задача, диалог»); `004/AC-40` (стенд 001/NFR-2, 50 проектов, БА участник 25, 20
  открытий, p95 ≤ 2 с, в списке 25 — подготовка данных описывается словами, без новых
  скриптов); `004/AC-43` (сравнение с `docs/ui/button-task.png`: светлая таблетка, «+» слева,
  «Задача» в одну строку, без шеврона, цвета как у «Выйти», фокус виден). В пункте UF-5 о
  Доске (если там упоминается создание) ничего не менять — создания там нет. Пути в обратных
  кавычках — только существующие. Пункты не упоминают `UF-3` вместе с `demo.ba2`.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `source .venv/bin/activate && pytest -q -m infra_static backend/tests/infra/test_docs_static.py`
  зелёный без правок теста; в чек-листе по одному пункту `004/AC-37`, `004/AC-40`, `004/AC-43`;
  бэкенд не тронут; `python scripts/task_scope.py R5-T09` → 0.
- **Попытки:** 0

## R5-T10 — Финальная приёмка 004
- **Статус:** TODO
- **AC:** AC-38, AC-39; AC-37, AC-40, AC-43 (*ручные* — передаются владельцу); сверка plan §6.1 и §6.2;
  дополнения к 003/AC-19, AC-27, AC-28, AC-30
- **Файлы:** нет (только проверки; дефекты — новые задачи R5-Tnn по решению оркестратора)
- **Зависит от:** R5-T01…R5-T09
- **Описание:** Выполнить и приложить итог:
  (1) `cd frontend && npm run lint && npm run typecheck && npm test`;
  (2) `bash scripts/check.sh` (тестовая БД — как в R4-T11);
  (3) AC-38: `git diff --stat e43d435 -- backend docs/api frontend/src/shared/api/schema.d.ts`
  пуст, `git diff e43d435 -- frontend/package.json` пуст;
  (4) AC-39/NFR-6: для каждого теста из spec, раздел 9 и plan §6.2 — где он теперь (новое имя,
  заменитель или «без замены» со ссылкой на spec, раздел 9);
  (5) мёртвый код (Q-8 а): `git grep -n -E "boards\.(add_task|create_)|ui-add-task|ui-create-form|data-action=\"add-task\"|CreateResult" -- frontend/src`
  пусто, в `frontend/src/features/boards/api.ts` нет `createTask`, у `BoardView` нет пропа
  `canCreate`;
  (6) каждый AC из plan §6.1 сопоставлен зелёному тесту (имя);
  (7) все тесты 003 зелёные, включая дополнения 004 к 003/AC-19, AC-27, AC-28, AC-30;
  (8) пункты `004/AC-37`, `004/AC-40`, `004/AC-43` есть в чек-листе. Ручные проверки
  выполняет владелец.
- **Старые тесты → AC:** итоговая сверка (п. 4).
- **Готово, когда:** пп. 1–8 выполнены, отчёт содержит команды и их итог; ручные AC отмечены
  как ожидающие владельца.
- **Попытки:** 0

---

## Ручные AC (сводка)

| AC | Где проверяется | Задача |
|---|---|---|
| AC-37 | `docs/acceptance/mvp-demo.md`, пункт `004/AC-37`; Chromium, клавиатура, экранный диктор | R5-T09, R5-T10 |
| AC-40 | `docs/acceptance/mvp-demo.md`, пункт `004/AC-40`; стенд 001/NFR-2, вне CI | R5-T09, R5-T10 |
| AC-43 | `docs/acceptance/mvp-demo.md`, пункт `004/AC-43`; сравнение с `docs/ui/button-task.png` | R5-T09, R5-T10 |
