// T82: общие помощники тестов экранов проектов.
//
// КОНТРАКТ ДЛЯ ИСПОЛНИТЕЛЯ (тесты привязаны к нему; строки интерфейса - только из словаря).
//
// src/features/projects/api.ts (всё поверх getAppClient(); не-2xx и сеть -> ApiError; без X-GT-Background)
//   listProjects(p: { page: number; pageSize?: number }): Promise<Page<ProjectListItem>>
//       GET /api/v1/projects?page=&page_size=   (page_size только если передан)
//   createProject(b: { name: string; description?: string }): Promise<ProjectDetail>  POST /projects
//   getProject(id): Promise<ProjectDetail>                                           GET /projects/{id}
//   updateProject(id, b: { name?: string; description?: string }): Promise<ProjectDetail>  PATCH
//   deleteProject(id): Promise<void>                                                 DELETE
//   changeOwner(id, userId): Promise<ProjectDetail>   PUT /projects/{id}/owner  тело { user_id }
//   listMembers(id, p: { page: number; pageSize?: number }): Promise<Page<ProjectMember>>
//       GET /projects/{id}/members?page=&page_size=
//   addMember(id, userId): Promise<void>              POST /projects/{id}/members  тело { user_id }
//   removeMember(id, userId): Promise<void>           DELETE /projects/{id}/members/{user_id}
//   Типы ProjectListItem/ProjectDetail/ProjectMember - из schema.d.ts.
//
// src/features/projects/ProjectsPage.tsx  export function ProjectsPage(...)  (маршрут /projects)
// src/features/projects/ProjectPage.tsx   export function ProjectPage(...)   (маршрут /projects/:projectId)
//   Оба маршрута - под BusinessScreen (guard сессии, business_access, меню) как в R1.1 T81.
//
// Разметка /projects:
//   h1 = ru["projects.title"];
//   строки tr[data-project-id="<uuid>"] с [data-field="name"] (внутри <a href="/projects/<id>">,
//     текст = название), [data-field="owner"] (login владельца), [data-field="task_count"] (число).
//     Поля status нет (FR-14: у проекта нет статуса);
//   пагинация (Pagination): button[data-action="next-page"|"prev-page"], запрос ?page=N;
//   создание - только при capability project_create: form[data-form="create-project"] c
//     input[name="name"] (label, maxLength=255), textarea[name="description"] (label),
//     button[type="submit"]. Пустое название (после trim) -> запрос не уходит, role="alert"
//     с errorMessage("validation_error"). Успех -> переход на /projects/<id из ответа>.
//     Ошибка -> p[role="alert"] (ErrorAlert) с errorMessage(code), введённое сохраняется.
//     Повторная отправка при летящем запросе блокируется (один POST).
//
// Разметка /projects/:projectId:
//   h1 = название проекта; [data-field="project-owner"] = login владельца;
//   [data-field="description"] = описание (в режиме чтения и при правке показывается результат);
//   вкладки: [role="tablist"] с тремя [role="tab"][data-tab="board"|"tasks"|"members"], тексты из
//     словаря и различны; по умолчанию aria-selected="true" у board; у вкладки aria-controls ->
//     id [role="tabpanel"] (aria-labelledby -> id вкладки); в активной панели h2 с текстом из
//     словаря (board/tasks - места под T86/T83, members - список участников);
//   правка - при permissions.manage: form[data-form="edit-project"] с input[name="name"]
//     (maxLength=255, предзаполнен), textarea[name="description"], button[type="submit"];
//     без manage формы нет (только чтение). Успех -> h1 и описание из ответа PATCH;
//   удаление - при permissions.manage: button[data-action="delete-project"] -> ConfirmDialog
//     ([role="alertdialog"], confirm/cancel как у /admin/users); confirm -> DELETE -> /projects;
//   передача владения - при permissions.manage: section[data-section="owner"] c
//     input[type="search"][name="owner_search"] (label) и строками-кандидатами
//     [data-owner-candidate="<user_id>"] (login + button[data-action="transfer-owner"]).
//     Кандидаты - участники проекта из GET /projects/{id}/members (все страницы, page_size=100
//     по цепочке has_next) с ролью business_admin или mixed и не is_blocked (FR-14a), кроме
//     текущего владельца; «Пользователь», заблокированные и без роли - не кандидаты. Фильтр
//     owner_search - на клиенте по подстроке login без учёта регистра. Список кандидатов - с
//     классом ui-list. Запрос GET /users НЕ используется. Клик по transfer-owner без
//     диалога -> PUT /owner {user_id}; права и поля - из ответа PUT. Ошибка -> role="alert";
//   участники (вкладка members): строки tr[data-user-id="<uuid>"] с [data-field="login"],
//     [data-field="role"] (из словаря, роль null - тоже текст), [data-field="owner"] (текст из
//     словаря только у владельца, у остальных пусто), [data-field="blocked"] (то же для is_blocked);
//     при permissions.manage_members: UserPicker (combobox, без allowedIds; выбор -> POST
//     /members {user_id}, затем перечитывается GET /members) и в каждой строке (в т.ч. у владельца)
//     button[data-action="remove-member"] -> DELETE без диалога в ЧУЖИХ строках; в строке
//     ТЕКУЩЕГО пользователя (user.id === me.id) тот же ConfirmDialog самоисключения, что у
//     button[data-action="leave-project"] (при permissions.remove_self): без подтверждения DELETE
//     не уходит; confirm -> DELETE /members/{me.id} -> /projects;
//   после мутаций состава (add/remove/leave/transfer) инвалидируется ["projects", id]: GET
//     /projects/{id} перечитывается (permissions, is_member), кнопка leave-project появляется и
//     исчезает без перезагрузки;
//   фокус: после создания проекта, передачи владения, удаления/выхода и добавления через picker
//     document.activeElement не body (h1 с tabIndex=-1 или логически следующий элемент);
//     combobox UserPicker во время запроса НЕ disabled, а aria-busy="true";
//   Pagination (общий) при busy: кнопки не disabled (фокус не теряется), aria-disabled="true",
//     повторный клик не шлёт запрос; на границах (нет next/prev) - disabled, как раньше;
//   перенос длинных слов: h1, ячейки таблиц и .ui-list попадают под правило ui.css с
//     overflow-wrap: anywhere;
//   загрузка /projects/not-a-uuid (422 validation_error на GET) -> alert errorMessage("not_found");
//   ошибка поиска UserPicker на странице не создаёт второй role="alert" (ошибка пикера выводится
//     как status или через общий канал);
//   вкладки: ArrowRight/ArrowLeft по кругу (фокус и выбор), Home/End, roving tabindex
//     (0 у выбранной, -1 у остальных); tabpanel без фокусируемого содержимого имеет tabIndex=0;
//     members запрашиваются с page_size=100;
//   на странице ровно один role="alert" (общий ErrorAlert; ошибки действий и загрузки);
//   ошибка загрузки проекта (403/404) -> alert errorMessage(code), без h1 с названием и без форм.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect } from "vitest";

