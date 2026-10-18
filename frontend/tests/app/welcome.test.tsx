// T103 (решение владельца 2026-10-16, заменяет T102): ссылки на смену пароля в интерфейсе нет НИГДЕ.
// Смена пароля - принудительное модальное окно на /change-password (см. password-modal.test.tsx).
//
// 003 (R4-T04, AC-26, AC-19): "/" - не экран, он ведёт на стартовый экран роли (/admin/users для ТА,
// /projects для БА и П). Проверки «нет ссылки "Сменить пароль", нет блока welcome» те же, но на стартовых экранах.
//
// Контракт для исполнителя (router.tsx; ru.ts):
//  - на стартовых экранах, в .ui-sidebar и на бизнес-экранах нет section[data-section="welcome"],
//    a[href="/change-password"] и ссылки с именем «Сменить пароль»;
//  - остальное меню (по capabilities) и «Выйти» на месте (меню и «Выйти» - на /projects).
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ru } from "../../src/shared/i18n";
import { CAPS_ALL, expectAt, installFetch, j, meWith, page, renderApp } from "../features/admin/helpers";

const ME = "GET /api/v1/me";
const NAME = /сменить пароль/i;
const BUSINESS = ["business_access", "project_create", "task_assign_others"];
// [имя, роль, возможности, стартовый путь, заголовок стартового экрана]
const CASES: [string, string, string[], string, string][] = [
  ["tech_admin", "tech_admin", CAPS_ALL, "/admin/users", ru["admin.users.title"]],
  ["business_admin", "business_admin", [...BUSINESS], "/projects", ru["projects.title"]],
  ["user", "user", ["business_access"], "/projects", ru["projects.title"]],
];
const DATA = {
  "GET /api/v1/projects": () => j(200, page([])),
  "GET /api/v1/admin/users": () => j(200, page([])),
};

describe("T103 no change-password link anywhere", () => {
  it.each(CASES)("003_ac26_%s_start_screen_has_no_change_password_link_and_no_welcome_block", async (_n, role, caps, path, title) => {
    installFetch({ ...DATA, [ME]: () => j(200, meWith(caps, role)) });
    const { container } = renderApp("/");
    await expectAt(path);
    await screen.findByRole("heading", { level: 1, name: title });
    expect(container.querySelector('section[data-section="welcome"]')).toBeNull();
    expect(container.querySelector('a[href="/change-password"]')).toBeNull();
    expect(screen.queryByRole("link", { name: NAME })).toBeNull();
    expect(screen.queryByText(NAME)).toBeNull();
    expect(screen.queryByRole("heading", { name: ru["app.welcome_title"] })).toBeNull();
  });

  it("003_ac19_ac26_sidebar_has_no_change_password_but_keeps_menu_and_logout", async () => {
    installFetch({ ...DATA, [ME]: () => j(200, meWith([...CAPS_ALL, ...BUSINESS])) });
    const { container } = renderApp("/");
    await expectAt("/projects");
    await screen.findByRole("heading", { level: 1, name: ru["projects.title"] });
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
