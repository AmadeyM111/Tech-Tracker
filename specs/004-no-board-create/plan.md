# Plan: Создание задачи — кнопкой «Задача» в боковом меню вместо колонок Доски

- **Spec:** ./spec.md v0.2 (APPROVED, утверждена владельцем 2026-10-18)
- **Статус:** DRAFT
- **Основа:** `specs/003-no-home-screen/plan.md`. 004 выполняется после 003 (Q-7) и
  опирается на её `Sidebar`, `RoleScreen`, `data-action="logout"` (003 plan §4.3). Код
  `e43d435` с изменениями R4.
- **Правка 2026-10-18:** по финальной приёмке (`reviews/FINAL-acceptance.md`, отклонения 1–4,
  остаток п. 4) в §4.4 записаны принятые отклонения реализации от плана, в §9 уточнены П-1,
  П-3, П-5 и добавлен П-6 (риск: Shift+Tab после щелчка по подложке). Поведение кода не
  меняется.
- **Нумерация:** решения — `D-1…` (снаружи — `004/D-1`), задачи — `R5-T01…`. Новые тесты
  vitest называются `004_acN_*`.

## 1. Подход

Создание переносится с Доски в диалог, который открывает кнопка бокового меню. Сначала
появляется замена, потом удаляется старое: так тесты создания из колонки заменяются
готовыми тестами диалога, и ничего не удаляется «в пустоту» (NFR-6).

1. **Функции** (R5-T01): `listCreatableProjects()` читает все страницы списка проектов и
   карточку каждого проекта и оставляет проекты с `permissions.create_task` (Q-1 а).
   `preselectProject()` — чистое правило FR-12.
2. **Диалог** (R5-T02, R5-T03): компонент `CreateTaskDialog` — модальное окно «Новая задача»
   (проект, название, «Создать задачу», «Отмена»). Он сам загружает список, ставит фокус,
   держит Tab внутри, проверяет ввод, отправляет существующий
   `POST /api/v1/projects/{id}/tasks` с телом `{ title }` и сообщает об успехе вызывающему.
   Тестируется отдельно от меню.
3. **Кнопка** (R5-T04, R5-T05): иконка «+», раскладка меню (к низу прижимается только
   «Выйти»), затем кнопка «Задача» в `Sidebar` при `business_access`. Кнопка открывает
   диалог, после закрытия возвращает фокус на себя, после создания открывает карточку
   задачи.
4. **Уборка Доски** (R5-T06, R5-T07): из `BoardView` удаляется форма создания в колонке, из
   API Доски — дубликат `createTask`, со страницы проекта — передача права. Затем удаляются
   ключи словаря и стили (Q-8 а).
5. **Документы и приёмка** (R5-T08…R5-T10).

Бэкенд, API и OpenAPI не меняются. Новых файлов в `frontend/src` нет (003 plan D-7).

## 2. Решения

