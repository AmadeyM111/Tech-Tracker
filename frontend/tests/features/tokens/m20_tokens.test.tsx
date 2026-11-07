// M20 / PN-15: the "Доступ для агентов" section (features/tokens) at /profile/agents.
// AC-1: the token is shown once and is not kept in the list or any cache after dismissal.
// AC-3: revoking refreshes the list; the revoked token is no longer active.
import type { QueryClient } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ru, t } from "../../../src/shared/i18n";
import { err, installFetch, j, meWith, NO_CONTENT, renderApp, type Handler } from "../admin/helpers";

const ME = "GET /api/v1/me";
const LIST = "GET /api/v1/me/tokens";
const CREATE = "POST /api/v1/me/tokens";
const revokeKey = (id: string) => `DELETE /api/v1/me/tokens/${id}`;

const T_ACTIVE = "aaaaaaaa-1111-4111-8111-111111111111";
const T_REVOKED = "bbbbbbbb-2222-4222-8222-222222222222";
const T_EXPIRED = "cccccccc-3333-4333-8333-333333333333";
const T_NEW = "dddddddd-4444-4444-8444-444444444444";
const TOKEN_VALUE = `gtrk_${"Q".repeat(43)}`;

const ACTIVE = {
  id: T_ACTIVE,
  name: "Ноутбук",
  created_at: "2026-10-13T09:00:00Z",
  expires_at: "2027-01-11T09:00:00Z",
  last_used_at: null,
  revoked_at: null,
  active: true,
};
const REVOKED = {
  id: T_REVOKED,
  name: "Старый",
  created_at: "2026-10-01T09:00:00Z",
  expires_at: "2026-12-30T09:00:00Z",
  last_used_at: "2026-10-05T08:00:00Z",
  revoked_at: "2026-10-20T10:00:00Z",
  active: false,
};
const EXPIRED = {
  id: T_EXPIRED,
  name: "Истёкший",
  created_at: "2026-06-01T09:00:00Z",
  expires_at: "2026-09-01T09:00:00Z",
  last_used_at: "2026-08-30T12:00:00Z",
  revoked_at: null,
  active: false,
};
const CREATED_ITEM = {
  id: T_NEW,
  name: "Ноутбук",
  created_at: "2026-11-08T09:00:00Z",
  expires_at: "2027-02-06T09:00:00Z",
  last_used_at: null,
  revoked_at: null,
  active: true,
};

type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;

function setup(list: Handler, extra: Record<string, Handler> = {}) {
  f = installFetch({
    [ME]: () => j(200, meWith(["business_access"])),
    [LIST]: list,
    ...extra,
  });
}

async function open(list: Handler = () => j(200, [ACTIVE, REVOKED, EXPIRED]), extra: Record<string, Handler> = {}) {
  setup(list, extra);
  const view = renderApp("/profile/agents");
  // The list request has been made and has settled (the loading text is gone).
  await waitFor(() => expect(f.count(LIST)).toBeGreaterThanOrEqual(1));
  await waitFor(() => expect(screen.queryByText(ru["agent_tokens.loading"])).toBeNull());
  return view;
}

function rowOf(container: HTMLElement, id: string): HTMLElement {
  const el = container.querySelector<HTMLElement>(`tr[data-token-id="${id}"]`);
  if (!el) throw new Error(`no row for ${id}`);
  return el;
}

/** Everything the query and mutation caches hold, as text. */
function cacheText(qc: QueryClient): string {
  return JSON.stringify([
    qc.getQueryCache().getAll().map((q) => q.state),
    qc.getMutationCache().getAll().map((m) => m.state),
  ]);
}

