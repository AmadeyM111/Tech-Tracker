// T24: журнал аудита /admin/audit (контракт разметки - в шапке helpers.tsx).
// AC: FR-41 (только метаданные, BR-2), FR-47 (постранично), FR-59, NFR-6, NFR-7, AC-64/65.
// Фильтры - только те, что есть в схеме API (GET /admin/audit): entity_type и actor_id;
// фильтров по периоду и действию в API нет, клиентские фильтры страницы не вводятся.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuditPage } from "../../../src/features/admin/AuditPage";
import { errorMessage, ru } from "../../../src/shared/i18n";
import {
  ADMIN_ID,
  CAPS_ALL,
  ID_IVANOV,
  action,
  cell,
  err,
  expectAt,
  installFetch,
  j,
  meWith,
  page,
  renderApp,
  where,
  type Handler,
} from "./helpers";

const DICT = Object.values(ru) as string[];
const AUDIT = "GET /api/v1/admin/audit";
const ME = "GET /api/v1/me";
const USERS_ROUTE: Record<string, Handler> = { "GET /api/v1/admin/users": () => j(200, page([])) };
const SECRET = "SECRET-TITLE-VALUE";

const E_USER = {
  id: 7,
  occurred_at: "2026-10-13T09:00:00Z",
  actor: { kind: "user", id: ADMIN_ID, login: "admin" },
  action: "user.role_set",
  entity_type: "user",
  entity_id: ID_IVANOV,
  entity_deleted: false,
  changed_fields: ["role"],
  details: { old_role: null, new_role: "user" },
};
const E_DEAL = {
  id: 6,
  occurred_at: "2026-10-12T21:30:00Z",
  actor: { kind: "system", id: null, login: null },
  action: "deal.updated",
  entity_type: "deal",
  entity_id: "44444444-4444-4444-8444-444444444444",
  entity_deleted: true,
  changed_fields: ["title", "amount_kopecks"],
  details: null,
  // защитная проверка BR-2: такого поля в схеме нет, но экран не должен его показывать
  changes: { title: SECRET },
};

type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;

function setup(over: Record<string, Handler> = {}, caps: string[] = CAPS_ALL) {
  f = installFetch({
    [ME]: () => j(200, meWith(caps)),
    [AUDIT]: () => j(200, page([E_USER, E_DEAL])),
    ...over,
  });
}

async function open(over: Record<string, Handler> = {}, caps: string[] = CAPS_ALL) {
  setup(over, caps);
  const view = renderApp("/admin/audit");
  await waitFor(() => expect(view.container.querySelector("tr[data-entry-id]")).toBeTruthy());
  return view;
}

const entry = (c: HTMLElement, id: number) => {
  const el = c.querySelector<HTMLElement>(`tr[data-entry-id="${id}"]`);
  if (!el) throw new Error(`no entry ${id}`);
  return el;
};

function filterForm(c: HTMLElement) {
  const actor = c.querySelector<HTMLInputElement>('input[name="actor_id"]');
  const type = c.querySelector<HTMLSelectElement>('select[name="entity_type"]');
  if (!actor || !type) throw new Error("no filter controls");
  const submit = actor.form?.querySelector<HTMLButtonElement>('button[type="submit"]');
  if (!submit) throw new Error("no filter submit");
  return { actor, type, submit };
}

describe("module (T24)", () => {
  it("audit_page_is_exported", () => {
    expect(typeof AuditPage).toBe("function");
  });
});

