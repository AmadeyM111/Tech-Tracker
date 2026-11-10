// 019/R8-T21: accounts without a role on /unassigned-accounts (AC-30, FR-13a; AC-26 for the business admin).
// Plan §4.7: table with login and names only (no email), ConfirmDialog before the role is assigned,
// list reload after the assignment, empty list message, Pagination.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { errorMessage, ru, t } from "../../../src/shared/i18n";
import {
  CAPS_ALL,
  ID_IVANOV,
  ID_PETROV,
  NO_CONTENT,
  action,
  cell,
  err,
  installFetch,
  j,
  meWith,
  page,
  renderApp,
  row,
  where,
  type Handler,
} from "./helpers";

const ME = "GET /api/v1/me";
const LIST = "GET /api/v1/unassigned-accounts";
const assignKey = (id: string) => `PUT /api/v1/unassigned-accounts/${id}/role`;
// The business admin holds onboard_accounts (ADR-0019, RG-11); the other roles do not.
const BA_CAPS = ["business_access", "project_create", "task_assign_others", "onboard_accounts"];

// Self-registered account: names come from the registration form.
const SELF_REGISTERED = {
  id: ID_IVANOV,
  login: "ivanov",
  first_name: "Ivan",
  last_name: "Ivanov",
  created_at: "2026-11-01T09:00:00Z",
};
// Account created by a tech admin without a name in the response.
const CREATED_BY_TA = {
  id: ID_PETROV,
  login: "petrov",
  first_name: null,
  last_name: "Petrova",
  created_at: "2026-11-02T09:00:00Z",
};

type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;

function setup(over: Record<string, Handler> = {}, caps: string[] = BA_CAPS, role = "business_admin") {
  f = installFetch({
    [ME]: () => j(200, meWith(caps, role)),
    [LIST]: () => j(200, page([SELF_REGISTERED, CREATED_BY_TA])),
    ...over,
  });
}

async function open(over: Record<string, Handler> = {}) {
  setup(over);
  const view = renderApp("/unassigned-accounts");
  await waitFor(() => expect(view.container.querySelector(`tr[data-user-id="${ID_IVANOV}"]`)).toBeTruthy());
  return view;
}

async function sentBody(r: Request): Promise<unknown> {
  return r.clone().json();
}

