// T84: помощники тестов карточки задачи (/tasks/:taskId) и списка подзадач.
//
// КОНТРАКТ ДЛЯ ИСПОЛНИТЕЛЯ (строки интерфейса - только из src/shared/i18n/ru.ts; новые ключи,
// перечисленные ниже, добавляются в словарь; тесты падают, если ключа нет).
//
// src/features/tasks/api.ts (дополнение; поверх getAppClient(); не-2xx и сеть -> ApiError)
//   getTask(id, options?): Promise<TaskDetail>             GET /api/v1/tasks/{id}
//   updateTask(id, b: TaskUpdate): Promise<TaskDetail>     PATCH /api/v1/tasks/{id}
//   deleteTask(id): Promise<void>                          DELETE /api/v1/tasks/{id}
//   createSubtask(id, b: TaskCreate): Promise<TaskDetail>  POST /api/v1/tasks/{id}/subtasks
//   Карточка читается через usePolledQuery (FR-29): тики опроса несут X-GT-Background: 1.
//
// Страница /tasks/:taskId (TaskPage; под BusinessScreen как остальные):
//   T101 (backlog п.2, решение владельца): НЕТ ДУБЛЯ полей. Каждое поле показывается ОДИН раз, секция
//   «Параметры» - dl со строками «подпись - значение»; при праве на правку значение - сам контрол, иначе текст.
//   Отдельных блоков «Сменить статус» / «Правка задачи» (ключ tasks.edit_title, h2) и повторных подписей нет
//   (ключи tasks.status_label / edit_title / assignee_label / title_label / due_label / priority_label на
//   карточке не используются; в словаре могут остаться - ими пользуются другие экраны).
//   h1 = название задачи (всегда ровно один h1, tabIndex=-1, получает фокус при открытии карточки).
//     Есть permissions.edit -> внутри h1 лежит input[name="title"] (доступное имя ru["tasks.field_title"],
//     значение = название; текстом название не дублируется), иначе h1 содержит название текстом.
//     Хелпер expectTitle(text) читает value input или textContent h1.
//   Ошибка загрузки -> ровно один role="alert" c errorMessage(code), без h1 с названием и без форм.
//     На странице всегда не более одного role="alert".
//   Подписи (dt, каждая ровно ОДИН раз на странице: getAllByText(label).length === 1; для Исполнителя подпись
//     может быть самим <label> пикера): Статус = ru["tasks.col_status"], Приоритет = ru["tasks.col_priority"],
//     Исполнитель = ru["tasks.col_assignee"], Срок = ru["tasks.col_due"], Описание = ru["tasks.field_description"],
//     Название (доступное имя input в h1) = ru["tasks.field_title"]. Новые ключи tasks.field_title = "Название",
//     tasks.field_description = "Описание" добавляются в ru.ts. Значения col_* остаются "Статус", "Приоритет",
//     "Исполнитель", "Срок". Контролы имеют доступное имя = эта же подпись (select статуса: combobox "Статус").
//   Значение строки лежит в [data-field="status|priority|assignee|due_date|description|project"] (dd).
//     Без права (или для project всегда): текст как раньше - status/priority = tasks.status.* / tasks.priority.*,
//       assignee = login или ru["tasks.assignee_none"], due_date = ru["tasks.due_none"] или
//       time[datetime="YYYY-MM-DD"] с DD.MM.YYYY, description = текст (пусто -> ru["tasks.description_none"]);
//       внутри такого [data-field] НЕТ input/select/textarea/button/combobox.
//     С правом - в [data-field=...] контрол (текстом значение не дублируется):
//       change_status   -> select[name="status"] (todo|in_progress|review|done): смена значения сразу шлёт
//                          PATCH {status} (только это поле). Если новый статус "done" и среди task.subtasks есть
//                          не "done" (FR-22) - сначала ConfirmDialog (role="alertdialog") с message
//                          ru["tasks.close_open_subtasks"]: confirm -> PATCH, cancel/Escape -> запроса нет,
//                          select возвращается к статусу задачи.
//       change_assignee -> UserPicker (combobox, доступное имя ru["tasks.col_assignee"], allowedIds = участники
//                          проекта из GET /projects/{pid}/members, page_size=100); в этом же [data-field="assignee"]
//                          текущий исполнитель текстом (login / ru["tasks.assignee_none"]); выбор -> PATCH
//                          {assignee_id: <id>}; button[data-action="clear-assignee"] (виден, если исполнитель
//                          есть) -> PATCH {assignee_id: null}. Других ключей в этих PATCH нет.
//       edit            -> form[data-form="edit-task"] (ОДНА форма, внутри title input, description, due_date,
//                          priority и submit ru["tasks.save"]; status/assignee могут быть внутри или снаружи):
//                          input[name="title"] (в h1), textarea[name="description"], input[type="date"]
//                          [name="due_date"], select[name="priority"] (base|high), каждый с доступным именем =
//                          подпись поля. Значения предзаполнены. Submit шлёт PATCH ТОЛЬКО с изменёнными
//                          полями (title - trim); без изменений запроса нет; очищенный срок -> due_date:null;
//                          ключа assignee_id/status в этом PATCH нет (UNSET). Пустое название -> запроса
//                          нет, role="alert" errorMessage("validation_error").
//       Без edit формы нет вовсе (form[data-form="edit-task"] отсутствует).
//     delete          -> button[data-action="delete-task"] -> ConfirmDialog (alertdialog, shared/ui);
//                        confirm -> DELETE /tasks/{id} -> переход на /projects/<project.id>; cancel -> запроса нет.
//     без права соответствующего элемента нет вовсе (не disabled).
//   [data-field="project"] c <a href="/projects/<id>">, [data-slot="comments"] - место под комментарии (T85).
//   Фокус (WCAG 2.4.3, T84 ревью): после смены статуса select остаётся в фокусе и НЕ disabled
//     (aria-busy допустим). После clear-assignee кнопка исчезает - фокус переходит на поле выбора
//     исполнителя (combobox "Исполнитель"); h1 для этого случая НЕ принимается.
//   Гонка опроса: ответ тика опроса, стартовавшего до PATCH, не откатывает результат PATCH.
//   Несохранённое название в форме не стирается сменой статуса/исполнителя; PATCH не содержит title,
//     если название не менялось (в т.ч. отличается лишь пробелами). Участники запрашиваются только
//     при permissions.change_assignee; заблокированные и без роли в исполнители не предлагаются.
//   422 при загрузке карточки (невалидный uuid) - как not_found: один alert errorMessage("not_found").
//   Успешный PATCH: карточка берёт ответ (h1, поля), форма синхронизируется с ответом.
//   Ошибка PATCH/DELETE: role="alert" errorMessage(code), введённое в форме сохраняется.
//   Опрос не затирает несохранённый ввод: поле, изменённое пользователем, не перезаписывается данными
//     опроса; нередактируемые значения (текст) и поля без правки показывают свежие данные сервера.
//
// Подзадачи (SubtaskList, внутри карточки): section[data-section="subtasks"] c h2 ru["tasks.subtasks_title"];
//   строки [data-subtask-id="<uuid>"] с [data-field="title"] (<a href="/tasks/<id>">), [data-field="status"],
//   [data-field="assignee"]; пустой список - [data-role="empty"] c ru["tasks.subtasks_empty"];
//   [data-field="progress"] (в секции): число -> текст "<n>%", null -> ровно ru["tasks.progress_none"]
//   (не "0%", FR-22).
//   Создание: form[data-form="create-subtask"] - только при permissions.create_subtask И parent_id === null
//   (FR-21); input[name="title"] (label ru["tasks.subtask_title_label"]), submit. POST /tasks/{id}/subtasks
//   с телом {title (trim)} без ключа assignee_id (FR-20/FR-19b: сервер назначает сам). Успех -> поле очищено
//   и в фокусе, карточка перечитана (подзадача и прогресс видны). Один POST при двойной отправке.
//   R6-T05 (006, FR-27/FR-28/FR-29, D-8; заменяет прежнее «alert validation_error» и «alert errorMessage(code)
//   в общей области» для формы подзадачи - RK-7): сообщения формы подзадачи - ровно один role="alert" ВНУТРИ
//   section[data-section="subtasks"], в общей области карточки их нет; поле с aria-invalid="true" и
//   aria-describedby -> id сообщения. Пустое/пробельное название -> запроса нет, «Введите название подзадачи»;
//   trim().length > 255 -> запроса нет, «Название подзадачи — не более 255 символов» (validation_error форма
//   подзадачи не показывает). Ошибка сервера/сети -> errorMessage(code) в секции, ввод сохраняется, повтор
//   шлёт новый запрос. busy защищает только POST (не перечитывание карточки).
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect } from "vitest";

