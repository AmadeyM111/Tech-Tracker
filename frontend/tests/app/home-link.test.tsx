// 003 / R4-T03 (переписан): ссылки «На главную» и ссылок на `/` нет на экранах ТА, бизнес-экранах
// и экранах отказа. AC-16 (+ AC-27, AC-28: экраны отказа). Фикстуры spec §5: BA, U, TA.
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ru } from "../../src/shared/i18n";
import { CAPS_ALL, err, expectAt, installFetch, j, meWith, page, renderApp, type Handler } from "../features/admin/helpers";
import { field } from "../features/auth/helpers";

// Удалённый ключ app.home_link (003): литерал, чтобы проверка «ссылки нет» не зависела от словаря.
const REMOVED_HOME_LINK = "На главную";

const ME = "GET /api/v1/me";
const TASK_ID = "44444444-4444-4444-8444-444444444444";
const PROJECT_ID = "33333333-3333-4333-8333-333333333333";
const PATHS = [
  "/projects",
  `/projects/${PROJECT_ID}`,
  `/tasks/${TASK_ID}`,
  "/my-tasks",
  "/admin/users",
  "/admin/audit",
];

const FIXTURES: Record<string, { caps: string[]; role: string }> = {
  BA: { caps: ["business_access", "project_create", "task_assign_others"], role: "business_admin" },
  U: { caps: ["business_access"], role: "user" },
  TA: { caps: CAPS_ALL, role: "tech_admin" },
};

const ROUTES: Record<string, Handler> = {
  "GET /api/v1/projects": () => j(200, page([])),
  "GET /api/v1/me/tasks": () => j(200, page([])),
  "GET /api/v1/admin/users": () => j(200, page([])),
  "GET /api/v1/admin/audit": () => j(200, page([])),
  [`GET /api/v1/tasks/${TASK_ID}`]: () => err(404, "not_found"),
  [`GET /api/v1/projects/${PROJECT_ID}`]: () => err(404, "not_found"),
  [`GET /api/v1/projects/${PROJECT_ID}/members`]: () => err(404, "not_found"),
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AC-16 no home link anywhere", () => {
  const cases = Object.keys(FIXTURES).flatMap((fx) => PATHS.map((path) => [fx, path] as const));

  it.each(cases)("ac16_%s_%s_has_no_home_link_no_href_root_no_home_text", async (fx, path) => {
    const { caps, role } = FIXTURES[fx]!;
    installFetch({ ...ROUTES, [ME]: () => j(200, meWith(caps, role)) });
    const { container } = renderApp(path);
    // боковое меню есть на каждом из этих экранов (в том числе на экранах отказа): ждём его
    await screen.findByRole("navigation", { name: ru["app.menu_label"] });
    expect(container.querySelector('a[href="/"]')).toBeNull();
    expect(screen.queryByRole("link", { name: REMOVED_HOME_LINK })).toBeNull();
    expect(container.querySelector(".ui-home-link")).toBeNull();
    expect(document.body.textContent ?? "").not.toContain("Главная");
    expect(document.body.textContent ?? "").not.toContain(REMOVED_HOME_LINK);
  });
});

// Значения словаря; шаблоны с {параметр} сопоставляются регулярным выражением (подстановка - не данные фикстур).
const DICT_PATTERNS = (Object.values(ru) as string[]).map(
  (v) =>
    new RegExp(
      "^" +
        v
          .split(/\{[a-z_]+\}/i)
          .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
          .join(".+") +
        "$",
    ),
);
const DICT_VALUES = { has: (text: string) => DICT_PATTERNS.some((re) => re.test(text)) };

/** Видимые текстовые узлы (без script/style и скрытых через hidden), обрезанные по краям. */
function visibleTexts(root: HTMLElement): string[] {
  const out: string[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    // [data-testid="where"] - проба адреса самого теста, не интерфейс
    if (!el || ["SCRIPT", "STYLE"].includes(el.tagName) || el.closest("[hidden],[data-testid='where']")) continue;
    const text = (n.textContent ?? "").trim();
    if (text) out.push(text);
  }
  return out;
}

const ANON = () => err(401, "not_authenticated");
const NR = () => err(403, "no_role");
const PWD = () => err(403, "password_change_required");

const CASES_26 = Object.keys(FIXTURES).flatMap((fx) => PATHS.map((path) => [fx, path] as const));

