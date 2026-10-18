// 004 / R5-T05: кнопка «Задача» в боковом меню и связка с диалогом «Новая задача» (через AppRoutes).
//
// КОНТРАКТ ДЛЯ ИСПОЛНИТЕЛЯ (plan §4.4): в Sidebar при business_access между `nav` и «Выйти» -
//   button[type=button][data-action="create-task"][aria-haspopup="dialog"] без aria-expanded и aria-label,
//   первый (и единственный) дочерний элемент-svg - иконка (aria-hidden), затем текст ru["nav.create_task"] = «Задача».
//   Окно диалога - сосед div.ui-sidebar (не внутри nav). onClose: закрыть и вернуть фокус на кнопку;
//   onCreated: закрыть и navigate(`/tasks/${id}`) (push). После размонтирования диалога (смена экрана,
//   пока запрос создания в полёте) onCreated НЕ вызывается (замечание R5-T03-1): путь не меняется.
// AC: 9, 10, 11, 12, 13, 14 (вне nav), 19 (кнопка видна, фокус после Escape), 20 (вкладки), 21, 26, 27, 28 (путь
// не изменился), 29 (401 -> /login), 31 (путь после 201), 32 (фокус на «Задача»), 35, 36, 41, 42 (разметка);
// FR-5, FR-6, FR-7, FR-15, FR-20..FR-22. Фикстуры BA/U/TA/NR/PWD - spec §5.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useNavigate, type NavigateFunction } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../src/app/router";
import { errorMessage, ru } from "../../src/shared/i18n";
import { boardBody, card, column } from "../features/boards/helpers";
import {
  CAPS_ALL,
  Where,
  deferred,
  err,
  expectAt,
  installFetch,
  j,
  meWith,
  page,
  where,
  type Handler,
} from "../features/admin/helpers";
import { emptyBoard } from "../features/projects/helpers";
import {
  CREATE_IN,
  LIST_BA,
  LIST_ONE,
  P1,
  P2,
  P3,
  T_NEW,
  T_NEW_ID,
  dialogRoutes,
  networkFail,
  readBody,
  renderDialog,
  routesBA,
  routesU,
} from "../features/tasks/create-dialog-helpers";
import { taskItem } from "../features/tasks/helpers";

const ME = "GET /api/v1/me";
// Литерал-запасной вариант: пока ключа нет, поиск по роли и имени не должен совпадать со всеми кнопками подряд.
const TASK = (ru as Record<string, string>)["nav.create_task"] ?? "Задача";
const MENU = ru["app.menu_label"];
const BA_CAPS = ["business_access", "project_create", "task_assign_others"];
const U_CAPS = ["business_access"];
const ROLES = [
  ["BA", "business_admin", BA_CAPS],
  ["U", "user", U_CAPS],
] as const;
const TID = "44444444-4444-4444-8444-444444444444";
const OLD_TASK = "a1a1a1a1-0000-4000-8000-000000000001";

afterEach(() => {
  vi.unstubAllGlobals();
});

// --------------------------------------------------------------------------------- helpers

/** Маршруты, которых экран требует «внутри» (доска, участники, комментарии): пустые ответы. Остальное - ошибка теста. */
function withFallback(routes: Record<string, Handler>): Record<string, Handler> {
  return new Proxy(routes, {
    get(target, key) {
      if (typeof key !== "string") return undefined;
      const own = target[key];
      if (own) return own;
      if (/^GET \/api\/v1\/projects\/[^/]+\/board$/.test(key)) return () => j(200, emptyBoard());
      if (/^GET \/api\/v1\/(projects|tasks)\/[^/]+\/(members|tasks|comments|subtasks|attachments)$/.test(key)) {
        return () => j(200, page([]));
      }
      return undefined;
    },
  });
}

type Role = (typeof ROLES)[number];

/** Общие маршруты экранов для роли: профиль, «Мои задачи», карточка новой задачи. */
function common(role: Role, over: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    [ME]: () => j(200, meWith([...role[2]], role[1])),
    "GET /api/v1/me/tasks": () => j(200, page([])),
    [`GET /api/v1/tasks/${T_NEW_ID}`]: () => j(200, T_NEW),
    [`GET /api/v1/tasks/${TID}`]: () => err(404, "not_found"),
    ...over,
  };
}

