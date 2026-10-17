// T103 (решение владельца 2026-10-16, заменяет T102): ссылки на смену пароля в интерфейсе нет НИГДЕ.
// Смена пароля - принудительное модальное окно на /change-password (см. password-modal.test.tsx).
//
// Контракт для исполнителя (router.tsx, Home; ru.ts):
//  - из Home убраны section[data-section="welcome"] и ссылка «Сменить пароль»;
//  - на "/", в .ui-sidebar и на бизнес-экранах нет a[href="/change-password"] и ссылки с именем «Сменить пароль»;
//  - остальное меню (по capabilities) и «Выйти» на месте.
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../src/shared/i18n";
import { CAPS_ALL, installFetch, j, meWith, page, renderApp } from "../features/admin/helpers";

const ME = "GET /api/v1/me";
const NAME = /Сменить пароль/;
const BUSINESS = ["business_access", "project_create", "task_assign_others"];
const CASES: [string, string, string[]][] = [
  ["tech_admin", "tech_admin", CAPS_ALL],
  ["business_admin", "business_admin", [...BUSINESS]],
  ["user", "user", ["business_access"]],
];

describe("T103 no change-password link anywhere", () => {
  it.each(CASES)("ac_%s_home_has_no_change_password_link_and_no_welcome_block", async (_n, role, caps) => {
    installFetch({ [ME]: () => j(200, meWith(caps, role)) });
    const { container } = renderApp("/");
    await screen.findByRole("heading", { level: 1, name: ru["app.home_title"] });
    expect(container.querySelector('section[data-section="welcome"]')).toBeNull();
    expect(container.querySelector('a[href="/change-password"]')).toBeNull();
    expect(screen.queryByRole("link", { name: NAME })).toBeNull();
    expect(screen.queryByText(NAME)).toBeNull();
    expect(screen.queryByRole("heading", { name: ru["app.welcome_title"] })).toBeNull();
  });

  it("ac_sidebar_has_no_change_password_but_keeps_menu_and_logout", async () => {
    installFetch({ [ME]: () => j(200, meWith([...CAPS_ALL, ...BUSINESS])) });
    const { container } = renderApp("/");
    await screen.findByRole("heading", { level: 1, name: ru["app.home_title"] });
    const sidebar = container.querySelector(".ui-sidebar") as HTMLElement;
    expect(sidebar).not.toBeNull();
    expect(within(sidebar).queryByRole("link", { name: NAME })).toBeNull();
    expect(sidebar.querySelector('a[href="/change-password"]')).toBeNull();
    expect(within(sidebar).getByRole("link", { name: ru["nav.projects"] })).toBeTruthy();
    expect(within(sidebar).getByRole("link", { name: ru["nav.my_tasks"] })).toBeTruthy();
    expect(within(sidebar).getByRole("button", { name: ru["auth.logout"] })).toBeTruthy();
  });

  it.each(["/projects", "/my-tasks"])("ac_%s_has_no_change_password_link", async (path) => {
    installFetch({
      [ME]: () => j(200, meWith(BUSINESS)),
      "GET /api/v1/projects": () => j(200, page([])),
      "GET /api/v1/me/tasks": () => j(200, page([])),
    });
    const { container } = renderApp(path);
    await screen.findByRole("main");
    await screen.findByRole("link", { name: ru["nav.projects"] });
    expect(container.querySelector('a[href="/change-password"]')).toBeNull();
    expect(screen.queryByRole("link", { name: NAME })).toBeNull();
  });
});
