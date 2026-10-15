// T81: маршруты MVP и меню по capabilities.
//
// КОНТРАКТ ДЛЯ ИСПОЛНИТЕЛЯ (router.tsx; страницы-заглушки заменят T82-T84):
//   Маршруты под guard сессии (как "/"): /projects, /projects/:projectId, /tasks/:taskId, /my-tasks.
//   Каждый показывает внутри role="main" непустой h1 с текстом из словаря (у четырёх маршрутов
//   тексты различаются и не равны заголовку главной). Заглушки не шлют запросов, кроме GET /me.
//   Состояние /me: 401 -> /login, 403 password_change_required -> /change-password,
//   403 no_role -> /no-role (как у /admin/*).
//   Нужна capability business_access: без неё остаётся на маршруте и показывает role="alert"
//   с errorMessage("forbidden"), h1 страницы не показывается.
//   Меню: <nav> на главной "/" и на каждой из четырёх страниц; ссылки (<a>):
//     a[href="/projects"] и a[href="/my-tasks"] - только при business_access;
//     a[href="/admin/users"] (manage_accounts), a[href="/admin/audit"] (view_audit) - как в R1.0;
//     ссылок на CRM, метки, корзину, поиск, упоминания нет ни при каких capabilities.
//   Текст ссылок - из словаря; ссылка в меню на текущую страницу может иметь aria-current="page".
// AC: FR-10, NFR-6, NFR-7.
import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../src/shared/i18n";
import { err, expectAt, installFetch, j, meWith, page, renderApp, where } from "../features/admin/helpers";

const DICT = Object.values(ru) as string[];
const ME = "GET /api/v1/me";
const BUSINESS = ["business_access", "project_create", "task_assign_others"];
const ADMIN_ONLY = ["manage_accounts", "assign_roles", "view_audit"];
const PAGE_PATHS = [
  "/projects",
  "/projects/33333333-3333-4333-8333-333333333333",
  "/tasks/44444444-4444-4444-8444-444444444444",
  "/my-tasks",
];
// T82 replaced the stubs of /projects and /projects/:id by real screens (own requests, dynamic h1);
// T83/T84 will do the same for the rest. STUB_PATHS keep the "stub" checks of T81.
const STUB_PATHS = PAGE_PATHS.slice(2);
const PROJECT_ID = "33333333-3333-4333-8333-333333333333";
const PROJECT_ROUTES = {
  "GET /api/v1/projects": () => j(200, page([])),
  [`GET /api/v1/projects/${PROJECT_ID}`]: () => err(404, "not_found"),
  [`GET /api/v1/projects/${PROJECT_ID}/members`]: () => err(404, "not_found"),
};
const FORBIDDEN_LINKS = ["/crm", "/labels", "/trash", "/search", "/mentions", "/deals", "/pipeline"];

function hrefs(): string[] {
  const nav = screen.getByRole("navigation");
  return Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "");
}

describe("T81 routes under the session gate", () => {
  it.each(STUB_PATHS)("ac_fr10_%s_shows_dictionary_h1_for_business_access", async (path) => {
    const f = installFetch({ [ME]: () => j(200, meWith(BUSINESS, "user")) });
    renderApp(path);
    const main = await screen.findByRole("main");
    const h1 = main.querySelector("h1");
    expect(h1?.textContent?.trim()).toBeTruthy();
    expect(DICT).toContain(h1?.textContent);
    expect(where()).toBe(path);
    expect(f.calls.map((c) => new URL(c.url).pathname)).toEqual(["/api/v1/me"]);
  });

  it("ac_stub_titles_are_distinct_and_differ_from_home", async () => {
    installFetch({ [ME]: () => j(200, meWith(BUSINESS, "user")), ...PROJECT_ROUTES });
    const titles: string[] = [];
    const home = renderApp("/");
    titles.push((await screen.findByRole("heading", { level: 1 })).textContent ?? "");
    home.unmount();
    for (const p of ["/projects", ...STUB_PATHS]) {
      const r = renderApp(p);
      await screen.findByRole("main");
      titles.push(screen.getByRole("heading", { level: 1 }).textContent ?? "");
      r.unmount();
    }
    expect(new Set(titles).size).toBe(titles.length);
  });

  it.each(PAGE_PATHS)("ac_guard_%s_401_goes_to_login", async (path) => {
    installFetch({ [ME]: () => err(401, "not_authenticated") });
    renderApp(path);
    await expectAt("/login");
  });

  it.each(PAGE_PATHS)("ac_guard_%s_no_role_goes_to_no_role", async (path) => {
    installFetch({ [ME]: () => err(403, "no_role") });
    renderApp(path);
    await expectAt("/no-role");
  });

  it("ac_guard_password_change_required_goes_to_change_password", async () => {
    installFetch({ [ME]: () => err(403, "password_change_required") });
    renderApp("/my-tasks");
    await expectAt("/change-password");
  });

  it.each(PAGE_PATHS)("ac_fr10_%s_without_business_access_shows_forbidden", async (path) => {
    const f = installFetch({ [ME]: () => j(200, meWith(ADMIN_ONLY)) });
    renderApp(path);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(ru["error.forbidden"]);
    expect(where()).toBe(path);
    expect(f.calls.length).toBe(1);
  });
});

