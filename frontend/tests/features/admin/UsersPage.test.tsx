// T24: экран учётных записей /admin/users (контракт разметки - в шапке helpers.tsx).
// AC: UF-2, FR-4, FR-5, FR-12, FR-42, FR-55, FR-57, FR-59, FR-62, FR-65, FR-69, FR-73, NFR-6, NFR-7.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UsersPage } from "../../../src/features/admin/UsersPage";
import { PASSWORD_MIN_LENGTH, errorMessage, ru } from "../../../src/shared/i18n";
import {
  CAPS_ALL,
  ID_IVANOV,
  ID_PETROV,
  NO_CONTENT,
  U_ADMIN,
  U_IVANOV,
  U_PETROV,
  action,
  cell,
  deferred,
  err,
  expectAt,
  spyMathRandomFromApp,
  installFetch,
  j,
  meWith,
  page,
  renderApp,
  row,
  where,
  type Handler,
} from "./helpers";

const DICT = Object.values(ru) as string[];
const LIST = "GET /api/v1/admin/users";
const ME = "GET /api/v1/me";
const CREATE = "POST /api/v1/admin/users";
const url = (id: string, tail: string) => `/api/v1/admin/users/${id}/${tail}`;

type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;

function setup(over: Record<string, Handler> = {}, caps: string[] = CAPS_ALL) {
  const routes: Record<string, Handler> = {
    [ME]: () => j(200, meWith(caps)),
    [LIST]: () => j(200, page([U_ADMIN, U_IVANOV, U_PETROV])),
    ...over,
  };
  f = installFetch(routes);
}

async function open(over: Record<string, Handler> = {}, caps: string[] = CAPS_ALL) {
  setup(over, caps);
  const view = renderApp("/admin/users");
  await waitFor(() =>
    expect(view.container.querySelector(`tr[data-user-id="${ID_IVANOV}"]`)).toBeTruthy(),
  );
  return view;
}

function loginInput(c: HTMLElement): HTMLInputElement {
  const el = c.querySelector<HTMLInputElement>('input[name="login"]');
  if (!el) throw new Error("no input[name=login]");
  return el;
}

function createButton(c: HTMLElement): HTMLButtonElement {
  const btn = loginInput(c).form?.querySelector<HTMLButtonElement>('button[type="submit"]');
  if (!btn) throw new Error("create form has no submit button");
  return btn;
}

function submitCreate(c: HTMLElement, login: string) {
  fireEvent.change(loginInput(c), { target: { value: login } });
  fireEvent.click(createButton(c));
}

function shownPassword(): string | null {
  return document.querySelector('[data-role="one-time-password"]')?.textContent ?? null;
}

async function sentPassword(r: Request): Promise<string> {
  const body = (await r.clone().json()) as { one_time_password: string };
  return body.one_time_password;
}

function fillBytes(seed: number) {
  return vi
    .spyOn(globalThis.crypto, "getRandomValues")
    .mockImplementation(((arr: ArrayBufferView) => {
      const u = new Uint8Array(arr.buffer, arr.byteOffset, arr.byteLength);
      for (let i = 0; i < u.length; i += 1) u[i] = (i * 13 + seed) % 200;
      return arr;
    }) as unknown as typeof crypto.getRandomValues);
}

const created = { ...U_IVANOV, id: "33333333-3333-4333-8333-333333333333", login: "sidorov" };

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => vi.restoreAllMocks());

describe("module (T24)", () => {
  it("users_page_is_exported", () => {
    expect(typeof UsersPage).toBe("function");
  });
});

