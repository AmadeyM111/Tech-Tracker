// T23 (попытка 2): проверка сессии, редиректы, колбэки навигации, очистка кэша.
// Контракт: AppRoutes без мока api-модуля, сеть подменена глобальным fetch.
//   GET /api/v1/me: 200 -> заглушка "/" (role="main" с непустым h1 из словаря);
//   401 -> /login; 403 password_change_required -> /change-password; 403 no_role -> /no-role.
//   Ожидание me -> role="status" с текстом из словаря, без полей и форм.
//   Один общий клиент приложения: 401 (кроме login/logout) -> queryClient.clear() + /login;
//   403 password_change_required -> /change-password; 403 no_role -> /no-role.
// AC: FR-4, FR-55, FR-56, FR-57, FR-66, AC-75, NFR-7.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";
import { ru, t } from "../../../src/shared/i18n";
import { Where, deferred, field, plainButtons, submitButton } from "./helpers";

const USER = { id: "11111111-1111-4111-8111-111111111111", login: "ivanov", role: "user", must_change_password: false, capabilities: [] };
const j = (s: number, b: unknown) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
const err = (s: number, code: string) => j(s, { detail: code, code });
const ME_OK = () => j(200, USER);
const ME_401 = () => err(401, "not_authenticated");
const ME_PWD = () => err(403, "password_change_required");
const ME_NOROLE = () => err(403, "no_role");
const OK204 = () => new Response(null, { status: 204 });

type Handler = (req: Request) => Response | Promise<Response>;
let routes: Record<string, Handler>;
let calls: Request[];
let qc: QueryClient;

function stubFetch() {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (r: Request) => {
      calls.push(r);
      const key = `${r.method} ${new URL(r.url).pathname}`;
      const h = routes[key];
      if (!h) throw new Error(`unexpected request ${key}`);
      return h(r);
    }),
  );
}

function renderApp(path: string) {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const out = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return out;
}

const where = () => screen.getByTestId("where").textContent;
const expectAt = (p: string) => waitFor(() => expect(where()).toBe(p));

beforeEach(() => {
  routes = {};
  stubFetch();
});
afterEach(() => vi.unstubAllGlobals());

describe("session gate on / (T23)", () => {
  it("me_200_with_role_shows_home_stub_not_blank", async () => {
    routes["GET /api/v1/me"] = ME_OK;
    renderApp("/");
    const main = await screen.findByRole("main");
    expect(main.querySelector("h1")?.textContent?.trim()).toBeTruthy();
    expect(Object.values(ru)).toContain(main.querySelector("h1")?.textContent);
    expect(where()).toBe("/");
  });

  it.each([
    ["401_to_login", ME_401, "/login"],
    ["password_change_required_to_change_password", ME_PWD, "/change-password"],
    ["no_role_to_no_role", ME_NOROLE, "/no-role"],
  ])("me_%s", async (_n, me, target) => {
    routes["GET /api/v1/me"] = me;
    renderApp("/");
    await expectAt(target);
    expect(screen.queryByRole("main")).toBeNull();
  });

  it("unknown_path_redirects_to_root_then_by_me", async () => {
    routes["GET /api/v1/me"] = ME_NOROLE;
    const first = renderApp("/no/such/page");
    await expectAt("/no-role");
    first.unmount();
    routes["GET /api/v1/me"] = ME_OK;
    renderApp("/another");
    expect(await screen.findByRole("main")).toBeTruthy();
    expect(where()).toBe("/");
  });

  it("loading_indicator_from_dictionary_while_me_pending", async () => {
    const d = deferred<Response>();
    routes["GET /api/v1/me"] = () => d.promise;
    const { container } = renderApp("/");
    const status = await screen.findByRole("status");
    expect(Object.values(ru)).toContain(status.textContent);
    expect(container.querySelector("input, form, [role=main]")).toBeNull();
    expect(where()).toBe("/");
    d.resolve(ME_OK());
    expect(await screen.findByRole("main")).toBeTruthy();
  });
});