describe("audit list (FR-41)", () => {
  it("shows_metadata_columns_with_readable_dates_and_dictionary_texts", async () => {
    const { container } = await open();
    const u = entry(container, 7);
    expect(cell(u, "actor").textContent).toBe("admin");
    expect(cell(u, "action").textContent).toContain("user.role_set");
    expect(cell(u, "entity_id").textContent).toContain(ID_IVANOV);
    expect(cell(u, "changed_fields").textContent).toContain("role");
    expect(DICT).toContain(cell(u, "entity_type").textContent);
    // читаемая дата: не сырой ISO; локальная дата 13.10.2026 при любом часовом поясе
    const when = cell(u, "occurred_at").textContent ?? "";
    expect(when).not.toContain("2026-10-13T");
    expect(when).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
    expect(when).toMatch(/13\.10\.2026/);
    expect(f.query(f.last(AUDIT)).get("page")).toBe("1");
  });

  it("system_actor_is_dictionary_text_not_null_or_empty", async () => {
    const { container } = await open();
    const text = cell(entry(container, 6), "actor").textContent;
    expect(text).toBeTruthy();
    expect(DICT).toContain(text);
    expect(text).not.toMatch(/null|undefined/);
    const fields = cell(entry(container, 6), "changed_fields").textContent ?? "";
    expect(fields).toContain("title");
    expect(fields).toContain("amount_kopecks");
  });

  it("bt2_values_of_business_fields_are_never_rendered", async () => {
    const { container } = await open();
    expect(container.textContent).not.toContain(SECRET);
    expect(container.innerHTML).not.toContain(SECRET);
  });

  it("empty_journal_shows_dictionary_text_not_blank_table", async () => {
    setup({ [AUDIT]: () => j(200, page([])) });
    const { container } = renderApp("/admin/audit");
    await waitFor(() => expect(container.querySelector("form")).toBeTruthy());
    await waitFor(() => expect(container.querySelector('[role="status"]')).toBeTruthy());
    expect(DICT).toContain(container.querySelector('[role="status"]')?.textContent);
    expect(container.querySelector("tr[data-entry-id]")).toBeNull();
  });

  it("api_error_is_shown_via_error_message", async () => {
    setup({ [AUDIT]: () => err(500, "internal_error") });
    renderApp("/admin/audit");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("internal_error"));
  });

  it("fr59_user_requests_carry_no_background_header_and_page_is_not_mutating", async () => {
    const { container } = await open({
      [AUDIT]: (r) => {
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return j(200, page([E_USER], p, p === 1));
      },
    });
    fireEvent.click(action(container, "next-page"));
    await waitFor(() => expect(f.count(AUDIT)).toBe(2));
    for (const c of f.calls) expect(c.headers.get("X-GT-Background")).toBeNull();
    expect(f.calls.every((c) => c.method === "GET")).toBe(true);
  });
});

describe("pagination (FR-47)", () => {
  it("next_prev_buttons_follow_has_next_and_request_page", async () => {
    const { container } = await open({
      [AUDIT]: (r) => {
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return j(200, page([p === 1 ? E_USER : E_DEAL], p, p === 1));
      },
    });
    expect(action(container, "prev-page").disabled).toBe(true);
    expect(action(container, "next-page").disabled).toBe(false);
    fireEvent.click(action(container, "next-page"));
    await waitFor(() => expect(container.querySelector('tr[data-entry-id="6"]')).toBeTruthy());
    expect(f.query(f.last(AUDIT)).get("page")).toBe("2");
    expect(action(container, "next-page").disabled).toBe(true);
    expect(action(container, "prev-page").disabled).toBe(false);
  });
});

