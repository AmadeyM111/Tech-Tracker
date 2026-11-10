// 019/R8-T20: dialog for changing a user's first and last name (AC-35; plan §4.7).
// Checked through the /admin/users screen: the NameDialog props are not fixed by the plan.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { errorMessage, ru } from "../../../src/shared/i18n";
import {
  CAPS_ALL,
  ID_IVANOV,
  U_ADMIN,
  U_IVANOV,
  U_PETROV,
  err,
  installFetch,
  j,
  meWith,
  page,
  renderApp,
  row,
} from "./helpers";

const LIST = "GET /api/v1/admin/users";
const ME = "GET /api/v1/me";
const NAME_PUT = `PUT /api/v1/admin/users/${ID_IVANOV}/name`;

type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;

async function openDialog(putResponse: () => Response = () => j(200, U_IVANOV)) {
  f = installFetch({
    [ME]: () => j(200, meWith(CAPS_ALL)),
    [LIST]: () =>
      j(200, page([
        { ...U_ADMIN, first_name: "Admin", last_name: "Root" },
        { ...U_IVANOV, first_name: "Ivan", last_name: "Ivanov" },
        U_PETROV,
      ])),
    [NAME_PUT]: putResponse,
  });
  const { container } = renderApp("/admin/users");
  await waitFor(() => expect(container.querySelector(`tr[data-user-id="${ID_IVANOV}"]`)).toBeTruthy());
  const opener = within(row(container, ID_IVANOV)).getByRole("button", {
    name: ru["admin.users.edit_name_aria"].replace("{login}", "ivanov"),
  });
  opener.focus();
  fireEvent.click(opener);
  const dialog = await screen.findByRole("dialog");
  return { dialog, opener, container };
}

function field(scope: HTMLElement, label: string): HTMLInputElement {
  return within(scope).getByLabelText(label) as HTMLInputElement;
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => vi.restoreAllMocks());

describe("NameDialog (019, R8-T20)", () => {
  it("019_ac35_dialog_is_modal_labelled_and_prefilled_with_current_names", async () => {
    const { dialog } = await openDialog();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const labelId = dialog.getAttribute("aria-labelledby");
    expect(labelId).toBeTruthy();
    const title = document.getElementById(labelId as string);
    expect(title?.textContent).toBe(ru["admin.users.name_dialog_title"].replace("{login}", "ivanov"));
    expect(field(dialog, ru["admin.users.first_name_label"]).value).toBe("Ivan");
    expect(field(dialog, ru["admin.users.last_name_label"]).value).toBe("Ivanov");
    expect(within(dialog).getByRole("button", { name: ru["admin.users.name_save"] })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: ru["admin.users.name_cancel"] })).toBeTruthy();
  });

  it("019_ac35_focus_moves_inside_dialog", async () => {
    const { dialog } = await openDialog();
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
  });

  it("019_ac35_tab_cycles_inside_dialog", async () => {
    const { dialog } = await openDialog();
    const cancel = within(dialog).getByRole("button", { name: ru["admin.users.name_cancel"] });
    const first = field(dialog, ru["admin.users.first_name_label"]);
    cancel.focus();
    fireEvent.keyDown(cancel, { key: "Tab" });
    expect(document.activeElement).toBe(first);
  });

  it("019_ac35_escape_closes_without_request_and_returns_focus", async () => {
    const { dialog, opener } = await openDialog();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(f.count(NAME_PUT)).toBe(0);
    expect(document.activeElement).toBe(opener);
  });

  it("019_ac35_cancel_closes_without_request", async () => {
    const { dialog } = await openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: ru["admin.users.name_cancel"] }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(f.count(NAME_PUT)).toBe(0);
  });

  // P2 (PR #29 design review): an empty name shows «Введите имя» / «Введите фамилию» under its own field.
  it.each([
    ["first", "   ", "Ivanov", "admin.users.first_name_label", "admin.users.first_name_required"],
    ["last", "Ivan", "", "admin.users.last_name_label", "admin.users.last_name_required"],
  ] as const)(
    "019_ac35_empty_%s_name_is_under_its_field_and_sends_nothing",
    async (_n, first, last, labelKey, textKey) => {
      const { dialog } = await openDialog();
      fireEvent.change(field(dialog, ru["admin.users.first_name_label"]), { target: { value: first } });
      fireEvent.change(field(dialog, ru["admin.users.last_name_label"]), { target: { value: last } });
      fireEvent.click(within(dialog).getByRole("button", { name: ru["admin.users.name_save"] }));
      const input = field(dialog, ru[labelKey]);
      const error = (await within(dialog).findByText(ru[textKey])).closest<HTMLElement>(".ui-field-error");
      expect(error?.getAttribute("role")).toBe("alert");
      expect(input.closest(".ui-field")?.contains(error)).toBe(true);
      expect(input.getAttribute("aria-invalid")).toBe("true");
      expect(input.getAttribute("aria-describedby")?.split(" ")).toContain(error?.id);
      expect(document.activeElement).toBe(input);
      expect(f.count(NAME_PUT)).toBe(0);
      expect(screen.queryByRole("dialog")).toBe(dialog);
    },
  );

  // Server codes of the name fields: the rule text goes under the field it refers to, not into a general block.
  it.each([
    ["first_name_invalid", "admin.users.first_name_label"],
    ["last_name_invalid", "admin.users.last_name_label"],
  ] as const)("019_ac35_server_%s_is_under_its_field_and_dialog_stays_open", async (code, labelKey) => {
    const { dialog } = await openDialog(() => err(422, code));
    fireEvent.click(within(dialog).getByRole("button", { name: ru["admin.users.name_save"] }));
    const error = (await within(dialog).findByText(errorMessage(code))).closest<HTMLElement>(".ui-field-error");
    const input = field(dialog, ru[labelKey]);
    expect(input.closest(".ui-field")?.contains(error)).toBe(true);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(within(dialog).queryByRole("alert")).toBe(error);
    expect(document.activeElement).toBe(input);
    expect(screen.queryByRole("dialog")).toBe(dialog);
  });
});