/** Список/карточки диалога для роли (BA: P1, P2 без права, P3; U: P1, P3). */
function dialogFor(role: Role, over: Record<string, Handler> = {}): Record<string, Handler> {
  return role[1] === "user" ? routesU(common(role, over)) : routesBA(common(role, over));
}

interface AppCtx {
  qc: QueryClient;
  nav: { go?: NavigateFunction };
}

/** renderApp + доступ к navigate (шаг «Назад») и необязательный staleTime кэша. */
function renderAppNav(path: string, staleTime?: number) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, ...(staleTime === undefined ? {} : { staleTime }) } },
  });
  const nav: AppCtx["nav"] = {};
  function Grab() {
    nav.go = useNavigate();
    return null;
  }
  const out = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
        <Where />
        <Grab />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...out, qc, nav };
}

function boot(routes: Record<string, Handler>, path: string, staleTime?: number) {
  const f = installFetch(withFallback(routes));
  return { f, ...renderAppNav(path, staleTime) };
}

const sidebar = () => document.querySelector<HTMLElement>(".ui-sidebar")!;
const menu = () => screen.findByRole("navigation", { name: MENU });
const createBtn = () => screen.getByRole("button", { name: TASK });
const dlg = () => screen.getByRole("dialog");
const projectSelect = () => within(dlg()).getByLabelText(ru["tasks.project_label"]) as HTMLSelectElement;
const titleInput = () => within(dlg()).getByLabelText(ru["tasks.title_label"]) as HTMLInputElement;
const submitBtn = () => within(dlg()).getByRole("button", { name: ru["tasks.create_submit"] });
const cancelBtn = () => within(dlg()).getByRole("button", { name: ru["admin.cancel"] });
const settle = (ms = 150) => new Promise((r) => setTimeout(r, ms));
const posts = (f: { calls: Request[] }) => f.calls.filter((c) => c.method === "POST");
const LIST = "GET /api/v1/projects";
const calls = (f: { calls: Request[] }) =>
  f.calls.map((c) => `${c.method} ${new URL(c.url).pathname}${new URL(c.url).search}`).sort();

async function openDialog() {
  await menu();
  fireEvent.click(await screen.findByRole("button", { name: TASK }));
  return screen.findByRole("dialog");
}
const loaded = () => screen.findByLabelText(ru["tasks.project_label"]);
const pick = (id: string) => fireEvent.change(projectSelect(), { target: { value: id } });
const type = (v: string) => fireEvent.change(titleInput(), { target: { value: v } });
const press = (key: string) => fireEvent.keyDown(document.activeElement as HTMLElement, { key });

/** Нажатие Tab как в браузере по ВСЕМУ документу: если обработчик не отменил событие, фокус идёт к соседу. */
function tabThroughDocument(shift: boolean) {
  const sel = 'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])';
  const els = Array.from(document.querySelectorAll<HTMLElement>(sel)).filter(
    (e) => !(e as HTMLButtonElement).disabled,
  );
  const active = document.activeElement as HTMLElement;
  const proceed = fireEvent.keyDown(active, { key: "Tab", shiftKey: shift });
  if (proceed) {
    const i = els.indexOf(active);
    const next = shift ? els[(i <= 0 ? els.length : i) - 1] : els[(i + 1) % els.length];
    (next ?? document.body).focus();
  }
}