import { ADMIN_ID, ID_IVANOV, ID_PETROV, j, meWith, page, type Handler } from "../admin/helpers";

export * from "../admin/helpers";

export const PID = "55555555-5555-4555-8555-555555555555";
export const PID2 = "66666666-6666-4666-8666-666666666666";
export const ID_SIDOROV = "77777777-7777-4777-8777-777777777777";
export const ID_KUZNETSOV = "88888888-8888-4888-8888-888888888888";

export const BUSINESS = ["business_access", "project_create", "task_assign_others"];
export const BUSINESS_NO_CREATE = ["business_access", "task_assign_others"];

export const ref = (id: string, login: string) => ({ id, login });
export const R_ME = ref(ADMIN_ID, "admin");
export const R_IVANOV = ref(ID_IVANOV, "ivanov");
export const R_PETROV = ref(ID_PETROV, "petrov");
export const R_SIDOROV = ref(ID_SIDOROV, "sidorov");
export const R_KUZNETSOV = ref(ID_KUZNETSOV, "kuznetsov");

export function listItem(id: string, name: string, owner = R_IVANOV, taskCount = 0) {
  return { id, name, owner, task_count: taskCount };
}

export const PERM_MANAGE = { manage: true, manage_members: true, create_task: true, remove_self: false };
export const PERM_READ = { manage: false, manage_members: false, create_task: true, remove_self: false };
export const PERM_MEMBER_LEAVE = { manage: false, manage_members: false, create_task: true, remove_self: true };

