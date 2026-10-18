// T23 (попытка 2): проверка сессии, редиректы, колбэки навигации, очистка кэша.
// Контракт: AppRoutes без мока api-модуля, сеть подменена глобальным fetch.
//   003 (R4-T04): "/" и неизвестные пути только перенаправляют на стартовый экран по FR-3, "Главной" нет.
//   GET /api/v1/me: 200 -> стартовый экран роли (USER = роль user без возможностей, фикстура NOCAP ->
//   /admin/users с отказом "нет прав" и одним запросом - профилем, AC-36);
//   401 -> /login; 403 password_change_required -> /change-password; 403 no_role -> /no-role.
//   Ожидание me -> role="status" с текстом из словаря, без полей и форм.
//   Один общий клиент приложения: 401 (кроме login/logout) -> queryClient.clear() + /login;
//   403 password_change_required -> /change-password; 403 no_role -> /no-role.
// AC: FR-4, FR-55, FR-57, FR-66, AC-75, NFR-7.
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
  // Бывший me_200_with_role_shows_home_stub_not_blank (003/AC-36): роль без возможностей -> /admin/users,
  // отказ вместо пустого экрана, меню только с «Выйти», ровно один запрос (профиль).
  it("003_ac36_me_200_with_role_without_capabilities_shows_forbidden_at_users_not_blank", async () => {
    routes["GET /api/v1/me"] = ME_OK;
    renderApp("/");
    const main = await screen.findByRole("main");
    await expectAt("/admin/users");
    expect((await screen.findByRole("alert")).textContent).toBe(ru["error.forbidden"]);
    expect(main.querySelector("a")).toBeNull();
    expect(screen.getAllByRole("button", { name: ru["auth.logout"] })).toHaveLength(1);
    expect(screen.queryByRole("heading", { name: "Главная" })).toBeNull();
    await new Promise((r) => setTimeout(r, 40));
    expect(calls).toHaveLength(1);
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

  // Бывший unknown_path_redirects_to_root_then_by_me (003/AC-5): неизвестный путь идёт по правилу «/» (прямоту
  // без промежуточного "/" проверяет start-screen.test.tsx, AC-8 и AC-9).
  it("003_ac5_unknown_path_start_screen_follows_me_rule", async () => {
    routes["GET /api/v1/me"] = ME_NOROLE;
    const first = renderApp("/no/such/page");
    await expectAt("/no-role");
    first.unmount();
    routes["GET /api/v1/me"] = ME_OK;
    renderApp("/another");
    expect(await screen.findByRole("main")).toBeTruthy();
    await expectAt("/admin/users");
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
  // Бывший login_with_active_session_goes_home (003/AC-6).
  it("003_ac6_login_with_active_session_goes_to_start_screen", async () => {
    routes["GET /api/v1/me"] = ME_OK;
    renderApp("/login");
    await expectAt("/admin/users");
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

  // T103: смена пароля по собственной инициативе не предусмотрена - не-принудительный уходит на
  // стартовый экран (003/AC-7; бывший t103_voluntary_change_password_redirects_home).
  it("003_ac7_t103_voluntary_change_password_redirects_to_start_screen", async () => {
    routes["GET /api/v1/me"] = ME_OK;
    const { container } = renderApp("/change-password");
    await expectAt("/admin/users");
    expect(await screen.findByRole("main")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(container.querySelector('input[autocomplete="new-password"]')).toBeNull();
  });

  it("t103_forced_me_403_shows_dialog_on_change_password", async () => {
    routes["GET /api/v1/me"] = ME_PWD;
    renderApp("/change-password");
    const dialog = await screen.findByRole("dialog");
    expect(field(dialog, "new-password", 1)).toBeTruthy();
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

  // Бывший change_password_with_role_lands_on_home (003/AC-12).
  it("003_ac12_change_password_with_role_lands_on_start_screen", async () => {
    let changed = false;
    routes["GET /api/v1/me"] = () => (changed ? ME_OK() : ME_PWD());
    routes["POST /api/v1/auth/password"] = () => ((changed = true), OK204());
    const { container } = renderApp("/change-password");
    await fillChange(container);
    fireEvent.click(submitButton(container));
    expect(await screen.findByRole("main")).toBeTruthy();
    await expectAt("/admin/users");
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

  // 003/AC-10: после входа - стартовый экран (USER -> /admin/users), кэш предыдущего пользователя очищен.
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
    await expectAt("/admin/users");
    expect(qc.getQueryData(["previous-user"])).toBeUndefined();
  });
});

describe("navigation callbacks of the shared client (T23)", () => {
  async function onChangePassword(next: Handler) {
    routes["GET /api/v1/me"] = ME_PWD;
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
    routes["GET /api/v1/me"] = ME_PWD; // T103: the flag is the reason for the redirect, so /me reports it
    fireEvent.click(plainButtons(container)[0]!);
    await expectAt("/change-password");
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });

  it("403_no_role_goes_to_no_role", async () => {
    const { getAppClient } = await import("../../../src/shared/api/client");
    routes["GET /api/v1/me"] = ME_OK;
    routes["GET /api/v1/admin/users"] = () => err(403, "no_role");
    renderApp("/");
    await screen.findByRole("main");
    await expectAt("/admin/users"); // 003/AC-36: "/" уже не экран
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
    routes["GET /api/v1/me"] = ME_PWD;
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

describe("no_role user and the forced password change (T23 attempt 3, T103)", () => {
  async function fill(c: HTMLElement) {
    await waitFor(() => field(c, "current-password"));
    fireEvent.change(field(c, "current-password"), { target: { value: "Old-Password-123" } });
    fireEvent.change(field(c, "new-password", 0), { target: { value: "New-Password-12345" } });
    fireEvent.change(field(c, "new-password", 1), { target: { value: "New-Password-12345" } });
  }

  // T103: пользователь без роли и без принудительной смены - не-forced: "/" -> /no-role, без диалога.
  it("t103_no_role_me_on_change_password_goes_to_no_role_without_dialog", async () => {
    routes["GET /api/v1/me"] = ME_NOROLE;
    renderApp("/change-password");
    await expectAt("/no-role");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("fr55_no_role_callback_from_password_request_stays_on_form", async () => {
    routes["GET /api/v1/me"] = ME_PWD;
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
    await expectAt("/admin/users"); // 003/AC-36: "/" уже не экран
    qc.setQueryData(["sentinel"], 1);
    const at = where();
    out.unmount();
    routes["GET /api/v1/me"] = ME_401;
    await getAppClient().GET("/api/v1/me").catch(() => undefined);
    expect(qc.getQueryData(["sentinel"])).toBe(1);
    expect(at).toBe("/admin/users");
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
    expect((await screen.findByRole("alert")).textContent).not.toBe(ru["error.forbidden"]);
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
    // 003/AC-8: после «Повторить» - стартовый экран; вместо ошибки сессии теперь только отказ (USER без возможностей)
    await expectAt("/admin/users");
    expect((await screen.findByRole("alert")).textContent).toBe(ru["error.forbidden"]);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });
});