import { ru } from "../../../src/shared/i18n";
import {
  ID_KUZNETSOV,
  M_KUZNETSOV,
  M_ME,
  M_OWNER,
  M_SIDOROV,
  MEMBERS,
  ME,
  PROJECT_REF,
  R_KUZNETSOV,
  R_ME,
  TID1,
  TID2,
  TID3,
  USER_CAPS,
  BA_CAPS,
  j,
  meWith,
  page,
  renderApp,
  installFetch,
  taskDetail,
  taskItem,
  type Handler,
} from "./helpers";

export * from "./helpers";

export const TASK = `GET /api/v1/tasks/${TID1}`;
export const PATCH = `PATCH /api/v1/tasks/${TID1}`;
export const DELETE = `DELETE /api/v1/tasks/${TID1}`;
export const SUB_POST = `POST /api/v1/tasks/${TID1}/subtasks`;
export const SUB1 = "c1c1c1c1-0000-4000-8000-000000000001";
export const SUB2 = "c2c2c2c2-0000-4000-8000-000000000002";
export const SUB3 = "c3c3c3c3-0000-4000-8000-000000000003";

export const ALL_PERMS = { edit: true, change_status: true, change_assignee: true, delete: true, create_subtask: true };
export const NO_PERMS = { edit: false, change_status: false, change_assignee: false, delete: false, create_subtask: false };
export const EXECUTOR_PERMS = { ...NO_PERMS, change_status: true, create_subtask: true };

