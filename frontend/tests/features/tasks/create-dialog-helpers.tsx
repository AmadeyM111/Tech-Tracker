// 004 / R5-T02: помощники тестов диалога «Новая задача» (plan §5; фикстуры spec §5).
//
// КОНТРАКТ ДЛЯ ИСПОЛНИТЕЛЯ: CreateTaskDialog({ currentProjectId, currentUser, canPickAssignee, onClose,
// onCreated }) из src/features/tasks/CreateTaskForm.tsx; разметка и поведение - plan §4.2 и (006, R6-T11) §4.7.
// 006: в состоянии «готово» строка выбранного исполнителя - [data-field="selected-assignee"], кнопка
// «Сбросить» - [data-action="clear-assignee"], строка «Пользователя» - [data-field="fixed-assignee"]
// (те же атрибуты, что у CreateTaskForm); участники проекта - GET /projects/{id}/members (listAllMembers).
// Диалог читает GET /api/v1/projects (page_size=100) и GET /api/v1/projects/{id} (permissions.create_task).
// Роли: BA (business_admin) видит P1, P2, P3, право создания у P1 и P3; U (user) видит P1, P3.
// Диалог от роли не зависит напрямую: роль определяет только то, что отвечает сервер.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, vi } from "vitest";

import { CreateTaskDialog } from "../../../src/features/tasks/CreateTaskForm";
import {
  ADMIN_ID,
  ID_IVANOV,
  ID_KUZNETSOV,
  ID_SIDOROV,
  LIST,
  M_KUZNETSOV,
  M_ME,
  M_OWNER,
  M_SIDOROV,
  PERM_READ,
  PID,
  PID2,
  detail,
  j,
  listItem,
  member,
  page,
  ref,
  type Handler,
} from "../projects/helpers";
import { taskDetail } from "./helpers";

export { deferred, err, installFetch, j, page } from "../admin/helpers";
export { ADMIN_ID, ID_KUZNETSOV };

// --- 006 / R6-T11: время, роли, участники ---

/** 2026-10-19T21:30:00Z = 2026-10-20 00:30 по Москве при любом поясе среды (как freezeTime в CreateTaskForm.test.tsx). */
export const NOW = new Date("2026-10-19T21:30:00Z");
export const TODAY = "2026-10-20";
export const YESTERDAY = "2026-10-19";

/** Фиксирует Date на NOW для каждого теста файла (таймеры не трогаем: only Date). Вызывать на верхнем уровне. */
export function freezeDateForFile(): void {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });
}

export const ID_UB = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
export const ID_PETROV_NM = "ffffffff-ffff-4fff-8fff-ffffffffffff"; // не участник проекта
/** Сессия BA (login «admin») и сессия U (login «ivanov»): пропсы currentUser/canPickAssignee диалога. */
export const BA = { currentUser: { id: ADMIN_ID, login: "admin" }, canPickAssignee: true } as const;
export const U = { currentUser: { id: ID_IVANOV, login: "ivanov" }, canPickAssignee: false } as const;

export const MEMBERS_OF = (id: string) => `GET /api/v1/projects/${id}/members`;
export const USERS_DIR = "GET /api/v1/users";

const M_UB = member(ref(ID_UB, "ub"), { role: "user", is_blocked: true });
/** P1/P2: admin, kuznetsov, заблокированный ub, участник без роли sidorov; petrov - не участник. P3: admin, ivanov. */
export const MEMBERS_P1 = [M_OWNER, M_ME, M_KUZNETSOV, M_UB, M_SIDOROV];
export const MEMBERS_P3 = [M_OWNER, M_ME];

const DIRECTORY = [
  { id: ADMIN_ID, login: "admin", role: "business_admin" },
  { id: ID_IVANOV, login: "ivanov", role: "business_admin" },
  { id: ID_KUZNETSOV, login: "kuznetsov", role: "business_admin" },
  { id: ID_UB, login: "ub", role: "user" },
  { id: ID_SIDOROV, login: "sidorov", role: "user" },
  { id: ID_PETROV_NM, login: "petrov", role: "user" },
];

/** GET /users?q=...: справочник, отфильтрованный по подстроке логина (как делает сервер). */
const directory: Handler = (r) => {
  const q = (new URL(r.url).searchParams.get("q") ?? "").toLowerCase();
  return j(200, page(DIRECTORY.filter((u) => u.login.includes(q)), 1, false, 50));
};

export const P1 = PID; // «Альфа»
export const P2 = PID2; // «Бета»
export const P3 = "99999999-0000-4999-8999-999999999993"; // «Гамма»
export const NAME: Record<string, string> = { [P1]: "Альфа", [P2]: "Бета", [P3]: "Гамма" };

