// 019 / R8-T22: AC-23, FR-14. The screens /change-password, /password-reset, /password-reset/confirm and /no-role
// do not change, and they show no "Зарегистрироваться" link even when the feature is enabled (enabled:true).
// Control: /login with enabled:true shows the link, so the absence on the other screens is not a broken setup.
// AppRoutes without module mocks; the network is replaced by the global fetch stub (installStatusFetch).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";
import { ru, t } from "../../../src/shared/i18n";
import { installStatusFetch } from "./helpers";

const j = (s: number, b: unknown) =>
  new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
const err = (s: number, code: string) => j(s, { detail: code, code });

const REGISTER_LINK = ru["auth.register_link"];

function renderApp(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Checks in the whole document (dialogs may be outside the container): no link text and no link to /register. */
function expectNoRegisterLink() {
  expect(screen.queryByRole("link", { name: REGISTER_LINK })).toBeNull();
  expect(screen.queryByText(REGISTER_LINK)).toBeNull();
  expect(document.querySelector('a[href="/register"]')).toBeNull();
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("019 AC-23: no register link on the existing auth screens", () => {
  it("019_ac23_control_login_with_enabled_true_shows_register_link", async () => {
    installStatusFetch(true, (r) =>
      new URL(r.url).pathname === "/api/v1/me" ? err(401, "not_authenticated") : err(404, "not_found"),
    );
    renderApp("/login");
    const link = await screen.findByRole("link", { name: REGISTER_LINK });
    expect(link.getAttribute("href")).toBe("/register");
  });

  it("019_ac23_change_password_has_no_register_link", async () => {
    installStatusFetch(true, (r) =>
      new URL(r.url).pathname === "/api/v1/me" ? err(403, "password_change_required") : err(404, "not_found"),
    );
    renderApp("/change-password");
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expectNoRegisterLink();
  });

  it("019_ac23_password_reset_request_has_no_register_link", async () => {
    installStatusFetch(true, (r) =>
      new URL(r.url).pathname === "/api/v1/me" ? err(401, "not_authenticated") : err(404, "not_found"),
    );
    renderApp("/password-reset");
    expect(await screen.findByRole("heading", { level: 1, name: t("auth.reset_request_title") })).toBeTruthy();
    expectNoRegisterLink();
  });

  it("019_ac23_password_reset_confirm_has_no_register_link", async () => {
    window.history.replaceState(null, "", "/password-reset/confirm#token=abc");
    installStatusFetch(true, (r) =>
      new URL(r.url).pathname === "/api/v1/me" ? err(401, "not_authenticated") : err(404, "not_found"),
    );
    renderApp("/password-reset/confirm");
    expect(await screen.findByRole("heading", { level: 1, name: t("auth.reset_confirm_title") })).toBeTruthy();
    expectNoRegisterLink();
  });

  it("019_ac23_no_role_has_no_register_link", async () => {
    installStatusFetch(true, (r) =>
      new URL(r.url).pathname === "/api/v1/me" ? err(403, "no_role") : err(404, "not_found"),
    );
    renderApp("/no-role");
    expect(await screen.findByRole("heading", { level: 1, name: t("auth.no_role_title") })).toBeTruthy();
    expectNoRegisterLink();
  });
});