export function sub(id: string, title: string, status = "todo") {
  return {
    id,
    title,
    status,
    priority: "base",
    due_date: null,
    assignee: null,
  };
}

export function card(over: Record<string, unknown> = {}) {
  return taskDetail({
    id: TID1,
    project: PROJECT_REF,
    title: "Подготовить отчёт",
    description: "Квартальный отчёт",
    status: "in_progress",
    priority: "high",
    due_date: "2026-12-31",
    assignee: R_KUZNETSOV,
    author: R_ME,
    permissions: ALL_PERMS,
    ...over,
  });
}

/** Словарный ключ обязан существовать (иначе тест падает осмысленно, а не сравнивает с undefined). */
export function d(key: string): string {
  const v = (ru as Record<string, string>)[key];
  expect(v, `ключ словаря ${key} отсутствует`).toBeTypeOf("string");
  return v!;
}

export function cardRoutes(
  cardFn: () => Record<string, unknown>,
  over: Record<string, Handler> = {},
  role: "business_admin" | "user" = "business_admin",
): Record<string, Handler> {
  return {
    [ME]: () => j(200, meWith(role === "user" ? USER_CAPS : BA_CAPS, role)),
    [TASK]: () => j(200, cardFn()),
    [MEMBERS]: () => j(200, page([M_OWNER, M_ME, M_KUZNETSOV, M_SIDOROV])),
    // T85: карточка читает комментарии; по умолчанию их нет.
    [`GET /api/v1/tasks/${TID1}/comments`]: () => j(200, page([])),
    ...over,
  };
}

export async function openCard(
  cardFn: () => Record<string, unknown> = () => card(),
  over: Record<string, Handler> = {},
  role: "business_admin" | "user" = "business_admin",
) {
  const f = installFetch(cardRoutes(cardFn, over, role));
  const view = renderApp(`/tasks/${TID1}`);
  await expectTitle("Подготовить отчёт");
  return { f, ...view };
}

/** Название на карточке: value input[name=title] внутри h1 (есть право edit) или текст h1. */
export const titleNow = (): string | null => {
  const h = document.querySelector("h1");
  if (h === null) return null;
  const input = h.querySelector<HTMLInputElement>('input[name="title"]');
  return input !== null ? input.value : h.textContent;
};
export const expectTitle = (text: string) => waitFor(() => expect(titleNow()).toBe(text));
export const titleInput = () => document.querySelector<HTMLInputElement>('h1 input[name="title"]');
export const descArea = () => document.querySelector<HTMLTextAreaElement>('textarea[name="description"]');
export const dueInput = () => document.querySelector<HTMLInputElement>('input[name="due_date"]');
export const prioritySelect = () => document.querySelector<HTMLSelectElement>('select[name="priority"]');
/** Показанное значение поля: текст, либо значение контрола (для select - текст выбранной опции). */
export function shown(scope: ParentNode, name: string): string | null {
  const el = scope.querySelector<HTMLElement>(`[data-field="${name}"]`);
  if (el === null) return null;
  const sel = el.querySelector("select");
  if (sel !== null) return sel.selectedOptions[0]?.textContent ?? "";
  const ctl = el.querySelector<HTMLInputElement | HTMLTextAreaElement>("input,textarea");
  if (ctl !== null && name !== "assignee") return ctl.value;
  return el.textContent;
}
export const assigneePicker = () => screen.getByRole("combobox", { name: ru["tasks.col_assignee"] });
export const editForm = (c: ParentNode) => c.querySelector<HTMLFormElement>('form[data-form="edit-task"]');
export const subForm = (c: ParentNode) => c.querySelector<HTMLFormElement>('form[data-form="create-subtask"]');
export const subSection = (c: ParentNode) => c.querySelector<HTMLElement>('section[data-section="subtasks"]');
export const statusSelect = () => screen.queryByRole("combobox", { name: d("tasks.col_status") }) as HTMLSelectElement | null;
export const deleteBtn = (c: ParentNode) => c.querySelector<HTMLButtonElement>('button[data-action="delete-task"]');
export const bodyOf = async (r: Request) => (await r.clone().json()) as Record<string, unknown>;
export const waitCount = (f: { count: (k: string) => number }, key: string, n: number) =>
  waitFor(() => expect(f.count(key)).toBe(n));
