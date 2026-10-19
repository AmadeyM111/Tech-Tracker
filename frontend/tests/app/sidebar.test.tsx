// 003 / R4-T02, R4-T03: боковое меню «Меню» с кнопкой «Выйти» на бизнес-экранах, экранах ТА и экранах отказа.
// R4-T03: AC-20, AC-21, AC-22 (TA), AC-27, AC-28, AC-29 (TA), AC-30 (TA); FR-11, FR-14.
// AC-19, AC-22 (BA на /projects), AC-23, AC-24, AC-25, AC-29 (BA), AC-30 (BA); FR-10, FR-13, NFR-2, NFR-3.
// Контракт (plan §4.3): div.ui-sidebar > nav[aria-label="Меню"] + button[type=button][data-action="logout"]
// (первый дочерний элемент кнопки - svg aria-hidden), затем p[role=alert] ошибки выхода.
import type { QueryClient } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ru } from "../../src/shared/i18n";
import { TID1, taskItem } from "../features/tasks/helpers";
import { CAPS_ALL, deferred, err, expectAt, installFetch, j, meWith, page, renderApp, type Handler } from "../features/admin/helpers";

// Удалённый ключ app.home_link (003): литерал, чтобы проверка «ссылки нет» не зависела от словаря.
const REMOVED_HOME_LINK = "На главную";

const ME = "GET /api/v1/me";
const LOGOUT = "POST /api/v1/auth/logout";
const MENU = "Меню";
// 004: кнопка «Задача» между ссылками и «Выйти» (только при business_access).
const CREATE_TASK = ru["nav.create_task"];
const DICT = Object.values(ru) as string[];
const BA_CAPS = ["business_access", "project_create", "task_assign_others"];
const U_CAPS = ["business_access"];
const capsFor = (role: string) => (role === "business_admin" ? BA_CAPS : U_CAPS);
const TASK_ID = "44444444-4444-4444-8444-444444444444";
const PROJECT_ID = "33333333-3333-4333-8333-333333333333";
const PATHS = ["/projects", `/projects/${PROJECT_ID}`, `/tasks/${TASK_ID}`, "/my-tasks"];

const ROUTES: Record<string, Handler> = {
  "GET /api/v1/projects": () => j(200, page([])),
  "GET /api/v1/me/tasks": () => j(200, page([])),
  [`GET /api/v1/tasks/${TASK_ID}`]: () => err(404, "not_found"),
  [`GET /api/v1/projects/${PROJECT_ID}`]: () => err(404, "not_found"),
  [`GET /api/v1/projects/${PROJECT_ID}/members`]: () => err(404, "not_found"),
};

function setup(role: string, over: Record<string, Handler> = {}) {
  return installFetch({ ...ROUTES, [ME]: () => j(200, meWith(capsFor(role), role)), ...over });
}

async function openMenu(path: string) {
  const out = renderApp(path);
  const nav = await screen.findByRole("navigation", { name: MENU });
  return { ...out, nav };
}

const logoutButton = () => screen.getByRole("button", { name: ru["auth.logout"] });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NFR-2 menu label", () => {
  it("ac_nfr2_dictionary_has_menu_label", () => {
    expect((ru as Record<string, string>)["app.menu_label"]).toBe(MENU);
  });
});

