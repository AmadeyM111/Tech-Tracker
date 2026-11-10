// Аудит #10: прямая ссылка на раздел без capability (RoleScreen) - ErrorAlert с errorMessage("forbidden")
// и ссылка «Назад» на стартовый раздел роли (startPath). Запросов к данным раздела нет.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ru } from "../../src/shared/i18n";
import { CAPS_ALL, expectAt, installFetch, j, meWith, page, renderApp, where } from "../features/admin/helpers";

const ME = "GET /api/v1/me";
const USERS = "GET /api/v1/admin/users";
const PROJECTS = "GET /api/v1/projects";

afterEach(() => vi.unstubAllGlobals());

describe("прямая ссылка на раздел без прав (аудит #10)", () => {
  it("ta_on_summary_shows_forbidden_and_back_link_to_admin_users", async () => {
    const f = installFetch({
      [ME]: () => j(200, meWith(CAPS_ALL, "tech_admin")),
      [USERS]: () => j(200, page([])),
    });
    renderApp("/summary");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(ru["error.forbidden"]);
    const back = screen.getByRole("link", { name: ru["admin.prev_page"] });
    expect(back.getAttribute("href")).toBe("/admin/users");
    expect(where()).toBe("/summary");
    expect(f.calls.some((c) => new URL(c.url).pathname.startsWith("/api/v1/me/overview"))).toBe(false);
  });

  it("user_on_admin_users_shows_forbidden_and_back_link_to_projects_which_navigates", async () => {
    installFetch({
      [ME]: () => j(200, meWith(["business_access"], "user")),
      [PROJECTS]: () => j(200, page([])),
    });
    renderApp("/admin/users");
    expect((await screen.findByRole("alert")).textContent).toBe(ru["error.forbidden"]);
    const back = screen.getByRole("link", { name: ru["admin.prev_page"] });
    expect(back.getAttribute("href")).toBe("/projects");
    fireEvent.click(back);
    await expectAt("/projects");
    await waitFor(() => expect(screen.queryByText(ru["error.forbidden"])).toBeNull());
  });

  it("no_back_link_when_start_screen_is_the_current_path", async () => {
    installFetch({ [ME]: () => j(200, meWith([], "user")) });
    renderApp("/admin/users");
    expect((await screen.findByRole("alert")).textContent).toBe(ru["error.forbidden"]);
    expect(screen.queryByRole("link", { name: ru["admin.prev_page"] })).toBeNull();
  });
});
