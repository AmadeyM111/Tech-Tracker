// 003 / R4-T04: "/" и неизвестные пути только перенаправляют на стартовый экран роли (FR-1, FR-3...FR-9).
// AC-1...AC-9 (перенаправления), AC-10, AC-11 (вход, пути и кэш), AC-12 (смена пароля), AC-35, AC-36.
// Фокус на заголовке (AC-13, AC-15) проверяет focus-heading.test.tsx (R4-T05, R4-T06).
//
// Контракт (plan §4.2): `/` и `*` показывают только индикатор проверки сессии (p[role=status]),
// затем <Navigate replace> на startPath(профиль); 401 / password_change_required / no_role - через
// redirectFor; 5xx и сеть - ErrorAlert + «Повторить» на месте, без меню. GuestOnly и
// ForcedPasswordChange ведут на startPath(профиль). LoginPage и ChangePasswordPage по-прежнему идут на "/".
// Фикстуры профиля - spec §5: BA, U, TA, AUD, NOCAP, NR, PWD, ANON. Строки - из словаря ru.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect } from "react";
import { MemoryRouter, useLocation, useNavigate, useNavigationType, type NavigateFunction } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../src/app/router";
import { ru } from "../../src/shared/i18n";
import { CAPS_ALL, err, installFetch, j, meWith, page, where, Where, type Handler } from "../features/admin/helpers";
import { field, submitButton } from "../features/auth/helpers";

const DICT = Object.values(ru) as string[];
const ME = "GET /api/v1/me";
const LOGIN = "POST /api/v1/auth/login";
const PWD_POST = "POST /api/v1/auth/password";
const PROJECTS = "GET /api/v1/projects";
const MY_TASKS = "GET /api/v1/me/tasks";
const USERS = "GET /api/v1/admin/users";
const AUDIT = "GET /api/v1/admin/audit";

const BA_CAPS = ["business_access", "project_create", "task_assign_others"];
const BA = () => j(200, meWith(BA_CAPS, "business_admin"));
const U = () => j(200, meWith(["business_access"], "user"));
const TA = () => j(200, meWith(CAPS_ALL, "tech_admin"));
const AUD = () => j(200, meWith(["view_audit"], "user"));
const NOCAP = () => j(200, meWith([], "user"));
const NR = () => err(403, "no_role");
const PWD = () => err(403, "password_change_required");
const ANON = () => err(401, "not_authenticated");

const DATA: Record<string, Handler> = {
  [PROJECTS]: () => j(200, page([])),
  [MY_TASKS]: () => j(200, page([])),
  [USERS]: () => j(200, page([])),
  [AUDIT]: () => j(200, page([])),
};

const FX = { BA, U, TA, AUD, NOCAP, NR, PWD, ANON } as const;
type Fx = keyof typeof FX;
// фикстура -> итоговый путь для "/" и неизвестных путей
const ALL_FX: [Fx, string][] = [
  ["BA", "/projects"],
  ["U", "/projects"],
  ["TA", "/admin/users"],
  ["NR", "/no-role"],
  ["PWD", "/change-password"],
  ["ANON", "/login"],
];

interface Step {
  path: string;
  type: string;
}

/** Рендер с записью переходов (путь + тип навигации) и зондом "Назад". */
function renderRecorded(path: string, seed?: (qc: QueryClient) => void) {
  const raw: Step[] = [];
  const api: { navigate?: NavigateFunction } = {};
  function Probe() {
    const l = useLocation();
    const type = useNavigationType();
    const navigate = useNavigate();
    useEffect(() => {
      api.navigate = navigate;
    }, [navigate]);
    useEffect(() => {
      raw.push({ path: l.pathname, type });
    }, [l, type]);
    return null;
  }
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  seed?.(qc);
  const out = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
        <Where />
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  // подряд идущие одинаковые шаги (рендер без смены адреса) схлопываются
  const steps = () => raw.filter((s, i) => i === 0 || s.path !== raw[i - 1]!.path || s.type !== raw[i - 1]!.type);
  const back = async () => {
    await act(async () => {
      api.navigate!(-1);
    });
    await new Promise((r) => setTimeout(r, 20));
  };
  return { ...out, qc, steps, back };
}