describe("AC-19 business sidebar", () => {
  const cases = ["business_admin", "user"].flatMap((role) => PATHS.map((path) => [role, path] as const));

  it.each(cases)("003_ac19_%s_%s_menu_links_and_single_logout", async (role, path) => {
    setup(role);
    const { container, nav } = await openMenu(path);
    const hrefs = within(nav)
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/projects", "/my-tasks"]);
    expect(within(nav).queryByRole("link", { name: ru["admin.home_users_link"] })).toBeNull();
    expect(within(nav).queryByRole("link", { name: ru["admin.home_audit_link"] })).toBeNull();

    const sidebar = container.querySelector<HTMLElement>(".ui-sidebar");
    expect(sidebar).not.toBeNull();
    expect(sidebar!.contains(nav)).toBe(true);
    const buttons = within(sidebar!).getAllByRole("button", { name: ru["auth.logout"] });
    expect(buttons).toHaveLength(1);
    const btn = buttons[0] as HTMLButtonElement;
    expect(btn.getAttribute("data-action")).toBe("logout");
    expect(btn.type).toBe("button");
    // «Выйти» после последней ссылки в порядке документа и вне nav
    const last = within(nav).getAllByRole("link").at(-1)!;
    expect(last.compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(nav.contains(btn)).toBe(false);
    // последний фокусируемый элемент меню
    const focusable = Array.from(sidebar!.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), [tabindex]:not([tabindex='-1'])"));
    expect(focusable.at(-1)).toBe(btn);
    // 004/AC-9, AC-12: «Задача» - сразу после последней ссылки и непосредственно перед «Выйти», вне nav
    const create = within(sidebar!).getByRole("button", { name: CREATE_TASK });
    expect(create.getAttribute("data-action")).toBe("create-task");
    expect(nav.contains(create)).toBe(false);
    expect(last.compareDocumentPosition(create) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(create.compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(focusable.at(-2)).toBe(create);
    expect(create.firstElementChild?.nodeName.toLowerCase()).toBe("svg");
    expect(create.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
    expect(create.firstElementChild?.innerHTML).not.toBe(btn.firstElementChild?.innerHTML);
    // первый дочерний элемент - декоративная иконка
    const icon = btn.firstChild as Element | null;
    expect(icon?.nodeType).toBe(Node.ELEMENT_NODE);
    expect(icon?.nodeName.toLowerCase()).toBe("svg");
    expect(icon?.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("AC-22 logout from BA /projects", () => {
  it("003_ac22_logout_204_one_request_login_cache_cleared", async () => {
    let out = false;
    const ref: { qc?: QueryClient } = {};
    // значение-маяк на момент запроса /me после выхода: кэш должен быть уже очищен самим выходом,
    // а не обработчиком 401 (он срабатывает позже, по ответу)
    const seen: unknown[] = [];
    const f = setup("business_admin", {
      [ME]: () => {
        if (!out) return j(200, meWith(BA_CAPS, "business_admin"));
        seen.push(ref.qc?.getQueryData(["sentinel"]));
        return err(401, "not_authenticated");
      },
      [LOGOUT]: () => ((out = true), new Response(null, { status: 204 })),
    });
    const { qc } = await openMenu("/projects");
    ref.qc = qc;
    qc.setQueryData(["sentinel"], 1);
    fireEvent.click(logoutButton());
    await expectAt("/login");
    expect(f.count(LOGOUT)).toBe(1);
    await waitFor(() => expect(seen.length).toBeGreaterThan(0));
    expect(seen.every((v) => v === undefined)).toBe(true);
    expect(qc.getQueryData(["sentinel"])).toBeUndefined();
  });
});

describe("AC-23 logout 401", () => {
  it("003_ac23_logout_401_goes_to_login_without_message", async () => {
    let out = false;
    setup("business_admin", {
      [ME]: () => (out ? err(401, "not_authenticated") : j(200, meWith(BA_CAPS, "business_admin"))),
      [LOGOUT]: () => ((out = true), err(401, "not_authenticated")),
    });
    await openMenu("/projects");
    fireEvent.click(logoutButton());
    await expectAt("/login");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("AC-24 logout failure", () => {
  const failures: [string, Handler][] = [
    ["500", () => err(500, "internal_error")],
    [
      "network",
      () => {
        throw new TypeError("Failed to fetch");
      },
    ],
  ];

  it.each(failures)("003_ac24_logout_%s_stays_one_message_button_enabled_retry_sends_again", async (_name, handler) => {
    const f = setup("business_admin", { [LOGOUT]: handler });
    await openMenu("/projects");
    fireEvent.click(logoutButton());
    const alert = await screen.findByRole("alert");
    expect(DICT).toContain(alert.textContent);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByTestId("where").textContent).toBe("/projects");
    await waitFor(() => expect((logoutButton() as HTMLButtonElement).disabled).toBe(false));
    expect(f.count(LOGOUT)).toBe(1);
    fireEvent.click(logoutButton());
    await waitFor(() => expect(f.count(LOGOUT)).toBe(2));
    expect(screen.getByTestId("where").textContent).toBe("/projects");
  });
});

describe("AC-25 logout in flight", () => {
  it("003_ac25_pending_logout_disables_button_and_second_click_sends_nothing", async () => {
    const d = deferred<Response>();
    const f = setup("business_admin", { [LOGOUT]: () => d.promise });
    await openMenu("/projects");
    fireEvent.click(logoutButton());
    await waitFor(() => expect((logoutButton() as HTMLButtonElement).disabled).toBe(true));
    fireEvent.click(logoutButton());
    expect(f.count(LOGOUT)).toBe(1);
    d.resolve(new Response(null, { status: 204 }));
    await expectAt("/login");
    expect(f.count(LOGOUT)).toBe(1);
  });
});

describe("AC-29 accessibility of the BA sidebar", () => {
  it("003_ac29_navigation_named_menu_differs_from_pagination_and_logout_is_button", async () => {
    setup("business_admin");
    await openMenu("/projects");
    expect(ru["admin.pagination_label"]).not.toBe(MENU);
    const navs = screen.getAllByRole("navigation", { name: MENU });
    expect(navs).toHaveLength(1);
    const btn = logoutButton() as HTMLButtonElement;
    expect(btn.tagName).toBe("BUTTON");
    expect(btn.getAttribute("type")).toBe("button");
  });
});

describe("AC-30 tab order of the BA /projects screen", () => {
  it("003_ac30_menu_links_then_logout_then_first_content_element", async () => {
    // форма создания проекта видна только при project_create (есть у BA)
    setup("business_admin");
    const { container } = await openMenu("/projects");
    await screen.findByRole("form", { name: ru["projects.create_title"] });
    const tabbable = Array.from(
      container.querySelectorAll<HTMLElement>("a[href], button, input, select, textarea, [tabindex]"),
    ).filter((el) => el.getAttribute("tabindex") !== "-1" && !(el as HTMLButtonElement).disabled);
    const form = container.querySelector<HTMLElement>('form[data-form="create-project"]')!;
    const firstInForm = tabbable.find((el) => form.contains(el))!;
    const labels = tabbable.slice(0, 5);
    expect(labels.slice(0, 2).map((el) => el.getAttribute("href"))).toEqual(["/projects", "/my-tasks"]);
    // 004/AC-12: ссылки меню, «Задача», «Выйти», затем содержимое
    expect(labels[2]?.getAttribute("data-action")).toBe("create-task");
    expect(labels[3]?.getAttribute("data-action")).toBe("logout");
    expect(labels[4]).toBe(firstInForm);
  });
});

describe("AC-30 tab order of the U /my-tasks screen (004/AC-12)", () => {
  it("003_ac30_U_menu_links_then_task_then_logout_then_content", async () => {
    // непустой список задач: после меню есть первый элемент содержимого (ссылка на задачу)
    setup("user", { "GET /api/v1/me/tasks": () => j(200, page([taskItem(TID1, "Подготовить отчёт")])) });
    const { container } = await openMenu("/my-tasks");
    const taskLink = await screen.findByRole("link", { name: "Подготовить отчёт" });
    const tabbable = Array.from(
      container.querySelectorAll<HTMLElement>("a[href], button, input, select, textarea, [tabindex]"),
    ).filter((el) => el.getAttribute("tabindex") !== "-1" && !(el as HTMLButtonElement).disabled);
    expect(tabbable.slice(0, 2).map((el) => el.getAttribute("href"))).toEqual(["/projects", "/my-tasks"]);
    expect(tabbable[2]?.getAttribute("data-action")).toBe("create-task");
    expect(tabbable[3]?.getAttribute("data-action")).toBe("logout");
    // дальше - содержимое экрана, не меню
    expect(tabbable[4]).toBe(taskLink);
    expect(tabbable[4]?.closest(".ui-sidebar") ?? null).toBeNull();
  });
});

// ---------------------------------------------------------------- R4-T03: экраны ТА и экраны отказа
const TA_CAPS = CAPS_ALL; // фикстура TA: manage_accounts, assign_roles, view_audit
const USERS = "/admin/users";
const AUDIT_PATH = "/admin/audit";
const ADMIN_ROUTES: Record<string, Handler> = {
  "GET /api/v1/admin/users": () => j(200, page([])),
  "GET /api/v1/admin/audit": () => j(200, page([])),
};
const hrefsOf = (nav: HTMLElement) =>
  within(nav)
    .getAllByRole("link")
    .map((a) => a.getAttribute("href"));

function setupTa(over: Record<string, Handler> = {}, caps: string[] = TA_CAPS) {
  return installFetch({ ...ADMIN_ROUTES, [ME]: () => j(200, meWith(caps)), ...over });
}

describe("AC-20 tech admin sidebar", () => {
  it.each([USERS, AUDIT_PATH])("003_ac20_ta_%s_links_by_capabilities_one_logout_after_links", async (path) => {
    setupTa();
    const { container, nav } = await openMenu(path);
    expect(hrefsOf(nav)).toEqual([USERS, AUDIT_PATH]);
    expect(within(nav).queryByRole("link", { name: ru["nav.projects"] })).toBeNull();
    expect(within(nav).queryByRole("link", { name: ru["nav.my_tasks"] })).toBeNull();
    expect(screen.queryByRole("button", { name: CREATE_TASK })).toBeNull(); // 004/AC-10
    const sidebar = container.querySelector<HTMLElement>(".ui-sidebar")!;
    expect(sidebar).not.toBeNull();
    expect(sidebar.parentElement?.classList.contains("ui-shell")).toBe(true);
    expect(sidebar.contains(nav)).toBe(true);
    const buttons = screen.getAllByRole("button", { name: ru["auth.logout"] });
    expect(buttons).toHaveLength(1);
    const btn = buttons[0] as HTMLButtonElement;
    expect(sidebar.contains(btn)).toBe(true);
    expect(nav.contains(btn)).toBe(false);
    expect(within(nav).getAllByRole("link").at(-1)!.compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each([
    [USERS, ru["admin.home_users_link"], ru["admin.home_audit_link"]],
    [AUDIT_PATH, ru["admin.home_audit_link"], ru["admin.home_users_link"]],
  ])("ac20_ta_%s_current_link_has_aria_current_page", async (path, current, other) => {
    setupTa();
    const { nav } = await openMenu(path);
    expect(within(nav).getByRole("link", { name: current }).getAttribute("aria-current")).toBe("page");
    expect(within(nav).getByRole("link", { name: other }).getAttribute("aria-current")).toBeNull();
  });

  it("003_ac20_ta_click_audit_link_goes_to_audit_with_same_menu", async () => {
    setupTa();
    const { nav } = await openMenu(USERS);
    fireEvent.click(within(nav).getByRole("link", { name: ru["admin.home_audit_link"] }));
    await expectAt(AUDIT_PATH);
    const after = await screen.findByRole("navigation", { name: MENU });
    expect(hrefsOf(after)).toEqual([USERS, AUDIT_PATH]);
    await waitFor(() =>
      expect(within(after).getByRole("link", { name: ru["admin.home_audit_link"] }).getAttribute("aria-current")).toBe("page"),
    );
    expect(screen.getAllByRole("button", { name: ru["auth.logout"] })).toHaveLength(1);
  });
});

describe("AC-21 partial capabilities", () => {
  it("003_ac21_only_manage_accounts_users_link_no_audit_link_logout_present", async () => {
    setupTa({}, ["manage_accounts"]);
    const { nav } = await openMenu(USERS);
    expect(hrefsOf(nav)).toEqual([USERS]);
    expect(within(nav).queryByRole("link", { name: ru["admin.home_audit_link"] })).toBeNull();
    expect(screen.getAllByRole("button", { name: ru["auth.logout"] })).toHaveLength(1);
  });
});

describe("AC-22 logout from TA /admin/users", () => {
  it("003_ac22_ta_logout_204_one_request_login_cache_cleared", async () => {
    let out = false;
    const ref: { qc?: QueryClient } = {};
    const seen: unknown[] = [];
    const f = setupTa({
      [ME]: () => {
        if (!out) return j(200, meWith(TA_CAPS));
        seen.push(ref.qc?.getQueryData(["sentinel"]));
        return err(401, "not_authenticated");
      },
      [LOGOUT]: () => ((out = true), new Response(null, { status: 204 })),
    });
    const { qc } = await openMenu(USERS);
    ref.qc = qc;
    qc.setQueryData(["sentinel"], 1);
    fireEvent.click(logoutButton());
    await expectAt("/login");
    expect(f.count(LOGOUT)).toBe(1);
    await waitFor(() => expect(seen.length).toBeGreaterThan(0));
    expect(seen.every((v) => v === undefined)).toBe(true);
    expect(qc.getQueryData(["sentinel"])).toBeUndefined();
  });
});

describe("AC-27 tech admin on business paths", () => {
  it.each(PATHS)("003_ac27_ta_%s_forbidden_in_place_ta_menu_logout_one_request", async (path) => {
    const f = setupTa();
    const { container, nav } = await openMenu(path);
    expect(screen.getByTestId("where").textContent).toBe(path);
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.textContent).toBe(ru["error.forbidden"]);
    expect(hrefsOf(nav)).toEqual([USERS, AUDIT_PATH]);
    expect(container.querySelector<HTMLElement>(".ui-sidebar")!.parentElement?.classList.contains("ui-shell")).toBe(true);
    expect(within(container.querySelector<HTMLElement>(".ui-sidebar")!).getAllByRole("button", { name: ru["auth.logout"] })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: CREATE_TASK })).toBeNull(); // 004/AC-10
    expect(container.querySelector('[data-action="create-task"]')).toBeNull();
    expect(screen.queryByRole("link", { name: REMOVED_HOME_LINK })).toBeNull();
    expect(container.querySelector('a[href="/"]')).toBeNull();
    expect(f.calls).toHaveLength(1);
    expect(f.count(ME)).toBe(1);
  });

  it("003_ac27_ta_logout_works_from_forbidden_screen", async () => {
    let out = false;
    const f = setupTa({
      [ME]: () => (out ? err(401, "not_authenticated") : j(200, meWith(TA_CAPS))),
      [LOGOUT]: () => ((out = true), new Response(null, { status: 204 })),
    });
    await openMenu("/projects");
    fireEvent.click(logoutButton());
    await expectAt("/login");
    expect(f.count(LOGOUT)).toBe(1);
  });
});

describe("AC-28 business roles on tech admin paths", () => {
  const cases = ["business_admin", "user"].flatMap((role) => [USERS, AUDIT_PATH].map((path) => [role, path] as const));

  it.each(cases)("003_ac28_%s_%s_forbidden_in_place_business_menu_no_admin_requests", async (role, path) => {
    const f = setup(role);
    const { container, nav } = await openMenu(path);
    expect(screen.getByTestId("where").textContent).toBe(path);
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]?.textContent).toBe(ru["error.forbidden"]);
    expect(hrefsOf(nav)).toEqual(["/projects", "/my-tasks"]);
    expect(container.querySelector<HTMLElement>(".ui-sidebar")!.parentElement?.classList.contains("ui-shell")).toBe(true);
    expect(within(nav).getByRole("link", { name: ru["nav.projects"] })).toBeTruthy();
    expect(within(nav).getByRole("link", { name: ru["nav.my_tasks"] })).toBeTruthy();
    expect(within(container.querySelector<HTMLElement>(".ui-sidebar")!).getAllByRole("button", { name: ru["auth.logout"] })).toHaveLength(1);
    // 004/AC-9 (Q-6 а): на экране отказа БА и «Пользователь» тоже видят «Задача»
    expect(within(container.querySelector<HTMLElement>(".ui-sidebar")!).getAllByRole("button", { name: CREATE_TASK })).toHaveLength(1);
    expect(screen.queryByRole("link", { name: REMOVED_HOME_LINK })).toBeNull();
    expect(f.calls.filter((c) => new URL(c.url).pathname.startsWith("/api/v1/admin"))).toHaveLength(0);
  });
});

describe("AC-29 accessibility of the TA sidebar", () => {
  it("003_ac29_ta_navigation_named_menu_and_logout_is_button", async () => {
    setupTa();
    await openMenu(USERS);
    expect(screen.getAllByRole("navigation", { name: MENU })).toHaveLength(1);
    const btn = logoutButton() as HTMLButtonElement;
    expect(btn.tagName).toBe("BUTTON");
    expect(btn.getAttribute("type")).toBe("button");
  });
});

describe("AC-30 tab order of the TA /admin/users screen", () => {
  it("003_ac30_ta_menu_links_then_logout_then_first_content_element", async () => {
    setupTa();
    const { container } = await openMenu(USERS);
    await screen.findByRole("form", { name: ru["admin.users.create_title"] });
    const tabbable = Array.from(
      container.querySelectorAll<HTMLElement>("a[href], button, input, select, textarea, [tabindex]"),
    ).filter((el) => el.getAttribute("tabindex") !== "-1" && !(el as HTMLButtonElement).disabled);
    expect(tabbable.slice(0, 2).map((el) => el.getAttribute("href"))).toEqual([USERS, AUDIT_PATH]);
    expect(tabbable[2]?.getAttribute("data-action")).toBe("logout");
    const form = container.querySelector<HTMLElement>("form")!;
    expect(tabbable[3]).toBe(form.querySelector('input[name="login"]'));
  });
});