| ID | Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---|---|---|---|
| D-1 | Источник доступных проектов | `listCreatableProjects()` в `features/projects/api.ts`: страницы `GET /api/v1/projects?page=N&page_size=100` по очереди, пока `has_next`; затем `GET /api/v1/projects/{id}` для всех проектов параллельно (`Promise.all`); фильтр `permissions.create_task`; порядок — как в списке сервера. Любая ошибка — отказ всей загрузки (`ApiError`) | (а) новый эндпоинт; (б) по одной карточке последовательно; (в) показывать проекты без проверки права | (а) запрещено NFR-1 (Q-1 а). (б) медленно для NFR-4 (25 из 50 проектов за ≤ 2 с). (в) нарушает FR-9. `page_size=100` — предел сервера (`MAX_PAGE_SIZE`), так меньше страниц |
| D-2 | Где код диалога | `CreateTaskDialog` и `preselectProject` — в `features/tasks/CreateTaskForm.tsx`, рядом с существующей формой; функция загрузки — в `features/projects/api.ts` | (а) новые файлы `CreateTaskDialog.tsx`; (б) `ConfirmDialog` с другим содержимым | (а) запрещено белым списком `test_frontend_scaffold.py` и AC-38 (003 plan D-7, §9 П-2). (б) `ConfirmDialog` — `alertdialog` с двумя фиксированными кнопками. Существующая форма вкладки «Задачи» (`CreateTaskForm`) не меняется (FR-4) |
| D-3 | Загрузка списка в диалоге | `useQuery({ queryKey: ["projects", "creatable"], queryFn: listCreatableProjects, retry: false, gcTime: 0, refetchOnMount: "always", refetchOnWindowFocus: false })`. Диалог монтируется при открытии и размонтируется при закрытии | Ручной `useEffect` + `useState` | Образец репозитория — данные сервера через TanStack Query. `refetchOnMount: "always"` и `gcTime: 0` дают свежий список при каждом открытии (FR-9, FR-21, AC-18, AC-35) |
| D-4 | Предвыбор | Чистая `preselectProject(projects, currentProjectId)`. `currentProjectId` — из `useMatch("/projects/:projectId")` в `Sidebar` (вкладки проекта — состояние компонента, а не URL, поэтому «любая вкладка» выполняется). Выбор пользователя хранится как `choice: string \| null` (`null` — не трогал), показывается `choice ?? preselect` | Записывать предвыбор в состояние эффектом | FR-12. Без `setState` в эффекте (линтер react-hooks 7). Повторное открытие начинается заново, потому что компонент монтируется заново (FR-21) |
| D-5 | Фокус при открытии, пока список грузится | Фокус ставится на само окно (`div[role=dialog]` с `tabIndex={-1}`). Когда список загружен, фокус один раз переходит по FR-20 (поле названия, выбор проекта или «Закрыть»), если он всё ещё на окне | Сразу на поле названия | FR-20 не определяет фокус на время загрузки (§9, П-2). Фокус внутри окна, и перенос не мешает вводу |
| D-6 | Состав окна по состояниям | **Загрузка:** заголовок, `p[role=status]` «Загрузка…» (`admin.loading`) вместо выбора проекта, поле названия, «Создать задачу» с `disabled`, «Отмена». **Ошибка списка:** заголовок, одно `ErrorAlert` с `errorMessage(code)`, «Отмена». **Нет проектов:** заголовок, текст FR-11, только «Закрыть». **Готово:** заголовок, `ErrorAlert` (ввод и создание), выбор «Проект», «Название задачи», «Создать задачу», «Отмена» | Форма без полей до загрузки | FR-8, FR-10, FR-11, AC-18 (отправка во время загрузки не уходит: кнопка недоступна, и обработчик отправки сам проверяет загрузку) |
| D-7 | Где отрисовывается диалог | Соседом `div.ui-sidebar` внутри оболочки (`Sidebar` возвращает фрагмент). Не внутри `nav` и не внутри `.ui-sidebar` | (а) внутри `.ui-sidebar`; (б) портал в `body` | (а) правила `.ui-sidebar button` (flex, `margin-top: auto`) попали бы на кнопки окна; FR-19 запрещает размещение в `nav`. (б) Тесты и окно смены пароля работают без порталов. CSS: `.ui-shell > .ui-overlay { margin: 0 }` (иначе на окно действуют отступы `.ui-shell > *`), `.ui-overlay { z-index: 10 }` (карточки Доски с `transform` иначе рисуются поверх подложки) |
| D-8 | Запрос создания | Существующая `createTask` из `features/tasks/api.ts`, тип тела расширяется до `TaskCreateInput = Pick<TaskCreate, "title"> & Partial<TaskCreate>`. Диалог передаёт ровно `{ title }`. `createTask` из `features/boards/api.ts` удаляется | Вызывать `createTask` Доски | FR-14, раздел 10 п. 3 («дублирует существующую функцию»). `CreateTaskForm` продолжает передавать полный `TaskCreate` |
| D-9 | После успеха | Диалог инвалидирует `["tasks", "project", pid]`, `["board", pid]`, `["tasks", "mine"]` и вызывает `onCreated(task)`. `Sidebar` закрывает диалог без возврата фокуса и вызывает `navigate(`/tasks/${task.id}`)` (push). `TaskCard` сама ставит фокус на `h1` | `replace`; возврат фокуса на кнопку | FR-15: «Назад» ведёт на экран, где открывали диалог. AC-27: данные на следующем экране свежие и без опроса |
| D-10 | Повторная отправка и закрытие во время запроса | `busy` (ref) + `pending` (state). У кнопки отправки `aria-busy="true"`, `disabled` не ставится (как у формы T91-R). «Отмена» `disabled`, Escape игнорируется | — | FR-17, FR-18, AC-30, AC-31 |
| D-11 | Вид кнопки «Задача» | Стили кнопки по умолчанию (`button`: `--button-bg`, `--button-text`, `border-radius: 999px`, `:focus-visible` — `--focus`), иконка `plus` (`M12 5v14`, `M5 12h14`). В `ui.css` только раскладка: `.ui-sidebar button` без `margin-top: auto`, `+ white-space: nowrap`; `.ui-sidebar [data-action="logout"] { margin-top: auto }` и узкий экран `{ margin-top: 0; margin-left: auto }`. Правил `:hover` для кнопки нет, как у «Выйти» | (а) отдельный класс с новыми цветами; (б) шеврон-часть по образцу | FR-6: «вид по умолчанию — как у остальных светлых кнопок», «цвета только токенами», шеврона нет. Образец `docs/ui/button-task.png` — светлая таблетка «+ Task» с отделённым шевроном; шеврон отброшен решением владельца. Без переноса правила `margin-top: auto` обе кнопки делили бы свободное место, и «Задача» встала бы в середине панели |
| D-12 | Строки | Новые ключи: `nav.create_task` «Задача», `tasks.project_label` «Проект», `tasks.project_placeholder` «Выберите проект», `tasks.no_creatable_projects` «Нет проектов, в которых вы можете создавать задачи», `tasks.dialog_close` «Закрыть». Существующие: `tasks.create_title` «Новая задача», `tasks.title_label` «Название задачи», `tasks.create_submit` «Создать задачу», `admin.cancel` «Отмена», `admin.loading` «Загрузка…» | Взять `admin.entity.task` для подписи кнопки | NFR-2, Q-9. `admin.entity.task` — тип объекта журнала, у него другой смысл |
| D-13 | Мёртвый код (Q-8 а) | Удалить: `CreateTask`, `CreateResult`, `onCreate`, проп `canCreate` у `BoardView` и `Column`, `onInvalid`, лишние импорты (`FormEvent`, `KeyboardEvent`, `createTask`); `createTask` в `boards/api.ts`; `canCreate={permissions.create_task}` у `BoardView` в `ProjectPage.tsx` (у `ProjectTaskList` остаётся); ключи `boards.add_task`, `boards.create_form_label`, `boards.create_title_label`, `boards.create_submit`, `boards.create_cancel`, `boards.create_move_failed`; правила `.ui-add-task`, `.ui-create-form`, `.ui-create-form-actions` | — | Раздел 10. **Правила стилей на `e43d435` есть** (`ui.css`, стр. 404–421), а не отсутствуют, как сказано в разделе 10 п. 2. Spec сама требует удалить их в этом случае (§9, П-1) |
| D-14 | Основа сравнения для AC-38 | `e43d435` | `main` | Как 003 plan D-9 |

## 3. Затрагиваемые модули и файлы

Код (`frontend/src`):
- `features/projects/api.ts` — `CreatableProject`, `listCreatableProjects()` (R5-T01).
- `features/tasks/CreateTaskForm.tsx` — `preselectProject` (R5-T01), `CreateTaskDialog`
  (R5-T02, R5-T03). `CreateTaskForm` не меняется.
