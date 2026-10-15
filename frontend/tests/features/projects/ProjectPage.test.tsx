// T82: карточка проекта /projects/:projectId (контракт разметки - в шапке helpers.tsx).
// AC: UF-3, FR-14 (правка), FR-14a (передача владения), FR-15 (добавление), FR-15a (самоисключение),
//     FR-17 (удаление), AC-52, AC-53, AC-54, AC-55, AC-72, AC-73, AC-110, NFR-6, NFR-7.
// Решение по ревью T81 п.1: кандидаты в владельцы - из GET /projects/{id}/members, не из /users.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectPage } from "../../../src/features/projects/ProjectPage";
import { errorMessage, ru } from "../../../src/shared/i18n";
import {
  ADD,
  ADMIN_ID,
  DEL,
  ID_PETROV,
  ID_SIDOROV,
  ID_KUZNETSOV,
  ID_IVANOV,
  M_ME,
  M_KUZNETSOV,
  M_BLOCKED_MIXED,
  M_PETROV,
  M_SIDOROV,
  PERM_SM_MEMBER,
  wraps,
  M_OWNER,
  MEMBERS,
  ONE,
  OWNER,
  PATCH,
  PERM_MEMBER_LEAVE,
  PERM_READ,
  PID,
  REMOVE,
  USERS,
  BUSINESS,
  R_KUZNETSOV,
  action,
  deferred,
  detail,
  err,
  expectAt,
  installFetch,
  j,
  member,
  NO_CONTENT,
  openMembersTab,
  page,
  projectRoutes,
  renderApp,
  where,
  type Handler,
} from "./helpers";

const DICT = Object.values(ru) as string[];
type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;

async function open(
  caps: string[] = BUSINESS,
  over: Record<string, Handler> = {},
  opts: { detail?: Record<string, unknown>; members?: unknown[] } = {},
) {
  f = installFetch(projectRoutes(caps, over, opts));
  const view = renderApp(`/projects/${PID}`);
  await screen.findByRole("heading", { level: 1, name: (opts.detail?.name as string | undefined) ?? "Альфа" });
  return view;
}

const body = async (r: Request) => (await r.clone().json()) as Record<string, unknown>;
const q = <T extends HTMLElement = HTMLElement>(c: ParentNode, sel: string) => c.querySelector<T>(sel);
const editForm = (c: ParentNode) => q<HTMLFormElement>(c, 'form[data-form="edit-project"]');
const ownerSection = (c: ParentNode) => q(c, 'section[data-section="owner"]');
const candidate = (c: ParentNode, id: string) => q(c, `[data-owner-candidate="${id}"]`);
const memberRow = (c: ParentNode, id: string) => q(c, `tr[data-user-id="${id}"]`);
const field = (scope: ParentNode, n: string) => q(scope, `[data-field="${n}"]`);

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => vi.restoreAllMocks());

describe("module (T82)", () => {
  it("project_page_is_exported", () => {
    expect(typeof ProjectPage).toBe("function");
  });
});