/** Все проверки AC-9 для одной кнопки «Задача» бокового меню текущего экрана. */
async function expectCreateButton() {
  await menu();
  const inSidebar = within(sidebar()).getAllByRole("button", { name: TASK });
  expect(inSidebar).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: TASK })).toHaveLength(1);
  const b = inSidebar[0] as HTMLButtonElement;
  expect(b.type).toBe("button");
  expect(b.getAttribute("data-action")).toBe("create-task");
  expect(b.getAttribute("aria-haspopup")).toBe("dialog");
  expect(b.hasAttribute("aria-expanded")).toBe(false);
  expect(b.hasAttribute("aria-label")).toBe(false);
  expect(b.textContent).toBe(TASK);
  expect(sidebar().querySelector("nav")!.contains(b)).toBe(false);
  const icon = b.firstElementChild;
  expect(b.firstChild).toBe(icon);
  expect(icon?.tagName.toLowerCase()).toBe("svg");
  expect(icon?.getAttribute("aria-hidden")).toBe("true");
  expect(icon?.innerHTML).not.toBe("");
  const others = Array.from(sidebar().querySelectorAll("a, button"))
    .filter((e) => e !== b)
    .map((e) => e.firstElementChild?.innerHTML);
  expect(others.length).toBeGreaterThan(0);
  for (const markup of others) expect(markup).not.toBe(icon!.innerHTML);
  return b;
}

// ------------------------------------------------------------------------------ dictionary

describe("dictionary (FR-6, NFR-2)", () => {
  it("004_fr6_button_label_is_in_dictionary", () => {
    expect((ru as Record<string, string>)["nav.create_task"]).toBe("Задача");
  });
});

// ------------------------------------------------------------------------------- AC-9..AC-13

describe("AC-9 button on every screen with a sidebar", () => {
  for (const role of ROLES) {
    const [name] = role;
    const routes = () => dialogFor(role);
    it.each(["/projects", "/my-tasks", `/tasks/${TID}`])(`004_ac9_${name}_%s_one_button_with_contract`, async (path) => {
      boot(routes(), path);
      await expectCreateButton();
    });

    it(`004_ac9_${name}_project_tabs_board_tasks_members`, async () => {
      boot(routes(), `/projects/${P1}`);
      await expectCreateButton();
      await screen.findByRole("tablist");
      for (const tab of ["tasks", "members", "board"]) {
        fireEvent.click(document.querySelector<HTMLElement>(`[role="tab"][data-tab="${tab}"]`)!);
        await waitFor(() =>
          expect(document.querySelector(`[role="tab"][data-tab="${tab}"]`)!.getAttribute("aria-selected")).toBe("true"),
        );
        await expectCreateButton();
      }
    });

    it.each(["/admin/users", "/admin/audit"])(`004_ac9_${name}_%s_denied_screen_has_the_button`, async (path) => {
      const f = boot(routes(), path).f;
      await expectCreateButton();
      expect(screen.getAllByRole("alert")).toHaveLength(1);
      expect(f.calls.filter((c) => new URL(c.url).pathname.startsWith("/api/v1/admin"))).toHaveLength(0);
    });
  }
});

describe("AC-10 no button without business_access", () => {
  const ADMIN_ROUTES: Record<string, Handler> = {
    [ME]: () => j(200, meWith(CAPS_ALL)),
    "GET /api/v1/admin/users": () => j(200, page([])),
    "GET /api/v1/admin/audit": () => j(200, page([])),
  };

  it.each(["/admin/users", "/admin/audit", "/projects", "/my-tasks"])("004_ac10_TA_%s_no_button", async (path) => {
    boot(ADMIN_ROUTES, path);
    await menu();
    await settle();
    expect(screen.queryByRole("button", { name: TASK })).toBeNull();
    expect(document.querySelector('[data-action="create-task"]')).toBeNull();
    expect(within(sidebar()).getAllByRole("button")).toHaveLength(1); // only "Выйти"
  });
});

describe("AC-11 no button on screens without a sidebar", () => {
  const noButton = async (path: string) => {
    await expectAt(path);
    await settle();
    expect(document.querySelector(".ui-sidebar")).toBeNull();
    expect(screen.queryByRole("button", { name: TASK })).toBeNull();
    expect(document.querySelector('[data-action="create-task"]')).toBeNull();
  };

  it("004_ac11_NR_no_role_screen_no_button", async () => {
    boot({ [ME]: () => err(403, "no_role") }, "/no-role");
    await noButton("/no-role");
  });
  it("004_ac11_PWD_change_password_no_button", async () => {
    boot({ [ME]: () => err(403, "password_change_required") }, "/change-password");
    await noButton("/change-password");
  });
  it("004_ac11_guest_login_no_button", async () => {
    boot({ [ME]: () => err(401, "not_authenticated") }, "/login");
    await noButton("/login");
  });
});

