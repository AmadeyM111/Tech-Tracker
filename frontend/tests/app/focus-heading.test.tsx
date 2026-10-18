// 003 / R4-T05: фокус на заголовке стартового экрана после входа (AC-15, FR-16) и после принудительной
// смены пароля (AC-13, FR-15) для BA, U, TA. NR и AUD - R4-T06.
//
// Контракт (plan §4.4): session.ts экспортирует FOCUS_HEADING_STATE ({ focusHeading: true }),
// focusHeadingState(state) и useFocusHeadingOnArrival(ref). LoginPage при роли и без флага идёт на "/" с
// этим состоянием, "/" -> StartRedirect сохраняет его, UsersPage ставит tabIndex=-1 на h1 и фокусирует его.
// Тесты идут через AppRoutes (состояние перехода живёт через "/" -> StartRedirect). Строки - из словаря ru.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../src/app/router";
import * as session from "../../src/features/auth/session";
import { ru } from "../../src/shared/i18n";
import { CAPS_ALL, err, installFetch, j, meWith, page, where, Where, type Handler } from "../features/admin/helpers";
import { field, submitButton } from "../features/auth/helpers";

const ME = "GET /api/v1/me";
const LOGIN = "POST /api/v1/auth/login";
const PWD_POST = "POST /api/v1/auth/password";
const OLD = "One-Time-Pass-123";
const NEW = "Brand-New-Passw0rd!";

const BA = () => j(200, meWith(["business_access", "project_create", "task_assign_others"], "business_admin"));
const U = () => j(200, meWith(["business_access"], "user"));
const TA = () => j(200, meWith(CAPS_ALL, "tech_admin"));
const ANON = () => err(401, "not_authenticated");
const PWD = () => err(403, "password_change_required");

const DATA: Record<string, Handler> = {
  "GET /api/v1/projects": () => j(200, page([])),
  "GET /api/v1/me/tasks": () => j(200, page([])),
  "GET /api/v1/admin/users": () => j(200, page([])),
  "GET /api/v1/admin/audit": () => j(200, page([])),
};

// фикстура, роль в ответе логина, заголовок целевого экрана, путь
const CASES = [
  ["BA", BA, "business_admin", ru["projects.title"], "/projects"],
  ["U", U, "user", ru["projects.title"], "/projects"],
  ["TA", TA, "tech_admin", ru["admin.users.title"], "/admin/users"],
] as const;

afterEach(() => vi.unstubAllGlobals());

function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function expectFocusedHeading(name: string) {
  const h1 = await screen.findByRole("heading", { level: 1, name });
  await waitFor(() => expect(document.activeElement).toBe(h1));
  expect(document.activeElement).not.toBe(document.body);
  expect(h1.getAttribute("tabindex")).toBe("-1");
  return h1;
}

describe("003 focus-heading state helpers (plan 4.4)", () => {
  it("003_fr16_focus_heading_state_constant", () => {
    expect(session.FOCUS_HEADING_STATE).toEqual({ focusHeading: true });
  });

  it.each([
    [{ focusHeading: true }, true],
    [{ focusHeading: true, other: 1 }, true],
    [{ focusHeading: false }, false],
    [{ focusHeading: "yes" }, false],
    [{}, false],
    [null, false],
    [undefined, false],
    ["focusHeading", false],
  ] as [unknown, boolean][])("003_fr16_focusHeadingState_%j", (state, keep) => {
    const r = session.focusHeadingState(state);
    if (keep) expect(r).toEqual({ focusHeading: true });
    else expect(r).toBeUndefined();
  });
});

describe("003 AC-15 focus after login (FR-16)", () => {
  it.each(CASES)("003_ac15_%s_login_focuses_start_heading", async (_n, profile, role, title, target) => {
    let loggedIn = false;
    installFetch({
      ...DATA,
      [ME]: () => (loggedIn ? profile() : ANON()),
      [LOGIN]: () => {
        loggedIn = true;
        return j(200, { user: { id: meWith([]).id, login: "ivanov", role, must_change_password: false } });
      },
    });
    const { container } = renderApp("/login");
    await waitFor(() => field(container, "username"));
    fireEvent.change(field(container, "username"), { target: { value: "ivanov" } });
    fireEvent.change(field(container, "current-password"), { target: { value: "Correct-Horse-Battery-9" } });
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(where()).toBe(target));
    await expectFocusedHeading(title);
  });
});

describe("003 AC-13 focus after forced password change (FR-15)", () => {
  it.each(CASES)("003_ac13_%s_password_change_focuses_start_heading", async (_n, profile, _role, title, target) => {
    let changed = false;
    installFetch({
      ...DATA,
      [ME]: () => (changed ? profile() : PWD()),
      [PWD_POST]: () => ((changed = true), new Response(null, { status: 204 })),
    });
    renderApp("/change-password");
    const dialog = await screen.findByRole("dialog");
    const input = (ac: string, n = 0) => dialog.querySelectorAll<HTMLInputElement>(`input[autocomplete="${ac}"]`)[n]!;
    fireEvent.change(input("current-password"), { target: { value: OLD } });
    fireEvent.change(input("new-password", 0), { target: { value: NEW } });
    fireEvent.change(input("new-password", 1), { target: { value: NEW } });
    fireEvent.click(within(dialog).getByRole("button", { name: ru["auth.change_password_submit"] }));
    await waitFor(() => expect(where()).toBe(target));
    await expectFocusedHeading(title);
  });
});

describe("003 no focus transfer on ordinary navigation (FR-16)", () => {
  it("003_fr16_menu_navigation_to_users_does_not_focus_heading", async () => {
    installFetch({ ...DATA, [ME]: TA });
    renderApp("/admin/audit");
    await screen.findByRole("heading", { level: 1, name: ru["admin.audit.title"] });
    const nav = await screen.findByRole("navigation", { name: ru["app.menu_label"] });
    const link = within(nav).getByRole("link", { name: ru["admin.users.title"] });
    link.focus();
    fireEvent.click(link);
    const h1 = await screen.findByRole("heading", { level: 1, name: ru["admin.users.title"] });
    expect(where()).toBe("/admin/users");
    await new Promise((r) => setTimeout(r, 60));
    expect(document.activeElement).not.toBe(h1);
  });

  it("003_fr16_direct_open_of_users_does_not_focus_heading", async () => {
    installFetch({ ...DATA, [ME]: TA });
    renderApp("/admin/users");
    const h1 = await screen.findByRole("heading", { level: 1, name: ru["admin.users.title"] });
    await new Promise((r) => setTimeout(r, 60));
    expect(document.activeElement).not.toBe(h1);
  });
});