- `features/tasks/api.ts` — `TaskCreateInput`, тип параметра `createTask` (R5-T03).
- `shared/ui/Icon.tsx` — иконка `plus` (R5-T04).
- `shared/ui/ui.css` — раскладка кнопок меню, `.ui-overlay` (R5-T04); удаление стилей
  создания из колонки (R5-T07).
- `app/router.tsx` — кнопка «Задача» и диалог в `Sidebar` (R5-T05).
- `shared/i18n/ru.ts` — новые ключи (R5-T02, R5-T05), удаление ключей Доски (R5-T07).
- `features/boards/BoardView.tsx`, `features/boards/api.ts`, `features/projects/ProjectPage.tsx`
  — удаление создания из колонки (R5-T06).
- **Не меняются:** `CreateTaskForm` (форма вкладки «Задачи»), `SubtaskList.tsx`, `TaskPage.tsx`
  (уже ставит фокус на `h1`), `TaskList.tsx`, `dnd.ts`, `polling.ts`, `client.ts`,
  `package.json`.

Тесты (`frontend/tests`): новые — `features/tasks/preselect.test.ts`,
`features/tasks/create-dialog-helpers.tsx`, `features/tasks/CreateTaskDialog.test.tsx`,
`features/tasks/CreateTaskDialogSubmit.test.tsx`, `shared/create-button.test.ts`,
`app/create-task-button.test.tsx`; изменяются — §6.2.

Документы: `specs/001-pilot-r1/spec.md`, `specs/001-pilot-r1/tasks.md` (R5-T08),
`docs/acceptance/mvp-demo.md` (R5-T09).

## 4. Интерфейсы

### 4.1. Доступные проекты (`features/projects/api.ts`, R5-T01)

```ts
/** Проект, в котором текущий пользователь может создавать задачи (004/FR-9). */
export interface CreatableProject {
  id: string;
  name: string;
}

/** Размер страницы при полном чтении списка: предел сервера (core/pagination.py, MAX_PAGE_SIZE). */
export const CREATABLE_PAGE_SIZE = 100;

/**
 * 004/FR-9 (Q-1 а): все страницы GET /projects (page=1,2,… пока has_next, page_size=100), затем
 * GET /projects/{id} для каждого проекта параллельно; остаются проекты с permissions.create_task,
 * в порядке списка сервера. Любой не-2xx или сбой сети — reject ApiError (без частичного результата).
 */
export async function listCreatableProjects(): Promise<CreatableProject[]>;
```

### 4.2. Предвыбор и диалог (`features/tasks/CreateTaskForm.tsx`, R5-T01…R5-T03)

```ts
/**
 * 004/FR-12: проект страницы, если он доступен; иначе единственный доступный; иначе null.
 * Чистая функция.
 */
export function preselectProject(
  projects: readonly CreatableProject[],
  currentProjectId: string | null,
): string | null;

export interface CreateTaskDialogProps {
  /** id проекта из пути `/projects/:projectId` (любая вкладка) или null. */
  currentProjectId: string | null;
  /** Закрытие без создания: Escape, «Отмена», «Закрыть». Фокус возвращает вызывающий. */
  onClose: () => void;
  /** 201: задача создана, кэши инвалидированы. Вызывающий закрывает диалог и открывает карточку. */
  onCreated: (task: TaskDetail) => void;
}

export function CreateTaskDialog(props: CreateTaskDialogProps): JSX.Element;
```

Разметка (D-6):
```
div.ui-overlay
  div[role=dialog][aria-modal=true][aria-labelledby=<id>-title][tabindex=-1].ui-dialog  (onKeyDown: Escape, Tab)
    h2#<id>-title                       t("tasks.create_title")            «Новая задача»
    ErrorAlert                          одно сообщение: ошибка списка, ввода или создания
    — загрузка:  p[role=status] t("admin.loading"), форма с полем названия, submit disabled, «Отмена»
    — ошибка:    button[type=button][data-action=cancel] t("admin.cancel")
    — пусто:     p t("tasks.no_creatable_projects"); button[type=button][data-action=close] t("tasks.dialog_close")
    — готово:    form[data-form="create-task-dialog"][noValidate]
                   label[for=<id>-project] t("tasks.project_label")
                   select#<id>-project[name=project]: option[value=""] t("tasks.project_placeholder"), option[value=<id>] <name>…
                   label[for=<id>-title-input] t("tasks.title_label")
                   input#<id>-title-input[name=title][type=text][autocomplete=off]
                   button[type=submit][aria-busy=true пока запрос] t("tasks.create_submit")
                   button[type=button][data-action=cancel][disabled пока запрос] t("admin.cancel")
```
Поведение:
- **Отправка (FR-13, FR-14).** `busy.current` → выход. Идёт загрузка → выход без сообщения.
  `name = title.trim()`. Если `name === ""` или проект не выбран → одно
  `errorMessage("validation_error")`, запроса нет, введённое сохраняется. Иначе
  `createTask(projectId, { title: name })`.
- **Успех (FR-15).** `invalidateQueries` для `["tasks","project",pid]`, `["board",pid]`,
  `["tasks","mine"]`, затем `onCreated(task)`. Перезапросы не ожидаются (принятое отклонение,
  §4.4, О-1).
- **Ошибка (FR-16).** `errorMessage(e instanceof ApiError ? e.code : "unknown")`, проект и
  название сохраняются, `busy` снимается. 401 обрабатывает клиент (переход на `/login`,
  диалог размонтируется вместе с экраном).
- **Клавиатура (FR-20).** Escape → `onClose()`, если запрос не идёт (`stopPropagation`). Tab и
  Shift+Tab ходят по кругу по фокусируемым элементам окна (`input, select, button, [tabindex]:not([tabindex="-1"])`
  без `disabled`), как `onKeyDown` в `ChangePasswordPage`. Если фокус вне окна, он
  возвращается на первый элемент. У подложки нет обработчика щелчка.