describe("AC-12 order in the document and Tab sequence", () => {
  const PATHS = ["/projects", `/projects/${P1}`, `/tasks/${TID}`, "/my-tasks", "/admin/users", "/admin/audit"];
  for (const role of ROLES) {
    it.each(PATHS)(`004_ac12_${role[0]}_%s_links_then_task_then_logout`, async (path) => {
      boot(dialogFor(role), path);
      const nav = await menu();
      const b = await screen.findByRole("button", { name: TASK });
      const logout = screen.getByRole("button", { name: ru["auth.logout"] });
      const lastLink = within(nav).getAllByRole("link").at(-1)!;
      expect(lastLink.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(b.compareDocumentPosition(logout) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      // "непосредственно перед «Выйти»": между ними в панели нет других фокусируемых элементов
      const focusable = Array.from(
        sidebar().querySelectorAll<HTMLElement>("a[href], button:not([disabled]), [tabindex]:not([tabindex='-1'])"),
      );
      const i = focusable.indexOf(b);
      expect(focusable[i - 1]).toBe(lastLink);
      expect(focusable[i + 1]).toBe(logout);
      expect(focusable.at(-1)).toBe(logout);
    });
  }

  it("004_ac12_BA_projects_tab_sequence_links_task_logout_content", async () => {
    boot(dialogFor(ROLES[0]), "/projects");
    await screen.findByRole("form", { name: ru["projects.create_title"] });
    const tabbable = Array.from(
      document.querySelectorAll<HTMLElement>("a[href], button, input, select, textarea, [tabindex]"),
    ).filter((el) => el.getAttribute("tabindex") !== "-1" && !(el as HTMLButtonElement).disabled);
    const form = document.querySelector<HTMLElement>('form[data-form="create-project"]')!;
    expect(tabbable.slice(0, 2).map((el) => el.getAttribute("href"))).toEqual(["/projects", "/my-tasks"]);
    expect(tabbable[2]?.getAttribute("data-action")).toBe("create-task");
    expect(tabbable[3]?.getAttribute("data-action")).toBe("logout");
    expect(tabbable[4]).toBe(tabbable.find((el) => form.contains(el)));
  });
});

describe("AC-13 no extra requests while the dialog is closed", () => {
  const CASES: [string, string[]][] = [
    ["/projects", [ME, "GET /api/v1/projects?page=1"]],
    [
      `/projects/${P1}`,
      [
        ME,
        `GET /api/v1/projects/${P1}`,
        `GET /api/v1/projects/${P1}/board`,
        `GET /api/v1/projects/${P1}/members?page=1&page_size=100`,
      ],
    ],
    ["/my-tasks", [ME, "GET /api/v1/me/tasks?page=1"]],
  ];
  it.each(CASES)("004_ac13_BA_%s_requests_are_only_the_screens_own", async (path, expected) => {
    const f = boot(dialogFor(ROLES[0]), path).f;
    await expectCreateButton();
    await settle(300);
    expect(calls(f)).toEqual([...expected].sort());
  });
});

// ------------------------------------------------------------------------------ AC-14, 19..21

describe("AC-14 dialog opened from the sidebar", () => {
  it("004_ac14_U_my_tasks_one_modal_dialog_outside_nav", async () => {
    boot(dialogFor(ROLES[1]), "/my-tasks");
    await openDialog();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    const d = screen.getByRole("dialog", { name: ru["tasks.create_title"] });
    expect(d.getAttribute("aria-modal")).toBe("true");
    expect(d.closest("nav")).toBeNull();
    expect(screen.getByRole("navigation", { name: MENU }).contains(d)).toBe(false);
    await loaded();
    expect(projectSelect().tagName).toBe("SELECT");
    expect(titleInput().tagName).toBe("INPUT");
    expect(submitBtn().getAttribute("type")).toBe("submit");
    expect(cancelBtn().getAttribute("type")).toBe("button");
    for (const key of ["tasks.description_label", "tasks.due_label", "tasks.priority_label", "tasks.assignee_label"]) {
      expect(within(d).queryByLabelText(ru[key as keyof typeof ru])).toBeNull();
    }
  });
});

describe("AC-19 no creatable projects", () => {
  const CASES: [string, Role, Record<string, Handler>][] = [
    ["U_empty_list", ROLES[1], dialogRoutes([], {}, common(ROLES[1]))],
    [
      "BA_all_create_task_false",
      ROLES[0],
      dialogRoutes(LIST_BA, { [P1]: false, [P2]: false, [P3]: false }, common(ROLES[0])),
    ],
  ];
  it.each(CASES)("004_ac19_%s_button_enabled_message_close_focus_escape_returns_to_task", async (_n, _r, routes) => {
    const f = boot(routes, "/my-tasks").f;
    await menu();
    const b = await screen.findByRole("button", { name: TASK });
    expect((b as HTMLButtonElement).disabled).toBe(false);
    await openDialog();
    expect(await within(dlg()).findByText(ru["tasks.no_creatable_projects"])).toBeTruthy();
    expect(within(dlg()).queryByLabelText(ru["tasks.title_label"])).toBeNull();
    expect(within(dlg()).queryByRole("button", { name: ru["tasks.create_submit"] })).toBeNull();
    const close = within(dlg()).getByRole("button", { name: ru["tasks.dialog_close"] });
    await waitFor(() => expect(document.activeElement).toBe(close));
    press("Escape");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(createBtn());
    expect(posts(f)).toHaveLength(0);
  });
});

describe("AC-20 preselect on a project page (any tab)", () => {
  it("004_ac20_BA_project_page_every_tab_selects_alpha_focus_on_title", async () => {
    boot(dialogFor(ROLES[0]), `/projects/${P1}`);
    await screen.findByRole("tablist");
    for (const tab of ["board", "tasks", "members"]) {
      fireEvent.click(document.querySelector<HTMLElement>(`[role="tab"][data-tab="${tab}"]`)!);
      await waitFor(() =>
        expect(document.querySelector(`[role="tab"][data-tab="${tab}"]`)!.getAttribute("aria-selected")).toBe("true"),
      );
      await openDialog();
      await loaded();
      expect(projectSelect().value).toBe(P1);
      expect(projectSelect().selectedOptions[0]?.textContent).toBe("Альфа");
      await waitFor(() => expect(document.activeElement).toBe(titleInput()));
      press("Escape");
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    }
  });

  it("004_ac20_BA_project_without_right_nothing_selected_no_beta_focus_on_select", async () => {
    boot(dialogFor(ROLES[0]), `/projects/${P2}`);
    await openDialog();
    await loaded();
    expect(projectSelect().value).toBe("");
    expect(Array.from(projectSelect().options).map((o) => o.textContent)).toEqual([
      ru["tasks.project_placeholder"],
      "Альфа",
      "Гамма",
    ]);
    await waitFor(() => expect(document.activeElement).toBe(projectSelect()));
  });
});

describe("AC-21 / AC-41 nothing or the only project is preselected outside a project page", () => {
  it.each(["/projects", "/my-tasks", `/tasks/${T_NEW_ID}`])(
    "004_ac21_U_two_projects_%s_nothing_selected_focus_on_select",
    async (path) => {
      boot(dialogFor(ROLES[1]), path);
      await openDialog();
      await loaded();
      expect(projectSelect().value).toBe("");
      await waitFor(() => expect(document.activeElement).toBe(projectSelect()));
    },
  );

  it.each(["/projects", "/my-tasks", `/tasks/${T_NEW_ID}`])(
    "004_ac41_U_single_project_%s_selected_focus_on_title",
    async (path) => {
      boot(dialogRoutes(LIST_ONE, {}, common(ROLES[1])), path);
      await openDialog();
      await loaded();
      expect(projectSelect().value).toBe(P1);
      expect(projectSelect().selectedOptions[0]?.textContent).toBe("Альфа");
      await waitFor(() => expect(document.activeElement).toBe(titleInput()));
    },
  );

  it("004_ac41_BA_only_alpha_creatable_on_beta_page_alpha_selected_no_beta", async () => {
    boot(dialogRoutes(LIST_BA, { [P1]: true, [P2]: false, [P3]: false }, common(ROLES[0])), `/projects/${P2}`);
    await openDialog();
    await loaded();
    expect(projectSelect().value).toBe(P1);
    expect(Array.from(projectSelect().options).map((o) => o.textContent)).toEqual([
      ru["tasks.project_placeholder"],
      "Альфа",
    ]);
  });
});

// ------------------------------------------------------------------------------ AC-26..AC-31

describe("AC-26 / AC-31 success opens the task card", () => {
  it("004_ac26_201_closes_dialog_opens_card_focus_on_h1_back_returns", async () => {
    const app = boot(dialogFor(ROLES[1]), "/my-tasks");
    await openDialog();
    await loaded();
    pick(P1);
    type("Отчёт");
    fireEvent.click(submitBtn());
    await expectAt(`/tasks/${T_NEW_ID}`);
    expect(screen.queryByRole("dialog")).toBeNull();
    const h1 = await screen.findByRole("heading", { level: 1 });
    // для задачи с правом правки название лежит в поле внутри h1
    expect(h1.querySelector("input")?.value ?? h1.textContent).toBe(T_NEW.title);
    await waitFor(() => expect(document.activeElement).toBe(h1));
    expect(posts(app.f)).toHaveLength(1);
    expect(app.nav.go).toBeTypeOf("function");
    act(() => {
      app.nav.go!(-1);
    });
    await expectAt("/my-tasks");
  });

  it("004_ac31_delayed_201_escape_ignored_cancel_disabled_then_path_is_the_card", async () => {
    const d = deferred<Response>();
    const f = boot(dialogFor(ROLES[0], { [CREATE_IN(P1)]: () => d.promise }), "/projects");
    await openDialog();
    await loaded();
    pick(P1);
    type("Отчёт");
    fireEvent.click(submitBtn());
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).toBe("true"));
    press("Escape");
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect((cancelBtn() as HTMLButtonElement).disabled).toBe(true);
    expect(where()).toBe("/projects");
    d.resolve(j(201, T_NEW));
    await expectAt(`/tasks/${T_NEW_ID}`);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts(f.f)).toHaveLength(1);
  });
});