describe("login/change-password/no-role guards (T23)", () => {
  it("login_with_active_session_goes_home", async () => {
    routes["GET /api/v1/me"] = ME_OK;
    renderApp("/login");
    await expectAt("/");
    expect(await screen.findByRole("main")).toBeTruthy();
  });

  it("login_without_session_shows_form", async () => {
    routes["GET /api/v1/me"] = ME_401;
    const { container } = renderApp("/login");
    await waitFor(() => expect(field(container, "username")).toBeTruthy());
    expect(where()).toBe("/login");
  });

  it.each(["/change-password", "/no-role"])("%s_without_session_goes_to_login", async (path) => {
    routes["GET /api/v1/me"] = ME_401;
    renderApp(path);
    await expectAt("/login");
  });

  it("fr56_voluntary_change_password_allowed_with_session", async () => {
    routes["GET /api/v1/me"] = ME_OK;
    const { container } = renderApp("/change-password");
    await waitFor(() => expect(field(container, "new-password")).toBeTruthy());
    expect(where()).toBe("/change-password");
  });
});

describe("after password change and login (T23)", () => {
  async function fillChange(c: HTMLElement, next = "New-Password-12345", confirm = next) {
    await waitFor(() => field(c, "current-password"));
    fireEvent.change(field(c, "current-password"), { target: { value: "Old-Password-123" } });
    fireEvent.change(field(c, "new-password", 0), { target: { value: next } });
    fireEvent.change(field(c, "new-password", 1), { target: { value: confirm } });
  }

  it("fr66_ac75_change_password_then_root_then_no_role_by_me", async () => {
    let changed = false;
    routes["GET /api/v1/me"] = () => (changed ? ME_NOROLE() : ME_PWD());
    routes["POST /api/v1/auth/password"] = () => ((changed = true), OK204());
    const { container } = renderApp("/change-password");
    await fillChange(container);
    fireEvent.click(submitButton(container));
    await expectAt("/no-role");
  });

  it("change_password_with_role_lands_on_home", async () => {
    let changed = false;
    routes["GET /api/v1/me"] = () => (changed ? ME_OK() : ME_PWD());
    routes["POST /api/v1/auth/password"] = () => ((changed = true), OK204());
    const { container } = renderApp("/change-password");
    await fillChange(container);
    fireEvent.click(submitButton(container));
    expect(await screen.findByRole("main")).toBeTruthy();
    expect(where()).toBe("/");
  });

  it("expired_session_on_password_change_goes_to_login_not_form", async () => {
    routes["GET /api/v1/me"] = ME_PWD;
    routes["POST /api/v1/auth/password"] = () => err(401, "not_authenticated");
    const { container } = renderApp("/change-password");
    await fillChange(container);
    fireEvent.click(submitButton(container));
    await expectAt("/login");
  });

  it("login_trims_login_in_request_body", async () => {
    routes["GET /api/v1/me"] = ME_401;
    routes["POST /api/v1/auth/login"] = () => j(200, { user: USER });
    const { container } = renderApp("/login");
    await waitFor(() => field(container, "username"));
    fireEvent.change(field(container, "username"), { target: { value: " uok " } });
    fireEvent.change(field(container, "current-password"), { target: { value: "Correct-Horse-Battery-9" } });
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/auth/login"))).toBe(true));
    const req = calls.find((c) => c.url.endsWith("/auth/login"))!;
    expect(await req.json()).toEqual({ login: "uok", password: "Correct-Horse-Battery-9" });
  });

  it("successful_login_clears_previous_users_cache", async () => {
    routes["GET /api/v1/me"] = ME_401;
    routes["POST /api/v1/auth/login"] = () => j(200, { user: USER });
    const { container } = renderApp("/login");
    await waitFor(() => field(container, "username"));
    qc.setQueryData(["previous-user"], { secret: 1 });
    fireEvent.change(field(container, "username"), { target: { value: "ivanov" } });
    fireEvent.change(field(container, "current-password"), { target: { value: "Correct-Horse-Battery-9" } });
    routes["GET /api/v1/me"] = ME_OK;
    fireEvent.click(submitButton(container));
    await expectAt("/");
    expect(qc.getQueryData(["previous-user"])).toBeUndefined();
  });
});