- **Фокус при открытии (D-5).** Эффект монтирования: `dialogRef.current.focus()`. Когда данные
  пришли, эффект переносит фокус один раз: предвыбран проект → поле названия; проектов нет →
  «Закрыть»; иначе → выбор проекта. Перенос происходит, только если
  `document.activeElement === dialogRef.current`.

### 4.3. Запрос создания (`features/tasks/api.ts`, R5-T03)

```ts
/** Тело запроса создания: обязательно только название, остальное — значения сервера (004/FR-14). */
export type TaskCreateInput = Pick<TaskCreate, "title"> & Partial<TaskCreate>;

export async function createTask(projectId: string, body: TaskCreateInput): Promise<TaskDetail>;
// тело уходит как есть: из диалога — ровно { title }, без assignee_id, priority, description, due_date
```

### 4.4. Кнопка в боковом меню (`app/router.tsx`, R5-T05)

```tsx
function Sidebar({ profile }: { profile: MeResponse }) {
  // 003: alert, logout
  const navigate = useNavigate();
  const projectMatch = useMatch("/projects/:projectId");
  const createRef = useRef<HTMLButtonElement>(null);
  // Реализовано: createPath вместо createOpen (§4.4, О-2)
  const { pathname } = useLocation();
  const [createPath, setCreatePath] = useState<string | null>(null);
  if (createPath !== null && createPath !== pathname) setCreatePath(null);
  const createOpen = createPath !== null;
  const canCreate = profile.capabilities.includes("business_access");   // FR-5 (Q-6 а): и на экранах отказа
  return (
    <>
      <div className="ui-sidebar">
        <nav aria-label={t("app.menu_label")}><MenuItems profile={profile} /></nav>
        {canCreate ? (
          <button type="button" data-action="create-task" aria-haspopup="dialog" ref={createRef}
                  onClick={() => setCreatePath(pathname)}>
            <Icon name="plus" />{t("nav.create_task")}
          </button>
        ) : null}
        <button type="button" data-action="logout" …>…</button>
        <ErrorAlert … />
      </div>
      {createOpen ? (
        <CreateTaskDialog
          currentProjectId={projectMatch?.params.projectId ?? null}
          onClose={() => { setCreatePath(null); createRef.current?.focus(); }}
          onCreated={(task) => { setCreatePath(null); navigate(`/tasks/${task.id}`); }}
        />
      ) : null}
    </>
  );
}
```
- Кнопка без `aria-expanded` и без `aria-label`: имя совпадает с видимой подписью (WCAG 2.5.3).
  Ровно один дочерний `svg` (AC-42).
- Пока диалог закрыт, запросов нет (FR-7, AC-13).
- Порядок документа: ссылки → «Задача» → «Выйти» → сообщение об ошибке выхода (`tabindex=-1`)
  → (окно диалога, если открыто) → содержимое экрана (AC-12, 003/AC-30).

**Принятые отклонения реализации от плана** (финальная приёмка `reviews/FINAL-acceptance.md`,
отклонения 1–4; ревью `reviews/R5-T03-1.md`, `reviews/R5-T05-1.md`). Код уже такой, тесты
зелёные.
- **О-1. Инвалидация без ожидания** (`CreateTaskForm.tsx`, `CreateTaskDialog`). После 201
  диалог вызывает `void queryClient.invalidateQueries(…)` для трёх ключей (D-9) и сразу
  `onCreated(task)`, не дожидаясь перезапросов. Причина: при ожидании
  `Promise.all(invalidateQueries)` окно оставалось запертым после 201 на время перезапросов
  активных запросов: до ~7 с при 503, без сети — бесконечно (блокирующее замечание
  R5-T03-1). `invalidateQueries` помечает кэш устаревшим синхронно, поэтому следующий экран
  всё равно читает свежие данные (FR-15, AC-27).
- **О-2. `createPath` вместо `createOpen`** (`router.tsx`, `Sidebar`). Состояние окна — путь,
  на котором его открыли (`string | null`), а не флаг. Если путь изменился, а `Sidebar` остался
  (например, «Назад» на другой экран с ролью), окно закрывается при рендере
  (`if (createPath !== null && createPath !== pathname) setCreatePath(null)`). Причина:
  `Sidebar` живёт при переходе между экранами с ролью (тот же экземпляр в `RoleScreen`), а
  окно должно принадлежать экрану, где его открыли. Фокус при таком закрытии не
  возвращается: кнопки прежнего экрана может уже не быть.
- **О-3. Флаг «смонтирован» и ref `created`** (`CreateTaskDialog`). `mounted` (ref,
  ставится эффектом монтирования, снимается при размонтировании): если окно размонтировано
  до ответа 201 (пользователь ушёл с экрана), `onCreated` не вызывается. `created` (ref,
  ставится сразу после 201): повторная отправка после успеха не создаёт дубликат, даже если
  `onCreated` бросил исключение. Вызов `onCreated` обёрнут в отдельный `try/catch`: сбой
  вызывающего — не «ошибка создания» (сообщения в окне нет), он пишется в
  `console.error("CreateTaskDialog: onCreated failed", e)`, чтобы не потеряться как
  необработанный отказ промиса.
- **О-4. Ширина окна.** Окну задан класс `ui-dialog ui-create-dialog`, в `ui.css` —
  `.ui-create-dialog { width: min(24rem, 100%) }` (дополнение к §4.5; добавлено в R5-T02,
  примечание оркестратора в `tasks.md`, первоначально `width: 24rem`). Окно не шире
  контейнера на узком экране. Цветов и `font-size` в правиле нет, AC-42 не затрагивается.

### 4.5. Стили (`ui.css`, R5-T04; D-7, D-11)