describe("AC-27 the new task is in lists on the next open, without a poll tick", () => {
  it("004_ac27_task_created_on_my_tasks_is_on_board_todo_and_in_tasks_tab_within_a_second", async () => {
    let created = false;
    const newCard = card(T_NEW_ID, "Отчёт", "todo", 100);
    const oldCard = card(OLD_TASK, "Старая", "todo", 10);
    const routes = dialogFor(ROLES[1], {
      [CREATE_IN(P1)]: () => ((created = true), j(201, T_NEW)),
      [`GET /api/v1/projects/${P1}/board`]: () =>
        j(
          200,
          boardBody({
            todo: created ? [oldCard, newCard] : [oldCard],
            in_progress: [],
            review: [],
            done: [],
          }),
        ),
      [`GET /api/v1/projects/${P1}/tasks`]: () =>
        j(200, page(created ? [taskItem(OLD_TASK, "Старая"), taskItem(T_NEW_ID, "Отчёт")] : [taskItem(OLD_TASK, "Старая")])),
    });
    // Кэш считается свежим минуту: новая карточка может появиться только из-за инвалидации диалогом.
    boot(routes, `/projects/${P1}`, 60_000);
    await screen.findByText("Старая");
    expect(within(column(document.body, "todo")!).queryByText("Отчёт")).toBeNull();
    fireEvent.click(within(await menu()).getByRole("link", { name: ru["nav.my_tasks"] }));
    await expectAt("/my-tasks");
    await openDialog();
    await loaded();
    pick(P1);
    type("Отчёт");
    fireEvent.click(submitBtn());
    await expectAt(`/tasks/${T_NEW_ID}`);
    await screen.findByRole("heading", { level: 1 });

    fireEvent.click(within(await menu()).getByRole("link", { name: ru["nav.projects"] }));
    await expectAt("/projects");
    fireEvent.click(await screen.findByRole("link", { name: "Альфа" }));
    await expectAt(`/projects/${P1}`);
    await waitFor(() => expect(within(column(document.body, "todo")!).getByText("Отчёт")).toBeTruthy(), {
      timeout: 1000,
    });

    const tab = document.querySelector<HTMLElement>('[role="tab"][data-tab="tasks"]')!;
    fireEvent.click(tab);
    await waitFor(() => expect(document.querySelector(`tr[data-task-id="${T_NEW_ID}"]`)).toBeTruthy(), {
      timeout: 1000,
    });
  });
});