export function detail(over: Record<string, unknown> = {}) {
  return {
    id: PID,
    name: "Альфа",
    description: "Описание альфы",
    owner: R_IVANOV,
    task_count: 4,
    is_member: true,
    created_at: "2026-10-01T08:00:00Z",
    updated_at: "2026-10-02T08:00:00Z",
    permissions: PERM_MANAGE,
    ...over,
  };
}

export function member(
  user: { id: string; login: string },
  over: { role?: string | null; is_blocked?: boolean; is_owner?: boolean } = {},
) {
  return { user, role: "user", is_blocked: false, is_owner: false, ...over };
}

export const M_OWNER = member(R_IVANOV, { role: "business_admin", is_owner: true });
export const M_ME = member(R_ME, { role: "mixed" });
export const M_PETROV = member(R_PETROV, { role: "user", is_blocked: true });
export const M_SIDOROV = member(R_SIDOROV, { role: null });
export const M_KUZNETSOV = member(R_KUZNETSOV, { role: "business_admin" });
export const R_BLOCKED = ref("99999999-9999-4999-8999-999999999999", "zablokirov");
export const M_BLOCKED_MIXED = member(R_BLOCKED, { role: "mixed", is_blocked: true });
export const PERM_SM_MEMBER = { manage: true, manage_members: true, create_task: true, remove_self: true };

/** Содержимое ui.css для проверки CSS-правил (jsdom стили не подключает). */
export function cssRulesWithWrap(): string[] {
  const css = readFileSync(resolve(process.cwd(), "src/shared/ui/ui.css"), "utf8");
  const out: string[] = [];
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (/overflow-wrap\s*:\s*anywhere/.test(m[2]!)) out.push(...m[1]!.split(",").map((x) => x.trim()));
  }
  return out;
}
/** Попадает ли элемент под правило ui.css с overflow-wrap: anywhere. */
export function wraps(el: Element): boolean {
  return cssRulesWithWrap().some((sel) => {
    try {
      return el.matches(sel);
    } catch {
      return false;
    }
  });
}

export const ME = "GET /api/v1/me";
export const LIST = "GET /api/v1/projects";
export const CREATE = "POST /api/v1/projects";
export const ONE = `GET /api/v1/projects/${PID}`;
export const PATCH = `PATCH /api/v1/projects/${PID}`;
export const DEL = `DELETE /api/v1/projects/${PID}`;
export const OWNER = `PUT /api/v1/projects/${PID}/owner`;
export const MEMBERS = `GET /api/v1/projects/${PID}/members`;
export const ADD = `POST /api/v1/projects/${PID}/members`;
export const REMOVE = (uid: string) => `DELETE /api/v1/projects/${PID}/members/${uid}`;
export const USERS = "GET /api/v1/users";
export const BOARD_GET = `GET /api/v1/projects/${PID}/board`;

/** Пустая доска из 4 колонок (вкладка «Доска» открыта по умолчанию, T86). */
export function emptyBoard() {
  return {
    project: { id: PID, name: "Альфа" },
    columns: ["todo", "in_progress", "review", "done"].map((status) => ({ status, tasks: [] })),
  };
}

/** Маршруты страницы проекта по умолчанию; over перекрывает. */
export function projectRoutes(
  caps: string[],
  over: Record<string, Handler> = {},
  opts: { detail?: Record<string, unknown>; members?: unknown[] } = {},
): Record<string, Handler> {
  return {
    [ME]: () => j(200, meWith(caps, "business_admin")),
    [ONE]: () => j(200, detail(opts.detail)),
    [MEMBERS]: () => j(200, page(opts.members ?? [M_OWNER, M_ME, M_PETROV, M_SIDOROV])),
    [BOARD_GET]: () => j(200, emptyBoard()),
    ...over,
  };
}

export async function openMembersTab() {
  await screen.findByRole("tablist");
  const tab = document.querySelector<HTMLElement>('[role="tab"][data-tab="members"]');
  if (!tab) throw new Error("no members tab");
  fireEvent.click(tab);
  await waitFor(() => expect(tab.getAttribute("aria-selected")).toBe("true"));
  return tab;
}