describe("navigation callbacks of the shared client (T23)", () => {
  async function onChangePassword(next: Handler) {
    routes["GET /api/v1/me"] = ME_OK;
    routes["POST /api/v1/auth/password"] = next;
    const { container } = renderApp("/change-password");
    await waitFor(() => field(container, "current-password"));
    qc.setQueryData(["sentinel"], 1);
    fireEvent.change(field(container, "current-password"), { target: { value: "Old-Password-123" } });
    fireEvent.change(field(container, "new-password", 0), { target: { value: "New-Password-12345" } });
    fireEvent.change(field(container, "new-password", 1), { target: { value: "New-Password-12345" } });
    fireEvent.click(submitButton(container));
  }

  it("401_clears_query_cache_and_goes_to_login", async () => {
    await onChangePassword(() => err(401, "not_authenticated"));
    await expectAt("/login");
    expect(qc.getQueryData(["sentinel"])).toBeUndefined();
  });

  it("403_password_change_required_goes_to_change_password", async () => {
    routes["POST /api/v1/auth/logout"] = () => err(403, "password_change_required");
    routes["GET /api/v1/me"] = ME_NOROLE;
    const { container } = renderApp("/no-role");
    await waitFor(() => plainButtons(container)[0]!);
    fireEvent.click(plainButtons(container)[0]!);
    await expectAt("/change-password");
  });

  it("403_no_role_goes_to_no_role", async () => {
    const { getAppClient } = await import("../../../src/shared/api/client");
    routes["GET /api/v1/me"] = ME_OK;
    routes["GET /api/v1/admin/users"] = () => err(403, "no_role");
    renderApp("/");
    await screen.findByRole("main");
    expect(where()).toBe("/");
    await act(async () => {
      await getAppClient().GET("/api/v1/admin/users", {}).catch(() => undefined);
    });
    await expectAt("/no-role");
  });
});

describe("logout and alert focus (T23)", () => {
  it("logout_401_is_success_goes_to_login_and_clears_cache", async () => {
    routes["GET /api/v1/me"] = ME_NOROLE;
    routes["POST /api/v1/auth/logout"] = () => err(401, "not_authenticated");
    const { container } = renderApp("/no-role");
    await waitFor(() => plainButtons(container)[0]!);
    qc.setQueryData(["sentinel"], 1);
    routes["GET /api/v1/me"] = ME_401;
    fireEvent.click(plainButtons(container)[0]!);
    await expectAt("/login");
    expect(qc.getQueryData(["sentinel"])).toBeUndefined();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("logout_success_clears_real_cache", async () => {
    routes["GET /api/v1/me"] = ME_NOROLE;
    routes["POST /api/v1/auth/logout"] = OK204;
    const { container } = renderApp("/no-role");
    await waitFor(() => plainButtons(container)[0]!);
    qc.setQueryData(["sentinel"], 1);
    routes["GET /api/v1/me"] = ME_401;
    fireEvent.click(plainButtons(container)[0]!);
    await expectAt("/login");
    expect(qc.getQueryData(["sentinel"])).toBeUndefined();
  });

  it("nfr7_repeated_identical_client_error_refocuses_alert", async () => {
    routes["GET /api/v1/me"] = ME_OK;
    const { container } = renderApp("/change-password");
    await waitFor(() => field(container, "current-password"));
    fireEvent.change(field(container, "current-password"), { target: { value: "Old-Password-123" } });
    fireEvent.change(field(container, "new-password", 0), { target: { value: "New-Password-12345" } });
    fireEvent.change(field(container, "new-password", 1), { target: { value: "Other-Password-1234" } });
    fireEvent.click(submitButton(container));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(t("auth.password_mismatch"));
    await waitFor(() => expect(document.activeElement).toBe(alert));
    field(container, "current-password").focus();
    expect(document.activeElement).not.toBe(alert);
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("alert")));
  });
});