describe("card and tabs (UF-3, NFR-7)", () => {
  it("uf3_shows_name_owner_and_description", async () => {
    const { container } = await open();
    expect(field(container, "project-owner")!.textContent).toBe("ivanov");
    expect(field(container, "description")!.textContent).toContain("Описание альфы");
    expect(f.count(ONE)).toBeGreaterThanOrEqual(1);
    for (const c of f.calls) expect(c.headers.get("X-GT-Background")).toBeNull();
  });

  it("uf3_three_tabs_with_dictionary_titles_board_selected_by_default", async () => {
    const { container } = await open();
    const tabs = Array.from(container.querySelectorAll<HTMLElement>('[role="tablist"] [role="tab"]'));
    expect(tabs.map((t) => t.getAttribute("data-tab"))).toEqual(["board", "tasks", "members"]);
    for (const t of tabs) expect(DICT).toContain(t.textContent);
    expect(new Set(tabs.map((t) => t.textContent)).size).toBe(3);
    expect(tabs.map((t) => t.getAttribute("aria-selected"))).toEqual(["true", "false", "false"]);
    const panel = screen.getByRole("tabpanel");
    expect(tabs[0]!.getAttribute("aria-controls")).toBe(panel.id);
    expect(panel.getAttribute("aria-labelledby")).toBe(tabs[0]!.id);
    const h2 = within(panel).getByRole("heading", { level: 2 });
    expect(DICT).toContain(h2.textContent);
  });

  it("uf3_switching_tabs_changes_selected_tab_and_panel_heading", async () => {
    const { container } = await open();
    const first = within(screen.getByRole("tabpanel")).getByRole("heading", { level: 2 }).textContent;
    fireEvent.click(q(container, '[role="tab"][data-tab="tasks"]')!);
    await waitFor(() =>
      expect(q(container, '[role="tab"][data-tab="tasks"]')!.getAttribute("aria-selected")).toBe("true"),
    );
    expect(q(container, '[role="tab"][data-tab="board"]')!.getAttribute("aria-selected")).toBe("false");
    const second = within(screen.getByRole("tabpanel")).getByRole("heading", { level: 2 }).textContent;
    expect(DICT).toContain(second);
    expect(second).not.toBe(first);
  });

  it.each([
    [403, "forbidden"],
    [404, "not_found"],
  ])("uf3_load_error_%s_shows_message_and_no_card", async (status, code) => {
    f = installFetch(projectRoutes(BUSINESS, { [ONE]: () => err(status, code) }));
    const { container } = renderApp(`/projects/${PID}`);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(code));
    expect(editForm(container)).toBeNull();
    expect(container.querySelector('[role="tab"]')).toBeNull();
    expect(container.querySelector("h1")?.textContent ?? "").not.toBe("Альфа");
    expect(where()).toBe(`/projects/${PID}`);
  });
});

describe("edit name and description (AC-110, FR-14c)", () => {
  it("ac110_form_is_prefilled_with_limits_when_manage", async () => {
    const { container } = await open();
    const form = editForm(container)!;
    const name = q<HTMLInputElement>(form, 'input[name="name"]')!;
    expect(name.value).toBe("Альфа");
    expect(name.maxLength).toBe(255);
    expect(q<HTMLTextAreaElement>(form, 'textarea[name="description"]')!.value).toBe("Описание альфы");
    expect(screen.getByLabelText(/./, { selector: 'input[name="name"]' })).toBe(name);
  });

  it("ac110_without_manage_card_is_read_only", async () => {
    const { container } = await open(BUSINESS, {}, { detail: { permissions: PERM_READ } });
    expect(editForm(container)).toBeNull();
    expect(q(container, 'input[name="name"]')).toBeNull();
    expect(q(container, 'button[data-action="delete-project"]')).toBeNull();
    expect(ownerSection(container)).toBeNull();
    expect(field(container, "description")!.textContent).toContain("Описание альфы");
  });

  it("ac110_submit_patches_and_shows_response", async () => {
    const { container } = await open(BUSINESS, {
      [PATCH]: () => j(200, detail({ name: "Альфа 2", description: "Новое" })),
    });
    const form = editForm(container)!;
    fireEvent.change(q(form, 'input[name="name"]')!, { target: { value: "Альфа 2" } });
    fireEvent.change(q(form, 'textarea[name="description"]')!, { target: { value: "Новое" } });
    fireEvent.submit(form);
    await screen.findByRole("heading", { level: 1, name: "Альфа 2" });
    expect(await body(f.last(PATCH))).toMatchObject({ name: "Альфа 2", description: "Новое" });
    expect(field(container, "description")!.textContent).toContain("Новое");
    expect(f.count(PATCH)).toBe(1);
  });

  it.each([
    [422, "validation_error"],
    [400, "bad_request"],
    [403, "forbidden"],
  ])("ac110_patch_error_%s_%s_shown_by_code", async (status, code) => {
    const { container } = await open(BUSINESS, { [PATCH]: () => err(status, code) });
    const form = editForm(container)!;
    fireEvent.change(q(form, 'input[name="name"]')!, { target: { value: "Другое" } });
    fireEvent.submit(form);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(code));
    expect(q<HTMLInputElement>(form, 'input[name="name"]')!.value).toBe("Другое");
  });

  it("ac110_empty_name_is_not_sent", async () => {
    const { container } = await open(BUSINESS, { [PATCH]: () => j(200, detail()) });
    const form = editForm(container)!;
    fireEvent.change(q(form, 'input[name="name"]')!, { target: { value: "  " } });
    fireEvent.submit(form);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("validation_error"));
    expect(f.count(PATCH)).toBe(0);
  });

  it("ac110_double_submit_sends_one_patch", async () => {
    const d = deferred<Response>();
    const { container } = await open(BUSINESS, { [PATCH]: () => d.promise });
    const form = editForm(container)!;
    fireEvent.change(q(form, 'input[name="name"]')!, { target: { value: "Омега" } });
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(f.count(PATCH)).toBe(1));
    await new Promise((r) => setTimeout(r, 50));
    expect(f.count(PATCH)).toBe(1);
    d.resolve(j(200, detail({ name: "Омега" })));
    await screen.findByRole("heading", { level: 1, name: "Омега" });
  });
});