function stubClipboard(writeText: (text: string) => Promise<void>): void {
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("navigation and list (PN-15, FR-1)", () => {
  it("lists name, dates, last use and status at /profile/agents", async () => {
    const { container } = await open();
    expect(screen.getByRole("heading", { name: ru["agent_tokens.title"] })).toBeTruthy();

    const active = rowOf(container, T_ACTIVE);
    expect(active.querySelector('[data-field="name"]')?.textContent).toBe("Ноутбук");
    expect(active.querySelector('[data-field="created"]')?.textContent).toMatch(/13\.10\.2026/);
    expect(active.querySelector('[data-field="expires"]')?.textContent).toMatch(/11\.01\.2027/);
    expect(active.querySelector('[data-field="last_used"]')?.textContent).toBe(ru["agent_tokens.never_used"]);
    expect(active.querySelector('[data-field="status"]')?.textContent).toBe(ru["agent_tokens.status_active"]);

    expect(rowOf(container, T_REVOKED).querySelector('[data-field="status"]')?.textContent).toBe(
      ru["agent_tokens.status_revoked"],
    );
    expect(rowOf(container, T_EXPIRED).querySelector('[data-field="status"]')?.textContent).toBe(
      ru["agent_tokens.status_expired"],
    );
    // The list never shows a token value.
    expect(container.textContent).not.toContain("gtrk_");
  });

  it("offers revoke only for active tokens", async () => {
    const { container } = await open();
    expect(rowOf(container, T_ACTIVE).querySelector('button[data-action="revoke-token"]')).not.toBeNull();
    expect(rowOf(container, T_REVOKED).querySelector('button[data-action="revoke-token"]')).toBeNull();
    expect(rowOf(container, T_EXPIRED).querySelector('button[data-action="revoke-token"]')).toBeNull();
  });

  it("shows the empty state", async () => {
    await open(() => j(200, []));
    expect(screen.getByRole("status").textContent).toBe(ru["agent_tokens.empty"]);
  });

  it("shows a list error as a dictionary text, not a raw code", async () => {
    setup(() => err(500, "internal_error"));
    renderApp("/profile/agents");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(ru["error.internal_error"]);
  });
});

describe("create token (AC-1)", () => {
  it("sends the trimmed name, shows the token once in a read-only field, copies it and drops it on dismissal", async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>(async () => undefined);
    stubClipboard(writeText);
    const bodies: unknown[] = [];
    let listCalls = 0;
    const view = await open(
      () => {
        listCalls += 1;
        return j(200, listCalls === 1 ? [ACTIVE] : [CREATED_ITEM, ACTIVE]);
      },
      {
        [CREATE]: async (r) => {
          bodies.push(await r.json());
          return j(201, { ...CREATED_ITEM, token: TOKEN_VALUE });
        },
      },
    );

    fireEvent.change(screen.getByLabelText(ru["agent_tokens.name_label"]), { target: { value: "  Ноутбук  " } });
    fireEvent.click(screen.getByRole("button", { name: ru["agent_tokens.create_submit"] }));

    const field = (await screen.findByLabelText(ru["agent_tokens.token_label"])) as HTMLInputElement;
    expect(bodies).toEqual([{ name: "Ноутбук" }]);
    expect(field.readOnly).toBe(true);
    expect(field.value).toBe(TOKEN_VALUE);
    expect(screen.getByText(ru["agent_tokens.issued_warning"])).toBeTruthy();
    // The list is refreshed after the create and shows the new token without its value.
    await waitFor(() => expect(view.container.querySelector(`tr[data-token-id="${T_NEW}"]`)).not.toBeNull());
    expect(f.count(LIST)).toBe(2);
    expect(view.container.textContent).not.toContain(TOKEN_VALUE);
    // The token is not in any cache, even while it is shown.
    expect(cacheText(view.qc)).not.toContain(TOKEN_VALUE);

    fireEvent.click(screen.getByRole("button", { name: ru["agent_tokens.copy"] }));
    await screen.findByText(ru["agent_tokens.copied"]);
    expect(writeText).toHaveBeenCalledWith(TOKEN_VALUE);

    fireEvent.click(screen.getByRole("button", { name: ru["agent_tokens.dismiss"] }));
    await waitFor(() => expect(screen.queryByLabelText(ru["agent_tokens.token_label"])).toBeNull());
    expect(view.container.textContent).not.toContain(TOKEN_VALUE);
    expect(document.body.innerHTML).not.toContain(TOKEN_VALUE);
    expect(cacheText(view.qc)).not.toContain(TOKEN_VALUE);
    // Focus goes back to the name field for the next token.
    expect(document.activeElement).toBe(screen.getByLabelText(ru["agent_tokens.name_label"]));
  });

  it("drops the token from memory when the page is left without dismissal", async () => {
    const view = await open(() => j(200, []), {
      [CREATE]: () => j(201, { ...CREATED_ITEM, token: TOKEN_VALUE }),
    });
    fireEvent.change(screen.getByLabelText(ru["agent_tokens.name_label"]), { target: { value: "Ноутбук" } });
    fireEvent.click(screen.getByRole("button", { name: ru["agent_tokens.create_submit"] }));
    await screen.findByLabelText(ru["agent_tokens.token_label"]);
    view.unmount();
    expect(cacheText(view.qc)).not.toContain(TOKEN_VALUE);
  });

  it("shows a copy failure as an alert and keeps the value selectable", async () => {
    stubClipboard(() => Promise.reject(new Error("denied")));
    await open(() => j(200, []), {
      [CREATE]: () => j(201, { ...CREATED_ITEM, token: TOKEN_VALUE }),
    });
    fireEvent.change(screen.getByLabelText(ru["agent_tokens.name_label"]), { target: { value: "Ноутбук" } });
    fireEvent.click(screen.getByRole("button", { name: ru["agent_tokens.create_submit"] }));
    await screen.findByLabelText(ru["agent_tokens.token_label"]);
    fireEvent.click(screen.getByRole("button", { name: ru["agent_tokens.copy"] }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(ru["agent_tokens.copy_failed"]);
  });

  it("rejects an empty name on the client without a request", async () => {
    await open();
    const input = screen.getByLabelText(ru["agent_tokens.name_label"]);
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: ru["agent_tokens.create_submit"] }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(ru["agent_tokens.name_required"]);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(f.count(CREATE)).toBe(0);
  });

  it("rejects a name longer than 64 characters on the client", async () => {
    await open();
    fireEvent.change(screen.getByLabelText(ru["agent_tokens.name_label"]), { target: { value: "a".repeat(65) } });
    fireEvent.click(screen.getByRole("button", { name: ru["agent_tokens.create_submit"] }));
    expect((await screen.findByRole("alert")).textContent).toBe(ru["agent_tokens.name_too_long"]);
    expect(f.count(CREATE)).toBe(0);
  });

  it("shows validation_error from the server as a readable text, not the code", async () => {
    const { container } = await open(undefined, {
      [CREATE]: () => err(422, "validation_error"),
    });
    fireEvent.change(screen.getByLabelText(ru["agent_tokens.name_label"]), { target: { value: "Ноутбук" } });
    fireEvent.click(screen.getByRole("button", { name: ru["agent_tokens.create_submit"] }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(ru["error.validation_error"]);
    expect(container.textContent).not.toContain("validation_error");
  });

  it("shows token_limit_reached as a readable text, not the code", async () => {
    const { container } = await open(undefined, {
      [CREATE]: () => err(409, "token_limit_reached"),
    });
    fireEvent.change(screen.getByLabelText(ru["agent_tokens.name_label"]), { target: { value: "Ноутбук" } });
    fireEvent.click(screen.getByRole("button", { name: ru["agent_tokens.create_submit"] }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(ru["error.token_limit_reached"]);
    expect(container.textContent).not.toContain("token_limit_reached");
    expect(screen.queryByLabelText(ru["agent_tokens.token_label"])).toBeNull();
  });
});

describe("revoke token (AC-3)", () => {
  it("cancel closes the dialog without a request", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: t("agent_tokens.revoke_aria", { name: ACTIVE.name }) }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: ru["admin.cancel"] }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(f.count(revokeKey(T_ACTIVE))).toBe(0);
  });

  it("confirm sends DELETE, refreshes the list and shows the token as revoked", async () => {
    let items: unknown[] = [ACTIVE, REVOKED];
    const { container } = await open(() => j(200, items), {
      [revokeKey(T_ACTIVE)]: () => {
        items = [{ ...ACTIVE, active: false, revoked_at: "2026-11-08T10:00:00Z" }, REVOKED];
        return NO_CONTENT();
      },
    });
    fireEvent.click(screen.getByRole("button", { name: t("agent_tokens.revoke_aria", { name: ACTIVE.name }) }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(t("agent_tokens.revoke_message", { name: ACTIVE.name }))).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: ru["admin.confirm"] }));

    await waitFor(() => expect(f.count(revokeKey(T_ACTIVE))).toBe(1));
    await waitFor(() =>
      expect(rowOf(container, T_ACTIVE).querySelector('[data-field="status"]')?.textContent).toBe(
        ru["agent_tokens.status_revoked"],
      ),
    );
    expect(f.count(LIST)).toBe(2);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(rowOf(container, T_ACTIVE).querySelector('button[data-action="revoke-token"]')).toBeNull();
    // Focus does not fall to the page body after the row loses its button.
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: ru["agent_tokens.list_title"] }));
  });

  it("shows a readable error when the revoke fails and still refreshes the list", async () => {
    await open(undefined, {
      [revokeKey(T_ACTIVE)]: () => err(404, "not_found"),
    });
    fireEvent.click(screen.getByRole("button", { name: t("agent_tokens.revoke_aria", { name: ACTIVE.name }) }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: ru["admin.confirm"] }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(ru["error.not_found"]);
    await waitFor(() => expect(f.count(LIST)).toBe(2));
  });
});