describe("T81 menu by capabilities (FR-10)", () => {
  it("ac_menu_business_access_has_projects_and_my_tasks_on_home", async () => {
    installFetch({ [ME]: () => j(200, meWith(BUSINESS, "user")) });
    renderApp("/");
    await screen.findByRole("navigation");
    const links = hrefs();
    expect(links).toContain("/projects");
    expect(links).toContain("/my-tasks");
    expect(links).not.toContain("/admin/users");
    expect(links).not.toContain("/admin/audit");
    const texts = Array.from(screen.getByRole("navigation").querySelectorAll("a")).map((a) => a.textContent);
    for (const text of texts) expect(DICT).toContain(text);
  });

  it("ac_menu_tech_admin_without_business_access_has_only_admin_items", async () => {
    installFetch({ [ME]: () => j(200, meWith(ADMIN_ONLY)) });
    renderApp("/");
    await screen.findByRole("navigation");
    const links = hrefs();
    expect(links).toContain("/admin/users");
    expect(links).toContain("/admin/audit");
    expect(links).not.toContain("/projects");
    expect(links).not.toContain("/my-tasks");
  });

  it("ac_menu_partial_admin_capabilities_as_in_r1_0", async () => {
    installFetch({ [ME]: () => j(200, meWith(["manage_accounts"])) });
    renderApp("/");
    await screen.findByRole("navigation");
    const links = hrefs();
    expect(links).toContain("/admin/users");
    expect(links).not.toContain("/admin/audit");
  });

  it("ac_menu_has_no_crm_labels_trash_search_mentions_items", async () => {
    const all = [...BUSINESS, ...ADMIN_ONLY, "labels_manage", "crm_read", "crm_write", "pipeline_manage", "project_manage_any"];
    installFetch({ [ME]: () => j(200, meWith(all, "business_admin")) });
    renderApp("/");
    await screen.findByRole("navigation");
    for (const href of hrefs()) {
      for (const bad of FORBIDDEN_LINKS) expect(href.startsWith(bad), href).toBe(false);
    }
  });

  it.each(PAGE_PATHS)("ac_menu_is_present_on_%s", async (path) => {
    installFetch({ [ME]: () => j(200, meWith(BUSINESS, "user")), ...PROJECT_ROUTES });
    renderApp(path);
    await screen.findByRole("main");
    await waitFor(() => expect(hrefs()).toContain("/projects"));
    expect(hrefs()).toContain("/my-tasks");
  });
});

describe("T82 projects screens in the shell", () => {
  it("ac_projects_page_h1_is_dictionary_title", async () => {
    installFetch({ [ME]: () => j(200, meWith(BUSINESS, "user")), ...PROJECT_ROUTES });
    renderApp("/projects");
    const h1 = await screen.findByRole("heading", { level: 1 });
    expect(h1.textContent).toBe(ru["projects.title"]);
  });

  it("ac_nav_projects_link_has_aria_current_only_on_projects_list", async () => {
    installFetch({ [ME]: () => j(200, meWith(BUSINESS, "user")), ...PROJECT_ROUTES });
    const list = renderApp("/projects");
    const link = () => screen.getByRole("navigation").querySelector<HTMLAnchorElement>('a[href="/projects"]')!;
    await waitFor(() => expect(link()).toBeTruthy());
    expect(link().getAttribute("aria-current")).toBe("page");
    list.unmount();
    renderApp(`/projects/${PROJECT_ID}`);
    await waitFor(() => expect(link()).toBeTruthy());
    expect(link().getAttribute("aria-current")).toBeNull();
  });
});