describe("delete project with confirmation (FR-14c, NFR-7)", () => {
  it("fr14c_delete_opens_alertdialog_with_focus_inside_and_sends_nothing", async () => {
    const { container } = await open();
    const opener = action(container, "delete-project");
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(f.count(DEL)).toBe(0);
  });

  it("fr14c_escape_cancels_without_request_and_returns_focus", async () => {
    const { container } = await open();
    const opener = action(container, "delete-project");
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(DEL)).toBe(0);
    expect(document.activeElement).toBe(opener);
    expect(where()).toBe(`/projects/${PID}`);
  });

  it("fr14c_confirm_deletes_and_goes_to_projects", async () => {
    const { container } = await open(BUSINESS, {
      [DEL]: NO_CONTENT,
      "GET /api/v1/projects": () => j(200, page([])),
    });
    fireEvent.click(action(container, "delete-project"));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    await expectAt("/projects");
    expect(f.count(DEL)).toBe(1);
  });

  it("fr14c_delete_error_is_shown_and_user_stays", async () => {
    const { container } = await open(BUSINESS, { [DEL]: () => err(403, "forbidden") });
    fireEvent.click(action(container, "delete-project"));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    const alert = await screen.findByRole("alert", {}, { timeout: 2000 });
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(where()).toBe(`/projects/${PID}`);
  });
});

const OWN_MEMBERS = [M_OWNER, M_ME, M_PETROV, M_SIDOROV, M_KUZNETSOV, M_BLOCKED_MIXED];
const ID_BLOCKED = "99999999-9999-4999-8999-999999999999";

