// T83: общие помощники тестов списков задач и формы создания.
//
// КОНТРАКТ ДЛЯ ИСПОЛНИТЕЛЯ (тесты привязаны к нему; строки интерфейса - только из словаря,
// новые ключи добавляются в src/shared/i18n/ru.ts).
//
// src/features/tasks/api.ts (поверх getAppClient(); не-2xx и сеть -> ApiError)
//   listProjectTasks(p: { projectId; page; pageSize?; assigneeId?; status? }): Promise<Page<TaskListItem>>
//       GET /api/v1/projects/{id}/tasks?page=&page_size=&assignee_id=&status=
//       (параметр в запросе только если задан; фильтры - через И)
//   listMyTasks(p: { page; pageSize? }): Promise<Page<TaskListItem>>  GET /api/v1/me/tasks?page=&page_size=
//   createTask(projectId, b: TaskCreate): Promise<TaskDetail>        POST /api/v1/projects/{id}/tasks
//   Списки читаются через usePolledQuery (FR-29): тики опроса несут X-GT-Background: 1,
//   первая загрузка и инвалидация после создания - нет.
//
// Вкладка «Задачи» (/projects/:id, [role="tab"][data-tab="tasks"]), панель tabpanel:
//   h2 из словаря; фильтры - select[name="assignee_id"] ("" = все; опции - участники проекта
//     из GET /projects/{id}/members, page_size=100, option value = user id, текст = login) и
//     select[name="status"] ("" + todo|in_progress|review|done; текст опций из словаря);
//     смена фильтра -> новый запрос с параметром и page=1;
//   таблица: tr[data-task-id="<uuid>"] с [data-field="title"] (внутри <a href="/tasks/<id>">),
//     [data-field="status"], [data-field="priority"] (тексты из словаря, разные для разных
//     значений), [data-field="assignee"] (login или текст «без исполнителя» из словаря),
//     [data-field="due_date"] (пусто -> текст «нет срока» из словаря; иначе
//     time[datetime="YYYY-MM-DD"] с текстом DD.MM.YYYY, без Date/пояса);
//   пустой список: [data-role="empty"] с текстом из словаря;
//   пагинация: button[data-action="next-page"] / [data-action="prev-page"] как у /admin/users;
//   ошибка загрузки: ровно один role="alert" с errorMessage(code).
//   Форма создания - form[data-form="create-task"], только при permissions.create_task:
//     input[name="title"] (label), textarea[name="description"] (label),
//     input[type="date"][name="due_date"] (label), select[name="priority"] (low|medium|high, по умолчанию
//     medium), button[type="submit"]; UserPicker (combobox, allowedIds = участники проекта) -
//     ТОЛЬКО если роль актора business_admin (me.role; 002 FR-9); у роли user поля исполнителя
//     нет. Выбранный исполнитель показан в [data-field="selected-assignee"] (login) и сбрасывается
//     button[data-action="clear-assignee"].
//     Тело POST: title (trim), priority, description (если непусто), due_date ("YYYY-MM-DD" как
//     введено, либо не передаётся/null), assignee_id - только если выбран (у П ключа нет совсем;
//     у БА/СМ без выбора ключа нет или null).
//     Пустое название -> запроса нет, role="alert" errorMessage("validation_error").
//     Успех -> форма очищается, список перечитывается (новая задача видна), фокус не body.
//     Ошибка -> role="alert" errorMessage(code), введённое сохраняется. Один POST при двойной отправке.
//
// /my-tasks: h1 = ru["tasks.my_title"]; та же таблица (без фильтров и без формы) из GET /me/tasks,
//   плюс [data-field="project"] c <a href="/projects/<project.id>"> (имя проекта); подзадачи
//   показываются как обычные строки.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect } from "vitest";