describe("no_role user keeps change-password reachable (T23 attempt 3)", () => {
  async function fill(c: HTMLElement) {
    await waitFor(() => field(c, "current-password"));
    fireEvent.change(field(c, "current-password"), { target: { value: "Old-Password-123" } });
    fireEvent.change(field(c, "new-password", 0), { target: { value: "New-Password-12345" } });
    fireEvent.change(field(c, "new-password", 1), { target: { value: "New-Password-12345" } });
  }

  it("fr56_fr66_no_role_me_stays_on_change_password_then_changes_and_goes_no_role", async () => {
    routes["GET /api/v1/me"] = ME_NOROLE;
    routes["POST /api/v1/auth/password"] = OK204;
    const { container } = renderApp("/change-password");
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/me"))).toBe(true));
    await new Promise((r) => setTimeout(r, 50));
    expect(where()).toBe("/change-password");
    await fill(container);
    expect(field(container, "new-password", 0)).toBeTruthy();
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/auth/password"))).toBe(true));
    await expectAt("/no-role");
  });

  it("fr56_no_role_callback_from_password_request_stays_on_form", async () => {
    routes["GET /api/v1/me"] = ME_OK;
    routes["POST /api/v1/auth/password"] = () => err(403, "no_role");
    const { container } = renderApp("/change-password");
    await fill(container);
    fireEvent.click(submitButton(container));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/auth/password"))).toBe(true));
    await new Promise((r) => setTimeout(r, 50));
    expect(where()).toBe("/change-password");
    expect(field(container, "new-password", 0)).toBeTruthy();
  });

  it("no_role_callback_on_protected_screen_goes_to_no_role", async () => {
    routes["GET /api/v1/me"] = ME_NOROLE;
    renderApp("/");
    await expectAt("/no-role");
  });
});

describe("handler removal (T23 attempt 3)", () => {
  it("returned_remover_resets_handlers_401_no_longer_navigates", async () => {
    const { setNavigationHandlers, getAppClient } = await import("../../../src/shared/api/client");
    const onUnauthenticated = vi.fn();
    const remove = setNavigationHandlers({ onUnauthenticated });
    routes["GET /api/v1/me"] = ME_401;
    await getAppClient().GET("/api/v1/me").catch(() => undefined);
    expect(onUnauthenticated).toHaveBeenCalledTimes(1);
    remove();
    await getAppClient().GET("/api/v1/me").catch(() => undefined);
    expect(onUnauthenticated).toHaveBeenCalledTimes(1);
  });

  it("unmount_of_app_routes_resets_handlers", async () => {
    const { getAppClient } = await import("../../../src/shared/api/client");
    routes["GET /api/v1/me"] = ME_OK;
    const out = renderApp("/");
    await screen.findByRole("main");
    qc.setQueryData(["sentinel"], 1);
    const at = where();
    out.unmount();
    routes["GET /api/v1/me"] = ME_401;
    await getAppClient().GET("/api/v1/me").catch(() => undefined);
    expect(qc.getQueryData(["sentinel"])).toBe(1);
    expect(at).toBe("/");
  });
});

describe("me error retry (T23 attempt 3)", () => {
  const cases: [string, Handler][] = [
    ["500", () => err(500, "internal_error")],
    ["network_error", () => Promise.reject(new TypeError("Failed to fetch"))],
  ];
  it.each(cases)("me_%s_shows_alert_and_retry_button_refetches", async (_n, bad) => {
    let ok = false;
    let meCalls = 0;
    routes["GET /api/v1/me"] = (r) => {
      meCalls += 1;
      return ok ? ME_OK() : bad(r);
    };
    renderApp("/");
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(where()).toBe("/");
    const btn = (await screen.findByRole("button")) as HTMLButtonElement;
    expect(btn.type).toBe("button");
    expect(btn.textContent?.trim()).toBeTruthy();
    expect(Object.values(ru)).toContain(btn.textContent);
    const before = meCalls;
    ok = true;
    fireEvent.click(btn);
    expect(await screen.findByRole("main")).toBeTruthy();
    expect(meCalls).toBeGreaterThan(before);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