export function setValue(el: Element | null, value: string) {
  fireEvent.change(el!, { target: { value } });
}
export { fireEvent, TID2, TID3, ID_KUZNETSOV, taskItem };

// ---- R6-T03: карточка подзадачи и маршрут родителя (только добавлено) ----
export const PARENT_GET = `GET /api/v1/tasks/${TID2}`;
export const PARENT_TITLE = "Отчёт за квартал";

/** Карточка подзадачи «Шаг 1» (id = TID1, parent_id = TID2), права как у участника с правкой. */
export function subCard(over: Record<string, unknown> = {}) {
  return card({ title: "Шаг 1", parent_id: TID2, ...over });
}

/** Карточка родителя (id = TID2, верхнего уровня), без прав правки: h1 содержит текст. */
export function parentCard(over: Record<string, unknown> = {}) {
  return card({ id: TID2, title: PARENT_TITLE, parent_id: null, permissions: NO_PERMS, ...over });
}

/** Маршруты карточки подзадачи + чтение родителя (по умолчанию 200) и комментариев родителя. */
export function subCardRoutes(
  cardFn: () => Record<string, unknown> = () => subCard(),
  parentFn: Handler = () => j(200, parentCard()),
  over: Record<string, Handler> = {},
): Record<string, Handler> {
  return cardRoutes(cardFn, {
    [PARENT_GET]: parentFn,
    [`GET /api/v1/tasks/${TID2}/comments`]: () => j(200, page([])),
    ...over,
  });
}

// ---- R6-T04: подзадачи подряд (только добавлено) ----
export interface SubtaskServer {
  /** Маршруты для openCard: POST подзадачи -> 201, GET карточки -> накопленные подзадачи. */
  routes: Record<string, Handler>;
  /** Названия, с которыми пришли POST, в порядке прихода. */
  posted: string[];
  /** Следующие GET карточки (после первого) ждут этот шлюз; null - не задерживать. */
  holdReads: (gate: Promise<unknown> | null) => void;
}

/** Сеть для сценариев AC-36/AC-37: каждый POST -> 201 и подзадача копится, каждый GET отдаёт накопленное. */
export function subtaskServer(perms: Record<string, boolean> = ALL_PERMS): SubtaskServer {
  const subs: ReturnType<typeof sub>[] = [];
  const posted: string[] = [];
  let reads = 0;
  let gate: Promise<unknown> | null = null;
  const snapshot = () => card({ permissions: perms, subtasks: [...subs], progress: subs.length === 0 ? null : 0 });
  return {
    posted,
    holdReads: (g) => {
      gate = g;
    },
    routes: {
      [TASK]: async () => {
        reads += 1;
        const body = snapshot();
        if (reads > 1 && gate !== null) await gate;
        return j(200, body);
      },
      [SUB_POST]: async (r) => {
        const b = (await r.clone().json()) as { title: string };
        posted.push(b.title);
        subs.push(sub(`d${subs.length + 1}d${subs.length + 1}d${subs.length + 1}d${subs.length + 1}-0000-4000-8000-00000000000${subs.length + 1}`, b.title));
        return j(201, card());
      },
    },
  };
}

/** Поле «Название подзадачи» в карточке. */
export const subTitleField = (c: ParentNode) => subForm(c)!.querySelector<HTMLInputElement>('input[name="title"]')!;
/** Названия подзадач в списке, в порядке показа. */
export const subTitlesShown = (c: ParentNode) =>
  Array.from(subSection(c)!.querySelectorAll<HTMLElement>('[data-subtask-id] [data-field="title"]')).map((e) => e.textContent);