import {
  BOARD_GET,
  BUSINESS,
  emptyBoard,
  ID_KUZNETSOV,
  ME,
  MEMBERS,
  M_KUZNETSOV,
  M_ME,
  M_OWNER,
  M_SIDOROV,
  ONE,
  PERM_READ,
  PID,
  R_IVANOV,
  R_KUZNETSOV,
  R_ME,
  detail,
  j,
  meWith,
  page,
  type Handler,
} from "../projects/helpers";

export * from "../projects/helpers";

export const TID1 = "a1a1a1a1-0000-4000-8000-000000000001";
export const TID2 = "a2a2a2a2-0000-4000-8000-000000000002";
export const TID3 = "a3a3a3a3-0000-4000-8000-000000000003";
export const PROJECT_REF = { id: PID, name: "Альфа" };

export const PROJ_TASKS = `GET /api/v1/projects/${PID}/tasks`;
export const PROJ_CREATE = `POST /api/v1/projects/${PID}/tasks`;
export const MY_TASKS = "GET /api/v1/me/tasks";

export function taskItem(id: string, title: string, over: Record<string, unknown> = {}) {
  return {
    id,
    project: PROJECT_REF,
    parent_id: null,
    title,
    status: "todo",
    priority: "medium",
    due_date: null,
    assignee: null,
    created_at: "2026-10-05T08:00:00Z",
    ...over,
  };
}

export const T1 = taskItem(TID1, "Подготовить отчёт", {
  status: "in_progress",
  priority: "high",
  due_date: "2026-12-31",
  assignee: R_KUZNETSOV,
});
export const T2 = taskItem(TID2, "Согласовать бюджет", { status: "done" });
export const T3 = taskItem(TID3, "Подзадача", { parent_id: TID1, due_date: "2026-01-01", assignee: R_ME });

export function taskDetail(over: Record<string, unknown> = {}) {
  return {
    ...taskItem(TID3, "Новая"),
    description: "",
    author: R_ME,
    position: 0,
    subtasks: [],
    progress: null,
    updated_at: "2026-10-05T08:00:00Z",
    permissions: { edit: true, change_status: true, change_assignee: true, delete: true, create_subtask: true },
    ...over,
  };
}

export const BA_CAPS = BUSINESS;
export const USER_CAPS = ["business_access"];

/** Маршруты страницы проекта + список задач; role - роль актора из /me. */
export function taskRoutes(
  role: "business_admin" | "user" | "tech_admin",
  over: Record<string, Handler> = {},
  opts: { items?: unknown[]; perms?: Record<string, boolean> } = {},
): Record<string, Handler> {
  const caps = role === "user" ? USER_CAPS : BA_CAPS; // tech_admin: права как у БА, чтобы роль (а не права) определяла выбор исполнителя
  return {
    [ME]: () => j(200, meWith(caps, role)),
    [ONE]: () => j(200, detail({ permissions: opts.perms ?? PERM_READ })),
    [MEMBERS]: () => j(200, page([M_OWNER, M_ME, M_KUZNETSOV, M_SIDOROV])),
    [PROJ_TASKS]: () => j(200, page(opts.items ?? [T1, T2, T3])),
    [BOARD_GET]: () => j(200, emptyBoard()),
    ...over,
  };
}

export async function openTasksTab() {
  await screen.findByRole("tablist");
  const tab = document.querySelector<HTMLElement>('[role="tab"][data-tab="tasks"]');
  if (!tab) throw new Error("no tasks tab");
  fireEvent.click(tab);
  await waitFor(() => expect(tab.getAttribute("aria-selected")).toBe("true"));
  return tab;
}

export const taskRow = (c: ParentNode, id: string) =>
  c.querySelector<HTMLElement>(`tr[data-task-id="${id}"]`);
export const f_ = (scope: ParentNode, n: string) => scope.querySelector<HTMLElement>(`[data-field="${n}"]`);
export const createForm = (c: ParentNode) =>
  c.querySelector<HTMLFormElement>('form[data-form="create-task"]');
export { R_IVANOV, ID_KUZNETSOV };
