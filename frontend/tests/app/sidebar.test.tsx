// 003 / R4-T02: боковое меню «Меню» с кнопкой «Выйти» на бизнес-экранах.
// AC-19, AC-22 (BA на /projects), AC-23, AC-24, AC-25, AC-29 (BA), AC-30 (BA); FR-10, FR-13, NFR-2, NFR-3.
// Контракт (plan §4.3): div.ui-sidebar > nav[aria-label="Меню"] + button[type=button][data-action="logout"]
// (первый дочерний элемент кнопки - svg aria-hidden), затем p[role=alert] ошибки выхода.
import type { QueryClient } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ru } from "../../src/shared/i18n";
import { deferred, err, expectAt, installFetch, j, meWith, page, renderApp, type Handler } from "../features/admin/helpers";

const ME = "GET /api/v1/me";
const LOGOUT = "POST /api/v1/auth/logout";
const MENU = "Меню";
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

  it.each(cases)("ac19_%s_%s_menu_links_and_single_logout", async (role, path) => {
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
    // первый дочерний элемент - декоративная иконка
    const icon = btn.firstChild as Element | null;
    expect(icon?.nodeType).toBe(Node.ELEMENT_NODE);
    expect(icon?.nodeName.toLowerCase()).toBe("svg");
    expect(icon?.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("AC-22 logout from BA /projects", () => {
  it("ac22_logout_204_one_request_login_cache_cleared", async () => {
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
  it("ac23_logout_401_goes_to_login_without_message", async () => {
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

  it.each(failures)("ac24_logout_%s_stays_one_message_button_enabled_retry_sends_again", async (_name, handler) => {
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
  it("ac25_pending_logout_disables_button_and_second_click_sends_nothing", async () => {
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
  it("ac29_navigation_named_menu_differs_from_pagination_and_logout_is_button", async () => {
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
  it("ac30_menu_links_then_logout_then_first_content_element", async () => {
    // форма создания проекта видна только при project_create (есть у BA)
    setup("business_admin");
    const { container } = await openMenu("/projects");
    await screen.findByRole("form", { name: ru["projects.create_title"] });
    const tabbable = Array.from(
      container.querySelectorAll<HTMLElement>("a[href], button, input, select, textarea, [tabindex]"),
    ).filter((el) => el.getAttribute("tabindex") !== "-1" && !(el as HTMLButtonElement).disabled);
    const form = container.querySelector<HTMLElement>('form[data-form="create-project"]')!;
    const firstInForm = tabbable.find((el) => form.contains(el))!;
    const labels = tabbable.slice(0, 4);
    expect(labels.slice(0, 2).map((el) => el.getAttribute("href"))).toEqual(["/projects", "/my-tasks"]);
    expect(labels[2]?.getAttribute("data-action")).toBe("logout");
    expect(labels[3]).toBe(firstInForm);
  });
});