const settle = () => new Promise((r) => setTimeout(r, 40));
const hrefsOf = (nav: HTMLElement) => Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href"));
const menu = () => screen.findByRole("navigation", { name: ru["app.menu_label"] });
const h1 = (name: string) => screen.findByRole("heading", { level: 1, name });

function expectAllReplace(steps: Step[]) {
  expect(steps.length).toBeGreaterThan(1);
  for (const s of steps.slice(1)) expect(s.type, JSON.stringify(steps)).toBe("REPLACE");
}

/** Редирект с гостевого/принудительного экрана: POP, затем только REPLACE; исходный и итоговый путь по одному разу. */
function expectSingleReplace(steps: Step[], from: string, target: string) {
  expect(steps[0], JSON.stringify(steps)).toEqual({ path: from, type: "POP" });
  expect(steps.at(-1), JSON.stringify(steps)).toEqual({ path: target, type: "REPLACE" });
  expectAllReplace(steps);
  expect(steps.filter((s) => s.path === from)).toHaveLength(1);
  expect(steps.filter((s) => s.path === target)).toHaveLength(1);
  expect(steps.some((s) => s.path === "/")).toBe(false);
}

afterEach(() => vi.unstubAllGlobals());

describe("AC-1, AC-2, AC-3 start screen by role on /", () => {
  it("003_ac1_ba_root_goes_to_projects_no_home_heading_menu_current", async () => {
    const f = installFetch({ ...DATA, [ME]: BA });
    renderRecorded("/");
    await h1(ru["projects.title"]);
    expect(where()).toBe("/projects");
    expect(screen.queryByRole("heading", { name: "Главная" })).toBeNull();
    const nav = await menu();
    await settle();
    expect(f.count(USERS)).toBe(0);
    expect(f.count(AUDIT)).toBe(0);
    expect(within(nav).getByRole("link", { name: ru["nav.projects"] }).getAttribute("aria-current")).toBe("page");
  });

  it("003_ac2_user_root_goes_to_projects", async () => {
    const f = installFetch({ ...DATA, [ME]: U });
    renderRecorded("/");
    await h1(ru["projects.title"]);
    expect(where()).toBe("/projects");
    await settle();
    expect(f.count(USERS)).toBe(0);
    expect(f.count(AUDIT)).toBe(0);
  });

  it("003_ac3_ta_root_goes_to_users_without_business_requests", async () => {
    const f = installFetch({ ...DATA, [ME]: TA });
    renderRecorded("/");
    await h1(ru["admin.users.title"]);
    expect(where()).toBe("/admin/users");
    await settle();
    expect(f.count(PROJECTS)).toBe(0);
    expect(f.count(MY_TASKS)).toBe(0);
  });
});

describe("AC-4 root without a usable session / role", () => {
  it("003_ac4_no_role_root_goes_to_no_role", async () => {
    installFetch({ [ME]: NR });
    renderRecorded("/");
    await waitFor(() => expect(where()).toBe("/no-role"));
    expect(await h1(ru["auth.no_role_title"])).toBeTruthy();
  });

  it("003_ac4_password_change_required_root_goes_to_change_password_with_dialog", async () => {
    installFetch({ [ME]: PWD });
    renderRecorded("/");
    await waitFor(() => expect(where()).toBe("/change-password"));
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });

  it("003_ac4_anonymous_root_goes_to_login", async () => {
    installFetch({ [ME]: ANON });
    renderRecorded("/");
    await waitFor(() => expect(where()).toBe("/login"));
  });
});

describe("AC-5 unknown paths follow the same rule as /", () => {
  const PATHS = ["/no/such/page", "/another", "/projects-x"];
  const cases = ALL_FX.flatMap(([name, target]) => PATHS.map((p) => [name, p, target] as const));

  it.each(cases)("003_ac5_%s_%s", async (name, path, target) => {
    installFetch({ ...DATA, [ME]: FX[name] });
    renderRecorded(path);
    await waitFor(() => expect(where()).toBe(target));
  });
});

