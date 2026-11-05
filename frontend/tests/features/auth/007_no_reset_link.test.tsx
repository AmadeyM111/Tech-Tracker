// 007/R7-T21: AC-15, FR-17. Ссылки «Забыли пароль?» нет на /change-password и /no-role,
// и эти экраны не запрашивают статус сброса. Контрольная проверка: на /login ссылка есть.
// AppRoutes без мока api-модуля, сеть подменена глобальным fetch.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";
import { ru, t } from "../../../src/shared/i18n";
import { installStatusFetch } from "./helpers";

const STATUS_PATH = "/api/v1/auth/password-reset/status";
const j = (s: number, b: unknown) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
const err = (s: number, code: string) => j(s, { detail: code, code });

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

const statusCalls = (calls: Request[]) => calls.filter((r) => new URL(r.url).pathname === STATUS_PATH);

afterEach(() => vi.unstubAllGlobals());

describe("007 AC-15: no reset link on forced-change and no-role screens", () => {
  it("007_ac15_change_password_has_no_forgot_link_and_no_status_request", async () => {
    // enabled:true - чтобы отсутствие ссылки не объяснялось выключенным сбросом.
    const calls = installStatusFetch(true, (r) =>
      new URL(r.url).pathname === "/api/v1/me" ? err(403, "password_change_required") : err(404, "not_found"),
    );
    renderApp("/change-password");
    await screen.findByRole("dialog");
    await waitFor(() => expect(calls.some((r) => new URL(r.url).pathname === "/api/v1/me")).toBe(true));
    expect(screen.queryByText(t("auth.forgot_password"))).toBeNull();
    expect(screen.queryByRole("link", { name: ru["auth.forgot_password"] })).toBeNull();
    expect(statusCalls(calls)).toHaveLength(0);
  });

  it("007_ac15_no_role_has_no_forgot_link_and_no_status_request", async () => {
    const calls = installStatusFetch(true, (r) =>
      new URL(r.url).pathname === "/api/v1/me" ? err(403, "no_role") : err(404, "not_found"),
    );
    renderApp("/no-role");
    await screen.findByRole("heading", { name: t("auth.no_role_title") });
    expect(screen.queryByText(t("auth.forgot_password"))).toBeNull();
    expect(screen.queryByRole("link", { name: ru["auth.forgot_password"] })).toBeNull();
    expect(statusCalls(calls)).toHaveLength(0);
  });

  it("007_ac15_control_login_with_enabled_true_shows_forgot_link", async () => {
    const calls = installStatusFetch(true, (r) =>
      new URL(r.url).pathname === "/api/v1/me" ? err(401, "not_authenticated") : err(404, "not_found"),
    );
    renderApp("/login");
    const link = await screen.findByRole("link", { name: ru["auth.forgot_password"] });
    expect(link).toBeTruthy();
    expect(statusCalls(calls).length).toBeGreaterThan(0);
  });
});