describe("AC-28 create errors keep the dialog and the path", () => {
  const CASES: [string, Handler, string][] = [
    ["403_forbidden", () => err(403, "forbidden"), "forbidden"],
    ["404_not_found", () => err(404, "not_found"), "not_found"],
    ["422_validation_error", () => err(422, "validation_error"), "validation_error"],
    ["503_service_busy", () => err(503, "service_busy"), "service_busy"],
    ["network", networkFail, "network_error"],
  ];
  it.each(CASES)("004_ac28_%s_one_alert_dialog_and_path_kept_resubmit_sends_again", async (_n, handler, code) => {
    const f = boot(dialogFor(ROLES[1], { [CREATE_IN(P3)]: handler }), "/my-tasks");
    await openDialog();
    await loaded();
    pick(P3);
    type("Отчёт");
    fireEvent.click(submitBtn());
    await waitFor(() => expect(within(dlg()).getAllByRole("alert")).toHaveLength(1));
    expect(within(dlg()).getByRole("alert").textContent).toBe(errorMessage(code));
    expect(where()).toBe("/my-tasks");
    expect(projectSelect().value).toBe(P3);
    expect(titleInput().value).toBe("Отчёт");
    expect(posts(f.f)).toHaveLength(1);
    await waitFor(() => expect((submitBtn() as HTMLButtonElement).getAttribute("aria-busy")).not.toBe("true"));
    fireEvent.click(submitBtn());
    await waitFor(() => expect(posts(f.f)).toHaveLength(2));
    expect(where()).toBe("/my-tasks");
    expect(await readBody(posts(f.f)[1]!)).toEqual({ title: "Отчёт" });
  });
});

