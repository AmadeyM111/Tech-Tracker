// 007/R7-T18: экран подтверждения сброса /password-reset/confirm. AC: AC-13, AC-8 (фронт), FR-10, FR-13.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "../../../src/app/router";
import { errorMessage, t } from "../../../src/shared/i18n";
import { field, renderAt, revealButtons } from "./helpers";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const PASSWORD = "Brand-New-Passw0rd!";
const CONFIRM = "/api/v1/auth/password-reset/confirm";

function stubNet(onConfirm: (r: Request) => Response | Promise<Response> = () => new Response(null, { status: 204 })) {
  const calls: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (r: Request) => {
      calls.push(r.clone());
      const p = new URL(r.url).pathname;
      if (p === "/api/v1/me") return json(401, { detail: "x", code: "unauthenticated" });
      if (p === CONFIRM) return onConfirm(r);
      return json(404, { detail: "x", code: "not_found" });
    }),
  );
  return calls;
}

const confirmCalls = (calls: Request[]) => calls.filter((c) => new URL(c.url).pathname === CONFIRM);
/** Адресная строка (jsdom) задаётся до рендера: токен читается из window.location.hash. */
function open(hash = "#token=abc") {
  window.history.replaceState(null, "", "/password-reset/confirm" + hash);
  return renderAt("/password-reset/confirm", <AppRoutes />, "*");
}
const fill = (c: HTMLElement, a = PASSWORD, b = PASSWORD) => {
  fireEvent.change(field(c, "new-password", 0), { target: { value: a } });
  fireEvent.change(field(c, "new-password", 1), { target: { value: b } });
};
const submit = (c: HTMLElement) => fireEvent.click(c.querySelector<HTMLButtonElement>('button[type="submit"]')!);

beforeEach(() => window.history.replaceState(null, "", "/"));
afterEach(() => vi.unstubAllGlobals());

describe("PasswordResetConfirmPage (007/R7-T18)", () => {
  it("007_ac13_fragment_is_removed_from_address_bar_and_form_is_shown", async () => {
    stubNet();
    const { container } = open();
    expect(await screen.findByRole("heading", { level: 1, name: t("auth.reset_confirm_title") })).toBeTruthy();
    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(window.location.pathname).toBe("/password-reset/confirm");
    expect(container.querySelectorAll('input[autocomplete="new-password"]')).toHaveLength(2);
    expect(screen.getByLabelText(t("auth.reset_new_password_label"), { selector: "input" })).toBeTruthy();
    expect(screen.getByLabelText(t("auth.reset_repeat_password_label"), { selector: "input" })).toBeTruthy();
    expect(revealButtons(container)).toHaveLength(2);
    expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')?.textContent).toBe(t("auth.reset_confirm_submit"));
  });

  it("007_ac13_mismatch_shows_message_and_sends_no_request", async () => {
    const calls = stubNet();
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fill(container, PASSWORD, PASSWORD + "x");
    submit(container);
    expect((await screen.findByRole("alert")).textContent).toContain(t("auth.password_mismatch"));
    expect(confirmCalls(calls)).toHaveLength(0);
  });

  it("007_ac13_submit_sends_token_and_new_password", async () => {
    const calls = stubNet();
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fill(container);
    submit(container);
    await waitFor(() => expect(confirmCalls(calls)).toHaveLength(1));
    const sent = confirmCalls(calls);
    expect(sent).toHaveLength(1);
    const [req] = sent;
    if (!req) throw new Error("confirm request was not sent");
    expect(req.method).toBe("POST");
    expect(await req.json()).toEqual({ token: "abc", new_password: PASSWORD });
  });

  it("007_ac8_success_shows_done_and_login_link_without_login_request_or_redirect", async () => {
    const calls = stubNet();
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fill(container);
    submit(container);
    expect(await screen.findByText(t("auth.reset_done"))).toBeTruthy();
    expect(screen.getByRole("link", { name: t("auth.reset_login_link") }).getAttribute("href")).toBe("/login");
    expect(calls.some((c) => new URL(c.url).pathname === "/api/v1/auth/login")).toBe(false);
    expect(screen.queryByTestId("where")).toBeNull();
    expect(screen.queryByRole("heading", { level: 1, name: t("auth.login_title") })).toBeNull();
    expect(container.querySelector('input[autocomplete="new-password"]')).toBeNull();
  });

  it("007_reset_token_invalid_shows_message_and_link_to_request_new", async () => {
    stubNet(() => json(400, { detail: "x", code: "reset_token_invalid" }));
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fill(container);
    submit(container);
    expect(await screen.findByText(errorMessage("reset_token_invalid"))).toBeTruthy();
    expect(screen.getByRole("link", { name: t("auth.reset_request_again") }).getAttribute("href")).toBe("/password-reset");
  });

  it("007_validation_error_422_shows_error_message_for_code", async () => {
    stubNet(() => json(422, { detail: "x", code: "password_too_short" }));
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    fill(container);
    submit(container);
    expect((await screen.findByRole("alert")).textContent).toContain(errorMessage("password_too_short"));
  });

  it("007_without_fragment_shows_invalid_link_message_and_no_form", async () => {
    const calls = stubNet();
    const { container } = open("");
    expect(await screen.findByText(t("auth.reset_link_invalid"))).toBeTruthy();
    expect(container.querySelector("input")).toBeNull();
    expect(container.querySelector('button[type="submit"]')).toBeNull();
    expect(screen.getByRole("link", { name: t("auth.reset_request_again") }).getAttribute("href")).toBe("/password-reset");
    expect(confirmCalls(calls)).toHaveLength(0);
  });
});