const NO_CREATE = { manage: false, manage_members: false, create_task: false, remove_self: false };

/** Ответ GET /api/v1/projects/{id} с permissions.create_task. */
export function projectCard(id: string, name: string, createTask: boolean) {
  return detail({ id, name, permissions: createTask ? PERM_READ : NO_CREATE });
}

export const LIST_BA = [listItem(P1, "Альфа"), listItem(P2, "Бета"), listItem(P3, "Гамма")];
export const LIST_U = [listItem(P1, "Альфа"), listItem(P3, "Гамма")];
export const LIST_ONE = [listItem(P1, "Альфа")];

export const CARD = (id: string) => `GET /api/v1/projects/${id}`;
export const CREATE_IN = (id: string) => `POST /api/v1/projects/${id}/tasks`;

/** Новая задача из ответа 201 с фиксированным id (проект - P1). */
export const T_NEW_ID = "d1d1d1d1-0000-4000-8000-000000000001";
export const T_NEW = taskDetail({ id: T_NEW_ID, title: "Отчёт", project: { id: P1, name: "Альфа" } });

/** Маршруты: один список (без пагинации) и карточки с правами `perms` (id -> create_task, по умолчанию true). */
export function dialogRoutes(
  items: ReturnType<typeof listItem>[],
  perms: Record<string, boolean> = {},
  over: Record<string, Handler> = {},
): Record<string, Handler> {
  const routes: Record<string, Handler> = {
    [LIST]: () => j(200, page(items, 1, false, 100)),
    [CREATE_IN(P1)]: () => j(201, T_NEW),
    [CREATE_IN(P2)]: () => j(201, T_NEW),
    [CREATE_IN(P3)]: () => j(201, T_NEW),
    [MEMBERS_OF(P1)]: () => j(200, page(MEMBERS_P1, 1, false, 100)),
    [MEMBERS_OF(P2)]: () => j(200, page(MEMBERS_P1, 1, false, 100)),
    [MEMBERS_OF(P3)]: () => j(200, page(MEMBERS_P3, 1, false, 100)),
    [USERS_DIR]: directory,
  };
  for (const it of items) routes[CARD(it.id)] = () => j(200, projectCard(it.id, it.name, perms[it.id] ?? true));
  return { ...routes, ...over };
}

/** Профиль BA: список [P1, P2, P3], право создания у P1 и P3. */
export const routesBA = (over: Record<string, Handler> = {}) =>
  dialogRoutes(LIST_BA, { [P1]: true, [P2]: false, [P3]: true }, over);
/** Профиль U: список [P1, P3], право у обоих. */
export const routesU = (over: Record<string, Handler> = {}) => dialogRoutes(LIST_U, {}, over);

/** Две страницы списка: первая (has_next) - Гамма, вторая - Альфа; право есть у обоих. */
export function routesTwoPages(): Record<string, Handler> {
  return dialogRoutes(
    [],
    {},
    {
      [LIST]: (r) =>
        new URL(r.url).searchParams.get("page") === "1"
          ? j(200, page([listItem(P3, "Гамма")], 1, true, 100))
          : j(200, page([listItem(P1, "Альфа")], 2, false, 100)),
      [CARD(P1)]: () => j(200, projectCard(P1, "Альфа", true)),
      [CARD(P3)]: () => j(200, projectCard(P3, "Гамма", true)),
    },
  );
}

export interface RenderOpts {
  currentProjectId?: string | null;
  /** Общий QueryClient: позволяет смонтировать диалог повторно с тем же кэшем. */
  qc?: QueryClient;
  /** 006: сессия диалога; по умолчанию U (login «ivanov», без выбора исполнителя). */
  session?: { currentUser: { id: string; login: string }; canPickAssignee: boolean };
}

export function renderDialog(opts: RenderOpts = {}) {
  const qc = opts.qc ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  const onCreated = vi.fn();
  const out = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CreateTaskDialog
          currentProjectId={opts.currentProjectId ?? null}
          currentUser={(opts.session ?? U).currentUser}
          canPickAssignee={(opts.session ?? U).canPickAssignee}
          onClose={onClose}
          onCreated={onCreated}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...out, qc, onClose, onCreated };
}

// --- R5-T03: отправка ---

/** Тело перехваченного запроса как объект (clone: тело можно читать повторно). */
export const readBody = async (r: Request) => (await r.clone().json()) as Record<string, unknown>;

/** Обработчик, имитирующий падение сети (fetch бросает TypeError). */
export const networkFail = (): Response => {
  throw new TypeError("Failed to fetch");
};

/** Подпись обязательного поля содержит знак «*» (006/PD-12): сравнение точное с учётом знака. */
export const exactLabel = (text: string): RegExp =>
  new RegExp(`^${text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\*?$`);