describe("transfer ownership from members (FR-14a, AC-52, AC-72, review T81 p.1)", () => {
  it("ac52_candidates_are_unblocked_business_admins_and_mixed_from_members_not_users", async () => {
    const { container } = await open(BUSINESS, {}, { members: OWN_MEMBERS });
    await waitFor(() => expect(candidate(container, ID_KUZNETSOV)).toBeTruthy());
    const sec = ownerSection(container)!;
    expect(candidate(sec, ADMIN_ID)).toBeTruthy(); // mixed
    expect(candidate(sec, ID_IVANOV)).toBeNull(); // текущий владелец
    expect(candidate(sec, ID_PETROV)).toBeNull(); // user и заблокирован
    expect(candidate(sec, ID_SIDOROV)).toBeNull(); // без роли
    expect(candidate(sec, ID_BLOCKED)).toBeNull(); // mixed, но заблокирован
    expect(f.count(MEMBERS)).toBeGreaterThanOrEqual(1);
    expect(f.count(USERS)).toBe(0);
  });

  it("ac52_user_role_member_is_not_a_candidate", async () => {
    const plainUser = member({ id: ID_PETROV, login: "petrov" }, { role: "user" });
    const { container } = await open(BUSINESS, {}, { members: [M_OWNER, M_KUZNETSOV, plainUser] });
    await waitFor(() => expect(candidate(container, ID_KUZNETSOV)).toBeTruthy());
    expect(candidate(container, ID_PETROV)).toBeNull();
  });

  it("ac52_search_filters_candidates_on_client_without_requests", async () => {
    const { container } = await open(BUSINESS, {}, { members: OWN_MEMBERS });
    await waitFor(() => expect(candidate(container, ID_KUZNETSOV)).toBeTruthy());
    const before = f.calls.length;
    const search = q<HTMLInputElement>(ownerSection(container)!, 'input[name="owner_search"]')!;
    expect(search.type).toBe("search");
    expect(screen.getByLabelText(/./, { selector: 'input[name="owner_search"]' })).toBe(search);
    fireEvent.change(search, { target: { value: "KUZN" } });
    expect(candidate(container, ID_KUZNETSOV)).toBeTruthy();
    expect(candidate(container, ADMIN_ID)).toBeNull();
    await new Promise((r) => setTimeout(r, 450));
    expect(f.calls.length).toBe(before);
  });

  it("ac52_candidates_include_members_from_all_pages", async () => {
    const { container } = await open(BUSINESS, {
      [MEMBERS]: (r) => {
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return p === 1
          ? j(200, page([M_OWNER, M_ME], 1, true, 100))
          : j(200, page([M_KUZNETSOV], 2, false, 100));
      },
    });
    await waitFor(() => expect(candidate(container, ID_KUZNETSOV)).toBeTruthy());
    expect(candidate(container, ADMIN_ID)).toBeTruthy();
    const pages = f.calls
      .filter((c) => c.method === "GET" && new URL(c.url).pathname === `/api/v1/projects/${PID}/members`)
      .map((c) => new URL(c.url).searchParams.get("page"));
    expect(pages).toContain("1");
    expect(pages).toContain("2");
    for (const c of f.calls.filter((x) => new URL(x.url).pathname.endsWith("/members"))) {
      expect(new URL(c.url).searchParams.get("page_size")).toBe("100");
    }
  });

  it("ac52_click_puts_owner_updates_card_from_response_and_keeps_focus", async () => {
    const after = detail({
      owner: R_KUZNETSOV,
      permissions: { manage: false, manage_members: false, create_task: true, remove_self: true },
    });
    const { container } = await open(BUSINESS, { [OWNER]: () => j(200, after) }, { members: OWN_MEMBERS });
    await waitFor(() => expect(candidate(container, ID_KUZNETSOV)).toBeTruthy());
    const btn = action(candidate(container, ID_KUZNETSOV)!, "transfer-owner");
    btn.focus();
    fireEvent.click(btn);
    await waitFor(() => expect(field(container, "project-owner")!.textContent).toBe("kuznetsov"));
    expect(await body(f.last(OWNER))).toEqual({ user_id: ID_KUZNETSOV });
    expect(f.count(OWNER)).toBe(1);
    // права из ответа: управление пропало
    await waitFor(() => expect(ownerSection(container)).toBeNull());
    expect(editForm(container)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    // фокус не потерян (кнопка исчезла из DOM)
    expect(document.activeElement).not.toBe(document.body);
  });

  it("ac52_owner_error_forbidden_is_shown_by_code_and_owner_unchanged", async () => {
    const { container } = await open(BUSINESS, { [OWNER]: () => err(403, "forbidden") }, { members: OWN_MEMBERS });
    await waitFor(() => expect(candidate(container, ID_KUZNETSOV)).toBeTruthy());
    fireEvent.click(action(candidate(container, ID_KUZNETSOV)!, "transfer-owner"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(field(container, "project-owner")!.textContent).toBe("ivanov");
  });

  it("ac52_no_owner_section_without_manage", async () => {
    const { container } = await open(BUSINESS, {}, { detail: { permissions: PERM_MEMBER_LEAVE } });
    expect(ownerSection(container)).toBeNull();
    expect(q(container, '[data-action="transfer-owner"]')).toBeNull();
  });

  it("ac52_candidates_list_wraps_long_logins", async () => {
    const { container } = await open(BUSINESS, {}, { members: OWN_MEMBERS });
    await waitFor(() => expect(candidate(container, ID_KUZNETSOV)).toBeTruthy());
    const list = q(ownerSection(container)!, ".ui-list")!;
    expect(list).toBeTruthy();
    expect(wraps(list)).toBe(true);
  });
});

describe("members tab (AC-53, AC-73, FR-15, FR-15a)", () => {
  it("ac73_lists_members_with_role_owner_and_blocked_flags", async () => {
    const { container } = await open();
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    const rows = container.querySelectorAll("tr[data-user-id]");
    expect(rows.length).toBe(4);
    const owner = memberRow(container, ID_IVANOV)!;
    const blocked = memberRow(container, ID_PETROV)!;
    const norole = memberRow(container, ID_SIDOROV)!;
    expect(field(owner, "login")!.textContent).toBe("ivanov");
    for (const r of [owner, blocked, norole]) expect(DICT).toContain(field(r, "role")!.textContent);
    expect(field(owner, "role")!.textContent).not.toBe(field(blocked, "role")!.textContent);
    expect(field(blocked, "role")!.textContent).not.toBe(field(norole, "role")!.textContent);
    expect(DICT).toContain(field(owner, "owner")!.textContent);
    expect(field(blocked, "owner")!.textContent).toBe("");
    expect(DICT).toContain(field(blocked, "blocked")!.textContent);
    expect(field(owner, "blocked")!.textContent).toBe("");
    const h2 = within(screen.getByRole("tabpanel")).getByRole("heading", { level: 2 });
    expect(DICT).toContain(h2.textContent);
  });

  it("ac73_add_via_directory_picker_posts_user_id_and_reloads_members", async () => {
    const { container } = await open(BUSINESS, {
      [USERS]: () => j(200, page([{ id: ID_KUZNETSOV, login: "kuznetsov", role: "user" }, { id: ID_PETROV, login: "petrov", role: "user" }])),
      [ADD]: NO_CONTENT,
    });
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "kuz" } });
    const opts = await screen.findAllByRole("option");
    // справочник без allowedIds: показан и не участник, и уже участник (решает сервер)
    expect(opts.length).toBe(2);
    expect(f.query(f.last(USERS)).get("q")).toBe("kuz");
    const before = f.count(MEMBERS);
    fireEvent.click(opts[0]!);
    await waitFor(() => expect(f.count(ADD)).toBe(1));
    expect(await body(f.last(ADD))).toEqual({ user_id: ID_KUZNETSOV });
    await waitFor(() => expect(f.count(MEMBERS)).toBeGreaterThan(before));
  });

  it("ac73_adding_existing_member_creates_no_duplicates", async () => {
    const { container } = await open(BUSINESS, {
      [USERS]: () => j(200, page([{ id: ID_PETROV, login: "petrov", role: "user" }])),
      [ADD]: NO_CONTENT,
    });
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "pet" } });
    fireEvent.click((await screen.findAllByRole("option"))[0]!);
    await waitFor(() => expect(f.count(ADD)).toBe(1));
    await waitFor(() => expect(f.count(MEMBERS)).toBeGreaterThanOrEqual(2));
    expect(container.querySelectorAll(`tr[data-user-id="${ID_PETROV}"]`).length).toBe(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([
    [422, "recipient_wrong_role"],
    [422, "user_blocked"],
    [403, "forbidden"],
  ])("ac73_add_error_%s_%s_is_shown_by_code", async (status, code) => {
    await open(BUSINESS, {
      [USERS]: () => j(200, page([{ id: ID_KUZNETSOV, login: "kuznetsov", role: "user" }])),
      [ADD]: () => err(status, code),
    });
    await openMembersTab();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "kuz" } });
    fireEvent.click((await screen.findAllByRole("option"))[0]!);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(code));
    expect(DICT).toContain(alert.textContent);
  });

  it("fr15_without_manage_members_no_picker_and_no_remove_buttons", async () => {
    const { container } = await open(BUSINESS, {}, { detail: { permissions: PERM_READ } });
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(q(container, 'button[data-action="remove-member"]')).toBeNull();
    expect(q(container, 'button[data-action="leave-project"]')).toBeNull();
  });

  it("ac73_remove_member_sends_delete_and_reloads", async () => {
    const { container } = await open(BUSINESS, { [REMOVE(ID_PETROV)]: NO_CONTENT });
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    const before = f.count(MEMBERS);
    fireEvent.click(action(memberRow(container, ID_PETROV)!, "remove-member"));
    await waitFor(() => expect(f.count(REMOVE(ID_PETROV))).toBe(1));
    await waitFor(() => expect(f.count(MEMBERS)).toBeGreaterThan(before));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ac53_owner_cannot_be_removed_code_is_shown", async () => {
    const { container } = await open(BUSINESS, {
      [REMOVE(ID_IVANOV)]: () => err(422, "owner_cannot_be_removed"),
    });
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_IVANOV)).toBeTruthy());
    fireEvent.click(action(memberRow(container, ID_IVANOV)!, "remove-member"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("owner_cannot_be_removed"));
  });

  it("fr15a_leave_project_requires_confirmation_then_deletes_self", async () => {
    const { container } = await open(BUSINESS, {
      [REMOVE(ADMIN_ID)]: NO_CONTENT,
      "GET /api/v1/projects": () => j(200, page([])),
    }, { detail: { permissions: PERM_MEMBER_LEAVE, owner: { id: ID_IVANOV, login: "ivanov" } } });
    await openMembersTab();
    const leave = action(container, "leave-project");
    leave.focus();
    fireEvent.click(leave);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(f.count(REMOVE(ADMIN_ID))).toBe(0);
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(REMOVE(ADMIN_ID))).toBe(0);
    fireEvent.click(leave);
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    await expectAt("/projects");
    expect(f.count(REMOVE(ADMIN_ID))).toBe(1);
  });

  it("fr15a_leave_button_absent_without_remove_self", async () => {
    const { container } = await open();
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    expect(q(container, 'button[data-action="leave-project"]')).toBeNull();
  });

  it("nfr7_exactly_one_alert_after_an_error_and_no_unlabelled_controls", async () => {
    const { container } = await open(BUSINESS, {
      [REMOVE(ID_PETROV)]: () => err(403, "forbidden"),
      [REMOVE(ID_SIDOROV)]: () => err(403, "forbidden"),
    });
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    expect(screen.queryAllByRole("alert").length).toBe(0);
    for (const el of container.querySelectorAll<HTMLElement>("input, textarea, select")) {
      expect((el as HTMLInputElement).labels?.length ?? 0, el.outerHTML).toBeGreaterThan(0);
    }
    for (const b of container.querySelectorAll<HTMLButtonElement>("button")) {
      expect((b.textContent ?? "").trim() !== "" || b.hasAttribute("aria-label"), b.outerHTML).toBe(true);
    }
    fireEvent.click(action(memberRow(container, ID_PETROV)!, "remove-member"));
    await screen.findByRole("alert");
    fireEvent.click(action(memberRow(container, ID_SIDOROV)!, "remove-member"));
    await waitFor(() => expect(f.count(REMOVE(ID_SIDOROV))).toBe(1));
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.getAllByRole("alert").length).toBe(1);
  });
});

