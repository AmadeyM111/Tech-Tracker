// T102: «Сменить пароль» вынесена из бокового меню в приветственное окно главной страницы.
//
// Контракт для исполнителя (router.tsx, Home; ru.ts; ui.css не меняется):
//  - на "/" внутри <main>, рядом с h1 «Главная», блок section[data-section="welcome"]:
//    h2 = ru["app.welcome_title"], абзац = ru["app.welcome_hint"] (новые ключи словаря, непустые),
//    ссылка ru["app.change_password_link"] -> href "/change-password", class "ui-home-link"
//    (существующая пилюля-кнопка, новых CSS-правил не нужно), первым дочерним svg.ui-icon[aria-hidden=true].
//  - в .ui-sidebar ссылки «Сменить пароль» нет (остаются пункты по capabilities и «Выйти»);
//    на бизнес-экранах её тоже нет. Один экземпляр ссылки на "/". Видна всем ролям.
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../src/shared/i18n";
import { CAPS_ALL, installFetch, j, meWith, page, renderApp } from "../features/admin/helpers";

const ME = "GET /api/v1/me";
const NAME = ru["app.change_password_link"];
const BUSINESS = ["business_access", "project_create", "task_assign_others"];
const CASES: [string, string, string[]][] = [
  ["tech_admin", "tech_admin", CAPS_ALL],
  ["business_admin", "business_admin", [...BUSINESS]],
  ["user", "user", ["business_access"]],
];
const dict = ru as Record<string, string>;

describe("T102 welcome block on home", () => {
  it.each(CASES)("ac_%s_welcome_block_has_change_password_link", async (_n, role, caps) => {
    installFetch({ [ME]: () => j(200, meWith(caps, role)) });
    const { container } = renderApp("/");
    const links = await screen.findAllByRole("link", { name: NAME });
    expect(links).toHaveLength(1);
    const link = links[0]!;
    expect(link.getAttribute("href")).toBe("/change-password");

    const section = container.querySelector('section[data-section="welcome"]') as HTMLElement | null;
    expect(section, "section[data-section=welcome]").not.toBeNull();
    expect(section!.contains(link)).toBe(true);
    expect(section!.closest("main, [role=main]")).not.toBeNull();
    expect(section!.closest(".ui-sidebar")).toBeNull();
    expect(link.closest(".ui-sidebar")).toBeNull();

    expect((dict["app.welcome_title"] ?? "").trim()).not.toBe("");
    expect((dict["app.welcome_hint"] ?? "").trim()).not.toBe("");
    const h2 = within(section!).getByRole("heading", { level: 2 });
    expect(h2.textContent).toBe(dict["app.welcome_title"]);
    expect(within(section!).getByText(dict["app.welcome_hint"]!)).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(ru["app.home_title"]);
  });

  it("ac_link_is_pill_with_key_icon_first", async () => {
    installFetch({ [ME]: () => j(200, meWith(CAPS_ALL)) });
    renderApp("/");
    const link = await screen.findByRole("link", { name: NAME });
    expect(link.className.split(/\s+/)).toContain("ui-home-link");
    const icon = link.firstElementChild!;
    expect(link.firstChild).toBe(icon);
    expect(icon.tagName.toLowerCase()).toBe("svg");
    expect(icon.classList.contains("ui-icon")).toBe(true);
    expect(icon.getAttribute("aria-hidden")).toBe("true");
    expect(icon.innerHTML).not.toBe("");
  });

  it("ac_sidebar_has_no_change_password_but_keeps_menu_and_logout", async () => {
    installFetch({ [ME]: () => j(200, meWith([...CAPS_ALL, ...BUSINESS])) });
    const { container } = renderApp("/");
    await screen.findByRole("link", { name: NAME });
    const sidebar = container.querySelector(".ui-sidebar") as HTMLElement;
    expect(sidebar).not.toBeNull();
    expect(within(sidebar).queryByRole("link", { name: NAME })).toBeNull();
    expect(sidebar.querySelector('a[href="/change-password"]')).toBeNull();
    expect(within(sidebar).getByRole("link", { name: ru["nav.projects"] })).toBeTruthy();
    expect(within(sidebar).getByRole("link", { name: ru["nav.my_tasks"] })).toBeTruthy();
    expect(within(sidebar).getByRole("button", { name: ru["auth.logout"] })).toBeTruthy();
  });

  it("ac_link_is_keyboard_focusable", async () => {
    installFetch({ [ME]: () => j(200, meWith(["business_access"], "user")) });
    renderApp("/");
    const link = await screen.findByRole("link", { name: NAME });
    link.focus();
    expect(document.activeElement).toBe(link);
    expect(link.getAttribute("tabindex") ?? "0").not.toBe("-1");
  });

  it.each(["/projects", "/my-tasks"])("ac_%s_has_no_change_password_link", async (path) => {
    installFetch({
      [ME]: () => j(200, meWith(BUSINESS)),
      "GET /api/v1/projects": () => j(200, page([])),
      "GET /api/v1/me/tasks": () => j(200, page([])),
    });
    renderApp(path);
    await screen.findByRole("main");
    await screen.findByRole("link", { name: ru["nav.projects"] });
    expect(screen.queryByRole("link", { name: NAME })).toBeNull();
  });
});