```css
.ui-sidebar button {               /* было: + margin-top: auto */
  display: flex; align-items: center; justify-content: center; white-space: nowrap;
}
.ui-sidebar [data-action="logout"] { margin-top: auto; }   /* «Выйти» прижата к низу панели */
/* @media (max-width: 719px): вместо `.ui-sidebar button { margin-top: 0; margin-left: auto; }` */
.ui-sidebar [data-action="logout"] { margin-top: 0; margin-left: auto; }
.ui-overlay { …; z-index: 10; }
.ui-shell > .ui-overlay { margin: 0; }
```
Иконка: `Icon.tsx`, `IconName += "plus"`, `PATHS.plus = ["M12 5v14", "M5 12h14"]` (рисунок
отличается от остальных иконок).

Проверка AC-42 (`tests/shared/create-button.test.ts`, статический разбор `ui.css`, как в
`theme.test.ts`). К кнопке применяются селекторы `button`, `button:disabled`, `:focus-visible`,
`.ui-sidebar button` и любые правила с `[data-action="create-task"]` или
`.ui-sidebar button:<состояние>`, если они появятся:
- все цветовые свойства — только `var(--…)`;
- `border-radius` у `button` — `999px`;
- контраст `--button-text`/`--button-bg` ≥ 4.5. Для `:hover`: если правило есть, пара его
  токенов ≥ 4.5, иначе действует обычное состояние;
- контраст `--focus`/`--surface` ≥ 3.

Разметку (ровно один `svg`, нет вложенных интерактивных элементов, шеврона и разделителя)
проверяет `app/create-task-button.test.tsx` (R5-T05).

### 4.6. Доска после уборки (R5-T06)

```ts
export function BoardView({ projectId }: { projectId: string }): JSX.Element;   // без canCreate
function Column({ status, cards }: { status: TaskStatus; cards: readonly BoardCard[] }): JSX.Element;
// boards/api.ts: getBoard, moveTask (createTask удалён)
// ProjectPage.tsx: <BoardView projectId={project.id} />
```
Шапка-комментарий `BoardView.tsx`: «T91: create a task from a column» заменить на «004:
создания задач на Доске нет (создание — диалог бокового меню и вкладка "Задачи")».

## 5. Данные и эксперименты

ML-кода нет, seed не нужен. Моки сети — `installFetch` (`frontend/tests/features/admin/helpers.tsx`)
и помощники проектов и Доски. Фикстуры spec, раздел 5, в
`frontend/tests/features/tasks/create-dialog-helpers.tsx` (R5-T02):
- `P1` «Альфа», `P2` «Бета», `P3` «Гамма» — фиксированные UUID;
  `projectCard(id, name, createTask: boolean)` — ответ `GET /api/v1/projects/{id}` с
  `permissions.create_task`;
- `LIST_BA` = страница `[P1, P2, P3]`, `LIST_U` = `[P1, P3]`, `LIST_ONE` = `[P1]`; две страницы
  (`has_next = true` на первой) для AC-17;
- `T_NEW` — ответ 201 `TaskDetail` с фиксированным id в выбранном проекте;
- `renderDialog({ currentProjectId, routes })` — `CreateTaskDialog` в `QueryClientProvider` +
  `MemoryRouter` со шпионами `onClose` и `onCreated` (для R5-T02, R5-T03);
- `deferred()` — отложенные ответы (AC-18, AC-30, AC-31).

Профили — как в 003 plan §5. AC-40 (50 проектов, p95 ≤ 2 с) — ручная проверка на стенде
001/NFR-2. Автотесты быстрые (полный vitest около 10–20 с), smoke-режим не нужен. GPU не
используется.

## 6. Тестовая стратегия и трассировка

### 6.1. AC → реализация → тест