describe("filters (entity_type, actor_id)", () => {
  it("entity_type_select_has_all_types_with_dictionary_labels", async () => {
    const { container } = await open();
    const { type } = filterForm(container);
    expect(Array.from(type.options).map((o) => o.value).sort()).toEqual(
      ["", "attachment", "comment", "deal", "project", "stage", "task", "user"],
    );
    for (const o of Array.from(type.options)) expect(DICT).toContain(o.textContent);
    expect(type.labels?.length).toBeGreaterThan(0);
  });

  it("apply_sends_filters_and_resets_page_to_first", async () => {
    const { container } = await open({
      [AUDIT]: (r) => {
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return j(200, page([E_USER], p, p === 1));
      },
    });
    fireEvent.click(action(container, "next-page"));
    await waitFor(() => expect(f.query(f.last(AUDIT)).get("page")).toBe("2"));
    const { actor, type, submit } = filterForm(container);
    fireEvent.change(type, { target: { value: "deal" } });
    fireEvent.change(actor, { target: { value: ` ${ADMIN_ID} ` } });
    fireEvent.click(submit);
    await waitFor(() => expect(f.query(f.last(AUDIT)).get("entity_type")).toBe("deal"));
    const q = f.query(f.last(AUDIT));
    expect(q.get("actor_id")).toBe(ADMIN_ID);
    expect(q.get("page")).toBe("1");
  });

  it("empty_filters_are_not_sent_and_reset_clears_them", async () => {
    const { container } = await open();
    const first = f.query(f.last(AUDIT));
    expect(first.has("entity_type")).toBe(false);
    expect(first.has("actor_id")).toBe(false);
    const { actor, type, submit } = filterForm(container);
    fireEvent.change(type, { target: { value: "task" } });
    fireEvent.click(submit);
    await waitFor(() => expect(f.query(f.last(AUDIT)).get("entity_type")).toBe("task"));
    fireEvent.change(actor, { target: { value: ADMIN_ID } });
    fireEvent.click(action(container, "reset-filters"));
    await waitFor(() => expect(f.query(f.last(AUDIT)).has("entity_type")).toBe(false));
    expect(f.query(f.last(AUDIT)).has("actor_id")).toBe(false);
    expect(filterForm(container).type.value).toBe("");
    expect(filterForm(container).actor.value).toBe("");
  });

  it("validation_422_for_bad_actor_id_is_shown_via_error_message_and_focused", async () => {
    const { container } = await open({
      [AUDIT]: (r) =>
        new URL(r.url).searchParams.has("actor_id") ? err(422, "validation_error") : j(200, page([E_USER])),
    });
    const { actor, submit } = filterForm(container);
    fireEvent.change(actor, { target: { value: "not-a-uuid" } });
    fireEvent.click(submit);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("validation_error"));
    await waitFor(() => expect(document.activeElement).toBe(alert));
  });

  it("nfr7_filter_controls_have_labels_and_audit_has_no_data_changing_buttons", async () => {
    const { container } = await open();
    const { actor, type, submit } = filterForm(container);
    for (const el of [actor, type]) {
      expect(DICT).toContain(el.labels?.[0]?.textContent);
    }
    expect(submit.textContent?.trim() || submit.getAttribute("aria-label")).toBeTruthy();
    expect(container.querySelector('button[data-action="block"], button[data-action="set-role"]')).toBeNull();
  });
});

describe("access and navigation (FR-41, FR-42, T23 note 1)", () => {
  it("without_view_audit_shows_forbidden_alert_and_makes_no_audit_requests", async () => {
    setup({}, ["manage_accounts", "assign_roles"]);
    const { container } = renderApp("/admin/audit");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(where()).toBe("/admin/audit");
    expect(container.querySelector("table, tr, form")).toBeNull();
    expect(f.count(AUDIT)).toBe(0);
  });

  it.each([
    ["401_to_login", () => err(401, "not_authenticated"), "/login"],
    ["password_change_required", () => err(403, "password_change_required"), "/change-password"],
    ["no_role", () => err(403, "no_role"), "/no-role"],
  ])("guard_%s", async (_n, me, target) => {
    setup({ [ME]: me });
    renderApp("/admin/audit");
    await expectAt(target);
    expect(f.count(AUDIT)).toBe(0);
  });

  it("guard_redirects_even_when_navigation_callback_already_fired", async () => {
    setup({ [ME]: () => err(401, "not_authenticated") });
    const first = renderApp("/admin/audit");
    await expectAt("/login");
    first.unmount();
    renderApp("/admin/audit");
    await expectAt("/login");
    expect(f.count(AUDIT)).toBe(0);
  });

  // Бывший home_links_follow_capabilities (003/AC-20, AC-36): "/" -> стартовый экран ТА, ссылки по возможностям;
  // пустые возможности -> отказ на /admin/users без ссылок /admin*.
  it("003_ac20_ac36_start_screen_links_follow_capabilities", async () => {
    setup(USERS_ROUTE, ["manage_accounts", "view_audit"]);
    const first = renderApp("/");
    await expectAt("/admin/users");
    await waitFor(() => expect(document.querySelector('a[href="/admin/users"]')).toBeTruthy());
    expect(document.querySelector('a[href="/admin/audit"]')).toBeTruthy();
    for (const a of Array.from(document.querySelectorAll("a"))) {
      expect(DICT).toContain(a.textContent);
    }
    first.unmount();

    setup(USERS_ROUTE, []);
    renderApp("/");
    await expectAt("/admin/users");
    expect((await screen.findByRole("alert")).textContent).toBe(errorMessage("forbidden"));
    expect(document.querySelector('a[href^="/admin"]')).toBeNull();
  });

  // Бывший home_shows_only_audit_link_with_only_view_audit (003/AC-35): AUD -> /admin/audit, в меню только журнал.
  it("003_ac35_only_view_audit_start_screen_has_only_audit_link", async () => {
    setup({}, ["view_audit"]);
    renderApp("/");
    await expectAt("/admin/audit");
    await waitFor(() => expect(document.querySelector('a[href="/admin/audit"]')).toBeTruthy());
    expect(document.querySelector('a[href="/admin/users"]')).toBeNull();
    expect(f.count("GET /api/v1/admin/users")).toBe(0);
  });
});