describe("list and pagination (UF-2)", () => {
  it("lists_users_with_login_role_and_status_from_dictionary", async () => {
    const { container } = await open();
    const iv = row(container, ID_IVANOV);
    const pe = row(container, ID_PETROV);
    expect(cell(iv, "login").textContent).toBe("ivanov");
    expect(cell(pe, "login").textContent).toBe("petrov");
    for (const r of [iv, pe, row(container, U_ADMIN.id)]) {
      expect(DICT).toContain(cell(r, "role").textContent);
      expect(DICT).toContain(cell(r, "status").textContent);
    }
    // роль не назначена и назначена выглядят по-разному, активна и заблокирована - тоже
    expect(cell(iv, "role").textContent).not.toBe(cell(pe, "role").textContent);
    expect(cell(iv, "status").textContent).not.toBe(cell(pe, "status").textContent);
    expect(f.query(f.last(LIST)).get("page")).toBe("1");
  });

  it("pagination_next_and_prev_request_pages_and_respect_has_next", async () => {
    const { container } = await open({
      [LIST]: (r) => {
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return j(200, page([p === 1 ? U_IVANOV : U_PETROV], p, p === 1));
      },
    });
    expect(action(container, "prev-page").disabled).toBe(true);
    expect(action(container, "next-page").disabled).toBe(false);
    fireEvent.click(action(container, "next-page"));
    await waitFor(() =>
      expect(container.querySelector(`tr[data-user-id="${ID_PETROV}"]`)).toBeTruthy(),
    );
    expect(f.query(f.last(LIST)).get("page")).toBe("2");
    expect(action(container, "next-page").disabled).toBe(true);
    expect(action(container, "prev-page").disabled).toBe(false);
    fireEvent.click(action(container, "prev-page"));
    await waitFor(() =>
      expect(container.querySelector(`tr[data-user-id="${ID_IVANOV}"]`)).toBeTruthy(),
    );
    expect(f.query(f.last(LIST)).get("page")).toBe("1");
  });

  it("list_error_is_shown_via_error_message_in_alert", async () => {
    setup({ [LIST]: () => err(500, "internal_error") });
    const { container } = renderApp("/admin/users");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("internal_error"));
    expect(container.querySelector("tr[data-user-id]")).toBeNull();
  });

  it("fr59_user_requests_never_carry_background_header", async () => {
    const { container } = await open({ [`POST ${url(ID_IVANOV, "block")}`]: NO_CONTENT });
    fireEvent.click(action(row(container, ID_IVANOV), "block"));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    await waitFor(() => expect(f.count(LIST)).toBeGreaterThanOrEqual(2));
    for (const c of f.calls) expect(c.headers.get("X-GT-Background")).toBeNull();
  });
});

describe("access: capabilities and session guard (FR-42, T23 note 1)", () => {
  it("without_manage_accounts_shows_forbidden_alert_and_makes_no_admin_requests", async () => {
    setup({}, ["view_audit"]);
    const { container } = renderApp("/admin/users");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(where()).toBe("/admin/users");
    expect(container.querySelector("table, tr, form")).toBeNull();
    expect(f.count(LIST)).toBe(0);
  });

  it("without_assign_roles_role_controls_are_absent_but_block_remains", async () => {
    const { container } = await open({}, ["manage_accounts"]);
    const r = row(container, ID_IVANOV);
    expect(r.querySelector('select[name="role"]')).toBeNull();
    expect(r.querySelector('button[data-action="set-role"]')).toBeNull();
    expect(action(r, "block")).toBeTruthy();
  });

  it.each([
    ["401_to_login", () => err(401, "not_authenticated"), "/login"],
    ["password_change_required", () => err(403, "password_change_required"), "/change-password"],
    ["no_role", () => err(403, "no_role"), "/no-role"],
  ])("guard_%s", async (_n, me, target) => {
    setup({ [ME]: me });
    renderApp("/admin/users");
    await expectAt(target);
    expect(f.count(LIST)).toBe(0);
  });

  it("guard_redirects_even_when_navigation_callback_already_fired", async () => {
    // Повторный вход на маршрут после «Назад» с /login: колбэк клиента уже сработал
    // (не взводится обратно без успешного ответа), решает guard по ошибке me.
    setup({ [ME]: () => err(401, "not_authenticated") });
    const first = renderApp("/admin/users");
    await expectAt("/login");
    first.unmount();
    renderApp("/admin/users");
    await expectAt("/login");
    expect(f.count(LIST)).toBe(0);
  });
});

