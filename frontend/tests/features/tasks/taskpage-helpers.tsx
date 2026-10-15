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
//   h1 = название задачи; ошибка загрузки -> ровно один role="alert" c errorMessage(code),
//     без h1 с названием и без форм. На странице всегда не более одного role="alert".
//   Чтение: [data-field="status"] / [data-field="priority"] (тексты tasks.status.* / tasks.priority.*),
//     [data-field="assignee"] (login или ru["tasks.assignee_none"]), [data-field="due_date"]
//     (ru["tasks.due_none"] или time[datetime="YYYY-MM-DD"] с текстом DD.MM.YYYY),
//     [data-field="description"] (текст описания), [data-field="project"] c <a href="/projects/<id>">,
//     [data-slot="comments"] - место под комментарии (T85), присутствует всегда.
//   Элементы - строго по task.permissions (AC-46, AC-47, NFR-7):
//     edit            -> form[data-form="edit-task"]: input[name="title"] (label ru["tasks.title_label"]),
//                        textarea[name="description"] (label tasks.description_label),
//                        input[type="date"][name="due_date"] (label tasks.due_label),
//                        select[name="priority"] (label tasks.priority_label; base|high), submit.
//                        Поля предзаполнены значениями задачи. Submit шлёт PATCH ТОЛЬКО с изменёнными
//                        полями (title - trim); без изменений запроса нет; очищенный срок -> due_date:null;
//                        ключа assignee_id/status в этом PATCH нет (UNSET). Пустое название -> запроса
//                        нет, role="alert" errorMessage("validation_error").
//     change_status   -> select[name="status"] (label ru["tasks.status_label"]; todo|in_progress|review|done);
//                        смена значения сразу шлёт PATCH {status} (только это поле).
//                        Если новый статус "done" и среди task.subtasks есть не "done" (FR-22) -
//                        сначала ConfirmDialog (role="alertdialog") с message ru["tasks.close_open_subtasks"]:
//                        confirm -> PATCH, cancel/Escape -> запроса нет, select возвращается к статусу задачи.
//     change_assignee -> UserPicker (combobox, label ru["tasks.assignee_label"], allowedIds = участники
//                        проекта из GET /projects/{pid}/members, page_size=100); выбор -> PATCH
//                        {assignee_id: <id>}; button[data-action="clear-assignee"] (виден, если исполнитель
//                        есть) -> PATCH {assignee_id: null}. Других ключей в этих PATCH нет.
//     delete          -> button[data-action="delete-task"] -> ConfirmDialog (alertdialog, shared/ui);
//                        confirm -> DELETE /tasks/{id} -> переход на /projects/<project.id>;
//                        cancel -> запроса нет.
//     без права соответствующего элемента нет вовсе (не disabled).
//   Фокус (WCAG 2.4.3, T84 ревью): после смены статуса select остаётся в фокусе и НЕ disabled
//     (aria-busy допустим). После clear-assignee кнопка исчезает - фокус переходит на поле выбора
//     исполнителя (combobox ru["tasks.assignee_label"]); h1 для этого случая НЕ принимается.
//   Гонка опроса: ответ тика опроса, стартовавшего до PATCH, не откатывает результат PATCH.
//   Несохранённое название в форме не стирается сменой статуса/исполнителя; PATCH не содержит title,
//     если название не менялось (в т.ч. отличается лишь пробелами). Участники запрашиваются только
//     при permissions.change_assignee; заблокированные и без роли в исполнители не предлагаются.
//   422 при загрузке карточки (невалидный uuid) - как not_found: один alert errorMessage("not_found").
//   Успешный PATCH: карточка берёт ответ (h1, поля), форма синхронизируется с ответом.
//   Ошибка PATCH/DELETE: role="alert" errorMessage(code), введённое в форме сохраняется.
//   Опрос не затирает несохранённый ввод: поле формы, изменённое пользователем, не перезаписывается
//     данными опроса; h1 и [data-field] показывают свежие данные сервера.
//
// Подзадачи (SubtaskList, внутри карточки): section[data-section="subtasks"] c h2 ru["tasks.subtasks_title"];
//   строки [data-subtask-id="<uuid>"] с [data-field="title"] (<a href="/tasks/<id>">), [data-field="status"],
//   [data-field="assignee"]; пустой список - [data-role="empty"] c ru["tasks.subtasks_empty"];
//   [data-field="progress"] (в секции): число -> текст "<n>%", null -> ровно ru["tasks.progress_none"]
//   (не "0%", FR-22).
//   Создание: form[data-form="create-subtask"] - только при permissions.create_subtask И parent_id === null
//   (FR-21); input[name="title"] (label ru["tasks.subtask_title_label"]), submit. POST /tasks/{id}/subtasks
//   с телом {title (trim)} без ключа assignee_id (FR-20/FR-19b: сервер назначает сам). Пустое название ->
//   запроса нет, alert validation_error. Успех -> поле очищено, карточка перечитана (подзадача и прогресс
//   видны). Один POST при двойной отправке. Ошибка -> alert errorMessage(code), ввод сохраняется.
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
  role: "business_admin" | "mixed" | "user" = "business_admin",
): Record<string, Handler> {
  return {
    [ME]: () => j(200, meWith(role === "user" ? USER_CAPS : BA_CAPS, role)),
    [TASK]: () => j(200, cardFn()),
    [MEMBERS]: () => j(200, page([M_OWNER, M_ME, M_KUZNETSOV, M_SIDOROV])),
    ...over,
  };
}

export async function openCard(
  cardFn: () => Record<string, unknown> = () => card(),
  over: Record<string, Handler> = {},
  role: "business_admin" | "mixed" | "user" = "business_admin",
) {
  const f = installFetch(cardRoutes(cardFn, over, role));
  const view = renderApp(`/tasks/${TID1}`);
  await screen.findByRole("heading", { level: 1, name: "Подготовить отчёт" });
  return { f, ...view };
}

export const editForm = (c: ParentNode) => c.querySelector<HTMLFormElement>('form[data-form="edit-task"]');
export const subForm = (c: ParentNode) => c.querySelector<HTMLFormElement>('form[data-form="create-subtask"]');
export const subSection = (c: ParentNode) => c.querySelector<HTMLElement>('section[data-section="subtasks"]');
export const statusSelect = () => screen.queryByRole("combobox", { name: d("tasks.status_label") }) as HTMLSelectElement | null;
export const deleteBtn = (c: ParentNode) => c.querySelector<HTMLButtonElement>('button[data-action="delete-task"]');
export const bodyOf = async (r: Request) => (await r.clone().json()) as Record<string, unknown>;
export const waitCount = (f: { count: (k: string) => number }, key: string, n: number) =>
  waitFor(() => expect(f.count(key)).toBe(n));
export function setValue(el: Element | null, value: string) {
  fireEvent.change(el!, { target: { value } });
}
export { fireEvent, TID2, TID3, ID_KUZNETSOV, taskItem };