describe("AC-6 /login with an active session", () => {
  it.each([
    ["BA", "/projects"],
    ["U", "/projects"],
    ["TA", "/admin/users"],
  ] as const)("003_ac6_%s_login_goes_to_start_screen_no_form", async (name, target) => {
    const title = name === "TA" ? ru["admin.users.title"] : ru["projects.title"];
    installFetch({ ...DATA, [ME]: FX[name] });
    const { container, steps } = renderRecorded("/login");
    await waitFor(() => expect(where()).toBe(target));
    await menu();
    expect(await h1(title)).toBeTruthy();
    expectSingleReplace(steps(), "/login", target);
    expect(screen.queryByRole("heading", { name: ru["auth.login_title"] })).toBeNull();
    expect(container.querySelector('input[autocomplete="current-password"]')).toBeNull();
  });
});

describe("AC-7 /change-password for a user who need not change the password", () => {
  it.each([
    ["BA", "/projects"],
    ["U", "/projects"],
    ["TA", "/admin/users"],
  ] as const)("003_ac7_%s_change_password_goes_to_start_screen_no_dialog", async (name, target) => {
    installFetch({ ...DATA, [ME]: FX[name] });
    const { steps } = renderRecorded("/change-password");
    await waitFor(() => expect(where()).toBe(target));
    await menu();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.querySelector(".ui-overlay")).toBeNull();
    expectSingleReplace(steps(), "/change-password", target);
  });

  // useSession(0) в ForcedPasswordChange: свежий профиль в кэше не должен заслонять ответ сервера.
  it("003_ac7_cached_fresh_profile_but_server_says_password_change_required_shows_dialog", async () => {
    const f = installFetch({ ...DATA, [ME]: PWD });
    const { steps } = renderRecorded("/change-password", (qc) =>
      qc.setQueryData(["auth", "me"], meWith(BA_CAPS, "business_admin")),
    );
    expect(await screen.findByRole("dialog")).toBeTruthy();
    await settle();
    expect(where()).toBe("/change-password");
    expect(f.count(ME)).toBeGreaterThanOrEqual(1);
    expect(steps().map((s) => s.path)).toEqual(["/change-password"]);
  });
});

describe("AC-8 session check failure on / (FR-7)", () => {
  const FAILURES: Record<string, Handler> = {
    "500": () => err(500, "internal_error"),
    network: () => Promise.reject(new TypeError("Failed to fetch")),
  };
  const cases = (["500", "network"] as const).flatMap(
    (failure) =>
      [
        [failure, "BA", "/projects"],
        [failure, "TA", "/admin/users"],
      ] as const,
  );

  it.each(cases)("003_ac8_%s_then_retry_with_%s", async (failure, name, target) => {
    let good = false;
    installFetch({ ...DATA, [ME]: (r) => (good ? FX[name]() : FAILURES[failure]!(r)) });
    renderRecorded("/");
    const alert = await screen.findByRole("alert");
    expect(DICT).toContain(alert.textContent);
    expect(where()).toBe("/");
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]!.textContent).toBe(ru["app.retry"]);
    expect(screen.queryByRole("navigation")).toBeNull();
    await settle();
    expect(where()).toBe("/");
    good = true;
    fireEvent.click(buttons[0]!);
    await waitFor(() => expect(where()).toBe(target));
    await menu();
  });
});

describe("AC-8 session check failure on an unknown path (FR-7, D-3)", () => {
  it.each([
    ["500", () => err(500, "internal_error")],
    ["network", () => Promise.reject(new TypeError("Failed to fetch"))],
  ] as const)("003_ac8_unknown_path_%s_stays_then_retry_goes_to_start_screen", async (_n, failure) => {
    let good = false;
    installFetch({ ...DATA, [ME]: (r) => (good ? BA() : (failure as Handler)(r)) });
    const { steps } = renderRecorded("/no/such/page");
    const alert = await screen.findByRole("alert");
    expect(DICT).toContain(alert.textContent);
    await settle();
    expect(where()).toBe("/no/such/page");
    expect(steps().map((s) => s.path)).toEqual(["/no/such/page"]);
    expect(screen.queryByRole("navigation")).toBeNull();
    good = true;
    fireEvent.click(screen.getByRole("button", { name: ru["app.retry"] }));
    await waitFor(() => expect(where()).toBe("/projects"));
    await menu();
  });
});