describe("AC-18 visible strings of the AC-16 screens are in the dictionary", () => {
  // Динамические данные фикстур исключены: страницы пустые, логин из /me на этих экранах не показывается.
  it.each(CASES_26)("ac18_%s_%s_all_visible_text_nodes_are_dictionary_values", async (fx, path) => {
    const { caps, role } = FIXTURES[fx]!;
    installFetch({ ...ROUTES, [ME]: () => j(200, meWith(caps, role)) });
    renderApp(path);
    await screen.findByRole("navigation", { name: ru["app.menu_label"] });
    await new Promise((r) => setTimeout(r, 40));
    const texts = visibleTexts(document.body);
    expect(texts.length).toBeGreaterThan(0);
    expect(texts.filter((t) => !DICT_VALUES.has(t))).toEqual([]);
  });
});

describe("AC-26 no change-password entry on screens with a menu", () => {
  it.each(CASES_26)("ac26_%s_%s_no_change_password_link_or_button", async (fx, path) => {
    const { caps, role } = FIXTURES[fx]!;
    installFetch({ ...ROUTES, [ME]: () => j(200, meWith(caps, role)) });
    const { container } = renderApp(path);
    await screen.findByRole("navigation", { name: ru["app.menu_label"] });
    expect(screen.queryByRole("link", { name: /Сменить пароль/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Сменить пароль/ })).toBeNull();
    expect(container.querySelector('a[href="/change-password"]')).toBeNull();
  });
});

describe("AC-17 no link to / on /no-role, /change-password, /login", () => {
  it("ac17_NR_no_role_has_no_root_link", async () => {
    installFetch({ [ME]: NR });
    const { container } = renderApp("/no-role");
    await screen.findByRole("heading", { level: 1, name: ru["auth.no_role_title"] });
    expect(container.querySelector('a[href="/"]')).toBeNull();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    const texts = visibleTexts(document.body);
    expect(texts.filter((t) => !DICT_VALUES.has(t))).toEqual([]);
  });

  it("ac17_PWD_change_password_has_no_root_link", async () => {
    installFetch({ [ME]: PWD });
    const { container } = renderApp("/change-password");
    await screen.findByRole("dialog");
    expect(container.querySelector('a[href="/"]')).toBeNull();
    expect(document.body.querySelector('a[href="/"]')).toBeNull();
    expect(screen.queryAllByRole("link", { hidden: true })).toHaveLength(0);
    const texts = visibleTexts(document.body);
    expect(texts.filter((t) => !DICT_VALUES.has(t))).toEqual([]);
  });

  it("ac17_ANON_login_has_no_root_link", async () => {
    installFetch({ [ME]: ANON });
    const { container } = renderApp("/login");
    await waitFor(() => field(container, "username"));
    expect(container.querySelector('a[href="/"]')).toBeNull();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    const texts = visibleTexts(document.body);
    expect(texts.filter((t) => !DICT_VALUES.has(t))).toEqual([]);
  });
});

describe("AC-32 /no-role without menu, /change-password window", () => {
  it("ac32_NR_no_menu_logout_logs_out_like_ac22", async () => {
    let out = false;
    const ref: { qc?: unknown } = {};
    const seen: unknown[] = [];
    const f = installFetch({
      [ME]: () => {
        if (!out) return NR();
        seen.push(ref.qc);
        return ANON();
      },
      "POST /api/v1/auth/logout": () => ((out = true), new Response(null, { status: 204 })),
    });
    const { container, qc } = renderApp("/no-role");
    await screen.findByRole("heading", { level: 1, name: ru["auth.no_role_title"] });
    expect(container.querySelector(".ui-sidebar")).toBeNull();
    expect(screen.queryByRole("navigation", { name: ru["app.menu_label"] })).toBeNull();
    qc.setQueryData(["sentinel"], 1);
    ref.qc = undefined;
    fireEvent.click(screen.getByRole("button", { name: ru["auth.logout"] }));
    await expectAt("/login");
    expect(f.count("POST /api/v1/auth/logout")).toBe(1);
    expect(qc.getQueryData(["sentinel"])).toBeUndefined();
  });

  it("ac32_PWD_window_has_logout_inside_blank_aria_hidden_backdrop_no_links", async () => {
    installFetch({ [ME]: PWD });
    const { container } = renderApp("/change-password");
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: ru["auth.logout"] })).toBeTruthy();
    const backdrop = container.querySelector(".ui-shell");
    expect(backdrop).not.toBeNull();
    expect(backdrop!.getAttribute("aria-hidden")).toBe("true");
    expect((backdrop!.textContent ?? "").trim()).toBe("");
    expect(backdrop!.querySelector("a, button, input")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(dialog.contains(backdrop)).toBe(false);
  });
});