describe("action texts, roles, timezone (review T24 attempt 2)", () => {
  const CODES = [
    "user.created",
    "user.blocked",
    "user.unblocked",
    "user.password_reset",
    "user.sessions_revoked",
    "user.role_assigned",
    "user.role_changed",
    "user.role_removed",
  ];
  const ACTION_TEXTS = Object.entries(ru)
    .filter(([k]) => k.startsWith("admin.audit.action."))
    .map(([, v]) => v as string);
  const mk = (id: number, code: string, details: Record<string, string | null> | null = null) => ({
    ...E_USER,
    id,
    action: code,
    details,
  });

  it("dictionary_has_texts_for_all_r1_actions", () => {
    expect(ACTION_TEXTS.length).toBeGreaterThanOrEqual(CODES.length);
    expect(new Set(ACTION_TEXTS).size).toBe(ACTION_TEXTS.length);
  });

  it("known_actions_show_dictionary_text_and_unknown_shows_raw_code", async () => {
    const items = CODES.map((c, i) => mk(100 + i, c, c === "user.role_changed" ? { role_from: "user", role_to: "mixed" } : null));
    items.push(mk(200, "user.mystery_action"));
    const { container } = await open({ [AUDIT]: () => j(200, page(items)) });
    const shown = CODES.map((c, i) => {
      const text = cell(entry(container, 100 + i), "action").textContent ?? "";
      expect(text, c).not.toBe(c);
      expect(text, c).not.toContain(c);
      expect(ACTION_TEXTS, c).toContain(text);
      return text;
    });
    expect(new Set(shown).size).toBe(CODES.length);
    expect(cell(entry(container, 200), "action").textContent).toBe("user.mystery_action");
  });

  it("002_fr20_historical_mixed_shows_mixed_role_name_not_code", async () => {
    const items = [
      mk(401, "user.role_assigned", { role_from: null, role_to: "mixed" }),
      mk(402, "user.role_changed", { role_from: "user", role_to: "mixed" }),
      mk(403, "user.role_removed", { role_from: "mixed", role_to: null }),
    ];
    const { container } = await open({ [AUDIT]: () => j(200, page(items)) });
    for (const id of [401, 402, 403]) {
      const t = entry(container, id).textContent ?? "";
      expect(t, String(id)).toContain(ru["admin.role.mixed"]);
      expect(t, String(id)).not.toMatch(/mixed/i);
    }
    expect(entry(container, 402).textContent).toContain(ru["admin.role.user"]);
  });

  it("role_events_show_role_names_from_dictionary", async () => {
    const items = [
      mk(301, "user.role_assigned", { role_from: null, role_to: "tech_admin" }),
      mk(302, "user.role_changed", { role_from: "user", role_to: "business_admin" }),
      mk(303, "user.role_removed", { role_from: "mixed", role_to: null }),
    ];
    const { container } = await open({ [AUDIT]: () => j(200, page(items)) });
    const text = (id: number) => entry(container, id).textContent ?? "";
    expect(text(301)).toContain(ru["admin.role.tech_admin"]);
    expect(text(302)).toContain(ru["admin.role.user"]);
    expect(text(302)).toContain(ru["admin.role.business_admin"]);
    expect(text(303)).toContain(ru["admin.role.mixed"]);
    for (const id of [301, 302, 303]) {
      expect(text(id)).not.toMatch(/tech_admin|business_admin|role_from|role_to/);
    }
  });

  it("project_ownership_transfer_shows_text_not_raw_code_or_owner_id", async () => {
    const transfer = {
      id: 400,
      occurred_at: "2026-10-13T09:00:00Z",
      actor: { kind: "user", id: ADMIN_ID, login: "demo.ba1" },
      action: "project.ownership_transferred",
      entity_type: "project",
      entity_id: "55555555-5555-4555-8555-555555555555",
      entity_deleted: false,
      changed_fields: ["owner_id"],
      details: null,
    };
    const { container } = await open({ [AUDIT]: () => j(200, page([transfer])) });
    const row = entry(container, 400);
    expect(cell(row, "action").textContent).toBe("Передано владение проектом");
    expect(cell(row, "action").textContent).toBe(ru["admin.audit.action.project.ownership_transferred"]);
    expect(row.textContent).not.toMatch(/ownership_transferred|owner_id|[{}]/);
    expect(cell(row, "changed_fields").textContent).toBe("Владелец проекта");
    expect(cell(row, "details").textContent).toBe("");
    expect(DICT).toContain(cell(row, "entity_type").textContent);
  });

  it("nfr5_time_is_europe_moscow_not_utc", async () => {
    const { container } = await open();
    // 2026-10-12T21:30:00Z -> 13.10.2026 00:30 MSK (UTC+3)
    expect(cell(entry(container, 6), "occurred_at").textContent).toBe("13.10.2026, 00:30");
  });
});