describe("review T82 attempt 2", () => {
  it("fr15a_remove_button_in_own_row_asks_confirmation", async () => {
    const { container } = await open(BUSINESS, { [REMOVE(ADMIN_ID)]: NO_CONTENT, "GET /api/v1/projects": () => j(200, page([])) }, {
      detail: { permissions: PERM_SM_MEMBER },
    });
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ADMIN_ID)).toBeTruthy());
    fireEvent.click(action(memberRow(container, ADMIN_ID)!, "remove-member"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(f.count(REMOVE(ADMIN_ID))).toBe(0);
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(REMOVE(ADMIN_ID))).toBe(0);
    fireEvent.click(action(memberRow(container, ADMIN_ID)!, "remove-member"));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    await expectAt("/projects");
    expect(f.count(REMOVE(ADMIN_ID))).toBe(1);
    expect(document.activeElement).not.toBe(document.body);
  });

  it("fr15a_remove_button_in_foreign_row_has_no_dialog", async () => {
    const { container } = await open(BUSINESS, { [REMOVE(ID_PETROV)]: NO_CONTENT }, {
      detail: { permissions: PERM_SM_MEMBER },
    });
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    fireEvent.click(action(memberRow(container, ID_PETROV)!, "remove-member"));
    await waitFor(() => expect(f.count(REMOVE(ID_PETROV))).toBe(1));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("fr15a_adding_self_shows_leave_button_without_reload_and_removal_refreshes_card", async () => {
    let joined = false;
    const { container } = await open(
      BUSINESS,
      {
        [ONE]: () => j(200, detail({ permissions: joined ? PERM_SM_MEMBER : { ...PERM_SM_MEMBER, remove_self: false }, is_member: joined })),
        [USERS]: () => j(200, page([{ id: ADMIN_ID, login: "admin", role: "mixed" }])),
        [ADD]: () => {
          joined = true;
          return NO_CONTENT();
        },
        [REMOVE(ID_PETROV)]: NO_CONTENT,
      },
      { detail: { permissions: PERM_SM_MEMBER } },
    );
    await openMembersTab();
    expect(q(container, 'button[data-action="leave-project"]')).toBeNull();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "adm" } });
    fireEvent.click((await screen.findAllByRole("option"))[0]!);
    await waitFor(() => expect(q(container, 'button[data-action="leave-project"]')).toBeTruthy());
    expect(document.activeElement).not.toBe(document.body);
    // удаление другого участника тоже перечитывает карточку
    const before = f.count(ONE);
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    fireEvent.click(action(memberRow(container, ID_PETROV)!, "remove-member"));
    await waitFor(() => expect(f.count(ONE)).toBeGreaterThan(before));
  });

  it("nfr7_picker_is_not_disabled_while_adding_but_marked_busy_and_focus_stays", async () => {
    const d = deferred<Response>();
    await open(BUSINESS, {
      [USERS]: () => j(200, page([{ id: ID_KUZNETSOV, login: "kuznetsov", role: "user" }])),
      [ADD]: () => d.promise,
    });
    await openMembersTab();
    const input = screen.getByRole("combobox") as HTMLInputElement;
    input.focus();
    fireEvent.change(input, { target: { value: "kuz" } });
    fireEvent.click((await screen.findAllByRole("option"))[0]!);
    await waitFor(() => expect(f.count(ADD)).toBe(1));
    expect(input.disabled).toBe(false);
    expect(input.getAttribute("aria-busy")).toBe("true");
    expect(document.activeElement).toBe(input);
    d.resolve(NO_CONTENT());
    await waitFor(() => expect(input.getAttribute("aria-busy")).not.toBe("true"));
    expect(document.activeElement).not.toBe(document.body);
  });

  it("uf3_invalid_uuid_422_is_shown_as_not_found", async () => {
    f = installFetch({
      ...projectRoutes(BUSINESS),
      "GET /api/v1/projects/not-a-uuid": () => err(422, "validation_error"),
      "GET /api/v1/projects/not-a-uuid/members": () => err(422, "validation_error"),
    });
    renderApp("/projects/not-a-uuid");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("not_found"));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getAllByRole("alert").length).toBe(1);
  });

  it("nfr7_picker_search_error_does_not_add_second_alert", async () => {
    const { container } = await open(BUSINESS, {
      [USERS]: () => err(500, "internal_error"),
      [REMOVE(ID_PETROV)]: () => err(403, "forbidden"),
    });
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    fireEvent.click(action(memberRow(container, ID_PETROV)!, "remove-member"));
    await screen.findByRole("alert");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "pet" } });
    await waitFor(() => expect(container.textContent).toContain(errorMessage("internal_error")));
    expect(screen.getAllByRole("alert").length).toBe(1);
  });

  it("nfr6_long_unbroken_name_wraps_h1_description_and_member_cells", async () => {
    const long = "Я".repeat(200);
    const { container } = await open(BUSINESS, {}, { detail: { name: long } });
    expect(wraps(q(container, "h1")!)).toBe(true);
    await openMembersTab();
    await waitFor(() => expect(memberRow(container, ID_PETROV)).toBeTruthy());
    expect(wraps(field(memberRow(container, ID_PETROV)!, "login")!)).toBe(true);
  });

  it("nfr7_tabs_roving_tabindex_and_arrow_home_end_keys", async () => {
    const { container } = await open();
    const tab = (n: string) => q<HTMLElement>(container, `[role="tab"][data-tab="${n}"]`)!;
    const idx = () => ["board", "tasks", "members"].map((n) => tab(n).getAttribute("tabindex"));
    expect(idx()).toEqual(["0", "-1", "-1"]);
    tab("board").focus();
    fireEvent.keyDown(tab("board"), { key: "ArrowRight" });
    await waitFor(() => expect(tab("tasks").getAttribute("aria-selected")).toBe("true"));
    expect(document.activeElement).toBe(tab("tasks"));
    expect(idx()).toEqual(["-1", "0", "-1"]);
    fireEvent.keyDown(tab("tasks"), { key: "End" });
    await waitFor(() => expect(tab("members").getAttribute("aria-selected")).toBe("true"));
    expect(document.activeElement).toBe(tab("members"));
    fireEvent.keyDown(tab("members"), { key: "ArrowRight" });
    await waitFor(() => expect(tab("board").getAttribute("aria-selected")).toBe("true"));
    fireEvent.keyDown(tab("board"), { key: "ArrowLeft" });
    await waitFor(() => expect(tab("members").getAttribute("aria-selected")).toBe("true"));
    fireEvent.keyDown(tab("members"), { key: "Home" });
    await waitFor(() => expect(tab("board").getAttribute("aria-selected")).toBe("true"));
    expect(document.activeElement).toBe(tab("board"));
    expect(idx()).toEqual(["0", "-1", "-1"]);
  });

  it("nfr7_placeholder_tabpanel_without_focusable_content_is_focusable", async () => {
    await open();
    const panel = screen.getByRole("tabpanel");
    expect(panel.querySelector("a, button, input, select, textarea, [tabindex]")).toBeNull();
    expect(panel.tabIndex).toBe(0);
  });

  it("nfr7_members_are_requested_with_page_size_100", async () => {
    await open();
    await waitFor(() => expect(f.count(MEMBERS)).toBeGreaterThanOrEqual(1));
    expect(f.query(f.last(MEMBERS)).get("page_size")).toBe("100");
  });
});
