// 007 R7-T20: диалог изменения/очистки email (plan §4.7; образец - shared/ui/ConfirmDialog).
// Проверяется через экран /admin/users: пропсы EmailDialog планом не фиксируются.
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
const EMAIL_PUT = `PUT /api/v1/admin/users/${ID_IVANOV}/email`;

type Fetcher = ReturnType<typeof installFetch>;
let f: Fetcher;

async function openDialog(putResponse: () => Response = () => j(200, U_IVANOV)) {
  f = installFetch({
    [ME]: () => j(200, meWith(CAPS_ALL)),
    [LIST]: () =>
      j(200, page([{ ...U_ADMIN, email: null }, { ...U_IVANOV, email: "ivanov@example.ru" }, { ...U_PETROV, email: null }])),
    [EMAIL_PUT]: putResponse,
  });
  const { container } = renderApp("/admin/users");
  await waitFor(() => expect(container.querySelector(`tr[data-user-id="${ID_IVANOV}"]`)).toBeTruthy());
  const opener = within(row(container, ID_IVANOV)).getByRole("button", {
    name: ru["admin.users.edit_email_aria"].replace("{login}", "ivanov"),
  });
  opener.focus();
  fireEvent.click(opener);
  const dialog = await screen.findByRole("dialog");
  return { dialog, opener, container };
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => vi.restoreAllMocks());

describe("EmailDialog (007, R7-T20)", () => {
  it("007_dialog_is_modal_labelled_with_title_and_hint", async () => {
    const { dialog } = await openDialog();
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const labelId = dialog.getAttribute("aria-labelledby");
    expect(labelId).toBeTruthy();
    const title = document.getElementById(labelId as string);
    expect(title?.textContent).toBe(ru["admin.users.email_dialog_title"].replace("{login}", "ivanov"));
    expect(within(dialog).getByText(ru["admin.users.email_dialog_hint"])).toBeTruthy();
  });

  it("007_field_has_current_value_and_save_cancel_buttons", async () => {
    const { dialog } = await openDialog();
    expect((within(dialog).getByRole("textbox") as HTMLInputElement).value).toBe("ivanov@example.ru");
    expect(within(dialog).getByRole("button", { name: ru["admin.users.email_save"] })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: ru["admin.users.email_cancel"] })).toBeTruthy();
  });

  it("007_focus_moves_inside_dialog", async () => {
    const { dialog } = await openDialog();
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
  });

  it("007_escape_closes_without_request_and_returns_focus", async () => {
    const { dialog, opener } = await openDialog();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(f.count(EMAIL_PUT)).toBe(0);
    expect(document.activeElement).toBe(opener);
  });

  it("007_cancel_closes_without_request", async () => {
    const { dialog } = await openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: ru["admin.users.email_cancel"] }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(f.count(EMAIL_PUT)).toBe(0);
  });

  it("007_email_invalid_422_shown_in_dialog_which_stays_open", async () => {
    const { dialog } = await openDialog(() => err(422, "email_invalid"));
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "bad" } });
    fireEvent.click(within(dialog).getByRole("button", { name: ru["admin.users.email_save"] }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toBe(errorMessage("email_invalid"));
    expect(screen.queryByRole("dialog")).toBe(dialog);
  });
});