describe("sidebar on admin screens (003/AC-20, AC-16)", () => {
  it.each(["/admin/audit", "/admin/users"])("%s_has_ta_menu_and_logout_and_no_link_to_home", async (path) => {
    setup({
      "GET /api/v1/admin/users": () => j(200, page([])),
    });
    const { container } = renderApp(path);
    await waitFor(() => expect(container.querySelector("form")).toBeTruthy());
    const nav = screen.getByRole("navigation", { name: ru["app.menu_label"] });
    const hrefs = Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/admin/users", "/admin/audit"]);
    for (const a of Array.from(nav.querySelectorAll("a"))) expect(DICT).toContain(a.textContent);
    const logout = screen.getAllByRole("button", { name: ru["auth.logout"] });
    expect(logout).toHaveLength(1);
    expect((logout[0] as HTMLButtonElement).type).toBe("button");
    expect(container.querySelector('a[href="/"]')).toBeNull();
  });
});

describe("start screen: logout and no password-change link (FR-55, FR-60; T103: only forced change)", () => {
  const LOGOUT = "POST /api/v1/auth/logout";

  // Бывший home_has_typed_logout_button_... (003/AC-22, AC-20): "/" -> /admin/users; на экране есть кнопки
  // UsersPage, поэтому «Выйти» ищется внутри .ui-sidebar: ровно одна, type=button, выход, кэш очищен.
  it("003_ac22_start_screen_has_typed_logout_button_that_logs_out_clears_cache_and_goes_to_login", async () => {
    let out = false;
    setup({
      ...USERS_ROUTE,
      [ME]: () => (out ? err(401, "not_authenticated") : j(200, meWith(CAPS_ALL))),
      [LOGOUT]: () => ((out = true), new Response(null, { status: 204 })),
    });
    const { container, qc } = renderApp("/");
    await expectAt("/admin/users");
    await screen.findByRole("main");
    await waitFor(() => expect(container.querySelector('a[href="/admin/audit"]')).toBeTruthy());
    qc.setQueryData(["sentinel"], 1);
    const sidebar = container.querySelector<HTMLElement>(".ui-sidebar");
    expect(sidebar).not.toBeNull();
    const btns = Array.from(sidebar!.querySelectorAll<HTMLButtonElement>("button"));
    expect(btns.length).toBe(1);
    const btn = btns[0] as HTMLButtonElement;
    expect(btn.type).toBe("button");
    expect(btn.textContent).toBe(ru["auth.logout"]);
    fireEvent.click(btn);
    await expectAt("/login");
    expect(f.count(LOGOUT)).toBe(1);
    expect(qc.getQueryData(["sentinel"])).toBeUndefined();
  });

  // Бывший t103_home_has_no_change_password_link (003/AC-26): на стартовых экранах ТА и без возможностей.
  it.each([
    ["TA", CAPS_ALL],
    ["NOCAP", [] as string[]],
  ])("003_ac26_t103_%s_start_screen_has_no_change_password_link", async (_n, caps) => {
    setup(USERS_ROUTE, caps);
    const { container } = renderApp("/");
    await expectAt("/admin/users");
    await screen.findByRole("main");
    await waitFor(() => expect(container.querySelector(".ui-sidebar")).toBeTruthy());
    expect(container.querySelector('a[href="/change-password"]')).toBeNull();
    expect(screen.queryByRole("link", { name: /Сменить пароль/ })).toBeNull();
  });
});