| AC | Где реализуется | Задача | Тест |
|---|---|---|---|
| AC-1, AC-2 | `BoardView` без создания | R5-T06 | `features/boards/BoardCreate.test.tsx::004_ac1_*`, `004_ac2_*` |
| AC-3 | без изменений поведения Доски | R5-T06 | существующие `BoardView`, `BoardOptimistic`, `BoardFilter`, `dnd*` — зелёные |
| AC-4 | опрос и фильтр (без изменений) | R5-T06 | `BoardFilter.test.tsx::t91_poll_keeps_filter_and_applies_new_data_to_it` |
| AC-5 | то же | R5-T06 | `BoardFilter.test.tsx::004_ac5_*` (новый) |
| AC-6 | `CreateTaskForm` без изменений | R5-T03 (смена типа), R5-T06 | `features/tasks/CreateTaskForm.test.tsx` — зелёный без правок |
| AC-7 | вкладка «Задачи» + Доска | R5-T06 | `BoardCreate.test.tsx::004_ac7_*` |
| AC-8 | `ru.ts` | R5-T07 | `BoardCreate.test.tsx::004_ac8_*` (бывший `t91_dictionary_keys_exist_with_expected_texts`) |
| AC-9, AC-10, AC-11 | `Sidebar` (`canCreate`) | R5-T05 | `app/create-task-button.test.tsx::004_ac9_*…004_ac11_*`; `navigation.test.tsx`; `icons.test.tsx` |
| AC-12 | порядок разметки `Sidebar` | R5-T05 | `app/create-task-button.test.tsx::004_ac12_*`; `app/sidebar.test.tsx::003_ac30_*` (дополнен) |
| AC-13 | диалог монтируется только при открытии | R5-T05 | `app/create-task-button.test.tsx::004_ac13_*` (точный набор запросов экранов) |
| AC-14 | `CreateTaskDialog` (D-6); вне `nav` (D-7) | R5-T02 (состав), R5-T05 (вне `nav`, `U` на `/my-tasks`) | `features/tasks/CreateTaskDialog.test.tsx::004_ac14_*`; `app/create-task-button.test.tsx::004_ac14_*` |
| AC-15, AC-16, AC-17 | `listCreatableProjects` + выбор | R5-T01 (функция), R5-T02 (окно) | `features/projects/api.test.ts::004_ac16_*`, `004_ac17_*`; `CreateTaskDialog.test.tsx::004_ac15_*…004_ac17_*` |
| AC-18 | D-3, D-6 | R5-T01 (отказ функции), R5-T02 | `CreateTaskDialog.test.tsx::004_ac18_*` |
| AC-19 | D-6 «пусто» + возврат фокуса | R5-T02 (окно, фокус на «Закрыть», Escape → `onClose`), R5-T05 (фокус на «Задача», кнопка видна) | `CreateTaskDialog.test.tsx::004_ac19_*`; `app/create-task-button.test.tsx::004_ac19_*` |
| AC-20, AC-21, AC-41 | `preselectProject`, D-4, D-5 | R5-T01 (правило), R5-T02 (окно), R5-T05 (путь → `currentProjectId`) | `features/tasks/preselect.test.ts`; `CreateTaskDialog.test.tsx::004_ac20_*`, `004_ac21_*`, `004_ac41_*`; `app/create-task-button.test.tsx::004_ac20_*` (вкладки «Доска», «Задачи», «Участники») |
| AC-22 | смена выбора, `choice` | R5-T03 | `CreateTaskDialogSubmit.test.tsx::004_ac22_*` |
| AC-23, AC-24 | проверка ввода | R5-T03 | `CreateTaskDialogSubmit.test.tsx::004_ac23_*`, `004_ac24_*` |
| AC-25 | D-8 | R5-T03 | `CreateTaskDialogSubmit.test.tsx::004_ac25_*` (тело ровно `{ "title": "Отчёт" }`, переносов нет) |
| AC-26 | D-9 | R5-T03 (`onCreated`), R5-T05 (путь, фокус на `h1`, «Назад») | `app/create-task-button.test.tsx::004_ac26_*` |
| AC-27 | D-9 (инвалидация) | R5-T05 | `app/create-task-button.test.tsx::004_ac27_*` (Доска и вкладка «Задачи» без тика опроса) |
| AC-28 | FR-16 | R5-T03 | `CreateTaskDialogSubmit.test.tsx::004_ac28_*` (403, 404, 422, 503, сеть) |
| AC-29 | клиент: 401 → `/login` | R5-T05 | `app/create-task-button.test.tsx::004_ac29_*` |
| AC-30 | D-10 | R5-T03 | `CreateTaskDialogSubmit.test.tsx::004_ac30_*` |
| AC-31 | D-10 | R5-T03 (Escape, «Отмена» недоступна), R5-T05 (путь после 201) | `CreateTaskDialogSubmit.test.tsx::004_ac31_*`; `app/create-task-button.test.tsx::004_ac31_*` |
| AC-32 | Escape и «Отмена» → `onClose` → фокус | R5-T02 (`onClose`), R5-T05 (фокус на «Задача») | `CreateTaskDialog.test.tsx::004_ac32_*`; `app/create-task-button.test.tsx::004_ac32_*` |
| AC-33, AC-34 | ловушка Tab, нет обработчика у подложки | R5-T02 | `CreateTaskDialog.test.tsx::004_ac33_*`, `004_ac34_*` |
| AC-35 | повторный монтаж (D-3, D-4) | R5-T05 | `app/create-task-button.test.tsx::004_ac35_*` |
| AC-36 | одно окно; ловушка Tab | R5-T05 | `app/create-task-button.test.tsx::004_ac36_*` |
| AC-37 *ручной* | — | R5-T09 (пункт), R5-T10 | `docs/acceptance/mvp-demo.md`, пункт `004/AC-37` |
| AC-38 | D-14 | R5-T10 | `git diff --stat e43d435 -- backend docs/api frontend/src/shared/api/schema.d.ts` пуст; `pytest -q backend/tests` |
| AC-39 | все задачи | R5-T10 | `npm run lint && npm run typecheck && npm test`; `bash scripts/check.sh`; сверка §6.2 |
| AC-40 *ручной, вне CI* | D-1 | R5-T09 (пункт), R5-T10 | `docs/acceptance/mvp-demo.md`, пункт `004/AC-40` |
| AC-42 | D-11, §4.5 | R5-T04 (CSS), R5-T05 (разметка) | `shared/create-button.test.ts::004_ac42_*`; `app/create-task-button.test.tsx::004_ac42_*` |
| AC-43 *ручной* | — | R5-T09 (пункт), R5-T10 | `docs/acceptance/mvp-demo.md`, пункт `004/AC-43` (сравнение с `docs/ui/button-task.png`) |

Дополнения к 003 (раздел 11 spec 004): 003/AC-19 и AC-30 на бизнес-экранах, 003/AC-27 и
AC-28 на экранах отказа — проверяются в `app/sidebar.test.tsx` (обновляет R5-T05) и
`app/create-task-button.test.tsx`.

### 6.2. Старые тесты → AC 004 (NFR-6)

Правила — как в 003 plan §6.2: тест переписывается на критерий 004 (`004_acN_*` или AC в
комментарии) либо удаляется как дубликат существующего заменителя, который назван в
комментарии. Тест «без замены» допустим только там, где это прямо сказано в spec, раздел 9.