describe("create user (FR-4, FR-55, FR-65, FR-73, OI-108)", () => {
  it("fr73_login_field_has_label_and_format_hint_from_dictionary", async () => {
    const { container } = await open();
    const input = loginInput(container);
    expect(input.getAttribute("autocomplete")).toBe("username");
    expect(input.labels?.length).toBeGreaterThan(0);
    expect(DICT).toContain(input.labels?.[0]?.textContent);
    const hintId = input.getAttribute("aria-describedby");
    expect(hintId).toBeTruthy();
    const hint = document.getElementById(hintId ?? "");
    expect(hint?.textContent?.trim()).toBeTruthy();
    expect(DICT).toContain(hint?.textContent);
  });

  it("t98_fr73a_login_hint_says_shown_as_entered_and_case_ignored_on_login", async () => {
    const { container } = await open();
    const hint = document.getElementById(loginInput(container).getAttribute("aria-describedby") ?? "");
    expect(hint?.textContent).toBe(ru["admin.users.login_hint"]);
    expect(hint?.textContent).toContain("показывается так, как введён");
    expect(hint?.textContent).toContain("регистр не учитывается");
    expect(hint?.textContent).not.toMatch(/\. Регистр не учитывается$/);
  });

  it("fr4_create_without_role_sends_login_and_client_generated_password_only", async () => {
    const spy = fillBytes(3);
    const { container } = await open({ [CREATE]: () => j(201, created) });
    const mathSpy = spyMathRandomFromApp();
    submitCreate(container, "sidorov");
    await waitFor(() => expect(f.count(CREATE)).toBe(1));
    const req = f.last(CREATE);
    expect(new URL(req.url).search).toBe("");
    const body = (await req.clone().json()) as Record<string, string>;
    expect(Object.keys(body).sort()).toEqual(["login", "one_time_password"]);
    expect(body["login"]).toBe("sidorov");
    expect(body["one_time_password"]?.length).toBeGreaterThanOrEqual(PASSWORD_MIN_LENGTH);
    expect(body["one_time_password"]).toMatch(/^\S+$/);
    expect(spy).toHaveBeenCalled();
    expect(mathSpy.appCalls).toEqual([]);
    // роль - отдельное действие: само создание ничего не назначает
    await waitFor(() => expect(shownPassword()).not.toBeNull());
    expect(f.calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("password_is_derived_from_get_random_values_not_a_constant", async () => {
    const pw: string[] = [];
    for (const seed of [3, 11]) {
      const spy = fillBytes(seed);
      const { container, unmount } = await open({ [CREATE]: () => j(201, created) });
      submitCreate(container, "sidorov");
      await waitFor(() => expect(f.count(CREATE)).toBe(1));
      pw.push(await sentPassword(f.last(CREATE)));
      expect(spy).toHaveBeenCalled();
      unmount();
      spy.mockRestore();
    }
    expect(pw[0]).not.toBe(pw[1]);
    for (const p of pw) expect(p.length).toBeGreaterThanOrEqual(PASSWORD_MIN_LENGTH);
  });

  it("password_is_shown_once_equal_to_sent_and_gone_after_close", async () => {
    const { container, qc } = await open({ [CREATE]: () => j(201, created) });
    const listBefore = f.count(LIST);
    submitCreate(container, "sidorov");
    await waitFor(() => expect(shownPassword()).not.toBeNull());
    const sent = await sentPassword(f.last(CREATE));
    expect(shownPassword()).toBe(sent);
    // список перечитан пользовательским (не фоновым) запросом
    await waitFor(() => expect(f.count(LIST)).toBeGreaterThan(listBefore));
    expect(f.last(LIST).headers.get("X-GT-Background")).toBeNull();
    // пароль не лежит в кэше запросов и в адресе
    expect(JSON.stringify(qc.getQueryCache().getAll().map((q) => q.state.data))).not.toContain(sent);
    expect(where()).not.toContain(sent);

    fireEvent.click(action(document.body, "close-password"));
    await waitFor(() => expect(shownPassword()).toBeNull());
    expect(document.body.textContent).not.toContain(sent);
    expect(container.innerHTML).not.toContain(sent);
  });

  it("fr57_password_never_reaches_url_console_or_web_storage", async () => {
    const logs = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    const { container } = await open({ [CREATE]: () => j(201, created) });
    submitCreate(container, "sidorov");
    await waitFor(() => expect(shownPassword()).not.toBeNull());
    const sent = await sentPassword(f.last(CREATE));
    for (const c of f.calls) expect(c.url).not.toContain(sent);
    for (const l of logs) expect(JSON.stringify(l.mock.calls)).not.toContain(sent);
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(sent);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(sent);
    expect(window.location.href).not.toContain(sent);
  });

  it("login_is_trimmed_before_sending", async () => {
    const { container } = await open({ [CREATE]: () => j(201, created) });
    submitCreate(container, "  sidorov  ");
    await waitFor(() => expect(f.count(CREATE)).toBe(1));
    const body = (await f.last(CREATE).clone().json()) as { login: string };
    expect(body.login).toBe("sidorov");
  });

  it("empty_login_sends_nothing_and_focuses_alert", async () => {
    const { container } = await open({ [CREATE]: () => j(201, created) });
    submitCreate(container, "   ");
    const alert = await screen.findByRole("alert");
    expect(DICT).toContain(alert.textContent);
    await waitFor(() => expect(document.activeElement).toBe(alert));
    expect(f.count(CREATE)).toBe(0);
    expect(shownPassword()).toBeNull();
  });

  it("server_error_login_taken_is_shown_via_error_message_without_password_panel", async () => {
    const { container } = await open({ [CREATE]: () => err(422, "login_taken") });
    submitCreate(container, "ivanov");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("login_taken"));
    await waitFor(() => expect(document.activeElement).toBe(alert));
    expect(shownPassword()).toBeNull();
  });

  it("double_submit_while_request_in_flight_sends_one_post", async () => {
    const d = deferred<Response>();
    const { container } = await open({ [CREATE]: () => d.promise });
    fireEvent.change(loginInput(container), { target: { value: "sidorov" } });
    const btn = createButton(container);
    fireEvent.click(btn);
    fireEvent.click(btn);
    const form = loginInput(container).form;
    if (form) fireEvent.submit(form);
    await waitFor(() => expect(f.count(CREATE)).toBe(1));
    d.resolve(j(201, created));
    await waitFor(() => expect(shownPassword()).not.toBeNull());
    expect(f.count(CREATE)).toBe(1);
  });
});

describe("block, unblock, sessions (FR-5, FR-62, UF-2)", () => {
  it("block_requires_confirmation_and_cancel_sends_nothing", async () => {
    const { container } = await open({ [`POST ${url(ID_IVANOV, "block")}`]: NO_CONTENT });
    fireEvent.click(action(row(container, ID_IVANOV), "block"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("ivanov");
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    fireEvent.click(action(dialog, "cancel"));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(`POST ${url(ID_IVANOV, "block")}`)).toBe(0);
  });

  it("escape_closes_confirmation_without_request_keyboard_nfr7", async () => {
    const { container } = await open({ [`POST ${url(ID_IVANOV, "block")}`]: NO_CONTENT });
    fireEvent.click(action(row(container, ID_IVANOV), "block"));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(`POST ${url(ID_IVANOV, "block")}`)).toBe(0);
  });

  it("block_confirm_posts_and_reloads_list_with_new_status", async () => {
    let blocked = false;
    const { container } = await open({
      [LIST]: () => j(200, page([{ ...U_IVANOV, is_blocked: blocked }])),
      [`POST ${url(ID_IVANOV, "block")}`]: () => ((blocked = true), NO_CONTENT()),
    });
    const before = cell(row(container, ID_IVANOV), "status").textContent;
    fireEvent.click(action(row(container, ID_IVANOV), "block"));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    await waitFor(() => expect(f.count(`POST ${url(ID_IVANOV, "block")}`)).toBe(1));
    await waitFor(() =>
      expect(cell(row(container, ID_IVANOV), "status").textContent).not.toBe(before),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(action(row(container, ID_IVANOV), "unblock")).toBeTruthy();
  });

  it("confirm_double_click_sends_one_request", async () => {
    const d = deferred<Response>();
    const { container } = await open({ [`POST ${url(ID_IVANOV, "block")}`]: () => d.promise });
    fireEvent.click(action(row(container, ID_IVANOV), "block"));
    const confirm = action(await screen.findByRole("alertdialog"), "confirm");
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(f.count(`POST ${url(ID_IVANOV, "block")}`)).toBe(1));
    d.resolve(NO_CONTENT());
    await waitFor(() => expect(f.count(LIST)).toBeGreaterThanOrEqual(2));
    expect(f.count(`POST ${url(ID_IVANOV, "block")}`)).toBe(1);
  });

  it("unblock_needs_no_confirmation", async () => {
    const { container } = await open({ [`POST ${url(ID_PETROV, "unblock")}`]: NO_CONTENT });
    fireEvent.click(action(row(container, ID_PETROV), "unblock"));
    await waitFor(() => expect(f.count(`POST ${url(ID_PETROV, "unblock")}`)).toBe(1));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("fr62_revoke_sessions_confirm_posts_and_shows_no_password", async () => {
    const path = `POST ${url(ID_PETROV, "revoke-sessions")}`;
    const { container } = await open({ [path]: NO_CONTENT });
    fireEvent.click(action(row(container, ID_PETROV), "revoke-sessions"));
    const dialog = await screen.findByRole("alertdialog");
    expect(f.count(path)).toBe(0);
    fireEvent.click(action(dialog, "confirm"));
    await waitFor(() => expect(f.count(path)).toBe(1));
    expect(shownPassword()).toBeNull();
  });

  it("fr69_block_last_account_admin_422_is_shown_via_error_message", async () => {
    const { container } = await open({
      [`POST ${url(U_ADMIN.id, "block")}`]: () => err(422, "last_account_admin"),
    });
    fireEvent.click(action(row(container, U_ADMIN.id), "block"));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("last_account_admin"));
    await waitFor(() => expect(document.activeElement).toBe(alert));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});

describe("reset password (FR-65, OI-108)", () => {
  it("reset_requires_confirmation_then_posts_client_password_shown_once", async () => {
    const spy = fillBytes(7);
    const path = `POST ${url(ID_PETROV, "reset-password")}`;
    const { container } = await open({ [path]: NO_CONTENT });
    const mathSpy = spyMathRandomFromApp();
    fireEvent.click(action(row(container, ID_PETROV), "reset-password"));
    const dialog = await screen.findByRole("alertdialog");
    expect(f.count(path)).toBe(0);
    fireEvent.click(action(dialog, "confirm"));
    await waitFor(() => expect(f.count(path)).toBe(1));
    const body = (await f.last(path).clone().json()) as Record<string, string>;
    expect(Object.keys(body)).toEqual(["one_time_password"]);
    const pw = body["one_time_password"] ?? "";
    expect(pw.length).toBeGreaterThanOrEqual(PASSWORD_MIN_LENGTH);
    expect(spy).toHaveBeenCalled();
    expect(mathSpy.appCalls).toEqual([]);
    await waitFor(() => expect(shownPassword()).toBe(pw));
    fireEvent.click(action(document.body, "close-password"));
    await waitFor(() => expect(shownPassword()).toBeNull());
    expect(document.body.textContent).not.toContain(pw);
  });

  it("reset_failure_shows_error_and_no_password", async () => {
    const path = `POST ${url(ID_PETROV, "reset-password")}`;
    const { container } = await open({ [path]: () => err(422, "password_too_common") });
    fireEvent.click(action(row(container, ID_PETROV), "reset-password"));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("password_too_common"));
    expect(shownPassword()).toBeNull();
  });
});

describe("roles as a separate action (FR-4, FR-12, FR-66, FR-69)", () => {
  function roleSelect(c: HTMLElement, id: string): HTMLSelectElement {
    const el = row(c, id).querySelector<HTMLSelectElement>('select[name="role"]');
    if (!el) throw new Error("no role select");
    return el;
  }

  it("role_select_has_accessible_name_and_all_options", async () => {
    const { container } = await open();
    const sel = roleSelect(container, ID_IVANOV);
    expect(sel.getAttribute("aria-label") ?? sel.labels?.[0]?.textContent).toBeTruthy();
    expect(
      Array.from(sel.options)
        .map((o) => o.value)
        .sort(),
    ).toEqual(["", "business_admin", "mixed", "tech_admin", "user"]);
    for (const o of Array.from(sel.options)) expect(DICT).toContain(o.textContent);
    expect(sel.value).toBe("");
    expect(roleSelect(container, ID_PETROV).value).toBe("user");
  });

  it("assign_role_puts_role_without_confirmation_and_reloads", async () => {
    const path = `PUT ${url(ID_IVANOV, "role")}`;
    const { container } = await open({ [path]: () => j(200, { ...U_IVANOV, role: "user" }) });
    fireEvent.change(roleSelect(container, ID_IVANOV), { target: { value: "user" } });
    fireEvent.click(action(row(container, ID_IVANOV), "set-role"));
    await waitFor(() => expect(f.count(path)).toBe(1));
    expect(await f.last(path).clone().json()).toEqual({ role: "user" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(f.count(LIST)).toBeGreaterThanOrEqual(2));
  });

  it("change_role_puts_new_role", async () => {
    const path = `PUT ${url(ID_PETROV, "role")}`;
    const { container } = await open({ [path]: () => j(200, { ...U_PETROV, role: "mixed" }) });
    fireEvent.change(roleSelect(container, ID_PETROV), { target: { value: "mixed" } });
    fireEvent.click(action(row(container, ID_PETROV), "set-role"));
    await waitFor(() => expect(f.count(path)).toBe(1));
    expect(await f.last(path).clone().json()).toEqual({ role: "mixed" });
  });

  it("remove_role_requires_confirmation_then_puts_null", async () => {
    const path = `PUT ${url(ID_PETROV, "role")}`;
    const { container } = await open({ [path]: () => j(200, { ...U_PETROV, role: null }) });
    fireEvent.change(roleSelect(container, ID_PETROV), { target: { value: "" } });
    fireEvent.click(action(row(container, ID_PETROV), "set-role"));
    const dialog = await screen.findByRole("alertdialog");
    expect(f.count(path)).toBe(0);
    fireEvent.click(action(dialog, "confirm"));
    await waitFor(() => expect(f.count(path)).toBe(1));
    expect(await f.last(path).clone().json()).toEqual({ role: null });
  });

  it("fr69_last_admin_role_change_422_shows_error_and_keeps_row", async () => {
    const path = `PUT ${url(U_ADMIN.id, "role")}`;
    const { container } = await open({ [path]: () => err(422, "last_account_admin") });
    fireEvent.change(roleSelect(container, U_ADMIN.id), { target: { value: "user" } });
    fireEvent.click(action(row(container, U_ADMIN.id), "set-role"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("last_account_admin"));
    expect(within(row(container, U_ADMIN.id)).getByText("admin")).toBeTruthy();
  });
});

describe("accessibility (NFR-7)", () => {
  it("every_control_has_an_accessible_name_and_buttons_are_typed", async () => {
    const { container } = await open();
    for (const el of Array.from(container.querySelectorAll("input, select"))) {
      const named =
        (el as HTMLInputElement).labels?.length ||
        el.getAttribute("aria-label") ||
        el.getAttribute("aria-labelledby");
      expect(named, el.outerHTML).toBeTruthy();
    }
    for (const b of Array.from(container.querySelectorAll<HTMLButtonElement>("button"))) {
      expect(b.textContent?.trim() || b.getAttribute("aria-label"), b.outerHTML).toBeTruthy();
      expect(["button", "submit"]).toContain(b.type);
    }
    // единственная submit-кнопка страницы - создание учётной записи
    expect(container.querySelectorAll('button[type="submit"]').length).toBe(1);
  });
});

describe("confirm dialog focus (NFR-7, review T24 attempt 2)", () => {
  function focusables(dialog: HTMLElement): HTMLElement[] {
    return Array.from(dialog.querySelectorAll<HTMLElement>("button, input, select, [tabindex]")).filter(
      (el) => !(el as HTMLButtonElement).disabled && el.getAttribute("tabindex") !== "-1",
    );
  }

  it("tab_cycles_inside_dialog_forward_and_backward", async () => {
    const { container } = await open();
    fireEvent.click(action(row(container, ID_IVANOV), "block"));
    const dialog = await screen.findByRole("alertdialog");
    const items = focusables(dialog);
    expect(items.length).toBeGreaterThanOrEqual(2);
    const first = items[0] as HTMLElement;
    const last = items[items.length - 1] as HTMLElement;
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    first.focus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("cancel_returns_focus_to_the_opener_button", async () => {
    const { container } = await open();
    const opener = action(row(container, ID_IVANOV), "block");
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(action(await screen.findByRole("alertdialog"), "cancel"));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it("escape_returns_focus_to_the_opener_button", async () => {
    const { container } = await open();
    const opener = action(row(container, ID_IVANOV), "reset-password");
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it("after_successful_action_focus_stays_in_row_or_table_not_on_body", async () => {
    let blocked = false;
    const { container } = await open({
      [LIST]: () => j(200, page([U_ADMIN, { ...U_IVANOV, is_blocked: blocked }, U_PETROV])),
      [`POST ${url(ID_IVANOV, "block")}`]: () => ((blocked = true), NO_CONTENT()),
    });
    const opener = action(row(container, ID_IVANOV), "block");
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    await waitFor(() => expect(action(row(container, ID_IVANOV), "unblock")).toBeTruthy());
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    await waitFor(() => {
      const active = document.activeElement;
      expect(active).not.toBe(document.body);
      const table = container.querySelector("table");
      expect(active && table?.contains(active)).toBe(true);
    });
  });
});

describe("password panel login and stale rows (review T24 attempt 2)", () => {
  it("panel_shows_server_normalized_login_not_the_typed_one", async () => {
    const reply = { ...U_IVANOV, id: "44444444-4444-4444-8444-444444444444", login: "probe.user1" };
    const { container } = await open({ [CREATE]: () => j(201, reply) });
    submitCreate(container, " Probe.User1 ");
    await waitFor(() => expect(shownPassword()).not.toBeNull());
    const body = (await f.last(CREATE).clone().json()) as { login: string };
    expect(body.login).toBe("Probe.User1");
    const pw = document.querySelector('[data-role="one-time-password"]') as HTMLElement;
    const close = action(document.body, "close-password");
    let panel: HTMLElement | null = pw;
    while (panel && !panel.contains(close)) panel = panel.parentElement;
    expect(panel).toBeTruthy();
    expect(panel?.textContent).toContain("probe.user1");
    expect(panel?.textContent).not.toContain("Probe.User1");
  });

  it("row_buttons_stay_disabled_until_list_reload_completes", async () => {
    const reload = deferred<Response>();
    let blocked = false;
    let calls = 0;
    const { container } = await open({
      [LIST]: () => {
        calls += 1;
        if (calls === 1) return j(200, page([U_ADMIN, U_IVANOV, U_PETROV]));
        return reload.promise;
      },
      [`POST ${url(ID_IVANOV, "block")}`]: () => ((blocked = true), NO_CONTENT()),
    });
    fireEvent.click(action(row(container, ID_IVANOV), "block"));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    await waitFor(() => expect(f.count(`POST ${url(ID_IVANOV, "block")}`)).toBe(1));
    await waitFor(() => expect(f.count(LIST)).toBe(2));
    expect(blocked).toBe(true);
    const r = row(container, ID_IVANOV);
    const controls = Array.from(r.querySelectorAll<HTMLButtonElement | HTMLSelectElement>("button, select"));
    expect(controls.length).toBeGreaterThan(0);
    for (const c of controls) expect(c.disabled, c.outerHTML).toBe(true);
    reload.resolve(j(200, page([U_ADMIN, { ...U_IVANOV, is_blocked: true }, U_PETROV])));
    await waitFor(() => expect(action(row(container, ID_IVANOV), "unblock").disabled).toBe(false));
  });
});