describe("AC-9 redirects replace the history entry (FR-8)", () => {
  it.each([
    ["BA", "/", "/projects"],
    ["TA", "/", "/admin/users"],
    ["BA", "/no/such/page", "/projects"],
    ["TA", "/no/such/page", "/admin/users"],
  ] as const)("003_ac9_%s_from_%s", async (name, from, target) => {
    installFetch({ ...DATA, [ME]: FX[name] });
    const { steps, back } = renderRecorded(from);
    await waitFor(() => expect(where()).toBe(target));
    await menu();
    expect(steps()[0]).toEqual({ path: from, type: "POP" });
    expect(steps().at(-1)).toEqual({ path: target, type: "REPLACE" });
    expectAllReplace(steps());
    // промежуточного шага "/" нет (для пути "/" это исходная запись, она единственная)
    expect(steps().filter((s) => s.path === "/")).toHaveLength(from === "/" ? 1 : 0);
    // "Назад" не ведёт на исходный путь: в истории осталась одна запись
    await back();
    expect(where()).toBe(target);
  });
});

describe("AC-10, AC-11 after login (FR-4, FR-8)", () => {
  function setupLogin(profile: Handler, user: { role: string | null; must_change_password: boolean }, afterLogin?: Handler) {
    let loggedIn = false;
    const next = afterLogin ?? profile;
    const f = installFetch({
      ...DATA,
      [ME]: (r) => (loggedIn ? next(r) : ANON()),
      [LOGIN]: () => {
        loggedIn = true;
        return j(200, { user: { id: meWith([]).id, login: "ivanov", ...user } });
      },
    });
    return f;
  }

  async function submitLogin(container: HTMLElement) {
    await waitFor(() => field(container, "username"));
    fireEvent.change(field(container, "username"), { target: { value: "ivanov" } });
    fireEvent.change(field(container, "current-password"), { target: { value: "Correct-Horse-Battery-9" } });
    fireEvent.click(submitButton(container));
  }

  it.each([
    ["BA", "business_admin", "/projects"],
    ["U", "user", "/projects"],
    ["TA", "tech_admin", "/admin/users"],
  ] as const)("003_ac10_%s_login_goes_to_start_screen_login_not_in_history_cache_cleared", async (name, role, target) => {
    setupLogin(FX[name], { role, must_change_password: false });
    const { container, qc, steps, back } = renderRecorded("/login");
    await waitFor(() => field(container, "username"));
    qc.setQueryData(["previous-user"], { secret: 1 });
    await submitLogin(container);
    await waitFor(() => expect(where()).toBe(target));
    await menu();
    expect(qc.getQueryData(["previous-user"])).toBeUndefined();
    expectAllReplace(steps());
    await back();
    expect(where()).toBe(target);
  });

  it("003_ac11_login_without_role_goes_to_no_role", async () => {
    setupLogin(NR, { role: null, must_change_password: false });
    const { container } = renderRecorded("/login");
    await submitLogin(container);
    await waitFor(() => expect(where()).toBe("/no-role"));
  });

  it.each([
    ["with_role", "user"],
    ["without_role", null],
  ] as const)("003_ac11_login_with_password_flag_%s_goes_to_change_password", async (_n, role) => {
    setupLogin(PWD, { role, must_change_password: true });
    const { container } = renderRecorded("/login");
    await submitLogin(container);
    await waitFor(() => expect(where()).toBe("/change-password"));
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });
});