| Файл (тесты) | Действие | AC | Задача |
|---|---|---|---|
| `features/boards/BoardCreate.test.tsx`: `t91_add_button_in_every_column_when_create_task_permitted`, `t91_no_add_buttons_without_create_task_permission`, `t91_click_opens_accessible_inline_form_in_same_column_with_focus_on_input` | Файл переписывается на тему «на Доске нет создания»: AC-1 (`BA` и `U` с правом, `BA` без права — ни `button`, ни `form`, ни поля, ни текста «Добавить задачу» в колонках). Доступность формы — в тестах диалога AC-14, AC-20 | AC-1 | R5-T06 |
| `BoardCreate.test.tsx`: `t91_escape_cancels_returns_focus_to_add_button_no_requests`, `t91_cancel_button_closes_form_and_restores_focus` | Удаляются, заменители — `CreateTaskDialog.test.tsx::004_ac32_*`, `app/create-task-button.test.tsx::004_ac32_*` | AC-32 | R5-T06 |
| `BoardCreate.test.tsx`: `t91_blank_title_%j_not_sent_single_validation_alert` (×2) | Заменитель `CreateTaskDialogSubmit.test.tsx::004_ac23_*` | AC-23 | R5-T06 |
| `BoardCreate.test.tsx`: `t91_todo_column_posts_trimmed_title_only_and_no_move`, `t91_role_%s_never_sends_assignee` (×2) | Заменитель `004_ac25_*` | AC-25 | R5-T06 |
| `BoardCreate.test.tsx`: `t91_column_%s_creates_then_moves_to_end_without_neighbors` (×3), `t91_move_failure_single_alert_task_stays_in_todo_board_reread`, `t91r_move_failure_after_create_has_dedicated_message_with_reason_and_column` | Без замены (spec, раздел 9): создания в другой колонке и связки «создать + перенести» больше нет. Отсутствие запросов создания с Доски проверяет `004_ac2_*` | AC-2 | R5-T06 |
| `BoardCreate.test.tsx`: `t91_double_submit_sends_one_create`, `t91r_submit_button_is_aria_busy_not_disabled_while_request_in_flight` | Заменитель `004_ac30_*` | AC-30 | R5-T06 |
| `BoardCreate.test.tsx`: `t91_create_error_%i_single_alert_form_kept_no_move` (×3) | Заменитель `004_ac28_*` | AC-28 | R5-T06 |
| `BoardCreate.test.tsx`: `t91r_%s_during_request_then_reopen_keeps_new_form_after_old_response` (×2) | Заменители `004_ac31_*`, `004_ac35_*` | AC-31, AC-35 | R5-T06 |
| `BoardCreate.test.tsx`: `t91_dictionary_keys_exist_with_expected_texts` | Остаётся до R5-T07, затем становится `004_ac8_*` (ключей раздела 10 п. 1 и значений «Добавить задачу», «Задача создана в колонке …» нет) | AC-8 | R5-T07 |
| `features/boards/BoardFilter.test.tsx`: `t91_create_with_filter_keeps_filter_and_shows_new_unassigned_card` | Удаляется, заменитель — существующий `t91_poll_keeps_filter_and_applies_new_data_to_it` (комментарий с AC-4) | AC-4 | R5-T06 |
| `BoardFilter.test.tsx`: `t91_create_under_other_member_filter_still_posts_and_hides_unassigned_new_card` | Становится `004_ac5_*`: опрос возвращает новую задачу без исполнителя, при фильтре `kuznetsov` её нет, при «Все исполнители» она последняя в «К выполнению» | AC-5 | R5-T06 |
| `features/boards/helpers.tsx`: шапка-контракт (блок «Создание» T91, п. (4) T91-R, ключи `boards.add_task`, `boards.create_*`), помощники `addBtn`, `createForm`, `titleInput`, `openCreate`, `NEW_TITLE`, `liveBoard` | Контракт: «на Доске нет создания (004/AC-1, AC-2)». Помощники удаляются, если после замены не используются. `TN` и всё, что нужно тесту опроса, остаётся | AC-1, AC-2 | R5-T06 |
| `tests/app/navigation.test.tsx` | Дописывается состав меню по ролям: «Задача» у `BA` и `U`, нет у `TA` | AC-9, AC-10 | R5-T05 |
| `tests/app/icons.test.tsx` | Проверка «у каждой ссылки и кнопки `.ui-sidebar` первая — иконка, иконки различны» охватывает «Задача» (на `/projects` с `business_access`) | AC-9 | R5-T05 |
| `tests/app/sidebar.test.tsx::003_ac30_*`, `003_ac19_*` (`BA`, `U`) | Порядок Tab: ссылки, «Задача», «Выйти», содержимое (оговорка 003/AC-30). «Первый дочерний — иконка» — и у «Задача». Проверка «Выйти» — последний tabbable-элемент меню остаётся | 003/AC-19, AC-30; AC-12 | R5-T05 |
| `tests/shared/theme.test.ts`, блок «003: "Выйти" в боковом меню» (R4-T07) | `margin-top: auto` проверяется у `.ui-sidebar [data-action="logout"]` (D-11), а не у `.ui-sidebar button` | 003/AC-19, FR-6 | R5-T04 |
| `tests/app/icons.test.tsx`, блок `.ui-icon styles` (`.ui-sidebar button` — flex и `align-items: center`) | Без изменений (правило остаётся) | — | R5-T04 |
| `features/projects/ProjectPage.test.tsx` (~стр. 540), `features/admin/UsersPage.test.tsx` (~стр. 538) | Без изменений: «Задача» — `button[type=button]` с текстом. На `/admin/users` у `TA` кнопки нет | — | R5-T05 |
| `tests/app/password-modal.test.tsx` | Без изменений (AC-11: на подложке кнопок нет) | AC-11 | R5-T05 |
| `features/tasks/CreateTaskForm.test.tsx`, `TaskList.test.tsx` | Без изменений (AC-6). Если поиск по имени «Новая задача» или «Создать задачу» стал неоднозначным, уточнить контейнер или роль без ослабления проверки, иначе `PLAN_ISSUE` | AC-6 | R5-T05, R5-T06 |

## 7. Зависимости

Новых пакетов нет (NFR-5). Используются `react-router-dom` 7 (`useMatch`, `useNavigate`),
`@tanstack/react-query` 5, vitest, Testing Library.

## 8. Риски

- **R-1. NFR-4 (≤ 2 с при 50 проектах)** — 1 запрос списка + 50 запросов карточек. Браузер
  ограничивает параллельные соединения (около 6 на HTTP/1.1), поэтому время зависит от стенда.
  Проверка ручная (AC-40). Если порог не выполняется, ускорить без бэкенда нельзя, нужна
  новая точка API (вне рамок NFR-1, решение владельца).