describe("AC-29 401 on create", () => {
  it("004_ac29_401_goes_to_login", async () => {
    let out = false;
    const f = boot(
      dialogFor(ROLES[1], {
        [ME]: () => (out ? err(401, "not_authenticated") : j(200, meWith(U_CAPS, "user"))),
        [CREATE_IN(P1)]: () => ((out = true), err(401, "not_authenticated")),
      }),
      "/my-tasks",
    );
    await openDialog();
    await loaded();
    pick(P1);
    type("Отчёт");
    fireEvent.click(submitBtn());
    await expectAt("/login");
    expect(posts(f.f)).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    await settle();
    expect(where()).toBe("/login");
  });
});

describe("R5-T03-1 no onCreated after unmount", () => {
  it("004_r5t03_1_dialog_unmounted_while_request_in_flight_never_calls_onCreated", async () => {
    const d = deferred<Response>();
    installFetch(routesU({ [CREATE_IN(P1)]: () => d.promise }));
    const { unmount, onCreated, onClose } = renderDialog({ currentProjectId: P1 });
    await loaded();
    fireEvent.change(screen.getByLabelText(ru["tasks.title_label"]), { target: { value: "Отчёт" } });
    fireEvent.click(screen.getByRole("button", { name: ru["tasks.create_submit"] }));
    await settle(30);
    unmount();
    d.resolve(j(201, T_NEW));
    await settle(100);
    expect(onCreated).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("004_r5t03_1_leaving_the_screen_during_the_request_keeps_the_new_path", async () => {
    const d = deferred<Response>();
    const f = boot(dialogFor(ROLES[0], { [CREATE_IN(P1)]: () => d.promise }), "/projects");
    await openDialog();
    await loaded();
    pick(P1);
    type("Отчёт");
    fireEvent.click(submitBtn());
    await waitFor(() => expect(submitBtn().getAttribute("aria-busy")).toBe("true"));
    fireEvent.click(within(await menu()).getByRole("link", { name: ru["nav.my_tasks"] }));
    await expectAt("/my-tasks");
    expect(screen.queryByRole("dialog")).toBeNull();
    d.resolve(j(201, T_NEW));
    await settle(200);
    expect(where()).toBe("/my-tasks");
    expect(posts(f.f)).toHaveLength(1);
  });
});

// ------------------------------------------------------------------------------ AC-32, 35, 36

describe("AC-32 focus returns to the button", () => {
  it("004_ac32_escape_closes_without_request_focus_on_task_button", async () => {
    const f = boot(dialogFor(ROLES[0]), "/projects");
    await openDialog();
    await loaded();
    press("Escape");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(createBtn());
    expect(posts(f.f)).toHaveLength(0);
  });

  it("004_ac32_cancel_closes_without_request_focus_on_task_button", async () => {
    const f = boot(dialogFor(ROLES[1]), "/my-tasks");
    await openDialog();
    await loaded();
    fireEvent.click(cancelBtn());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(createBtn());
    expect(posts(f.f)).toHaveLength(0);
  });
});

describe("AC-35 every open starts afresh", () => {
  it("004_ac35_reopen_on_project_page_empty_title_alpha_no_messages_list_requested_again", async () => {
    const f = boot(dialogFor(ROLES[0]), `/projects/${P1}`);
    await openDialog();
    await loaded();
    expect(f.f.calls.filter((c) => `${c.method} ${new URL(c.url).pathname}` === LIST)).toHaveLength(1);
    type("Черновик");
    pick(P3);
    expect(projectSelect().value).toBe(P3);
    press("Escape");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await openDialog();
    await loaded();
    expect(titleInput().value).toBe("");
    expect(projectSelect().value).toBe(P1);
    expect(within(dlg()).queryByRole("alert")).toBeNull();
    expect(f.f.calls.filter((c) => `${c.method} ${new URL(c.url).pathname}` === LIST)).toHaveLength(2);
    expect(posts(f.f)).toHaveLength(0);
  });

  it("004_ac35_error_message_does_not_survive_reopen", async () => {
    boot(dialogFor(ROLES[1]), "/my-tasks");
    await openDialog();
    await loaded();
    type("   ");
    fireEvent.submit(dlg().querySelector("form")!);
    await within(dlg()).findByRole("alert");
    press("Escape");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await openDialog();
    await loaded();
    expect(within(dlg()).queryByRole("alert")).toBeNull();
    expect(titleInput().value).toBe("");
  });
});

describe("AC-36 one dialog, the Task button is out of reach by Tab", () => {
  it("004_ac36_single_dialog_and_tab_cycle_never_reaches_task_button", async () => {
    boot(dialogFor(ROLES[0]), "/projects");
    await openDialog();
    await loaded();
    fireEvent.click(createBtn()); // a second open must not add a window (FR-22)
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1);
    const task = createBtn();
    const inside = (e: Element | null) => e !== null && dlg().contains(e);
    expect(inside(document.activeElement)).toBe(true);
    for (const shift of [false, true]) {
      for (let i = 0; i < 8; i += 1) {
        tabThroughDocument(shift);
        expect(inside(document.activeElement), `step ${i} shift=${shift}`).toBe(true);
        expect(document.activeElement).not.toBe(task);
      }
    }
  });
});

// ------------------------------------------------------------------------------------- AC-42

describe("AC-42 markup of the button", () => {
  it.each(ROLES)("004_ac42_%s_one_svg_no_inner_controls_no_chevron", async (...role) => {
    boot(dialogFor(role as unknown as Role), "/projects");
    const b = await expectCreateButton();
    expect(b.querySelectorAll("svg")).toHaveLength(1);
    expect(b.children).toHaveLength(1);
    expect(b.querySelectorAll("button, a, [role], input, select, [tabindex]")).toHaveLength(0);
    expect(b.querySelector("hr, [aria-expanded]")).toBeNull();
  });
});