describe("AC-12 after the forced password change (FR-5, FR-8)", () => {
  const OLD = "One-Time-Pass-123";
  const NEW = "Brand-New-Passw0rd!";

  it.each([
    ["BA", "/projects"],
    ["U", "/projects"],
    ["TA", "/admin/users"],
    ["NR", "/no-role"],
  ] as const)("003_ac12_%s_profile_reread_after_post_all_replace", async (name, target) => {
    let changed = false;
    const f = installFetch({
      ...DATA,
      [ME]: () => (changed ? FX[name]() : PWD()),
      [PWD_POST]: () => ((changed = true), new Response(null, { status: 204 })),
    });
    const { steps, back } = renderRecorded("/change-password");
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(field(dialog, "current-password"), { target: { value: OLD } });
    fireEvent.change(field(dialog, "new-password", 0), { target: { value: NEW } });
    fireEvent.change(field(dialog, "new-password", 1), { target: { value: NEW } });
    fireEvent.click(within(dialog).getByRole("button", { name: ru["auth.change_password_submit"] }));
    await waitFor(() => expect(where()).toBe(target));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await settle();
    // профиль запрошен повторно после запроса смены пароля
    const keys = f.calls.map((c) => `${c.method} ${new URL(c.url).pathname}`);
    const post = keys.indexOf(PWD_POST);
    expect(post).toBeGreaterThan(-1);
    expect(keys.slice(post + 1)).toContain(ME);
    // все переходы - замены, /change-password не остался в истории
    expect(steps()[0]).toEqual({ path: "/change-password", type: "POP" });
    expect(steps().at(-1)).toEqual({ path: target, type: "REPLACE" });
    expectAllReplace(steps());
    expect(steps().filter((s) => s.path === "/change-password")).toHaveLength(1);
    await back();
    expect(where()).toBe(target);
  });
});

describe("AC-35 only view_audit (AUD)", () => {
  async function expectAuditScreen(f: ReturnType<typeof installFetch>) {
    await h1(ru["admin.audit.title"]);
    expect(where()).toBe("/admin/audit");
    const nav = await menu();
    expect(hrefsOf(nav)).toEqual(["/admin/audit"]);
    expect(screen.getAllByRole("button", { name: ru["auth.logout"] })).toHaveLength(1);
    await settle();
    expect(f.count(USERS)).toBe(0);
    expect(f.count(PROJECTS)).toBe(0);
    expect(f.count(MY_TASKS)).toBe(0);
  }

  it.each(["/", "/no/such/page"])("003_ac35_aud_from_%s_goes_to_audit", async (path) => {
    const f = installFetch({ ...DATA, [ME]: AUD });
    renderRecorded(path);
    await expectAuditScreen(f);
  });

  it("003_ac35_aud_login_goes_to_audit", async () => {
    let loggedIn = false;
    const f = installFetch({
      ...DATA,
      [ME]: () => (loggedIn ? AUD() : ANON()),
      [LOGIN]: () => {
        loggedIn = true;
        return j(200, { user: { id: meWith([]).id, login: "auditor", role: "user", must_change_password: false } });
      },
    });
    const { container } = renderRecorded("/login");
    await waitFor(() => field(container, "username"));
    fireEvent.change(field(container, "username"), { target: { value: "auditor" } });
    fireEvent.change(field(container, "current-password"), { target: { value: "Correct-Horse-Battery-9" } });
    fireEvent.click(submitButton(container));
    await expectAuditScreen(f);
  });
});

describe("AC-36 a role without capabilities (NOCAP)", () => {
  it("003_ac36_nocap_root_goes_to_users_with_forbidden_menu_only_logout_one_request", async () => {
    const f = installFetch({ ...DATA, [ME]: NOCAP });
    renderRecorded("/");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(ru["error.forbidden"]);
    expect(where()).toBe("/admin/users");
    const nav = await menu();
    expect(nav.querySelectorAll("a")).toHaveLength(0);
    expect(screen.getAllByRole("button", { name: ru["auth.logout"] })).toHaveLength(1);
    await settle();
    expect(f.calls).toHaveLength(1);
    expect(f.count(ME)).toBe(1);
  });
});