- **R-2. Наложение слоёв.** Карточки Доски с `transform` (dnd-kit) рисуются поверх
  фиксированной подложки, если у неё нет `z-index`. Мера: `.ui-overlay { z-index: 10 }` (D-7).
  Визуально это проверяется в AC-43 и AC-37.
- **R-3. Текст «Задача» и «Новая задача» уже есть на экранах** (тип объекта журнала, заголовок
  формы вкладки «Задачи»). Тесты ищут их по роли и контейнеру (`button` в `.ui-sidebar`,
  `dialog`).
- **R-4. Окно между R5-T05 и R5-T06** — на Доске ещё есть кнопки «Добавить задачу», а в меню
  уже есть «Задача». Это промежуточное состояние ветки, не поставка. Задачи выпускаются
  вместе (R5-T10).
- **R-5. `refetchOnMount: "always"` и `gcTime: 0`** — если открыть окно повторно, пока прежний
  запрос ещё летит, TanStack Query может переиспользовать этот запрос. AC-18 и AC-35
  открывают окно повторно после ответа, поэтому критерии выполняются.
- **R-6. Линтер react-hooks 7** — предвыбор без `setState` в эффекте (D-4). Перенос фокуса
  после загрузки — `focus()` в эффекте, без изменения состояния.

## 9. Противоречия и неполнота spec (не исправлены; на решение владельца или spec-writer)

- **П-1. Раздел 10 п. 2 — неверный факт.** «На `e43d435` правил для `.ui-add-task`,
  `.ui-create-form`, `.ui-create-form-actions` в `ui.css` уже нет». На самом деле они есть
  (`git show e43d435:frontend/src/shared/ui/ui.css`, стр. 404–421). Требование не нарушается:
  п. 2 сам предписывает удалить такие правила. R5-T07 их удаляет.
  Итог (финальная приёмка): правила на `e43d435` фактически были и удалены в R5-T07; в
  текущем `ui.css` селекторов `.ui-add-task`, `.ui-create-form*` нет. Неверен только факт в
  разделе 10 п. 2 spec, требование выполнено.
- **П-2. FR-10 / FR-20: фокус и форма на время загрузки списка не определены.** AC-18 говорит
  «отправка формы не отправляет запрос» во время загрузки. План: форма видна, отправка
  недоступна, фокус на окне до загрузки (D-5, D-6). При иной трактовке меняется только
  разметка состояния «загрузка».
- **П-3. AC-38 «сравнение с `main`»** — невыполнимо буквально, как 003/AC-33 (003 plan §9,
  П-1). Используется `e43d435`. Итог (финальная приёмка): сравнение выполнено с `e43d435`,
  `git diff --stat e43d435 -- backend docs/api frontend/src/shared/api/schema.d.ts` и
  `frontend/package*.json` — пусто. С `main` не сравнивалось. В диапазон `e43d435..HEAD`
  попали и коммиты 003 и 005, но в перечисленных путях изменений нет.
- **П-4. Новые модули фронтенда** запрещены белым списком в тесте бэкенда (003 plan §9, П-2).
  План кладёт диалог в существующий `CreateTaskForm.tsx`.
- **П-5. FR-6 «состояния наведения и нажатия задаются токенами»** — у кнопок проекта (и
  «Выйти») правил `:hover` и `:active` нет. План их не вводит («вид как у остальных светлых
  кнопок», «изменение вида других кнопок — вне рамок»). AC-42 для наведения проверяет
  обычное состояние. Если владелец хочет видимую реакцию на наведение, нужно отдельное
  решение для всех кнопок.
  Итог (финальная приёмка): правил `:hover` и `:active` для кнопок в `ui.css` нет и не
  добавлено (есть только `.ui-table tbody tr:hover` и `.ui-sidebar a:hover`). У «Задача»
  наведение и нажатие выглядят как обычное состояние; фокус — `:focus-visible` с `--focus`.
- **П-6 (риск, на решение владельца). Shift+Tab после щелчка по подложке.** У подложки нет
  обработчика щелчка (FR-20, AC-34), и фон не помечен `inert`. Щелчок по подложке снимает
  фокус с элементов окна (он уходит на `body`), но Chromium запоминает точку щелчка как
  начало последовательной навигации. Нажатие клавиши тогда приходит не в `onKeyDown` окна, и
  ловушка Tab (§4.2) не срабатывает: Tab ведёт в окно (подложка в документе после меню и
  перед содержимым), а Shift+Tab может увести фокус на элементы бокового меню за окном. Тот
  же образец у окна смены пароля (`ChangePasswordPage`, `PasswordModal`). AC-34 и AC-36
  выполняются (их тесты проверяют Tab и Shift+Tab при фокусе внутри окна и отсутствие
  реакции на щелчок). Варианты: (а) принять; (б) `inert` на фон или обработчик `focusin` на
  документе, возвращающий фокус в окно, — отдельная правка для обоих окон. Решение
  владельца.

## 10. Связь с 001 и 003 (файлы 001 правит только R5-T08; текст 003 не меняется)

| Документ | Правка | Задача |
|---|---|---|
| spec 001, история версий | В пункт v0.19 (создан R4-T09) добавить: «создание задачи из колонки Доски (решение владельца 2026-10-16, T91, вне spec) снято; создание из бокового меню — 004/FR-1…FR-22». Если v0.19 уже выпущена отдельным коммитом и владелец против дописывания, то v0.20 с тем же текстом | R5-T08 |
| tasks 001, T91 | `- **Пересмотрено:** 004 снимает создание из колонки (кнопка, форма, связка create + move, `createTask` в `boards/api.ts`, ключи `boards.add_task`, `boards.create_*`); оптимистичный перенос и фильтр остаются; заметка бэклога о задаче, созданной под фильтром, неактуальна` | R5-T08 |
| spec 003 | Не правится. Дополнения 004 к 003/AC-19, AC-27, AC-28, AC-30 — в тестах (§6.1) | — |