describe("019 AC-30 list of accounts without a role", () => {
  it("019_ac30_list_shows_login_and_names_from_unassigned_endpoint", async () => {
    const { container } = await open();
    expect(f.count(LIST)).toBe(1);
    expect(f.query(f.last(LIST)).get("page")).toBe("1");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(ru["accounts.unassigned_title"]);
    const self = row(container, ID_IVANOV);
    expect(cell(self, "login").textContent).toBe("ivanov");
    expect(cell(self, "first_name").textContent).toBe("Ivan");
    expect(cell(self, "last_name").textContent).toBe("Ivanov");
    const byTa = row(container, ID_PETROV);
    expect(cell(byTa, "login").textContent).toBe("petrov");
    expect(cell(byTa, "first_name").textContent).toBe(ru["admin.users.name_missing"]);
  });

  it("019_ac30_table_has_no_email_column_and_never_renders_an_email", async () => {
    // The server must not send email (NFR-1); even if it did, the page must not render it.
    await open({
      [LIST]: () => j(200, page([{ ...SELF_REGISTERED, email: "ivanov@example.test" }])),
    });
    const table = screen.getByRole("table");
    expect(within(table).queryByText(ru["admin.users.email_column"])).toBeNull();
    expect(table.querySelector('[data-field="email"]')).toBeNull();
    expect(document.body.textContent).not.toContain("ivanov@example.test");
  });

  it("019_ac30_empty_list_shows_message_and_no_table", async () => {
    setup({ [LIST]: () => j(200, page([])) });
    renderApp("/unassigned-accounts");
    expect(await screen.findByText(ru["accounts.unassigned_empty"])).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("019_ac30_pagination_next_requests_page_two_and_next_is_disabled_on_last_page", async () => {
    setup({
      [LIST]: (r) => {
        const p = Number(new URL(r.url).searchParams.get("page") ?? "1");
        return j(200, page([p === 1 ? SELF_REGISTERED : CREATED_BY_TA], p, p === 1));
      },
    });
    const { container } = renderApp("/unassigned-accounts");
    await waitFor(() => row(container, ID_IVANOV));
    expect(action(container, "prev-page").disabled).toBe(true);
    expect(action(container, "next-page").disabled).toBe(false);
    fireEvent.click(action(container, "next-page"));
    await waitFor(() => row(container, ID_PETROV));
    expect(f.query(f.last(LIST)).get("page")).toBe("2");
    expect(action(container, "next-page").disabled).toBe(true);
  });
});

describe("019 AC-30 assigning the role user", () => {
  it("019_ac30_assign_opens_confirm_dialog_with_login_and_cancel_sends_nothing", async () => {
    const { container } = await open();
    fireEvent.click(action(row(container, ID_IVANOV), "assign-user"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain(t("accounts.assign_message", { login: "ivanov" }));
    fireEvent.click(action(dialog, "cancel"));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(assignKey(ID_IVANOV))).toBe(0);
  });

  it("019_ac30_confirm_sends_put_with_role_user_and_reloads_the_list", async () => {
    let listed = [SELF_REGISTERED, CREATED_BY_TA];
    const { container } = await open({
      [LIST]: () => j(200, page(listed)),
      [assignKey(ID_IVANOV)]: () => {
        listed = [CREATED_BY_TA];
        return NO_CONTENT();
      },
    });
    fireEvent.click(action(row(container, ID_IVANOV), "assign-user"));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    await waitFor(() => expect(container.querySelector(`tr[data-user-id="${ID_IVANOV}"]`)).toBeNull());
    expect(f.count(assignKey(ID_IVANOV))).toBe(1);
    expect(await sentBody(f.last(assignKey(ID_IVANOV)))).toEqual({ role: "user" });
    expect(f.count(LIST)).toBe(2);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("019_ac30_forbidden_on_assign_shows_forbidden_message_and_keeps_the_row", async () => {
    const { container } = await open({ [assignKey(ID_IVANOV)]: () => err(403, "forbidden") });
    fireEvent.click(action(row(container, ID_IVANOV), "assign-user"));
    fireEvent.click(action(await screen.findByRole("alertdialog"), "confirm"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(row(container, ID_IVANOV)).toBeTruthy();
  });

  it("019_ac30_list_forbidden_shows_alert_and_no_table", async () => {
    setup({ [LIST]: () => err(403, "forbidden") });
    renderApp("/unassigned-accounts");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("019 AC-26 / AC-30 access by capability onboard_accounts", () => {
  it.each([
    ["tech_admin", CAPS_ALL],
    ["user", ["business_access"]],
  ])("019_ac30_%s_without_onboard_accounts_sees_forbidden_and_no_list_request", async (role, caps) => {
    setup({}, caps, role);
    renderApp("/unassigned-accounts");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("forbidden"));
    expect(where()).toBe("/unassigned-accounts");
    expect(f.count(LIST)).toBe(0);
    expect(f.count(ME)).toBe(1);
  });
});

// Аудит #9: пустой список первой страницы - без пагинации; непустой - с пагинацией.
describe("пагинация неназначенных учётных записей при пустом списке (аудит #9)", () => {
  it("empty_first_page_has_no_pagination", async () => {
    setup({ [LIST]: () => j(200, page([])) });
    const { container } = renderApp("/unassigned-accounts");
    expect(await screen.findByText(ru["accounts.unassigned_empty"])).toBeTruthy();
    expect(container.querySelector(".ui-pagination")).toBeNull();
    expect(container.querySelector('[data-action="next-page"]')).toBeNull();
    expect(container.querySelector('[data-action="prev-page"]')).toBeNull();
  });

  it("non_empty_list_single_page_hides_pagination", async () => {
    const { container } = await open();
    expect(container.querySelector(".ui-pagination")).toBeNull();
  });
});
